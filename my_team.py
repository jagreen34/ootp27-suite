"""
OOTP 27 Suite — My Team Module
================================
The diagnostic dashboard for Jeff's own roster.

Three tabs:
  🧢 Roster      — active/reserve player tables, Bat/Pit sub-views
  📊 Team View   — F1 by position, service time buckets, WAR pace, payroll
  ⚙️ Auto-Config — auto-detected need/surplus positions with write-back

Roster is persisted via league.save_last_roster() / league.get_last_roster().
Other modules uploading CSVs do not affect the saved roster.

Position fluidity uses the ZR_MODELS from acquisitions.py — full-season
ZR projections drive PLAYABLE / PLUS / position-aware thresholds.

SP-capable = STM ≥ 45 AND CNT_eff ≥ 3 (informational tag).

Auto-detect need/surplus thresholds (no league CSV required):
  Need:    best-F1 at position < 2.0 (Competing) / 1.5 (Sustaining) / 1.0 (Rebuilding)
  Surplus: 2+ players at position with F1 ≥ 3.0 AND best F1 ≥ 4.0
"""

import pandas as pd
import streamlit as st

from db import League, compute_control_window, compute_arb_status

# Reuse everything we can from acquisitions — single source of truth for
# F1 formulas, rename pipeline, positional constants, ZR models.
from acquisitions import (
    prep_data,
    batter_f1, pitcher_f1, sp_f1, rp_f1,
    off_f1, def_war, pos_adj,
    trade_value,
    cnt_eff_pitches, min_eff_pitch,
    babip_luck_flag,
    BUY_LUCK_FLAGS, SELL_LUCK_FLAGS,
    ZR_MODELS, ZR_WAR_FACTOR,
    POS_MULT, POS_ADJ_CONSTANTS,
    BATTER_POSITIONS, PITCHER_POSITIONS,
    EFF_PITCH_THRESHOLD,
    _s,
)

# Service time constant — AC rules
_DAYS_PER_SERVICE_YEAR = 76

# ══════════════════════════════════════════════════════════════════════════════
# POSITION FLUIDITY — ZR-DRIVEN PLAYABILITY
# ══════════════════════════════════════════════════════════════════════════════
#
# A player is PLAYABLE at a position if their predicted full-season ZR
# (from acquisitions.ZR_MODELS) meets the position's floor.
# Thresholds are position-aware: defense matters less at 1B/LF, more at SS/CF.
# These floors are projections, not in-season totals — same scale Jeff's SS
# accumulates 16-20 ZR on.

ZR_PLAYABLE_FLOOR = {
    '1B': -5,  # very forgiving — bat carries the position
    'LF': -3,  # forgiving
    'RF':  0,  # average projection
    '3B':  0,
    '2B':  0,
    'CF':  2,  # CF demands above-average range
    'C':   0,
    'SS':  2,  # SS demands above-average range/arm
}

ZR_PLUS_FLOOR = {
    '1B':  3,
    'LF':  4,
    'RF':  5,
    '3B':  5,
    '2B':  5,
    'CF':  7,
    'C':   5,
    'SS':  8,
}

# SP-capable threshold (registry hard rules + gameplay)
SP_STM_FLOOR    = 45
SP_PITCHES_MIN  = 3


def predict_zr(row, pos: str) -> float:
    """
    Predict full-season ZR at a given position from underlying fielding ratings.
    Returns 0.0 if position not modeled (e.g. P, DH-only).
    """
    if pos not in ZR_MODELS:
        return 0.0
    m  = ZR_MODELS[pos]
    zr = m['intercept']
    for col, coef in m['coefs'].items():
        zr += _s(row.get(col, 0)) * coef
    return zr


def positions_playable(row) -> list[dict]:
    """
    Return every position the player projects PLAYABLE at, with predicted ZR
    and tier (PLUS / PLAYABLE). Sorted best-first by ZR.

    Soft rule: a CF tagged PLUS gets downgraded to PLAYABLE if OF_ARM < 40,
    since the CF ZR model is single-variable (range only) and can over-credit
    no-arm CFs.

    Returns: [{'pos': 'SS', 'zr': 12.4, 'tier': 'PLUS'}, ...]
    """
    results = []
    for pos in ZR_PLAYABLE_FLOOR.keys():
        zr = predict_zr(row, pos)
        floor      = ZR_PLAYABLE_FLOOR[pos]
        plus_floor = ZR_PLUS_FLOOR[pos]

        if zr < floor:
            continue

        tier = 'PLUS' if zr >= plus_floor else 'PLAYABLE'

        # CF arm downgrade — model has no arm term
        if pos == 'CF' and tier == 'PLUS' and _s(row.get('OF_ARM', 0)) < 40:
            tier = 'PLAYABLE'

        results.append({'pos': pos, 'zr': round(zr, 1), 'tier': tier})

    results.sort(key=lambda r: r['zr'], reverse=True)
    return results


def sp_capable(row) -> bool:
    """SP-capable: STM ≥ 45 AND 3+ effective pitches (grade ≥ 30)."""
    return (_s(row.get('STM', 0)) >= SP_STM_FLOOR
            and cnt_eff_pitches(row) >= SP_PITCHES_MIN)


def flex_summary(row) -> str:
    """
    Compact flex string for the roster table.
    Shows non-current positions the player can play, PLUS-tier ones first.

    Example: "PLUS@2B, +SS, +3B"
              ^^^^      ^   ^
              PLUS      PLAYABLE (prefixed with +)
    """
    current = str(row.get('POS', ''))
    if current in PITCHER_POSITIONS:
        # Pitchers don't flex to position-player roles
        return ''

    playable = [p for p in positions_playable(row) if p['pos'] != current]
    if not playable:
        return ''

    parts = []
    for p in playable[:4]:  # cap at 4 for display sanity
        if p['tier'] == 'PLUS':
            parts.append(f"PLUS@{p['pos']}")
        else:
            parts.append(f"+{p['pos']}")
    return ', '.join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# ACTIVE / RESERVE SPLIT
# ══════════════════════════════════════════════════════════════════════════════

def split_active_reserve(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split a roster into (active_25, reserve) DataFrames using IS_ACTIVE if present.

    Falls back to returning (all, empty) if IS_ACTIVE column not in export.
    """
    if 'IS_ACTIVE' not in df.columns:
        return df.copy(), df.iloc[0:0].copy()

    active_mask = df['IS_ACTIVE'].astype(str).str.lower().isin(
        ('1', 'true', 'yes', 'y', 't')
    )
    return df[active_mask].copy(), df[~active_mask].copy()


# ══════════════════════════════════════════════════════════════════════════════
# F1 / SERVICE TIME ROW BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_player_row(row_dict: dict) -> dict:
    """
    One row → display dict with F1, TV, control, arb, flex, flags.
    Used by both Roster and Team View tables.
    """
    pos = str(row_dict.get('POS', ''))
    age = int(_s(row_dict.get('AGE', row_dict.get('Age', 25))))

    # F1 by role
    if pos in PITCHER_POSITIONS:
        f1 = pitcher_f1(row_dict)
    elif pos in BATTER_POSITIONS:
        f1 = batter_f1(row_dict)
    else:
        f1 = 0.0

    # Service / control
    ml_yrs   = _s(row_dict.get('ML_YRS', 0))
    ml_days  = _s(row_dict.get('ML_DAYS', 0))
    years    = _s(row_dict.get('YEARS_LEFT', 0))
    control  = compute_control_window(years, ml_yrs, ml_days)
    arb      = compute_arb_status(ml_yrs, ml_days)
    svc_yrs  = round(ml_yrs + ml_days / _DAYS_PER_SERVICE_YEAR, 1)
    tv       = trade_value(f1, control, pos)
    salary   = _s(row_dict.get('SALARY', 0))

    # Flags
    flags = []
    personality = str(row_dict.get('Personality', row_dict.get('PIT_TYPE', '')))
    prone       = str(row_dict.get('PRONE', ''))
    we          = str(row_dict.get('WE', ''))

    if personality == 'Unmotivated':
        flags.append('UNMOTIVATED')
    if personality == 'Disruptive':
        flags.append('DISRUPTIVE')
    if prone == 'Fragile':
        flags.append('FRAGILE')
    if we == 'L':
        flags.append('WE:L')
    elif we == 'H':
        flags.append('WE:H')

    # Position-specific
    if pos in PITCHER_POSITIONS:
        cnt_eff = cnt_eff_pitches(row_dict)
        is_sp_capable = sp_capable(row_dict)
        if is_sp_capable and pos != 'SP':
            flags.append('SP-CAPABLE')
        if pos == 'SP' and not is_sp_capable:
            flags.append('SP-MARGINAL')
        if _s(row_dict.get('PIT_CON', 0)) < 40:
            flags.append('LOW-CON')
        if cnt_eff < 3 and pos == 'SP':
            flags.append('THIN-ARSENAL')
        flex = ''
        luck = ''
    else:
        cnt_eff = None
        flex = flex_summary(row_dict)
        luck = babip_luck_flag(row_dict) if pos in BATTER_POSITIONS else ''
        if luck == 'STRONG_BUY':
            flags.append('STRONG-BUY-LOW')
        elif luck == 'BUY_LOW':
            flags.append('BUY-LOW')
        elif luck == 'STRONG_SELL':
            flags.append('STRONG-SELL-HIGH')
        elif luck == 'SELL_HIGH':
            flags.append('SELL-HIGH')

    waivers = str(row_dict.get('ON_WAIVERS', '')).lower() in ('1', 'true', 'yes')
    is_dfa  = str(row_dict.get('IS_DFA', '')).lower() in ('1', 'true', 'yes')
    if waivers: flags.append('WAIVERS')
    if is_dfa:  flags.append('DFA')

    return {
        'Name':     str(row_dict.get('Name', '')),
        'POS':      pos,
        'Age':      age,
        'F1':       round(f1, 2),
        'TV':       tv,
        'Control':  control,
        'Svc_Yrs':  svc_yrs,
        'Arb':      arb,
        'Salary':   int(salary),
        'Yrs_Left': int(years),
        # Batter-specific
        'CON':      int(_s(row_dict.get('CON', 0)))  if pos in BATTER_POSITIONS else None,
        'POW':      int(_s(row_dict.get('POW', 0)))  if pos in BATTER_POSITIONS else None,
        'GAP':      int(_s(row_dict.get('GAP', 0)))  if pos in BATTER_POSITIONS else None,
        'EYE':      int(_s(row_dict.get('EYE', 0)))  if pos in BATTER_POSITIONS else None,
        'SPE':      int(_s(row_dict.get('SPE', 0)))  if pos in BATTER_POSITIONS else None,
        'Flex':     flex,
        'Luck':     luck,
        # Pitcher-specific
        'STU':      int(_s(row_dict.get('STU', 0)))     if pos in PITCHER_POSITIONS else None,
        'MOV':      int(_s(row_dict.get('MOV', 0)))     if pos in PITCHER_POSITIONS else None,
        'PIT_CON':  int(_s(row_dict.get('PIT_CON', 0))) if pos in PITCHER_POSITIONS else None,
        'STM':      int(_s(row_dict.get('STM', 0)))     if pos in PITCHER_POSITIONS else None,
        'CNT_eff':  cnt_eff,
        # Tail
        'Flags':    ', '.join(flags),
        '_personality': personality,  # internal — used for hard-skip diagnostics
    }


def build_roster_table(df: pd.DataFrame) -> pd.DataFrame:
    """Build the full roster display DataFrame from a prepped CSV."""
    if df.empty:
        return df.copy()
    rows = [_build_player_row(r) for r in df.to_dict('records')]
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values(['F1', 'TV'], ascending=[False, False]).reset_index(drop=True)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-DETECT NEED / SURPLUS
# ══════════════════════════════════════════════════════════════════════════════

# Need thresholds by mode (best-F1 at position must clear this to NOT be a need)
NEED_FLOORS = {
    'Competing':  2.0,
    'Sustaining': 1.5,
    'Rebuilding': 1.0,
}

SURPLUS_QUALITY_FLOOR = 3.0   # players at the position must clear this F1
SURPLUS_BEST_FLOOR    = 4.0   # AND best at position must clear this
SURPLUS_MIN_COUNT     = 2


def detect_needs_and_surplus(roster_df: pd.DataFrame, mode: str) -> tuple[list[str], list[str]]:
    """
    Auto-detect need / surplus positions from the roster table.

    Need: best-F1 player at the position is below mode-specific floor,
          AND at least one player nominally lists that position
          (or no one does — also a need).

    Surplus: at least 2 players at the position with F1 >= 3.0,
             AND best-F1 at that position >= 4.0.

    Returns (needs, surplus) — both sorted alphabetically.
    """
    if roster_df.empty:
        return [], []

    need_floor = NEED_FLOORS.get(mode, NEED_FLOORS['Competing'])

    needs   = []
    surplus = []

    all_positions = list(BATTER_POSITIONS) + ['SP', 'RP']  # CL folds into RP

    for pos in all_positions:
        # For pitchers: SP = listed SP; RP = listed RP or CL
        if pos == 'RP':
            at_pos = roster_df[roster_df['POS'].isin(['RP', 'CL'])]
        else:
            at_pos = roster_df[roster_df['POS'] == pos]

        if at_pos.empty:
            # No one at this position — it's a need (every position needs a starter)
            needs.append(pos)
            continue

        best_f1 = at_pos['F1'].max()
        quality_count = (at_pos['F1'] >= SURPLUS_QUALITY_FLOOR).sum()

        if best_f1 < need_floor:
            needs.append(pos)

        # Surplus only applies to position players. On a 25-man you need exactly
        # 6 SP + 5 RP; "extra" pitchers aren't surplus, they're just the best
        # available pitching depth. Surplus is about positions where you have
        # too many quality bodies to play them all.
        if pos in ('SP', 'RP'):
            continue

        if quality_count >= SURPLUS_MIN_COUNT and best_f1 >= SURPLUS_BEST_FLOOR:
            surplus.append(pos)

    return sorted(needs), sorted(surplus)


# ══════════════════════════════════════════════════════════════════════════════
# F1 BY POSITION (TEAM VIEW)
# ══════════════════════════════════════════════════════════════════════════════

def f1_by_position(roster_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate F1 by listed position. Returns one row per position with
    count, best F1, avg F1, total F1, avg age. CL is folded into RP since
    closer is an RP role, not a separate position.
    """
    if roster_df.empty:
        return pd.DataFrame()

    all_positions = sorted(BATTER_POSITIONS) + ['SP', 'RP']  # CL folds into RP
    rows = []
    for pos in all_positions:
        if pos == 'RP':
            at_pos = roster_df[roster_df['POS'].isin(['RP', 'CL'])]
        else:
            at_pos = roster_df[roster_df['POS'] == pos]
        if at_pos.empty:
            rows.append({
                'POS':    pos,
                'Count':  0,
                'Best':   None,
                'Avg':    None,
                'Total':  None,
                'Avg_Age': None,
            })
        else:
            rows.append({
                'POS':    pos,
                'Count':  len(at_pos),
                'Best':   round(at_pos['F1'].max(), 2),
                'Avg':    round(at_pos['F1'].mean(), 2),
                'Total':  round(at_pos['F1'].sum(), 1),
                'Avg_Age': round(at_pos['Age'].mean(), 1),
            })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# HARD-RULE DIAGNOSTICS
# ══════════════════════════════════════════════════════════════════════════════

def diagnose_roster_construction(active_df: pd.DataFrame) -> list[dict]:
    """
    Check roster construction against locked hard rules. Returns a list of
    {level: 'ok'|'warn'|'error', msg: str} for display.

    Rules checked:
      - 7+ RPs is a hard error (registry rule)
      - RP count of 6 is a soft warning (registry says 5 is WAR-maximizing)
      - SP count != 6 is a soft warning (6-man rotation is locked)
      - Active roster != 25 is a warn (AC roster cap)
      - Unmotivated/Disruptive on active roster is a warn
      - Fragile players over age 32 on active is a soft note
    """
    issues = []

    if active_df.empty:
        issues.append({'level': 'warn', 'msg': 'No active roster loaded.'})
        return issues

    n = len(active_df)
    if n != 25:
        issues.append({
            'level': 'warn',
            'msg': f"Active roster has {n} players (AC rule: 25).",
        })
    else:
        issues.append({'level': 'ok', 'msg': f"Active roster: {n} players ✓"})

    # Pitcher counts
    sp_count = (active_df['POS'] == 'SP').sum()
    rp_count = active_df['POS'].isin(['RP', 'CL']).sum()

    if rp_count >= 7:
        issues.append({
            'level': 'error',
            'msg': f"Carrying {rp_count} relievers — registry rule: never carry 7+ RP.",
        })
    elif rp_count == 6:
        issues.append({
            'level': 'warn',
            'msg': f"Carrying {rp_count} relievers — 5 is WAR-maximizing per registry.",
        })
    elif rp_count == 5:
        issues.append({'level': 'ok', 'msg': f"Relievers: {rp_count} ✓"})
    else:
        issues.append({
            'level': 'warn',
            'msg': f"Only {rp_count} relievers — may stretch the bullpen.",
        })

    if sp_count == 6:
        issues.append({'level': 'ok', 'msg': f"Starters: {sp_count} ✓ (6-man rotation)"})
    else:
        issues.append({
            'level': 'warn',
            'msg': f"Have {sp_count} starters — registry locked at 6-man rotation.",
        })

    # Personality red flags
    bad_personalities = active_df[
        active_df['_personality'].isin(['Unmotivated', 'Disruptive'])
    ]
    if not bad_personalities.empty:
        names = ', '.join(bad_personalities['Name'].tolist())
        issues.append({
            'level': 'warn',
            'msg': f"Personality red flags on active roster: {names}",
        })

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render_my_team(league: League):
    """Main entry point — called from app.py."""

    st.header("📊 My Team")

    tc       = league.team_config
    my_team  = tc.get('my_team', '')
    mode     = tc.get('mode', 'Competing')

    if not my_team:
        st.warning(
            "Set your team in ⚙️ Settings before using My Team. "
            "All filters and auto-detection depend on knowing which team is yours."
        )
        return

    # ── Load roster ──────────────────────────────────────────────────────────
    saved_df = league.get_last_roster()
    has_saved = saved_df is not None and not saved_df.empty

    with st.expander(
        "📤 Upload roster CSV" + (" (replace current)" if has_saved else ""),
        expanded=not has_saved,
    ):
        st.caption(
            "Upload a CSV export from OOTP 27. Can be your team-only export or the "
            "full league export — the module will filter to your team automatically "
            "using ORG. This roster persists until you upload a new one — other CSV "
            "uploads in the suite don't affect it."
        )
        uploaded = st.file_uploader(
            "Roster CSV",
            type=['csv'],
            key='myteam_upload',
        )
        if uploaded is not None:
            # Guard against infinite st.rerun() loop: file_uploader preserves the
            # uploaded file across reruns. Track which file (by name+size) we've
            # already processed so we don't re-save on every rerun.
            upload_id = f"{uploaded.name}:{uploaded.size}"
            last_processed = st.session_state.get('_myteam_last_upload_id')

            if upload_id != last_processed:
                try:
                    # Read raw — DO NOT prep_data yet. Filter to my team first to avoid
                    # running the heavy F1/rename pipeline on the entire league.
                    raw = pd.read_csv(uploaded, encoding='utf-8-sig', low_memory=False)

                    # Find the team column. ORG is canonical (registry A10) since
                    # multiple cities share team names. TM is fallback.
                    team_col = None
                    for cand in ('ORG', 'TM', 'Team'):
                        if cand in raw.columns:
                            team_col = cand
                            break
                    if team_col is None:
                        st.error("CSV has no ORG, TM, or Team column to filter on.")
                        return

                    team_rows = raw[raw[team_col].astype(str).str.strip() == my_team]
                    if team_rows.empty:
                        st.error(
                            f"No players in the CSV with {team_col} == '{my_team}'. "
                            f"Check that the team name in Settings matches the {team_col} "
                            f"column exactly. Available teams: "
                            f"{', '.join(sorted(raw[team_col].astype(str).unique())[:10])}..."
                        )
                        return

                    # NOW run prep_data on just the team rows
                    df = prep_data(team_rows.copy())
                    league.save_last_roster(df)
                    st.session_state['_myteam_last_upload_id'] = upload_id
                    st.success(f"Roster saved — {len(df)} players from {my_team}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to read CSV: {e}")
                    return

    if not has_saved:
        st.info("Upload a roster CSV to begin.")
        return

    # Saved data is already prepped + filtered to my team — use it directly.
    df = saved_df.copy()
    # Defensive re-filter in case an older saved roster contained other teams
    if 'ORG' in df.columns:
        df = df[df['ORG'].astype(str).str.strip() == my_team].copy()
    if df.empty:
        st.error(
            f"No players for '{my_team}' in saved roster. Re-upload your CSV."
        )
        return

    # Build the unified player table ONCE — slice it for active/reserve views
    full_tbl = build_roster_table(df)
    active_raw, reserve_raw = split_active_reserve(df)
    # For active/reserve sub-tables, build a Name set from each and slice full_tbl
    active_names  = set(active_raw['Name'].astype(str)) if not active_raw.empty else set()
    reserve_names = set(reserve_raw['Name'].astype(str)) if not reserve_raw.empty else set()
    active_tbl    = full_tbl[full_tbl['Name'].isin(active_names)].copy()
    reserve_tbl   = full_tbl[full_tbl['Name'].isin(reserve_names)].copy()

    # ── Header strip — always visible ────────────────────────────────────────
    payroll_curr = _s(tc.get('payroll_current', 0))
    tax_thresh   = _s(tc.get('tax_threshold', 0))
    headroom     = tax_thresh - payroll_curr if tax_thresh > 0 else 0
    over_tax     = payroll_curr > tax_thresh and tax_thresh > 0

    # Only show payroll column if Team Config has a value set — otherwise use a 4-col layout
    show_payroll = payroll_curr > 0 or tax_thresh > 0
    if show_payroll:
        h1, h2, h3, h4, h5 = st.columns(5)
    else:
        h1, h2, h3, h4 = st.columns(4)

    h1.metric("Team",     my_team)
    h2.metric("Mode",     mode)
    h3.metric("Active",   len(active_tbl))
    h4.metric("Reserve",  len(reserve_tbl))
    if show_payroll:
        if tax_thresh > 0:
            h5.metric(
                "Payroll",
                f"${int(payroll_curr):,}",
                delta=(
                    f"${int(headroom):,} under" if not over_tax
                    else f"${int(-headroom):,} OVER"
                ),
                delta_color=('normal' if not over_tax else 'inverse'),
            )
        else:
            h5.metric("Payroll", f"${int(payroll_curr):,}")

    # Top-level construction warnings — surface here, don't bury
    construction = diagnose_roster_construction(active_tbl) if not active_tbl.empty else []
    errors = [i for i in construction if i['level'] == 'error']
    warns  = [i for i in construction if i['level'] == 'warn']
    if errors:
        for i in errors:
            st.error(f"⛔ {i['msg']}")
    if warns:
        for i in warns:
            st.warning(f"⚠️ {i['msg']}")
    if not errors and not warns and construction:
        st.success("✅ Roster construction passes all hard-rule checks.")

    st.markdown("---")

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab_roster, tab_view, tab_config = st.tabs([
        "🧢 Roster",
        "📊 Team View",
        "⚙️ Auto-Config",
    ])

    with tab_roster:
        _render_roster_tab(active_tbl, reserve_tbl, full_tbl)

    with tab_view:
        _render_team_view_tab(active_tbl, reserve_tbl, full_tbl, tc, league)

    with tab_config:
        _render_autoconfig_tab(full_tbl, tc, mode, league)


# ── ROSTER TAB ───────────────────────────────────────────────────────────────
def _render_roster_tab(active_tbl, reserve_tbl, full_tbl):
    st.subheader("🧢 Roster")

    # Active / Reserve / All filter
    view = st.radio(
        "View",
        ['Active 25', 'Reserve', 'All'],
        horizontal=True,
        key='myteam_roster_view',
    )

    if view == 'Active 25':
        tbl = active_tbl
    elif view == 'Reserve':
        tbl = reserve_tbl
    else:
        tbl = full_tbl

    if tbl.empty:
        st.info(f"No players in {view}.")
        return

    # Bat / Pit sub-tabs
    bat_tbl = tbl[tbl['POS'].isin(BATTER_POSITIONS)]
    pit_tbl = tbl[tbl['POS'].isin(PITCHER_POSITIONS)]

    sub_bat, sub_pit = st.tabs([
        f"⚾ Batters ({len(bat_tbl)})",
        f"🥎 Pitchers ({len(pit_tbl)})",
    ])

    bat_cols = [c for c in [
        'Name', 'POS', 'Age', 'F1', 'TV', 'Control', 'Svc_Yrs', 'Arb',
        'Salary', 'Yrs_Left',
        'CON', 'POW', 'GAP', 'EYE', 'SPE',
        'Flex', 'Luck', 'Flags',
    ] if c in bat_tbl.columns]

    pit_cols = [c for c in [
        'Name', 'POS', 'Age', 'F1', 'TV', 'Control', 'Svc_Yrs', 'Arb',
        'Salary', 'Yrs_Left',
        'STU', 'MOV', 'PIT_CON', 'STM', 'CNT_eff',
        'Flags',
    ] if c in pit_tbl.columns]

    with sub_bat:
        if bat_tbl.empty:
            st.info("No batters in this view.")
        else:
            st.caption(
                "**Flex** shows positions the player could play besides their listed one — "
                "`PLUS@X` = projected ZR clears the plus-defender floor at X, "
                "`+X` = projected ZR clears the playability floor at X. "
                "Flex is ZR-driven from underlying fielding ratings, not current position eligibility."
            )
            st.dataframe(
                bat_tbl[bat_cols],
                use_container_width=True,
                hide_index=True,
                height=520,
            )

    with sub_pit:
        if pit_tbl.empty:
            st.info("No pitchers in this view.")
        else:
            st.caption(
                "**CNT_eff** = pitches at grade ≥30 (usability threshold). "
                "**SP-CAPABLE** = STM ≥45 and 3+ effective pitches; tagged on RPs who could be stretched out. "
                "**LOW-CON** = PIT_CON < 40. **THIN-ARSENAL** = listed SP with fewer than 3 effective pitches."
            )
            st.dataframe(
                pit_tbl[pit_cols],
                use_container_width=True,
                hide_index=True,
                height=520,
            )


# ── TEAM VIEW TAB ────────────────────────────────────────────────────────────
def _render_team_view_tab(active_tbl, reserve_tbl, full_tbl, tc, league):
    st.subheader("📊 Team View")

    # ── WAR pace ─────────────────────────────────────────────────────────────
    active_f1_sum  = active_tbl['F1'].sum()  if not active_tbl.empty else 0.0
    reserve_f1_sum = reserve_tbl['F1'].sum() if not reserve_tbl.empty else 0.0
    full_f1_sum    = full_tbl['F1'].sum()    if not full_tbl.empty else 0.0

    w1, w2, w3 = st.columns(3)
    w1.metric("Active F1 sum",  f"{active_f1_sum:.1f}")
    w2.metric("Reserve F1 sum", f"{reserve_f1_sum:.1f}")
    w3.metric("Total F1 sum",   f"{full_f1_sum:.1f}")
    st.caption(
        "F1 sum approximates projected season WAR for the listed group. "
        "Treat tier-level (above 30 = contender, 20-30 = competitive, below 20 = rebuilder) as reliable; "
        "exact totals are approximate (R²=0.738 for batter F1)."
    )

    st.markdown("---")

    # ── F1 by position ───────────────────────────────────────────────────────
    st.markdown("#### F1 by Position")
    pos_breakdown = f1_by_position(full_tbl)
    if not pos_breakdown.empty:
        st.dataframe(
            pos_breakdown,
            use_container_width=True,
            hide_index=True,
            height=420,
        )
        st.caption(
            "Best = top F1 at the position. Avg = mean. Total = sum (depth indicator). "
            "Empty rows indicate positions with no listed players — possible holes."
        )

    st.markdown("---")

    # ── Service time dashboard ───────────────────────────────────────────────
    st.markdown("#### Service Time")
    if full_tbl.empty:
        st.info("No players loaded.")
        return

    pre_arb = full_tbl[full_tbl['Arb'] == 'Pre-Arb']
    arb     = full_tbl[full_tbl['Arb'] == 'Arb']
    fa_elig = full_tbl[full_tbl['Arb'] == 'FA-Elig']

    s1, s2, s3 = st.columns(3)
    s1.metric("Pre-Arb",  len(pre_arb), help="<3 service years — cost-controlled")
    s2.metric("Arb-Elig", len(arb),     help="3-5 service years — arbitration salaries")
    s3.metric("FA-Elig",  len(fa_elig), help="6+ service years — free agent at end of contract")

    svc_cols = ['Name', 'POS', 'Age', 'F1', 'Svc_Yrs', 'Control', 'Yrs_Left', 'Salary']

    # Players in last year of control — call out specifically
    last_year = full_tbl[(full_tbl['Control'] > 0) & (full_tbl['Control'] <= 1.0)]
    if not last_year.empty:
        st.markdown("**⏰ In last year of control** (decide: extend, trade, or let walk)")
        st.dataframe(
            last_year[svc_cols].sort_values('F1', ascending=False),
            use_container_width=True, hide_index=True, height=200,
        )

    with st.expander(f"Pre-Arb players ({len(pre_arb)})", expanded=False):
        if not pre_arb.empty:
            st.dataframe(
                pre_arb[svc_cols].sort_values('F1', ascending=False),
                use_container_width=True, hide_index=True,
            )

    with st.expander(f"Arb-eligible players ({len(arb)})", expanded=False):
        if not arb.empty:
            st.dataframe(
                arb[svc_cols].sort_values('F1', ascending=False),
                use_container_width=True, hide_index=True,
            )

    with st.expander(f"FA-eligible players ({len(fa_elig)})", expanded=False):
        if not fa_elig.empty:
            st.dataframe(
                fa_elig[svc_cols].sort_values('F1', ascending=False),
                use_container_width=True, hide_index=True,
            )


# ── AUTO-CONFIG TAB ──────────────────────────────────────────────────────────
def _render_autoconfig_tab(full_tbl, tc, mode, league):
    st.subheader("⚙️ Auto-Config")
    st.caption(
        "Auto-detected need and surplus positions from your roster. "
        "Review, edit, and apply to Team Config — Acquisitions reads these "
        "values when scoring fit."
    )

    if full_tbl.empty:
        st.info("Load a roster to see auto-detected needs.")
        return

    detected_needs, detected_surplus = detect_needs_and_surplus(full_tbl, mode)
    current_needs   = tc.get('need_positions', [])
    current_surplus = tc.get('surplus_positions', [])

    st.markdown(f"**Mode:** {mode} — need threshold = best F1 below {NEED_FLOORS.get(mode, 2.0)}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Auto-detected NEEDS**")
        if detected_needs:
            st.code(', '.join(detected_needs), language=None)
        else:
            st.caption("None detected — every position clears the floor.")

        st.markdown("**Currently saved**")
        st.code(', '.join(current_needs) if current_needs else '(none)', language=None)

    with c2:
        st.markdown("**Auto-detected SURPLUS**")
        if detected_surplus:
            st.code(', '.join(detected_surplus), language=None)
        else:
            st.caption("None detected — no position has 2+ quality players.")

        st.markdown("**Currently saved**")
        st.code(', '.join(current_surplus) if current_surplus else '(none)', language=None)

    st.markdown("---")
    st.markdown("**Edit before applying**")

    all_positions = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'SP', 'RP']

    edited_needs = st.multiselect(
        "Needs (will be saved to Team Config)",
        options=all_positions,
        default=detected_needs,
        key='myteam_edit_needs',
    )
    edited_surplus = st.multiselect(
        "Surplus (will be saved to Team Config)",
        options=all_positions,
        default=detected_surplus,
        key='myteam_edit_surplus',
    )

    apply_col, _ = st.columns([1, 3])
    with apply_col:
        if st.button("💾 Apply to Team Config", type='primary', key='myteam_apply'):
            league.save_team_config({
                'need_positions':    edited_needs,
                'surplus_positions': edited_surplus,
            })
            st.success("Saved. Acquisitions will use these values for fit scoring.")
            st.rerun()

    # Untouchables overview
    st.markdown("---")
    st.markdown("**Untouchables**")
    untouchables = tc.get('untouchables', [])
    if untouchables:
        # Look them up in the roster
        un_set = {u.lower().strip() for u in untouchables}
        un_rows = full_tbl[full_tbl['Name'].str.lower().str.strip().isin(un_set)]
        if not un_rows.empty:
            st.dataframe(
                un_rows[['Name', 'POS', 'Age', 'F1', 'TV', 'Control', 'Salary']],
                use_container_width=True, hide_index=True,
            )
        # Anything in the untouchables list that's not on the roster?
        on_roster = {n.lower().strip() for n in un_rows['Name'].tolist()}
        orphans   = [u for u in untouchables if u.lower().strip() not in on_roster]
        if orphans:
            st.caption(f"⚠️ In untouchables list but not on roster: {', '.join(orphans)}")
    else:
        st.caption("No untouchables listed. Add them in ⚙️ Settings → Team Config.")
