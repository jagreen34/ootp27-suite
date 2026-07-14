"""
OOTP 27 Suite — Draft Module (Live-Draft Board)
================================================
The one question no other module answers: given a PRE-DRAFT prospect pool
(ORG="-", ages 17-22, the July-31 draft-day snapshot), what's each prospect's
projected mature WAR, how much do we trust it, and what hard rules apply?

  📋 Board        — F2 live-draft projected CAREER mature WAR (primary rank, BPA).
                    Side columns: Disc WAR (career re-scored on delivery-haircut
                    expected-mature ratings) + Growth-bet (the gap = credited
                    upside), Window WAR (capturable in the AC play window),
                    Projected Trade Value at maturity, and a read-only Need tag
                    from My Team. Nothing reorders silently. A 🔍 inspect panel
                    opens any prospect's per-rating current→potential→discounted
                    breakdown. Round selector drives the "never draft RP before
                    Round 4" warning + slot context.
  🥎 Pitch Grades — H3 priority view: SI > CH > SL > FB prominent (the dominant
                    pitcher signal), STU/MOV demoted (roll-ups). Arsenal flags,
                    BIG-CON-bet, predraft SP-capability, top-pitch gate.
  📐 Methodology  — the locked F2 spec, the per-realization R² (0.376 pitcher /
                    0.325 batter, K-T) and the honest ±1.29/±1.64 WAR error band,
                    the interim-K-T-regime note, pitcher-uncertainty caveat, the
                    unverified-schema / column-audit note, and the park-factor caveat.

Design decisions (locked in design review, May 2026):
  • Per-realization formula lineage (F2 pitcher CV R²=0.376 / batter 0.325, K-T),
    fit on the real K-T data and cross-validated independently by ChatGPT + Gemini
    plus the registry's own v14.0 correction. Supersedes the per-prospect v12 line
    (0.151/0.216): the K-T seeds don't preserve player identity, so a per-prospect
    average is a synthetic blend, while a live draft scores one real realization.
  • Coefficients are DEPLOYED but INTERIM — calibrated to K-T rating distributions,
    re-fit on a real American Circuit draft pool at migration (~July 2026). Swap =
    one localized change in acquisitions.py (the two COEF dicts + intercepts).
  • Primary rank = raw career mature WAR (BPA). Trade value is the relief valve —
    take the best player, convert to need later. Window WAR + Need are
    INFORMATIONAL side columns; they never reorder the board.
  • Pitcher uncertainty is a BLANKET caveat (not a per-prospect SP-dominant flag —
    that classification is deprecated, unknowable at draft day). SP-leaning arms
    can't be fully ranked from draft-day grades; the predictive split signal only
    emerges ~90 days post-draft.
  • Own upload + ORG=="-" filter (inverse of the roster modules) + the same
    engine guard. State in config.json under 'draft_state'. Formulas imported
    from acquisitions.py (single source). Colorblind-safe shape glyphs.
  • FAIL LOUD on missing columns. The draft-pool schema is UNVERIFIED (A1 was
    confirmed against mature exports). audit_draft_columns() gates scoring; a
    missing load-bearing column blocks the board rather than feeding a silent
    zero into the formula. First task on a real draft CSV: reconcile the audit.

Validation: against a REAL OOTP 27 draft-pool export post-migration (~July 2026).
The bundled fixture is a TEST export, not the schema of record; synthetic data
can't fully exercise the predraft regime.
"""

import pandas as pd
import streamlit as st

from db import League
from acquisitions import (
    prep_draft_pool, audit_draft_columns,
    f2_war, f2_batter_war, f2_pitcher_war, f2_is_placeholder,
    f2_discounted_war, delivery_breakdown, draft_pool_has_potentials,
    DELIVERY_AGE_DEFAULTS, delivery_age_mult,
    f2_trade_value, window_war,
    F2_BATTER_R2, F2_PITCHER_R2, F2_BATTER_SD, F2_PITCHER_SD,
    draft_tier, DRAFT_TIER_DEFAULTS, DRAFT_TIER_LABELS, DRAFT_TIER_ICONS,
    draftee_skip_reason, draftee_fragile,
    big_con_bet_flag, pitcher_promised_con_growth,
    predraft_sp_capable, PREDRAFT_PITCH_GATE_DEFAULTS,
    top_pitch_grade, secondary_pitch_count, thin_out_pitch,
    cnt_eff_pitches, hand_str, throws_hand, bats_hand,
    defense_summary, defense_detail, arsenal_detail,
    draft_pool_has_defense, draft_pool_has_handedness,
    glove_war, best_fit_position, position_value_table, draft_pool_can_glove,
    LOW_CONF_DEF_POS,
    PITCHER_POSITIONS, BATTER_POSITIONS,
    _s,
)
from roster_construction import detect_needs_and_surplus   # shared team-need primitive
from my_team import build_roster_table
from rating_scale import _convert_1to100_to_2080   # B3.1: shared scale toggle
import park_fit as pf   # A22 hitter Park Fit Δ — shared additive lens
import edge_confidence as ec   # Edge Stability + Total Value (opt-in composite lens)

# A6: Fragile → −40% projected value.
FRAGILE_VALUE_MULT = 0.60
# A6: never draft RP before Round 4.
RP_ROUND_FLOOR = 4

# Carries the per-build Park Fit Δ profile resolution from build_board → the board
# tab caption (so the fail-loud notice for a non-calibrated park surfaces in the UI).
_DRAFT_PARK_STATUS: dict = {}

# Individual pitch-grade columns in H3 priority order (SI > CH > SL > FB, then
# the rest for display completeness).
PITCH_DISPLAY_ORDER = [
    ('PIT_SI', 'SI'), ('PIT_CH', 'CH'), ('PIT_SL', 'SL'), ('PIT_FB_GR', 'FB'),
    ('PIT_CB', 'CB'), ('PIT_CT', 'CT'), ('PIT_SP', 'SP'),
]


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE (draft_state in config.json — mirrors pitching_state)
# ══════════════════════════════════════════════════════════════════════════════

def _load_draft_state(league: League) -> dict:
    cfg = league.get_config()
    state = cfg.get('draft_state', {})
    return {
        'tier_bands':    {**DRAFT_TIER_DEFAULTS, **state.get('tier_bands', {})},
        'predraft_gate': {**PREDRAFT_PITCH_GATE_DEFAULTS, **state.get('predraft_gate', {})},
        'current_round': int(state.get('current_round', 1)),
        'conf_floor':    float(state.get('conf_floor', 0.85)),
        'tval_base':     state.get('tval_base', 'disc'),
    }


def _save_draft_state(league: League, tier_bands=None, predraft_gate=None,
                      current_round=None, conf_floor=None, tval_base=None):
    cur = _load_draft_state(league)
    payload = {
        'tier_bands':    tier_bands    if tier_bands    is not None else cur['tier_bands'],
        'predraft_gate': predraft_gate if predraft_gate is not None else cur['predraft_gate'],
        'current_round': current_round if current_round is not None else cur['current_round'],
        'conf_floor':    conf_floor    if conf_floor    is not None else cur['conf_floor'],
        'tval_base':     tval_base     if tval_base     is not None else cur['tval_base'],
    }
    league.save_config({'draft_state': payload})


# ══════════════════════════════════════════════════════════════════════════════
# DRAFT-POOL LOADING (own upload, ORG=="-" filter, engine guard, FAIL-LOUD audit)
# ══════════════════════════════════════════════════════════════════════════════

LAST_DRAFT_POOL_LABEL = '__last_draft_pool__'


def _save_draft_pool(league: League, df: pd.DataFrame):
    """Persist the prepped draft pool as its own snapshot (not the roster)."""
    import io
    buf = io.StringIO(); df.to_csv(buf, index=False)
    with league._conn() as c:
        c.execute("DELETE FROM snapshots WHERE label=?", (LAST_DRAFT_POOL_LABEL,))
        c.execute("INSERT INTO snapshots (label, player_count, csv_data) VALUES (?,?,?)",
                  (LAST_DRAFT_POOL_LABEL, len(df), buf.getvalue()))


def _get_draft_pool(league: League):
    import io
    with league._conn() as c:
        row = c.execute("SELECT csv_data FROM snapshots WHERE label=?",
                        (LAST_DRAFT_POOL_LABEL,)).fetchone()
    if row is None:
        return None
    return pd.read_csv(io.StringIO(row['csv_data']), encoding='utf-8', low_memory=False)


def _ingest_draft_upload(uploaded, scale: str = '20-80'):
    """
    Read + engine-guard + ORG=="-" filter + audit + prep a draft-pool CSV.
    Returns (df, audit_report, error). FAILS LOUD: if the column audit finds a
    missing load-bearing F2 column, returns (None, report, None) so the caller
    can show exactly what's missing instead of scoring on silent zeros.

    `scale`: '20-80' (default, the scale the model expects) or '1-100' (converts
    to 20-80 on load via the verified round_to_5(20 + 0.6*v) formula).
    """
    try:
        raw = pd.read_csv(uploaded, encoding='utf-8-sig', low_memory=False)
    except Exception as e:
        return None, None, f"Failed to read CSV: {e}"

    # Scale normalization — BEFORE anything else touches the ratings.
    if scale == '1-100':
        raw = _convert_1to100_to_2080(raw)

    # Engine guard (same signature check as the roster modules).
    v27 = {'CON_1', 'BABIP_1', 'WAR_1'}
    v26 = {'CON.1', 'BABIP.1', 'WAR.1'}
    cols = set(raw.columns)
    if (v26 & cols) and not (v27 & cols):
        return None, None, ("⛔ This looks like an OOTP 26 export, not OOTP 27. "
                            "Column structures differ between engines and F2 values "
                            "would be wrong. Re-export from OOTP 27.")

    # Column audit BEFORE prep — fail loud on missing load-bearing F2 columns.
    report = audit_draft_columns(raw.columns)
    if not report['ok']:
        return None, report, None

    # ORG=="-" filter (the INVERSE of the roster modules). Predraft prospects
    # carry ORG="-"; DRAFT_YR=0 sentinel means we must NOT filter on DRAFT_YR.
    org_col = 'ORG' if 'ORG' in raw.columns else None
    if org_col is None:
        return None, report, "CSV has no ORG column — cannot isolate the predraft pool."
    pool = raw[raw[org_col].astype(str).str.strip() == '-'].copy()
    if pool.empty:
        return None, report, ("No predraft rows (ORG=\"-\") found. A draft-pool export "
                              "should be all unsigned prospects. Check the export.")

    return prep_draft_pool(pool), report, None


# ══════════════════════════════════════════════════════════════════════════════
# BOARD CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════

def _need_set(league: League) -> set:
    """Read-only need positions from My Team's auto-config (if a roster exists)."""
    saved = league.get_last_roster()
    if saved is None or saved.empty:
        return set()
    my_team = league.team_config.get('my_team', '')
    if my_team and 'ORG' in saved.columns:
        saved = saved[saved['ORG'].astype(str).str.strip() == my_team]
    if saved.empty:
        return set()
    try:
        tbl = build_roster_table(saved)
        mode = league.team_config.get('mode', 'Competing')
        needs, _ = detect_needs_and_surplus(tbl, mode)
        return set(needs)
    except Exception:
        return set()


def _row_park_fit(r, pos, is_pit, park_entry):
    """Per-row hitter Park Fit Δ as a full-season (per-650) RATE — the pure
    profile-fit signal. Returns a float WAR/650 or None (pitcher [A23 NULL] /
    uncalibrated park / missing POW|SPE). Never reorders the board — purely
    additive (methodology #6)."""
    if is_pit or park_entry is None or pos not in BATTER_POSITIONS:
        return None
    res = pf.park_fit_rate(dict(r), park_entry['factors'])
    return res['delta_war'] if res['ok'] else None


def build_board(pool_df: pd.DataFrame, league: League, state: dict) -> list[dict]:
    """
    Score every prospect and assemble board rows. Primary sort = career WAR (BPA).
    Window WAR / TV / Need are informational. A6 hard rules applied: auto-skip
    Unmotivated/Disruptive, Fragile −40%, BIG-CON-bet flag, predraft SP-capability
    drives the RP-before-R4 warning.
    """
    needs = _need_set(league)
    gate  = state['predraft_gate']
    # Park Fit Δ (A22, hitters) — additive side lens, computed once per build from
    # Team Config park factors. Fails loud (status carried out via the closure dict
    # below) for any non-calibrated park; NEVER reorders the BPA rank. Draftees use
    # a full-season PA (650) so the column is a per-650 rate comparable across the
    # board (prospects have no MLB PA yet).
    park_profile = pf.profile_from_team_config(league.team_config or {})
    park_entry = pf.match_profile(park_profile)
    _DRAFT_PARK_STATUS.clear()
    _DRAFT_PARK_STATUS.update({
        'ok': park_entry is not None,
        'profile': park_profile,
        'name': park_entry['name'] if park_entry else None,
        'confidence': park_entry['confidence'] if park_entry else None,
    })
    rows = []
    for _, r in pool_df.iterrows():
        pos = str(r.get('POS', '')).strip()
        is_pit = pos in PITCHER_POSITIONS

        skip = draftee_skip_reason(r)
        raw_war = f2_war(r)
        fragile = draftee_fragile(r)
        fmult = FRAGILE_VALUE_MULT if fragile else 1.0
        career = round(raw_war * fmult, 2)
        # Discounted WAR — additive, re-scored on delivery-haircut mature ratings.
        # Same fragile −40% applies (a value haircut independent of delivery).
        disc = round(f2_discounted_war(r) * fmult, 2)
        age = int(_s(r.get('AGE', r.get('Age', 0))))

        # RP-ceiling = pitcher who fails the predraft SP-capability gate.
        rp_ceiling = is_pit and not predraft_sp_capable(r, gate)

        flags = []
        if fragile:               flags.append('FRAGILE-40%')
        if is_pit and _s(r.get('PIT_CON', 0)) < 40: flags.append('LOW-CON')
        bcb = big_con_bet_flag(r)
        if bcb:                   flags.append(bcb)
        if is_pit and thin_out_pitch(r, gate): flags.append('THIN-OUT-PITCH')
        if rp_ceiling:            flags.append('RP-CEILING')

        # Edge Stability + Total Value (opt-in composite). glove/parkfit pulled into
        # locals so the composite reuses the exact additive lenses the board shows.
        glove_local   = (round(glove_war(r), 2) if not is_pit else None)   # A12, batters only
        parkfit_local = _row_park_fit(r, pos, is_pit, park_entry)           # A22, hitters only
        eb = ec.annotate(r, is_pit=is_pit, career=career, disc=disc,
                         glove=glove_local, parkfit=parkfit_local,
                         conf_floor=state['conf_floor'], base=state['tval_base'])

        rows.append({
            'row':       r,
            'name':      str(r.get('Name', '')),
            'pos':       pos,
            'age':       age,
            'career':    career,
            'disc':      disc,
            'growth_bet': round(disc - career, 2),   # gap = credited growth upside
            'window':    window_war(career, age),
            'tv':        f2_trade_value(career, pos),
            'tier':      draft_tier(career, state['tier_bands']),
            'need':      pos in needs,
            'is_pit':    is_pit,
            'rp_ceiling': rp_ceiling,
            'skip':      skip,
            'fragile':   fragile,
            'flags':     ' '.join(flags),
            'top_pitch': int(top_pitch_grade(r)) if is_pit else 0,
            # scouting display (cohort-aware; '—'/'' when a column is absent)
            'bt':        hand_str(r),
            'throws':    throws_hand(r),
            'stm':       int(_s(r.get('STM', 0))) if is_pit else None,
            'npitch':    cnt_eff_pitches(r) if is_pit else None,
            'velo':      int(_s(r.get('velo_mid', 0))) if is_pit else None,
            'def_sum':   defense_summary(r) if not is_pit else None,
            # glove WAR + best-fit (batters only; A12 soft-tax, never reorders)
            'glove':     glove_local,
            'bestfit':   (best_fit_position(r) if not is_pit else None),
            # Park Fit Δ (A22, hitters only; A23 pitcher NULL). PA=650 → per-650
            # rate. None when uncalibrated park / pitcher / missing POW|SPE.
            'parkfit':   parkfit_local,
            # ── Edge Stability + Total Value (opt-in composite; never reorders BPA) ──
            'edge':         eb['edge'],
            'edge_ok':      eb['edge_ok'],
            'edge_reason':  eb['edge_reason'],
            'edge_glyph':   eb['edge_glyph'],
            'edge_drivers': eb['edge_drivers'],
            'grade_flags':  eb['grade_flags'],
            'conf':         eb['conf'],
            'tval':         eb['tval'],
        })

    rows.sort(key=lambda x: x['career'], reverse=True)
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render_draft(league: League):
    st.header("📋 Draft Board")

    if f2_is_placeholder():
        st.warning(
            "⚠️ **PLACEHOLDER F2** — scores run on non-production weights. "
            "Use for relative ordering, not absolute WAR."
        )
    else:
        st.caption(
            "F2 coefficients are fit on real K-T data (per-realization, "
            f"CV R² {F2_PITCHER_R2:.2f} pitcher / {F2_BATTER_R2:.2f} batter) and are "
            "**interim** — calibrated to the K-T rating regime, to be re-fit on a "
            "real American Circuit draft pool at migration. Read the board as tiers; "
            "single-prospect WAR carries a wide error band (see 📐 Methodology)."
        )

    pool = _get_draft_pool(league)

    with st.expander("📤 Upload draft-pool CSV" + ("" if pool is not None else " (required)"),
                     expanded=pool is None):
        st.caption(
            "The draft pool is a SEPARATE export from your roster — the predraft "
            "prospects (ORG=\"-\", ages 17-22). The board filters to ORG=\"-\" and "
            "audits every F2 column before scoring."
        )
        up = st.file_uploader("Draft-pool CSV", type=['csv'], key='draft_upload')
        _scale = st.radio(
            "Rating scale in this file",
            ['20-80', '1-100'],
            horizontal=True,
            key='draft_scale',
            help="OOTP Global Settings → Player Rating Scales. The suite/model is "
                 "built on 20-80. Pick 1-100 if your export used that scale — it's "
                 "converted on load via round_to_5(20 + 0.6×v), verified exact. "
                 "Wrong scale = every prospect reads as replacement-level filler.",
        )
        if up is not None:
            uid = f"{up.name}:{up.size}:{_scale}"
            if st.session_state.get('_draft_upload_id') != uid:
                new_df, report, err = _ingest_draft_upload(up, scale=_scale)
                if err:
                    st.error(err)
                elif report is not None and not report['ok']:
                    # FAIL LOUD — show exactly which load-bearing columns are missing.
                    st.error(
                        "⛔ **Column audit failed.** The export is missing "
                        "load-bearing F2 columns — refusing to score on silent "
                        "zeros. Reconcile the export (select the right tabs/"
                        "columns) and re-upload."
                    )
                    st.markdown("**Missing load-bearing columns:** "
                                + ", ".join(f"`{c}`" for c in report['missing_load_bearing']))
                    if report['missing_display']:
                        st.caption("Missing display-only (non-blocking): "
                                   + ", ".join(report['missing_display']))
                else:
                    _save_draft_pool(league, new_df)
                    st.session_state['_draft_upload_id'] = uid
                    if report.get('missing_display'):
                        st.info("Loaded. Some display-only fields are absent: "
                                + ", ".join(report['missing_display']))
                    st.success(f"Draft pool saved — {len(new_df)} predraft prospects.")
                    st.rerun()

    if pool is None:
        st.info("Upload a draft-pool CSV to begin. (The bundled fixture is a TEST "
                "export — validate against a real OOTP 27 draft pool post-migration.)")
        return

    state = _load_draft_state(league)
    rows = build_board(pool, league, state)
    pot_active  = draft_pool_has_potentials(pool)
    def_active  = draft_pool_has_defense(pool)
    hand_active = draft_pool_has_handedness(pool)
    glove_active = draft_pool_can_glove(pool)

    # ── Flat spreadsheet export (all raw ratings + all 12 pitch types +
    #    A31 effective-ceiling + derived engine fields). Slice-it-yourself board.
    try:
        from draft_export import board_to_dataframe, write_board_xlsx
        _exp_df = board_to_dataframe(rows, pool)
        _exp_path = write_board_xlsx(_exp_df, league)
        with open(_exp_path, 'rb') as _fh:
            st.download_button(
                "⬇️ Export board (.xlsx)",
                data=_fh.read(),
                file_name=f"draft_board{('_'+str(getattr(league,'season','')) if getattr(league,'season',None) else '')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Flat table: every rating, all 12 pitch grades, effective-ceiling "
                     "(A31 age cap), and the derived board fields — sort/filter in Excel.",
            )
    except Exception as _exp_err:
        st.caption(f"⚠️ board export unavailable: {_exp_err}")

    tab_board, tab_grades, tab_method = st.tabs(
        ["📋 Board", "🥎 Pitch Grades", "📐 Methodology"]
    )
    with tab_board:
        _render_board_tab(league, rows, state, pot_active, def_active, hand_active, glove_active)
    with tab_grades:
        _render_grades_tab(rows)
    with tab_method:
        _render_methodology()


# ── BOARD TAB ─────────────────────────────────────────────────────────────────

def _render_board_tab(league, rows, state, pot_active=True, def_active=True,
                      hand_active=True, glove_active=True):
    # Round selector — drives the RP-before-R4 warning + slot context.
    c1, c2 = st.columns([1, 3])
    with c1:
        rnd = st.number_input("Current round", min_value=1, max_value=60,
                              value=int(state['current_round']), key='draft_round')
        if int(rnd) != int(state['current_round']):
            _save_draft_state(league, current_round=int(rnd))
    with c2:
        if int(rnd) < RP_ROUND_FLOOR:
            st.caption(f"⚠️ Round {int(rnd)}: **A6 — never draft RP before Round "
                       f"{RP_ROUND_FLOOR}.** Prospects with an RP ceiling (failed "
                       "the predraft SP gate) are flagged `RP-CEILING` below; skip "
                       "them this early.")
        else:
            st.caption(f"Round {int(rnd)}: RP-ceiling arms are draftable from here.")

    leg = " · ".join(f"{DRAFT_TIER_ICONS[k]} {DRAFT_TIER_LABELS[k]}"
                     for k in ('elite', 'solid', 'flier', 'filler'))
    st.caption(f"**Tiers:** {leg}  ·  ranked by your selected **Sort** (Career WAR / BPA by default)")

    show_skipped = st.checkbox("Show auto-skipped (Unmotivated/Disruptive)", value=False,
                               key='draft_show_skip')
    sort_mode = st.radio(
        "Sort", ["Career WAR (BPA — default)", "Total Value (glove + park + confidence)"],
        horizontal=True, key='draft_sort_mode',
        help="BPA never reorders on the side lenses (A22/A12 locks). Total Value is "
             "the opt-in composite — it DOES reorder; the sub-columns show why.")
    use_tval = sort_mode.startswith("Total")
    early_round = int(rnd) < RP_ROUND_FLOOR

    visible = [x for x in rows if (show_skipped or not x['skip'])]
    if use_tval:
        visible = sorted(visible, key=lambda x: x['tval'], reverse=True)
    # Colorblind-safe glyph for a notable growth bet (▲ scales with the gap).
    def _gb_glyph(gap):
        if not pot_active or gap < 0.3: return ''
        if gap >= 1.0: return '▲▲'
        return '▲'

    # Glove cell: signed def-WAR vs an average glove (◆ asset / ◇ liability / · avg).
    def _glove_cell(x):
        if x['is_pit'] or x['glove'] is None or not glove_active:
            return ''
        g = x['glove']
        lc = '~' if (x['bestfit'] and x['bestfit']['low_conf'] and x['pos'] == 'C') else ''
        if g >= 0.5:  return f"◆ {g:+.2f}{lc}"
        if g <= -0.5: return f"◇ {g:+.2f}{lc}"
        return f"· {g:+.2f}{lc}"

    # Fit cell: '✓' when listed = best fit; '→3B (−0.41)' when he profiles elsewhere.
    def _fit_cell(x):
        if x['is_pit'] or x['bestfit'] is None or not glove_active:
            return ''
        bf = x['bestfit']
        if not bf['moves']:
            return f"{bf['best']} ✓"          # ideal = listed; name shown for clarity
        return f"→{bf['best']} ({-bf['delta']:+.2f})"  # profiles better elsewhere

    table = []
    for x in visible:
        # RP-before-R4 inline marker on the row when relevant.
        rp_warn = ' ⛔R4' if (x['rp_ceiling'] and early_round) else ''
        gb = x['growth_bet']
        table.append({
            ' ':            DRAFT_TIER_ICONS[draft_tier(x['tval'], state['tier_bands'])
                                             if use_tval else x['tier']],
            'Name':         x['name'] + (' 🚫' if x['skip'] else ''),
            'POS':          x['pos'] + rp_warn,
            'B/T':          x['bt'],
            'Age':          x['age'],
            'STM':          (x['stm'] if x['is_pit'] else ''),
            'Def':          (x['def_sum'] if not x['is_pit'] else ''),
            'Glove':        _glove_cell(x),
            'Fit':          _fit_cell(x),
            'Career WAR':   x['career'],
            'Disc WAR':     (x['disc'] if pot_active else x['career']),
            'Total':        x['tval'],
            'Conf':         (f"{x['edge_glyph']} {x['edge']:.2f}" if x['edge_ok'] else '⚠'),
            'Growth-bet':   (f"{_gb_glyph(gb)} +{gb:.2f}".strip() if (pot_active and gb > 0)
                             else ('+0.00' if pot_active else '—')),
            'Window WAR':   x['window'],
            'Park Fit Δ':   (f"{x['parkfit']:+.2f}" if x['parkfit'] is not None else ''),
            'Proj TV':      x['tv'],
            'Need':         '✓' if x['need'] else '',
            'Flags':        x['flags'],
        })
    df = pd.DataFrame(table)
    # Row-selection on the board itself: click a row's selector → open that card.
    # Requires Streamlit >= 1.35 (on_select); falls back gracefully if unsupported.
    board_sel = None
    dialog_fn = getattr(st, 'dialog', None) or getattr(st, 'experimental_dialog', None)
    try:
        board_sel = st.dataframe(
            df, use_container_width=True, hide_index=True,
            height=min(620, 80 + 35 * len(table)),
            on_select='rerun', selection_mode='single-row', key='draft_board_table')
    except TypeError:
        # older Streamlit without on_select — plain render, selector below handles it
        st.dataframe(df, use_container_width=True, hide_index=True,
                     height=min(620, 80 + 35 * len(table)))

    # If a row was selected in the board, open that prospect's card.
    sel_rows = []
    if board_sel is not None:
        try:
            sel_rows = board_sel['selection']['rows']
        except (KeyError, TypeError):
            sel_rows = []
    if sel_rows:
        sel_i = sel_rows[0]
        if 0 <= sel_i < len(visible):
            if dialog_fn is not None:
                @dialog_fn("🔍 Prospect card")
                def _board_popup(idx=sel_i):
                    _render_prospect_card(visible[idx])
                _board_popup()
            else:
                with st.container():
                    _render_prospect_card(visible[sel_i])
        st.caption("👆 Select a row in the board above to open that prospect's card "
                   "(or use the picker at the bottom).")

    if not pot_active:
        st.warning(
            "⚠️ **Discount inactive — no potential columns found in this pool.** "
            "`Disc WAR` is showing **Career WAR** unchanged and `Growth-bet` is "
            "`—`. The delivery haircut needs the prospect potential columns "
            "(`CON P`, `STU P`, `EYE P`, …) in the export. Re-export the draft "
            "pool with potentials included to activate the Discounted ranking. "
            "(Not silently zeroed — the column is honest about being off.)"
        )

    st.caption(
        "**B/T** = bats / throws.  **STM** = stamina (pitchers — a smoother "
        "innings-volume lever; no eligibility floor per the registry, but a "
        "short-stamina arm is a reliever).  **Def** = position-appropriate "
        "fielding, *range · arm · error* (catchers: *ability · arm · framing*) — "
        "the raw defensive skills, scored at the LISTED position.  **Glove** = "
        "defensive WAR at the listed position vs an *average* glove there "
        "(◆ asset / ◇ liability / · ≈average) — predicted from current fielding "
        "ratings, which the registry shows are ~fixed from draft day, so no "
        "projection needed.  **POS** = position he plays now; **Fit** = his ideal "
        "(best-value) position — `POS ✓` when those match, else "
        "→ the position that maximizes glove + positional value (the WAR left on "
        "the table at his listed spot in parens). A `~` marks catcher, whose ZR "
        "model is weak by engine design — trust the bat there, not the glove "
        "number. Glove/Fit are scouting context; like Disc, they never reorder "
        "the BPA rank — defense isn't in the F2 number yet, so weight it by hand."
    )
    miss = []
    if not hand_active: miss.append("handedness (`B`/`T`)")
    if not def_active:  miss.append("fielding (`IF RNG`, `OF RNG`, `C ABI`, …)")
    if miss:
        st.info(
            "ℹ️ This export is missing " + " and ".join(miss) + " — those cells "
            "show `—`. Add the column(s) to the OOTP export (the fielding + "
            "bats/throws fields) and re-upload to populate them. STM is always "
            "present (it's a model input)."
        )

    st.caption(
        "**Career WAR** = raw projected mature WAR on **current** ratings (the BPA "
        "rank — nothing reorders it). **Disc WAR** = the same F2 re-scored on "
        "**expected-mature** ratings: current + promised growth haircut by the "
        "registry-locked delivery factors (batter CON/GAP .48, POW .45, EYE .28; "
        "pitcher CON .43, STU .53, MOV .40), age-adjusted (younger draftees deliver "
        "2-3× the growth). **Growth-bet** = Disc − Career = the projected upside "
        "surviving the haircut (▲ / ▲▲ mark the bigger bets). A finished college bat "
        "shows ≈0; a toolsy 17-yo shows a large ▲. Disc is **additive** — it never "
        "reorders the board. **Window WAR** = the portion capturable in ~4-5 AC "
        "sim-seasons. **Proj TV** = trade value at maturity (full 6-yr control). "
        "**Need ✓** = My Team auto-config (read-only). **Select a row** to open that "
        "prospect's full card with the per-rating haircut."
    )

    # ── Park Fit Δ caption / fail-loud notice (A22 — additive, hitters only) ────
    _ps = _DRAFT_PARK_STATUS
    if _ps.get('ok'):
        conf = _ps.get('confidence') or {}
        st.caption(
            f"**Park Fit Δ** ({_ps.get('name')}) = the home-park run re-weight a "
            "hitter's **profile** earns that the **park-neutral** Career WAR strips "
            "out (A22) — a **full-season (per-650) fit rate**, so it's pure park "
            "fit, not playing time. **Additive only: it never reorders the BPA "
            "rank** (methodology #6); the gap between it and Career WAR is the "
            f"signal. Confidence — SPE **{conf.get('SPE','?')}** (the locked "
            f"demotion), POW **{conf.get('POW','?')}** (concave premium), GAP/2B/3B "
            "not used. Pitchers show blank (A23 NULL — no pitcher park edge). "
            "Calibrated for THIS park's profile only."
        )
    else:
        prof = _ps.get('profile') or {}
        st.info(
            "ℹ️ **Park Fit Δ withheld — no calibrated coefficients for your park "
            f"profile** (HR {prof.get('HR','?')} / AVG {prof.get('AVG','?')} / "
            f"2B {prof.get('2B','?')} / 3B {prof.get('3B','?')}). A22 is calibrated "
            "for HR 1.30 / AVG 0.98 / 2B 0.95 / 3B 0.90 only; the re-weight is "
            "asymmetric, so the coefficients are **not** extrapolated to other parks "
            "(a 0.7 park is not the mirror of a 1.30 park). The column is blank "
            "rather than wrong. Set your park in ⚙️ Settings, or run the OFAT study "
            "to calibrate this profile."
        )

    # ── Fallback picker (board row-select above is the primary path) ─────────────
    _render_inspect(visible, pot_active)

    if any(x['need'] for x in visible):
        st.caption("ℹ️ Need tags reflect your current My Team roster. No My Team "
                   "roster loaded → no need tags (the board is still pure BPA).")
    else:
        saved = league.get_last_roster()
        if saved is None or saved.empty:
            st.caption("ℹ️ No My Team roster loaded — Need column is blank "
                       "(board is pure BPA, which is the intended default).")

    n_skip = sum(1 for x in rows if x['skip'])
    if n_skip and not show_skipped:
        st.caption(f"🚫 {n_skip} prospect(s) auto-skipped (Unmotivated/Disruptive, "
                   "A6 — never override). Toggle above to view.")

    with st.expander("⚙️ Tier bands + predraft SP-capability gate (provisional)"):
        st.caption("Prospects project lower WAR than established players, so these "
                   "bands are draft-scaled. The predraft pitch gate is rescaled "
                   "for the predraft regime (lower than the mature 50/40) and is "
                   "UN-STUDIED — provisional, editable.")
        tb = state['tier_bands']
        cc = st.columns(3)
        elite = cc[0].number_input(f"{DRAFT_TIER_ICONS['elite']} Blue-chip ≥",
                                   value=float(tb['elite']), step=0.1, key='dt_elite')
        solid = cc[1].number_input(f"{DRAFT_TIER_ICONS['solid']} Regular ≥",
                                   value=float(tb['solid']), step=0.1, key='dt_solid')
        flier = cc[2].number_input(f"{DRAFT_TIER_ICONS['flier']} Flier ≥",
                                   value=float(tb['flier']), step=0.1, key='dt_flier')
        gate = state['predraft_gate']
        gc = st.columns(3)
        gtop = gc[0].number_input("Gate: top pitch ≥", value=int(gate['top_min']),
                                  min_value=20, max_value=80, key='dg_top')
        gsec = gc[1].number_input("Gate: secondary ≥", value=int(gate['secondary_min']),
                                  min_value=20, max_value=80, key='dg_sec')
        gcnt = gc[2].number_input("Gate: # secondaries", value=int(gate['secondary_count']),
                                  min_value=0, max_value=4, key='dg_cnt')
        st.markdown("**Total Value composite** (opt-in sort — never changes the BPA default):")
        vc = st.columns(2)
        cfloor = vc[0].slider("Confidence floor", 0.50, 1.00,
                              float(state['conf_floor']), 0.01, key='dt_cfloor',
                              help="Worst-case Total-Value haircut for a fully fragile "
                                   "edge. 0.85 = max −15%. Lower bites harder.")
        tbase = vc[1].radio("Total Value base", ["disc", "career"],
                            index=0 if state['tval_base'] == 'disc' else 1,
                            horizontal=True, key='dt_tbase',
                            help="disc = growth-discounted (realistic draft value); "
                                 "career = no-growth floor.")
        b1, b2 = st.columns(2)
        if b1.button("Save", key='dt_save'):
            _save_draft_state(league,
                tier_bands={'elite': elite, 'solid': solid, 'flier': flier},
                predraft_gate={'top_min': int(gtop), 'secondary_min': int(gsec),
                               'secondary_count': int(gcnt)},
                conf_floor=float(cfloor), tval_base=tbase)
            st.success("Saved."); st.rerun()
        if b2.button("Reset", key='dt_reset'):
            _save_draft_state(league, tier_bands=dict(DRAFT_TIER_DEFAULTS),
                              predraft_gate=dict(PREDRAFT_PITCH_GATE_DEFAULTS),
                              conf_floor=0.85, tval_base='disc')
            st.success("Reset."); st.rerun()


# ── ON-DEMAND PROSPECT INSPECT ─────────────────────────────────────────────────

def _inspect_label(x):
    return (f"{x['name'] or '(unnamed)'} — {x['pos']}, age {x['age']}  ·  "
            f"Career {x['career']:.2f} → Disc {x['disc']:.2f}")


def _render_inspect(visible, pot_active=True):
    """
    Prospect inspector. Renders the full per-prospect card (scouting + delivery
    haircut + best-fit table). When the installed Streamlit supports st.dialog,
    the card opens in a MODAL popup over the board (pick a prospect → popup);
    otherwise it falls back to an inline expander so it works on any version.
    """
    if not visible:
        with st.expander("🔍 Inspect a prospect", expanded=False):
            st.info("No prospects to inspect.")
        return

    idxs = list(range(len(visible)))
    dialog_fn = getattr(st, 'dialog', None) or getattr(st, 'experimental_dialog', None)

    if dialog_fn is not None:
        # ── Modal popup path ────────────────────────────────────────────────
        @dialog_fn("🔍 Prospect card")
        def _popup(idx):
            _render_prospect_card(visible[idx])

        st.markdown("**🔍 Or pick from the list** — open a prospect's full card:")
        i = st.selectbox("Prospect", idxs, index=0, format_func=lambda k: _inspect_label(visible[k]),
                         key='draft_inspect_pick', label_visibility='collapsed')
        if st.button("Open card", key='draft_inspect_open', use_container_width=False):
            _popup(i)
    else:
        # ── Inline expander fallback (older Streamlit) ──────────────────────
        with st.expander("🔍 Inspect a prospect — scouting card + delivery haircut", expanded=False):
            i = st.selectbox("Prospect", idxs, index=0,
                             format_func=lambda k: _inspect_label(visible[k]),
                             key='draft_inspect_pick')
            _render_prospect_card(visible[i])


def _render_prospect_card(x):
    """Full per-prospect card: scouting (handedness + fielding/arsenal) + delivery
    haircut + best-fit position table. Used by both the modal and the fallback."""
    r = x['row']
    # ── 1. Scouting card ────────────────────────────────────────────────
    st.markdown(f"**{x['name'] or '(unnamed)'}** · {x['pos']} · age {x['age']} · "
                f"bats **{bats_hand(r)}** / throws **{throws_hand(r)}**")
    # Edge stability + Total Value decomposition (the "why" behind the composite).
    if x.get('edge_ok'):
        parts = [f"disc {x['disc']:.2f}"]
        if x.get('glove') is not None:
            parts.append(f"glove {x['glove']:+.2f}")
        if isinstance(x.get('parkfit'), (int, float)):
            parts.append(f"park {x['parkfit']:+.2f}")
        st.caption(f"**Edge {x['edge_glyph']} {x['edge']:.2f}** · conf ×{x['conf']:.2f} · "
                   f"**Total {x['tval']:.2f}** (= {' + '.join(parts)}, ×conf)")
        for d in x.get('edge_drivers', []):
            st.caption(f"• fragile input: {d['rating']} = {d['share'] * 100:.0f}% of tool "
                       f"value — {d['why']}")
        for g in x.get('grade_flags', []):
            st.caption(f"• noisy grade: {g['pitch']} {g['grade']} — {g['why']}")
    elif x.get('edge_reason'):
        st.caption(f"⚠ edge stability unavailable: {x['edge_reason']}")
    if x['is_pit']:
        ars = arsenal_detail(r)
        line = (f"Stamina **{x['stm']}** · mid-velo **{x['velo']}** · "
                f"**{x['npitch']}** usable pitches (≥30)")
        st.caption(line)
        if ars:
            st.dataframe(
                pd.DataFrame([{'Pitch': p, 'Grade': g} for p, g in ars]),
                use_container_width=True, hide_index=True)
        else:
            st.caption("No pitch grades present in the export.")
    else:
        dd = defense_detail(r)
        if dd:
            st.caption("Underlying fielding (raw skills, not the position-experience "
                       "rating):")
            st.dataframe(
                pd.DataFrame([{'Skill': lab, 'Grade': val} for lab, val in dd]),
                use_container_width=True, hide_index=True)
        else:
            st.caption("No fielding columns in this export — add the fielding "
                       "fields to the OOTP export to see range / arm / error here.")
        # Best-fit position table — def WAR + positional value at each spot.
        if x['glove'] is not None and dd:
            bf = x['bestfit']
            pvt = position_value_table(r)
            st.caption(
                "Defensive value by position (the bat is the same everywhere, so "
                "best fit is a pure glove + positional-value call). **Glove WAR** "
                "is vs an average fielder there; **Pos val** is the positional "
                "premium; **Total** is what best-fit maximizes over *eligible* "
                "spots (engine floor ≥40):")
            pv_rows = []
            for pr in pvt:
                tag = []
                if pr['listed']:   tag.append('listed')
                if pr['pos'] == bf['best']: tag.append('BEST')
                if not pr['eligible']: tag.append('ineligible')
                if pr['low_conf']: tag.append('low-conf')
                pv_rows.append({
                    'Pos': pr['pos'],
                    'Glove WAR': f"{pr['def_war']:+.2f}",
                    'Pos val': f"{pr['pos_adj']:+.2f}",
                    'Total': f"{pr['total']:+.2f}",
                    '': ' · '.join(tag),
                })
            st.dataframe(pd.DataFrame(pv_rows), use_container_width=True, hide_index=True)
            if bf['moves'] and not bf['low_conf']:
                st.caption(
                    f"➜ Profiles best at **{bf['best']}**, not {bf['listed']} "
                    f"(**{bf['delta']:+.2f}** WAR vs staying). His listed-position "
                    "Glove number reflects where he's tagged today; the engine will "
                    "let him develop at the better spot (ratings clear the floor).")
            elif not bf['moves']:
                st.caption(f"➜ Best fit **is** his listed {bf['listed']} — no move "
                           "indicated.")

    # ── 2. Delivery haircut ─────────────────────────────────────────────
    st.markdown("---")
    bd = delivery_breakdown(r)
    if not bd['any_pot']:
        st.caption("**Delivery haircut:** no potential columns for this prospect "
                   "→ Discounted = Career (no growth credited). Re-export with "
                   "potentials to activate.")
        return

    amult = delivery_age_mult(x['age'])
    gap = x['growth_bet']
    st.markdown(
        f"**Delivery haircut** — Career **{x['career']:.2f}** → Discounted "
        f"**{x['disc']:.2f}** (growth-bet **{'+' if gap >= 0 else ''}{gap:.2f}** WAR)")
    st.caption(
        f"Age multiplier on every factor at age {x['age']}: **×{amult:.2f}** "
        f"(1.00 at age {int(DELIVERY_AGE_DEFAULTS['ref_age'])}; younger delivers "
        "more, clamped 0.50–1.50). Effective = locked factor × age multiplier, "
        "capped at 1.00. Discounted rating = current + (potential − current) × effective."
    )

    det = []
    for d in bd['ratings']:
        if d['has_pot']:
            growth = d['potential'] - d['current']
            det.append({
                'Rating':     d['label'],
                'Current':    f"{d['current']:.0f}",
                'Potential':  f"{d['potential']:.0f}",
                'Promised':   f"+{growth:.0f}" if growth > 0 else f"{growth:.0f}",
                'Factor':     f"{d['factor']:.2f}",
                'Age×':       f"{d['age_mult']:.2f}",
                'Effective':  f"{d['eff_factor']:.2f}",
                'Discounted': f"{d['discounted']:.1f}",
            })
        else:
            det.append({
                'Rating': d['label'], 'Current': f"{d['current']:.0f}",
                'Potential': '—', 'Promised': '—', 'Factor': f"{d['factor']:.2f}",
                'Age×': f"{d['age_mult']:.2f}", 'Effective': '—',
                'Discounted': f"{d['current']:.1f}*",
            })
    st.dataframe(pd.DataFrame(det), use_container_width=True, hide_index=True)

    notes = []
    if bd['is_pit']:
        notes.append("SP **STM** has no delivery factor and stays at current "
                     "(it's an innings-volume lever, not a developing quality).")
    else:
        notes.append("**SPE** and the fielding skills have no delivery factor and "
                     "stay at current.")
    notes.append("Pitch grades, AGE, amateur, personality and HSC are outside the "
                 "locked delivery study — held at current in the discount.")
    if any(not d['has_pot'] for d in bd['ratings']):
        notes.append("`*` = no potential column for that rating → no growth credited "
                     "(shown at current, not silently zeroed).")
    if bd['big_con_bet']:
        notes.append("⚠️ **BIG-CON-bet** — 30+ promised control growth. Control "
                     "development is high-bust, worse in older draftees (~22% "
                     "delivery at 21+ vs ~57% at 17); the haircut above is doing "
                     "real work here. Prefer arms that already throw strikes.")
    st.caption("  ".join(f"• {n}" for n in notes))
    st.caption(
        "Factors are registry-locked **population means** (±5-10pt individual "
        "variance) — a calibration anchor for expectations, not a per-prospect "
        "guarantee. EYE is the OOTP-27 outlier (28% delivery vs 40-53%)."
    )




def _render_grades_tab(rows):
    st.subheader("🥎 Pitcher prospects — pitch-grade view")
    st.caption(
        "Ordered by Career WAR. Pitch grades shown in **H3 signal priority** "
        "(SI > CH > SL > FB) — the dominant pitcher live-draft signal. STU/MOV "
        "are demoted: the registry shows they collapse under pitch-grade "
        "conditioning (roll-ups of the individual grades, not independent signal). "
        "A grade of 0 / '—' means the prospect doesn't throw that pitch."
    )
    pits = [x for x in rows if x['is_pit'] and not x['skip']]
    if not pits:
        st.info("No pitcher prospects in the pool.")
        return

    table = []
    for x in pits:
        r = x['row']
        rec = {
            'Name': x['name'], 'POS': x['pos'], 'T': x['throws'], 'Age': x['age'],
            'Career WAR': x['career'], 'STM': x['stm'], 'Velo': x['velo'],
            'Top': x['top_pitch'], '#P': x['npitch'],
        }
        for col, label in PITCH_DISPLAY_ORDER:
            g = int(_s(r.get(col, 0)))
            rec[label] = g if g > 0 else '—'
        rec['STU'] = int(_s(r.get('STU', 0)))
        rec['MOV'] = int(_s(r.get('MOV', 0)))
        rec['CON'] = int(_s(r.get('PIT_CON', 0)))
        rec['CON→'] = f"+{int(pitcher_promised_con_growth(r))}"
        rec['SP-able'] = '✓' if not x['rp_ceiling'] else ''
        rec['Flags'] = x['flags']
        table.append(rec)
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
    st.caption(
        "**T** = throws. **STM** = stamina (innings-volume lever — no hard "
        "rotation floor, but a low-STM arm is a reliever). **Velo** = mid "
        "velocity. **#P** = usable pitches (grade ≥ 30 — the registry's "
        "usable-pitch boundary). Look at pitch VALUES, not the count: a 4-pitch "
        "arm at 50/50/50/50 beats a 2-pitch arm at 60/60 + two at 20/25 (low "
        "grades are phantom depth that rarely develops)."
    )
    st.caption(
        "**SP-able ✓** = clears the (provisional, predraft-rescaled) top-pitch "
        "gate; blank = RP ceiling. **CON→** = promised control growth "
        "(potential − current); **BIG-CON-bet** fires at +30 (A6: betting on "
        "control development is high-bust, especially in older draftees — ~22% "
        "delivery at 21+ vs ~57% at 17). **Draft pitchers who already have "
        "control; don't bet on projected control.**"
    )
    st.info(
        "⚠️ **Pitcher projections are less certain than batter projections** and "
        "can't be fully ranked from draft-day grades. SP success in OOTP 27 is "
        "materially encoded in handedness (v-split) quality that the live-draft "
        "scout grades don't expose — that signal only emerges ~90 days post-draft. "
        "Treat the pitcher ordering as coarse; weight your own read on close calls."
    )


# ── METHODOLOGY TAB ───────────────────────────────────────────────────────────

def _render_methodology():
    if f2_is_placeholder():
        st.error(
            "⚠️ **PLACEHOLDER coefficients in use.** Scores encode F2 structure but "
            "are NOT production numbers. Trust relative ordering, not absolute WAR."
        )
    st.markdown(
        "**Formula lineage — per-realization** (F2 pitcher CV "
        f"R²={F2_PITCHER_R2}, batter R²={F2_BATTER_R2}, K-T data, GroupKFold by ID). "
        "Fit on the real K-T draft pool joined to mature outcomes (ages 23–27), one "
        "`(ID, seed)` realization per row. This **supersedes the per-prospect v12 "
        "line (0.151/0.216)**: the K-T seeds don't preserve player identity — the "
        "same `ID` is a different generated player across seeds — so a per-prospect "
        "average is a synthetic blend that exists in no save, while a live draft "
        "scores one real realization. The per-realization unit was confirmed "
        "independently by two external models (ChatGPT, Gemini) and the registry's "
        "own v14.0 correction; all four agree on the unit and the coefficient "
        "structure. **Interim:** coefficients are calibrated to the K-T rating "
        "regime and get re-fit on a real American Circuit draft pool at migration."
    )
    st.markdown(
        "**The point estimates carry a wide error band — read the board as tiers.** "
        f"Out-of-fold residual SD is ±{F2_PITCHER_SD:.2f} WAR (pitcher) / "
        f"±{F2_BATTER_SD:.2f} WAR (batter): a single prospect's mature WAR is ~30% "
        "engine RNG, so a Career WAR of 2.4 vs 2.1 is not a real distinction. The "
        "board shows coarse TIERS deliberately. Use tiers + your own read."
    )
    st.markdown(
        "**What the formula uses (locked structure):** current ratings (not "
        "potential — potentials are themselves drifting projections). **AGE is a "
        "strong NEGATIVE predictor** — younger draftees project higher mature WAR, "
        "all else equal (the board surfaces age prominently). For pitchers, "
        "**individual pitch grades carry signal beyond aggregate STU/MOV** (SI / CH "
        "lead), and the throws-it indicator goes negative while the grade goes "
        "positive — a bad version of a pitch hurts; a good one is gold. HSC×amateur "
        "stays in the batter/pitcher formula (the 9→2 reduction was rejected), but "
        "amateur stats carry little independent causal signal beyond ratings; don't "
        "over-weight them."
    )
    st.markdown(
        "**Discounted WAR — the delivery-haircut view (additive, never reorders):** "
        "Career WAR scores **current** ratings. Disc WAR re-scores the *same* F2 on "
        "**expected-mature** ratings — `current + (potential − current) × factor` — "
        "using the registry-locked OOTP-27 delivery factors (batter CON **.48** / "
        "GAP **.48** / POW **.45** / EYE **.28**; pitcher CON **.43** / STU **.53** / "
        "MOV **.40**). **EYE is the standout**: OOTP 27 under-delivers projected eye "
        "discipline (28% vs 40-53% for everything else), so a high-EYE-projection bat "
        "loses most of that growth. Factors are **age-adjusted** — younger draftees "
        "deliver 2-3× the promised growth (the same mechanism behind F2's negative "
        "AGE coefficient), applied as a shared multiplier (1.0 at age 19, clamped "
        "0.50–1.50). **SPE/STM** and everything outside the study (pitch grades, "
        "amateur, personality, HSC) hold at current. The **Growth-bet** column "
        "(Disc − Career) is the signal: how much projected upside survives the "
        "haircut — large for toolsy teens, ≈0 for finished college players. Open the "
        "🔍 inspect panel for any prospect's per-rating breakdown. Factors are "
        "population means (±5-10pt individual SD): an anchor, not a guarantee. The "
        "age curve is calibrated on the only age-stratified data (pitcher CON) and "
        "generalized across ratings — revisit at the AC re-fit."
    )
    st.markdown(
        "**Glove WAR & best-fit position — closing the defensive blind spot:** "
        "F2 sees defense only through a flat position dummy, so a 75-range SS and "
        "a 40-range SS score identically. **Glove WAR** fixes the *visibility* by "
        "running the deployed, sim-validated per-position ZR models (predict ZR "
        "from current fielding ratings → DEF_WAR) — it's runs above/below an "
        "*average* glove at the position, so 0 ≈ average. Because ZR is centered "
        "on average and the F2 dummy already credits the average fielder, Glove WAR "
        "(the deviation) is **additive and doesn't double-count** — which is also "
        "why it stays a side column and never folds into the rank. Per A12, "
        "defensive value is a **soft tax, not a hard floor** (premium positions "
        "punish a bad glove only ~1.2× harder, smooth slope, no cliff), so we score "
        "continuously and never gate on quality. The only real gate is the **engine "
        "eligibility floor** (ratings ≥40 — the game won't roster him there), which "
        "bounds the **best-fit** search: since the bat is identical at every "
        "position, best fit = argmax of *def_war + positional value* over eligible "
        "spots. A 75-range SS maximizes at SS and stays; a 45-range 'SS' maximizes "
        "at 2B/3B and relocates — the math doing a floor's job continuously. "
        "Defense is ~fixed draft-day→prime (r 0.96–0.99), so current ratings are "
        "the prime ratings: no projection, no delivery haircut on the glove. "
        "**Catcher caveat:** the C ZR model is near-useless (R²=0.037) because the "
        "engine barely varies catcher ZR — not fixable with CERA (A8: debunked, it "
        "reflects the staff/defense around the catcher, already in pitcher PBABIP). "
        "Catcher Glove WAR is small-by-design and flagged low-confidence; judge the "
        "bat + framing/arm tools directly."
    )
    st.markdown(
        "**Pitcher uncertainty (blanket caveat, not a per-prospect flag):** "
        "pitcher projections — especially SP-leaning arms — can't be fully ranked "
        "from draft-day grades. SP success depends on v-split quality that only "
        "becomes observable ~90 days post-draft. (The old SP-dominant per-prospect "
        "classification is deprecated: it's unknowable at draft day.)"
    )
    st.markdown(
        "**Hard rules (A6, locked):** never draft RP before Round 4 (the round "
        "selector drives the warning; RP-ceiling = fails the predraft SP gate); "
        "Unmotivated/Disruptive = auto-skip, never override; Fragile = −40% "
        "projected value; PIT_CON < 40 = LOW-CON; 30+ promised CON growth = "
        "BIG-CON-bet (don't bet on control development, especially in older "
        "draftees). Mature CON itself is a settled continuous lever with NO gate "
        "(A15) — BIG-CON-bet is a draft-time *delivery* concern only."
    )
    st.markdown(
        "**Top-pitch quality over arsenal count (A14):** arsenal flags use "
        "top-pitch grade + secondary count, NOT a raw pitch count (count is an "
        "inverted proxy — more pitches correlates with *worse* outcomes because "
        "fewer-pitch arms carry better best-pitches). Predraft gate thresholds are "
        "rescaled DOWN from the mature 50/40 because predraft and MLB ratings live "
        "in different regimes on the same 20-80 scale — and the predraft thresholds "
        "are themselves UN-STUDIED and provisional."
    )
    st.warning(
        "⚠️ **Your AC park factors are HR-skewed** (see Settings → Team "
        "Configuration). F2 does NOT park-adjust, so **power bats project "
        "conservatively for your home environment, and flyball pitchers project "
        "optimistically.** This is an unrun research question — no numeric "
        "adjustment is baked in. Mentally adjust close calls accordingly."
    )
    st.warning(
        "⚠️ **Draft-pool schema is UNVERIFIED.** The column map (registry A1) was "
        "confirmed against the MATURE roster export, not a real draft-pool export "
        "— no one has inspected one yet. The board runs a column audit on upload "
        "and FAILS LOUD on any missing load-bearing F2 column rather than feeding "
        "silent zeros into the formula. **First task on a real OOTP 27 draft CSV: "
        "reconcile the audit** (the A1 analogue for the draft-pool export), then "
        "lock the real coefficients."
    )
