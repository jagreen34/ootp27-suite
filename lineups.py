"""
OOTP 27 Suite — Lineups Module (Depth Chart + Lineup Optimizer)
================================================================
Two tabs, Acquisitions-style:
  📋 Depth Chart  — every eligible player ranked at every position, with the
                    OFF / DEF / POS_ADJ / total-WAR-at-position breakdown so the
                    defensive tax is explicit. Per-player position LOCKS live here.
  ⚾ Lineup       — Hungarian-optimal alignment over the UNLOCKED field slots,
                    plus The Book (Tango) batting order. Pitcher bats 9th (no-DH).

Design decisions (locked in design review, May 2026):
  • Reads the saved roster from league.get_last_roster() — same upload that powers
    My Team. Upload-to-replace fallback for landing here first (same engine guard).
  • Ranking currency is TOTAL WAR-at-position = off_f1 + def_war(pos) + pos_adj(pos),
    evaluated at the CANDIDATE position (not the player's listed one). This is
    batter_f1 generalised across positions. The 253K study confirmed the bat
    dominates and the premium-position defensive tax is mild (~1.2x); defense is a
    real subtracted cost in the WAR math, not a hard wall — EXCEPT where Jeff's own
    gameplay rule sets a floor.
  • Eligibility is gated on PREDICTED ZR (from acquisitions.ZR_MODELS), not realized
    ZR. Realized ZR in the export may be position-blended for multi-position players;
    predicted ZR from ratings is immune to that. Floors are EDITABLE per position.
  • No-DH: exactly 8 field slots, every one must be filled by a position player.
  • Catcher locked by default — the C DEF model is weak (R²=0.21) and catcher ZR
    barely moves, so the model can't discriminate catchers; Jeff picks the C.
  • Locks: per-player lock is the core mechanism. "Lock whole chart" is one button
    that locks all current optimal assignments at once (same machinery).

ZR-anchored floor defaults (back-solved from Jeff's stated rating rules):
  SS  : IF_RNG ≥ 60  → predicted ZR floor
  CF  : OF_RNG ≥ 60  → predicted ZR floor
  2B  : IF_RNG ≥ 50  → predicted ZR floor
  3B  : range + arm gate (arm is engine-supported at 3B, IF_ARM β=+0.2642)
  LF/RF: minimal (bat-first)
  1B  : near-zero ("wears a glove")
  C   : locked by default (no usable ZR signal)
"""

import numpy as np
import pandas as pd
import streamlit as st
from scipy.optimize import linear_sum_assignment

from db import League

from acquisitions import (
    prep_data,
    off_f1, def_war, pos_adj, batter_f1,
    ZR_MODELS, ZR_WAR_FACTOR,
    POS_ADJ_CONSTANTS,
    BATTER_POSITIONS, PITCHER_POSITIONS,
    _s,
)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

# The 8 field positions, in defensive-spectrum order (glove-priority high → low).
# This order also drives display and the "premium vs corner" framing.
FIELD_POSITIONS = ['C', 'SS', 'CF', '2B', '3B', 'RF', 'LF', '1B']

# Display order for the lineup card (conventional left-to-right field order).
CARD_ORDER = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']

# ── ZR ELIGIBILITY FLOORS (predicted-ZR units) ───────────────────────────────
# Defaults are back-solved from Jeff's stated rating rules through ZR_MODELS at a
# league-average arm. e.g. SS IF_RNG=60 → predicted ZR ≈ +6 via the SS model.
# These are the DEFAULTS; the UI lets Jeff edit each one directly.
#
# Anchoring math (for reference, computed from the augmented K-T ZR_MODELS):
#   SS  ZR = -97.44 + 1.1074*IF_RNG + 0.4221*IF_ARM + 0.1589*IF_ERR ; @RNG60,ARM60,ERR55 ≈ +3.1
#   CF  ZR = -80.38 + 1.3874*OF_RNG                                 ; @RNG60             ≈ +2.9
#   2B  ZR = -75.46 + 1.0723*IF_RNG + 0.1578*IF_ARM + 0.1372*IF_ERR ; @RNG50,ARM55,ERR55 ≈ -5.6
# The raw back-solve gives uneven numbers; we round to clean, slightly-conservative
# floors that preserve the spectrum (SS/CF strict, 2B moderate, rest loose).
DEFAULT_ZR_FLOORS = {   # PROVISIONAL — re-stated on augmented K-T ZR_MODELS (encoded rating rules preserved)
    'C':   -99.0,   # locked by default — floor effectively off
    'SS':    3.0,   # strict (IF_RNG ≥ 60 → +3.1 under new SS model; unchanged)
    'CF':    3.0,   # strict (OF_RNG ≥ 60 → +2.9 under new CF model; was 6.0 — steeper A26 CF model)
    '2B':   -5.5,   # moderate (IF_RNG ≥ 50 → -5.6 under new 2B model; was -1.0)
    '3B':   -6.0,   # looser; arm-gated below (THIRD_BASE_ARM_FLOOR does the real work) — keep
    'RF':  -99.0,   # bat-first
    'LF':  -99.0,   # bat-first
    '1B':  -99.0,   # "wears a glove"
}

# 3B is the one corner-ish spot where arm is engine-supported (IF_ARM β=+0.2642,
# nearly tied with range). Gate on a modest raw IF_ARM in addition to ZR.
THIRD_BASE_ARM_FLOOR = 45

# Catcher locked-by-default
CATCHER_LOCK_DEFAULT = True

# Infeasible-cell sentinel for the assignment matrix
_NEG = -1.0e6


# ══════════════════════════════════════════════════════════════════════════════
# ZR PREDICTION + ELIGIBILITY
# ══════════════════════════════════════════════════════════════════════════════

def predict_zr(row, pos: str) -> float:
    """Predicted full-season ZR at a position from underlying fielding ratings.
    Mirrors my_team.predict_zr — uses acquisitions.ZR_MODELS. Returns 0.0 if the
    position is not modeled."""
    if pos not in ZR_MODELS:
        return 0.0
    m = ZR_MODELS[pos]
    zr = m['intercept']
    for col, coef in m['coefs'].items():
        zr += _s(row.get(col, 0)) * coef
    return zr


def is_eligible(row, pos: str, zr_floors: dict) -> bool:
    """Eligibility gate for a position: predicted ZR clears the (editable) floor.
    3B additionally requires a modest arm. Catcher is always 'eligible' here —
    catcher assignment is governed by the lock, not the ZR floor."""
    if pos == 'C':
        return True  # governed by lock; ZR model can't discriminate catchers
    if predict_zr(row, pos) < zr_floors.get(pos, DEFAULT_ZR_FLOORS.get(pos, -99.0)):
        return False
    if pos == '3B' and _s(row.get('IF_ARM', 0)) < THIRD_BASE_ARM_FLOOR:
        return False
    return True


def war_at_position(row, pos: str) -> float:
    """Total projected WAR for this player AT this position =
    OFF (position-independent) + DEF_WAR(pos) + POS_ADJ(pos).
    This is batter_f1 generalised to an arbitrary candidate position."""
    return off_f1(row) + def_war(row, pos) + pos_adj(row, pos)


# ══════════════════════════════════════════════════════════════════════════════
# DEPTH CHART
# ══════════════════════════════════════════════════════════════════════════════

def build_depth_chart(bats_df: pd.DataFrame, zr_floors: dict) -> dict:
    """
    For each field position, return a list of eligible players ranked by total
    WAR-at-position (best first), each with the component breakdown.

    Returns: { 'SS': [ {Name, OFF, DEF, POS_ADJ, WAR, ZR, listed}, ... ], ... }
    """
    recs = bats_df.to_dict('records')
    chart = {}
    for pos in FIELD_POSITIONS:
        rows = []
        for r in recs:
            if not is_eligible(r, pos, zr_floors):
                continue
            off = off_f1(r)
            dfw = def_war(r, pos)
            padj = pos_adj(r, pos)
            rows.append({
                'Name':    str(r.get('Name', '')),
                'Listed':  str(r.get('POS', '')),
                'Age':     int(_s(r.get('AGE', r.get('Age', 0)))),
                'OFF':     round(off, 2),
                'DEF':     round(dfw, 2),
                'POS_ADJ': round(padj, 2),
                'WAR':     round(off + dfw + padj, 2),
                'ZR':      round(predict_zr(r, pos), 1),
            })
        rows.sort(key=lambda x: x['WAR'], reverse=True)
        chart[pos] = rows
    return chart


# ══════════════════════════════════════════════════════════════════════════════
# HUNGARIAN OPTIMIZER
# ══════════════════════════════════════════════════════════════════════════════

def optimize_lineup(bats_df: pd.DataFrame, zr_floors: dict,
                    locks: dict) -> dict:
    """
    Assign position players to the 8 field slots maximizing total WAR-at-position.

    locks: { 'SS': 'Player Name', ... } — pre-assigned slots. Locked slots are
           removed from the optimization; the named player is forced there (even
           if they'd fail the ZR floor — a manual lock overrides the gate, by
           design: Jeff's call beats the model's).

    Returns:
      {
        'assignment': { pos: {Name, OFF, DEF, POS_ADJ, WAR, locked: bool} | None },
        'total_war':  float,
        'unfilled':   [pos, ...],            # slots with no eligible/available player
        'bench':      [ {Name, best_pos, WAR} ... ],  # eligible bats not starting
      }
    """
    recs = bats_df.to_dict('records')
    by_name = {str(r.get('Name', '')): r for r in recs}

    assignment = {p: None for p in FIELD_POSITIONS}
    used_names = set()

    # 1) Apply locks first (manual lock overrides ZR floor)
    for pos, name in (locks or {}).items():
        if pos not in FIELD_POSITIONS:
            continue
        r = by_name.get(name)
        if r is None:
            continue  # locked player not on roster (e.g. stale lock) — skip
        assignment[pos] = {
            'Name':    name,
            'OFF':     round(off_f1(r), 2),
            'DEF':     round(def_war(r, pos), 2),
            'POS_ADJ': round(pos_adj(r, pos), 2),
            'WAR':     round(war_at_position(r, pos), 2),
            'locked':  True,
        }
        used_names.add(name)

    # 2) Optimize the remaining (open) slots over the remaining (unused) players
    open_slots = [p for p in FIELD_POSITIONS if assignment[p] is None]
    cand = [(str(r.get('Name', '')), r) for r in recs
            if str(r.get('Name', '')) not in used_names]

    if open_slots and cand:
        M = np.full((len(cand), len(open_slots)), _NEG)
        for i, (_, r) in enumerate(cand):
            for j, pos in enumerate(open_slots):
                if is_eligible(r, pos, zr_floors):
                    M[i, j] = war_at_position(r, pos)
        rows_idx, cols_idx = linear_sum_assignment(-M)
        for i, j in zip(rows_idx, cols_idx):
            pos = open_slots[j]
            if M[i, j] <= -1.0e5:
                continue  # infeasible — leave slot unfilled
            name, r = cand[i]
            assignment[pos] = {
                'Name':    name,
                'OFF':     round(off_f1(r), 2),
                'DEF':     round(def_war(r, pos), 2),
                'POS_ADJ': round(pos_adj(r, pos), 2),
                'WAR':     round(war_at_position(r, pos), 2),
                'locked':  False,
            }
            used_names.add(name)

    unfilled = [p for p in FIELD_POSITIONS if assignment[p] is None]
    total_war = round(sum(a['WAR'] for a in assignment.values() if a), 2)

    # 3) Bench = eligible bats who didn't start, with their best position
    bench = []
    for r in recs:
        nm = str(r.get('Name', ''))
        if nm in used_names:
            continue
        best_pos, best_war = None, _NEG
        for pos in FIELD_POSITIONS:
            if is_eligible(r, pos, zr_floors):
                w = war_at_position(r, pos)
                if w > best_war:
                    best_war, best_pos = w, pos
        if best_pos is not None:
            bench.append({'Name': nm, 'best_pos': best_pos, 'WAR': round(best_war, 2)})
    bench.sort(key=lambda x: x['WAR'], reverse=True)

    return {
        'assignment': assignment,
        'total_war':  total_war,
        'unfilled':   unfilled,
        'bench':      bench,
    }


def diagnose_unfilled(pos: str, bats_df: pd.DataFrame, zr_floors: dict,
                      locks: dict) -> str:
    """
    Explain WHY a field slot couldn't be filled, naming the cause:
      - no bat clears the floor, or
      - the only eligible bat(s) are locked to other slots.
    Returns a one-line, actionable message.
    """
    recs = bats_df.to_dict('records')
    floor = zr_floors.get(pos, DEFAULT_ZR_FLOORS.get(pos, -99.0))

    eligible = [str(r.get('Name', '')) for r in recs if is_eligible(r, pos, zr_floors)]
    # who is locked to OTHER positions
    locked_elsewhere = {name: p for p, name in (locks or {}).items() if p != pos}
    eligible_but_locked = [(n, locked_elsewhere[n]) for n in eligible if n in locked_elsewhere]
    eligible_free = [n for n in eligible if n not in locked_elsewhere]

    if not eligible:
        return (f"**{pos}**: no bat clears the +{floor:g} ZR floor. "
                f"Lower the {pos} floor in Eligibility floors above, or lock a player "
                f"into {pos} (a lock overrides the floor).")

    if not eligible_free and eligible_but_locked:
        who = ', '.join(f"{n} → {p}" for n, p in eligible_but_locked)
        return (f"**{pos}**: the only eligible bat(s) are locked elsewhere ({who}). "
                f"Unlock one of them, lower another position's floor to free a "
                f"substitute, or lock a player into {pos}.")

    # eligible_free non-empty but slot still unfilled → consumed by the assignment
    # (their value was higher at another open slot). Rare; give a generic nudge.
    return (f"**{pos}**: eligible bats exist ({', '.join(eligible_free[:3])}…) but the "
            f"optimizer placed them at higher-value slots. Lock your preferred {pos} "
            f"to force the assignment.")


# ══════════════════════════════════════════════════════════════════════════════
# BATTING ORDER — THE BOOK (TANGO/LICHTMAN/DOLPHIN)
# ══════════════════════════════════════════════════════════════════════════════
#
# The Book's rule: your 3 best hitters bat in #1/#2/#4; 4th & 5th best in #3/#5;
# 6-9 in descending quality. Within the top group, higher-OBP up top (1/2),
# bigger-SLG at 4. We operationalise with rating-based proxies:
#   "OPS / overall bat" → off_f1 (blends POW/BABIP/EYE/CON/AVK/GAP)
#   "OBP skill"         → EYE + AVK + BABIP_rating
#   "SLG skill"         → POW + GAP
#
# Fill sequence (per the operationalised Book method):
#   2 ← best OFF ; 4 ← 2nd OFF ; 1 ← best remaining OBP ; 5 ← best remaining SLG ;
#   3 ← next SLG ; 6-9 ← descending OFF.
# Worth ~1 win/season — a starting point, freely hand-editable; does NOT affect
# the defensive assignment.

def _obp_skill(r) -> float:
    return (_s(r.get('EYE', 0)) + _s(r.get('AVK', 0))
            + _s(r.get('BAT_BABIP_RATING', r.get('BABIP', 0))))


def _slg_skill(r) -> float:
    return _s(r.get('POW', 0)) + _s(r.get('GAP', 0))


def book_batting_order(starters: list[dict]) -> list[dict]:
    """
    starters: list of {Name, row, pos} for the 8 position players (pitcher added
    separately at #9). Returns ordered list of {slot, Name, pos} for slots 1-8.
    """
    pool = list(starters)
    if not pool:
        return []

    def take(key, remaining):
        best = max(remaining, key=key)
        remaining.remove(best)
        return best

    order = {}
    rem = list(pool)

    # 2 ← best OFF, 4 ← 2nd OFF
    if rem: order[2] = take(lambda s: off_f1(s['row']), rem)
    if rem: order[4] = take(lambda s: off_f1(s['row']), rem)
    # 1 ← best remaining OBP
    if rem: order[1] = take(lambda s: _obp_skill(s['row']), rem)
    # 5 ← best remaining SLG
    if rem: order[5] = take(lambda s: _slg_skill(s['row']), rem)
    # 3 ← next remaining SLG
    if rem: order[3] = take(lambda s: _slg_skill(s['row']), rem)
    # 6-9 ← descending OFF
    rem.sort(key=lambda s: off_f1(s['row']), reverse=True)
    slot = 6
    for s in rem:
        order[slot] = s
        slot += 1

    out = []
    for slot in sorted(order.keys()):
        s = order[slot]
        out.append({'slot': slot, 'Name': s['Name'], 'pos': s['pos']})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE (locks + floors live in config.json via league.save_config)
# ══════════════════════════════════════════════════════════════════════════════

def _load_lineup_state(league: League) -> dict:
    cfg = league.get_config()
    state = cfg.get('lineup_state', {})
    return {
        'locks':       state.get('locks', {}),
        'zr_floors':   {**DEFAULT_ZR_FLOORS, **state.get('zr_floors', {})},
        'chart_locked': state.get('chart_locked', False),
    }


def _save_lineup_state(league: League, locks: dict, zr_floors: dict,
                       chart_locked: bool):
    league.save_config({'lineup_state': {
        'locks':        locks,
        'zr_floors':    zr_floors,
        'chart_locked': chart_locked,
    }})


# ══════════════════════════════════════════════════════════════════════════════
# ROSTER LOADING (mirrors my_team: engine guard + ORG filter + prep)
# ══════════════════════════════════════════════════════════════════════════════

def _load_roster(league: League, my_team: str):
    """Return (df_prepped_for_my_team_or_None, error_or_None)."""
    saved = league.get_last_roster()
    if saved is None or saved.empty:
        return None, None
    df = saved.copy()
    if 'ORG' in df.columns:
        df = df[df['ORG'].astype(str).str.strip() == my_team].copy()
    if df.empty:
        return None, f"No players for '{my_team}' in the saved roster. Re-upload in My Team."
    return df, None


def _ingest_upload(uploaded, my_team: str):
    """Engine-guard + ORG-filter + prep an uploaded CSV. Returns (df, error)."""
    try:
        raw = pd.read_csv(uploaded, encoding='utf-8-sig', low_memory=False)
    except Exception as e:
        return None, f"Failed to read CSV: {e}"

    v27 = {'CON_1', 'BABIP_1', 'WAR_1'}
    v26 = {'CON.1', 'BABIP.1', 'WAR.1'}
    cols = set(raw.columns)
    if (v26 & cols) and not (v27 & cols):
        return None, ("⛔ This looks like an OOTP 26 export, not OOTP 27. The column "
                      "structures differ between engines and F1 values would be wrong. "
                      "Use the OOTP 26 suite, or re-export from OOTP 27.")

    team_col = next((c for c in ('ORG', 'TM', 'Team') if c in raw.columns), None)
    if team_col is None:
        return None, "CSV has no ORG, TM, or Team column to filter on."

    team_rows = raw[raw[team_col].astype(str).str.strip() == my_team]
    if team_rows.empty:
        avail = ', '.join(sorted(raw[team_col].astype(str).unique())[:8])
        return None, (f"No players with {team_col} == '{my_team}'. Check the team name "
                      f"in Settings matches the export. Some teams present: {avail}...")

    return prep_data(team_rows.copy()), None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render_lineups(league: League):
    st.header("⚾ Lineups")

    tc = league.team_config
    my_team = tc.get('my_team', '')
    if not my_team:
        st.warning("Set your team in ⚙️ Settings before using Lineups.")
        return

    # ── Load roster (saved first; upload-to-replace fallback) ──────────────────
    df, err = _load_roster(league, my_team)
    if err:
        st.error(err)

    with st.expander("📤 Upload roster CSV" + ("" if df is None else " (replace current)"),
                     expanded=df is None):
        st.caption(
            "Lineups uses the same saved roster as My Team. Upload here only to "
            "replace it. Full league export or team-only export both work — it "
            "filters to your team via ORG."
        )
        up = st.file_uploader("Roster CSV", type=['csv'], key='lineup_upload')
        if up is not None:
            uid = f"{up.name}:{up.size}"
            if st.session_state.get('_lineup_upload_id') != uid:
                new_df, uerr = _ingest_upload(up, my_team)
                if uerr:
                    st.error(uerr)
                else:
                    league.save_last_roster(new_df)
                    st.session_state['_lineup_upload_id'] = uid
                    st.success(f"Roster saved — {len(new_df)} players from {my_team}.")
                    st.rerun()

    if df is None:
        st.info("Upload a roster CSV (here or in My Team) to begin.")
        return

    bats = df[df['POS'].isin(BATTER_POSITIONS)].copy()
    pits = df[df['POS'].isin(PITCHER_POSITIONS)].copy()
    if bats.empty:
        st.error("No position players found in the roster.")
        return

    # ── Load persisted state ───────────────────────────────────────────────────
    state = _load_lineup_state(league)
    locks = dict(state['locks'])
    zr_floors = dict(state['zr_floors'])
    chart_locked = state['chart_locked']

    # Default catcher lock (only if no catcher lock set yet and feature on)
    if CATCHER_LOCK_DEFAULT and 'C' not in locks:
        cers = bats[bats['POS'] == 'C']
        if not cers.empty:
            # lock the best-bat catcher by default
            best_c = max(cers.to_dict('records'), key=lambda r: off_f1(r))
            locks['C'] = str(best_c.get('Name', ''))

    bat_names = sorted(bats['Name'].astype(str).tolist())

    tab_depth, tab_lineup = st.tabs(["📋 Depth Chart", "⚾ Lineup"])

    with tab_depth:
        _render_depth_tab(league, bats, bat_names, locks, zr_floors, chart_locked)

    with tab_lineup:
        _render_lineup_tab(league, bats, pits, locks, zr_floors)


# ── DEPTH CHART TAB ───────────────────────────────────────────────────────────
def _render_depth_tab(league, bats, bat_names, locks, zr_floors, chart_locked):
    st.subheader("📋 Depth Chart")
    st.caption(
        "Every eligible bat ranked at every position by **total WAR-at-position** "
        "(OFF + DEF + POS_ADJ). DEF is the ZR-driven defensive tax — a big bat with "
        "a poor glove still ranks well, it just pays in the DEF column. Eligibility "
        "is gated on **predicted** ZR (from fielding ratings), so multi-position "
        "playing time can't contaminate it."
    )

    # ── Floor editor ───────────────────────────────────────────────────────────
    # Auto-open when the Lineup tab reported an unfilled slot, so the fix is in view.
    _auto_open = bool(st.session_state.get('_lineup_unfilled', False))
    with st.expander("⚙️ Eligibility floors (predicted ZR)", expanded=_auto_open):
        st.caption(
            "A bat is eligible at a position only if its projected full-season ZR "
            "clears the floor. Defaults encode your gameplay rule: strict up the "
            "middle (SS/CF), moderate at 2B, loose at the corners, off at 1B. "
            "3B also requires IF_ARM ≥ "
            f"{THIRD_BASE_ARM_FLOOR} (arm is engine-rewarded at third). "
            "Catcher is governed by the lock, not a floor."
        )
        cols = st.columns(4)
        new_floors = {}
        editable = [p for p in FIELD_POSITIONS if p != 'C']
        for i, pos in enumerate(editable):
            with cols[i % 4]:
                new_floors[pos] = st.number_input(
                    f"{pos} ZR floor",
                    value=float(zr_floors.get(pos, DEFAULT_ZR_FLOORS[pos])),
                    step=1.0, key=f"floor_{pos}",
                )
        new_floors['C'] = zr_floors.get('C', DEFAULT_ZR_FLOORS['C'])
        c1, c2 = st.columns(2)
        if c1.button("💾 Save floors", key='save_floors'):
            _save_lineup_state(league, locks, new_floors, chart_locked)
            st.success("Floors saved.")
            st.rerun()
        if c2.button("↺ Reset to defaults", key='reset_floors'):
            _save_lineup_state(league, locks, dict(DEFAULT_ZR_FLOORS), chart_locked)
            st.success("Floors reset.")
            st.rerun()
        zr_floors = new_floors  # use edited values for this render

    # ── Locks editor ───────────────────────────────────────────────────────────
    st.markdown("#### 🔒 Position locks")
    st.caption(
        "Lock a player to a slot and the optimizer builds the other slots around "
        "them — a manual lock overrides the ZR floor (your call beats the model). "
        "Catcher is locked by default. **Lock whole chart** freezes every current "
        "assignment at once."
    )

    lock_cols = st.columns(4)
    new_locks = dict(locks)
    for i, pos in enumerate(CARD_ORDER):
        with lock_cols[i % 4]:
            current = locks.get(pos, '(open)')
            options = ['(open)'] + bat_names
            idx = options.index(current) if current in options else 0
            choice = st.selectbox(f"{pos}", options, index=idx, key=f"lock_{pos}")
            if choice == '(open)':
                new_locks.pop(pos, None)
            else:
                new_locks[pos] = choice

    b1, b2, b3 = st.columns(3)
    if b1.button("💾 Save locks", key='save_locks'):
        _save_lineup_state(league, new_locks, zr_floors, chart_locked)
        st.success("Locks saved.")
        st.rerun()
    if b2.button("🔒 Lock whole chart", key='lock_chart'):
        # Compute current optimal and freeze every slot as a lock
        result = optimize_lineup(bats, zr_floors, new_locks)
        frozen = {p: a['Name'] for p, a in result['assignment'].items() if a}
        _save_lineup_state(league, frozen, zr_floors, True)
        st.success("Whole chart locked. Clear locks to re-optimize.")
        st.rerun()
    if b3.button("🔓 Clear all locks", key='clear_locks'):
        _save_lineup_state(league, {}, zr_floors, False)
        st.success("All locks cleared.")
        st.rerun()

    st.markdown("---")

    # ── Depth chart tables ─────────────────────────────────────────────────────
    chart = build_depth_chart(bats, zr_floors)
    for pos in FIELD_POSITIONS:
        rows = chart[pos]
        locked_to = locks.get(pos)
        header = f"**{pos}**" + (f"  🔒 {locked_to}" if locked_to else "")
        st.markdown(header)
        if not rows:
            st.caption("— no eligible players clear the floor at this position —")
            continue
        tbl = pd.DataFrame(rows)
        # mark the locked player
        if locked_to:
            tbl.insert(0, '', tbl['Name'].apply(lambda n: '🔒' if n == locked_to else ''))
        st.dataframe(
            tbl[[c for c in ['', 'Name', 'Listed', 'Age', 'OFF', 'DEF', 'POS_ADJ', 'WAR', 'ZR']
                 if c in tbl.columns]],
            use_container_width=True, hide_index=True, height=min(35 * (len(rows) + 1) + 3, 260),
        )


# ── LINEUP TAB ────────────────────────────────────────────────────────────────
def _render_lineup_tab(league, bats, pits, locks, zr_floors):
    st.subheader("⚾ Optimal Lineup")

    result = optimize_lineup(bats, zr_floors, locks)
    assignment = result['assignment']

    if result['unfilled']:
        # Flag the depth tab to auto-open the floors expander next render
        st.session_state['_lineup_unfilled'] = True
        st.error("⛔ Some field slots can't be filled — see why below.")
        for pos in result['unfilled']:
            st.warning(diagnose_unfilled(pos, bats, zr_floors, locks))
        st.caption(
            "Adjust eligibility floors or locks on the **📋 Depth Chart** tab "
            "(the floors panel will be open for you)."
        )
    else:
        st.session_state['_lineup_unfilled'] = False

    # ── Defensive alignment card ───────────────────────────────────────────────
    by_name = {str(r.get('Name', '')): r for r in bats.to_dict('records')}
    starters = []
    align_rows = []
    for pos in CARD_ORDER:
        a = assignment.get(pos)
        if a:
            align_rows.append({
                'POS': pos, 'Player': a['Name'],
                'OFF': a['OFF'], 'DEF': a['DEF'], 'POS_ADJ': a['POS_ADJ'],
                'WAR': a['WAR'], '🔒': '🔒' if a['locked'] else '',
            })
            r = by_name.get(a['Name'])
            if r is not None:
                starters.append({'Name': a['Name'], 'row': r, 'pos': pos})
        else:
            align_rows.append({
                'POS': pos, 'Player': '(unfilled)',
                'OFF': None, 'DEF': None, 'POS_ADJ': None, 'WAR': None, '🔒': '',
            })

    m1, m2 = st.columns(2)
    m1.metric("Total WAR (8 field slots)", f"{result['total_war']:.1f}")
    n_locked = sum(1 for a in assignment.values() if a and a['locked'])
    m2.metric("Locked slots", n_locked)

    st.dataframe(
        pd.DataFrame(align_rows)[['POS', 'Player', '🔒', 'OFF', 'DEF', 'POS_ADJ', 'WAR']],
        use_container_width=True, hide_index=True,
    )
    st.caption(
        "Defensive alignment maximizes total WAR across the 8 no-DH field slots "
        "(Hungarian assignment). DEF is the per-position ZR tax — negative DEF on a "
        "high-OFF bat is the cost of carrying that glove, and the optimizer has "
        "already weighed it. R²=0.738 on batter F1, so trust the tier, not the decimal."
    )

    st.markdown("---")

    # ── Batting order ──────────────────────────────────────────────────────────
    st.markdown("#### Batting order — The Book (Tango)")
    order = book_batting_order(starters)
    order_rows = [{'#': o['slot'], 'Player': o['Name'], 'POS': o['pos']} for o in order]

    # Pitcher 9th (no-DH). Use the projected SP1 if listed, else a placeholder.
    if not pits.empty:
        # best pitcher by simple stuff proxy — informational only
        p_recs = pits.to_dict('records')
        p9 = max(p_recs, key=lambda r: _s(r.get('STU', 0)) + _s(r.get('MOV', 0)))
        order_rows.append({'#': 9, 'Player': f"{p9.get('Name', 'Pitcher')} (P)", 'POS': 'P'})
    else:
        order_rows.append({'#': 9, 'Player': '(pitcher)', 'POS': 'P'})

    st.dataframe(pd.DataFrame(order_rows), use_container_width=True, hide_index=True)
    st.caption(
        "The Book: 3 best bats in slots 1/2/4 (higher-OBP up top, bigger-SLG at 4), "
        "4th–5th best at 3/5, then descending; pitcher 9th (no-DH). Order is worth "
        "~1 win/season — a starting point, freely editable, and it doesn't change "
        "the defensive assignment above."
    )

    # ── Bench ──────────────────────────────────────────────────────────────────
    if result['bench']:
        st.markdown("---")
        st.markdown("#### Bench (eligible bats not starting)")
        bench_rows = [{'Player': b['Name'], 'Best Pos': b['best_pos'], 'WAR@best': b['WAR']}
                      for b in result['bench']]
        st.dataframe(pd.DataFrame(bench_rows), use_container_width=True, hide_index=True,
                     height=min(35 * (len(bench_rows) + 1) + 3, 280))
