"""
OOTP 27 Suite — Roster Construction (UI renderer)
=================================================
Thin Streamlit renderer for the new top-level 🧱 Roster Construction section, peer
to Lineups / Pitching / Draft. The pure logic lives in `roster_construction.py`
(team-need primitive + reserve keep/cut allocator); this file only wires it to the
screen and reuses the existing Development helpers so there is no second copy of the
roster-load / inspect-modal / state-save behaviour.

Two tabs:
  🧭 Team Needs      — the ONE team-need readout (need / surplus by position),
                       sourced from roster_construction.detect_needs_and_surplus.
                       This is the same primitive Draft's Need tag and Acquisitions'
                       Fit auto-fill consume — shown here as the canonical view.
  📋 Reserve Roster  — the Layer-3 keep/cut board, relocated verbatim from
                       Development (it consumes Layer-1 ΣweightedGap, which is still
                       produced by the Slider Optimizer).
"""

import pandas as pd
import streamlit as st

from db import League
import roster_construction as rc

# Reuse Development's roster-load, recommend, inspect-modal and state-save helpers
# (single source of truth — no duplicate roster pipeline). build_roster_table comes
# from My Team; split_active_reserve too.
from development import (
    _load_dev_state, _save_reserve_cfg, _saved_roster, _load_roster,
    recommend_player, _inspect_picker,
)
from my_team import build_roster_table, split_active_reserve, _active_flag_col


def render_roster_construction(league: League):
    st.header("🧱 Roster Construction")
    st.caption("The shared roster-construction layer — team-need is defined **once** "
               "here and read by Draft, Acquisitions, Lineups and Development. The "
               "reserve keep/cut board lives here too (it consumes the Slider "
               "Optimizer's ΣweightedGap).")

    complete, missing = league.team_config_complete()
    if not complete:
        st.warning(f"Team Config incomplete ({', '.join(missing)} missing). "
                   "Configure in ⚙️ Settings.")

    cfg = _load_dev_state(league)
    mode = league.team_config.get('mode', 'Competing')

    tabs = st.tabs(["🧭 Team Needs", "🔧 Roster Decisions"])
    with tabs[0]:
        _render_team_needs(league, mode)
    with tabs[1]:
        # Whole-roster promote/keep/trade/cut/hold-down board. Owns the uploader so
        # the section works standalone; the saved roster is shared with My Team.
        _render_decisions(league, cfg, _load_roster(league))


# ══════════════════════════════════════════════════════════════════════════════
# TEAM NEEDS — the canonical readout
# ══════════════════════════════════════════════════════════════════════════════

def _render_team_needs(league: League, mode: str):
    df = _saved_roster(league)
    if df is None or df.empty:
        st.info("Upload a roster in the 📋 Reserve Roster tab (or My Team / "
                "Development) — the team-need readout reads your saved roster.")
        return

    try:
        tbl = build_roster_table(df)
    except Exception as e:
        st.error(f"Couldn't build the roster table: {e}")
        return
    if tbl.empty:
        st.info("Roster table is empty after filtering to your team.")
        return

    needs, surplus = rc.detect_needs_and_surplus(tbl, mode)

    st.markdown(f"**Mode:** {mode} — batter need floor "
                f"`best-F1 < {rc.NEED_FLOORS.get(mode, rc.NEED_FLOORS['Competing'])}` "
                f"· pitcher need floor "
                f"`best-F2 < {rc.PITCHER_NEED_FLOORS.get(mode, rc.PITCHER_NEED_FLOORS['Competing'])}` "
                f"· surplus `≥{rc.SURPLUS_MIN_COUNT} bodies F1≥{rc.SURPLUS_QUALITY_FLOOR} "
                f"AND best F1≥{rc.SURPLUS_BEST_FLOOR}`.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 🔻 Needs")
        st.markdown(("`" + "`  `".join(needs) + "`") if needs else "_none_")
    with c2:
        st.markdown("##### 🔺 Surplus")
        st.markdown(("`" + "`  `".join(surplus) + "`") if surplus else "_none_")

    st.caption("ℹ️ Surplus is position-players only — on a 25-man you need exactly "
               "6 SP + 5 RP, so extra pitching is depth, not surplus (CL folds into "
               "RP). This is the same need set Draft's **Need ✓** tag uses.")
    st.caption("ℹ️ **Score** = present-WAR **F1** for hitters, rating-based projected "
               "**F2** for pitchers. Pitcher F1 is innings-driven (it reads negative "
               "with no IP, e.g. fresh-season or bench arms), so pitcher need is "
               "judged on arm quality (F2), not banked innings.")

    # Per-position context — F1 for hitters, F2 for pitchers (mirrors detection).
    has_f2 = 'F2' in tbl.columns
    rows = []
    all_pos = sorted(rc.BATTER_POSITIONS) + ['SP', 'RP']
    for pos in all_pos:
        at = (tbl[tbl['POS'].isin(['RP', 'CL'])] if pos == 'RP'
              else tbl[tbl['POS'] == pos])
        is_pit = pos in ('SP', 'RP')
        score_col = 'F2' if (is_pit and has_f2) else 'F1'
        rows.append({
            'POS': pos,
            'Count': int(len(at)),
            'Score': round(float(at[score_col].max()), 2) if not at.empty else 0.0,
            'Basis': ('F2' if (is_pit and has_f2) else 'F1'),
            'Verdict': ('NEED' if pos in needs else
                        'SURPLUS' if pos in surplus else '—'),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# ROSTER DECISIONS — whole-roster promote / keep / trade / cut / hold-down
# ══════════════════════════════════════════════════════════════════════════════

_VERDICT_META = {
    'promote':   ('⬆️ PROMOTE',  'Reserve player who cracks your best-25 on present WAR — call him up.'),
    'keep':      ('✓ KEEP',      'Held — core value or future upside, fits under the cap.'),
    'hold-down': ('⏸️ HOLD-DOWN', 'Rebuild: promote-worthy but under the service clock — banking a control year is worth more than the marginal WAR now.'),
    'trade':     ('🔁 TRADE',     'Sell, do not release — proactive rebuild vet sale, or a useful player forced off an over-cap roster.'),
    'cut':       ('✕ CUT',       'Forced off an over-cap roster, lowest overall projection. Only fires when you are over the cap.'),
}
_VERDICT_ORDER = ['promote', 'trade', 'hold-down', 'keep', 'cut']


def _render_decisions(league: League, cfg: dict, df):
    if df is None or df.empty:
        st.info("Upload a roster CSV (the **📤 Upload roster** expander) to see "
                "promote / keep / trade / cut decisions.")
        # still show the uploader
        _load_roster(league)
        return

    mode = league.team_config.get('mode', 'Competing')

    # ── Scale guard: the WAR formulas are calibrated on the 20-80 scale. A 1-100
    #    (Test-league) export inflates every rating ~1.65× and corrupts the board.
    rating_max = 0.0
    for c in ('POW', 'EYE', 'STU', 'MOV', 'CON'):
        if c in df.columns:
            try:
                rating_max = max(rating_max, float(pd.to_numeric(df[c], errors='coerce').max()))
            except Exception:
                pass
    if rating_max > 85:
        st.error("⚠️ This looks like a **1–100 scale** export (ratings exceed 80). "
                 "The WAR formulas are calibrated for the **20–80** scale, so every "
                 "value here would be inflated and unreliable. Re-export this roster "
                 "on the 20–80 scale (Test-league exports use 1–100; real-league "
                 "rosters should be 20–80).")
        return

    if _active_flag_col(df) is None:
        st.warning("Export has no active-roster flag (**ACT** / IS_ACTIVE) — promote "
                   "vs demote can't be computed. Add the **ACT** column to your export "
                   "for full promote/cut logic. (Showing keep/trade/cut on the whole "
                   "roster meanwhile.)")

    # ── Controls ────────────────────────────────────────────────────────────────
    rcfg = cfg['reserve']
    with st.expander("⚙️ Phase · budget · trade window", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            phases = list(rc.PHASE_PRESETS.keys())
            phase = st.selectbox(
                "Roster phase", phases,
                index=phases.index(rcfg['phase']) if rcfg.get('phase') in phases else 0,
                key='dec_phase',
                help="Sets the active-roster cap (the cut-down target). Cuts are "
                     "forced ONLY when the roster is over this cap.")
            cap = rc.PHASE_PRESETS[phase].get('active')
            st.caption(f"Active cap: **{cap if cap is not None else '—'}**")
        with c2:
            default_budget = int(league.team_config.get('budget', 0) or 0)
            budget = st.number_input(
                "Team budget ($, 0 = ignore)", min_value=0, step=100_000,
                value=default_budget, key='dec_budget',
                help="Active-roster salary ceiling. Under budget → salary is just a "
                     "tiebreaker. Over → expensive low-WAR guys are flagged.")
        max_trades = st.slider(
            "Max proactive trades this window", 0, 12,
            int(rcfg.get('max_proactive_trades', 4)), 1, key='dec_maxtrade',
            help="Rebuild: how many aging vets to actively shop (you can only absorb "
                 "so many returns). Best-value vets first; rest are held. Rolling — "
                 "trade one, re-export, and the next vet surfaces.")
        if st.button("💾 Save decision settings", key='dec_save'):
            _save_reserve_cfg(league, phase=phase,
                              max_proactive_trades=int(max_trades))
            st.success("Saved.")

    # ── Build inputs & run the allocator ─────────────────────────────────────────
    tbl = build_roster_table(df)            # canonical F1/F2/TV per player
    rows = df.to_dict('records')
    active_flag = {str(r.get('Name', '')):
                   str(r.get('IS_ACTIVE', r.get('ACT', ''))).strip().lower()
                   in ('yes', 'true', '1', 'y', 't') for r in rows}
    payroll = {str(r.get('Name', '')): float(rc._s(r.get('SALARY', 0))) for r in rows}

    # Future-upside lens: prefer the Slider-Optimizer ΣweightedGap if present,
    # else fall back to the rating-based F2 projection so the board still works.
    growth = {}
    for row in rows:
        rec = recommend_player(row, cfg)
        nm = str(row.get('Name', ''))
        if rec:
            growth[nm] = sum(rec['weighted_gaps'].values())
    f2_by_name = {str(t['Name']): float(t.get('F2', 0) or 0) for _, t in tbl.iterrows()} \
        if 'F2' in tbl.columns else {}
    for nm, f2 in f2_by_name.items():
        growth.setdefault(nm, max(0.0, f2))

    res = rc.allocate_roster(rows, growth, mode, phase=phase,
                             active_flag_by_name=active_flag, budget=float(budget),
                             payroll_by_name=payroll,
                             max_proactive_trades=int(max_trades))

    # ── Summary line ─────────────────────────────────────────────────────────────
    st.markdown(
        f"**Mode:** {mode}  ·  **Phase:** {phase} (cap "
        f"{res['active_cap'] if res['active_cap'] is not None else '—'})  ·  "
        f"⬆️ {res['n_promote']} promote · 🔁 {res['n_trade']} trade · "
        f"⏸️ {res['n_hold']} hold · ✓ {res['n_keep']} keep · ✕ {res['n_cut']} cut")
    if res['budget']:
        over = res['over_budget']
        st.markdown(f"**Payroll:** ${res['payroll']:,} / ${res['budget']:,} "
                    + ("🔴 **over budget**" if over else "🟢 under budget"))

    # ── Grouped verdict tables ────────────────────────────────────────────────────
    recs = res['records']
    for v in _VERDICT_ORDER:
        group = [r for r in recs if r['decision'] == v]
        if not group:
            continue
        label, blurb = _VERDICT_META[v]
        # sort within group: promote/keep/hold by value, trade by chip, cut worst-first
        if v == 'cut':
            group.sort(key=lambda r: (r['now'] + r['later']))
        elif v == 'trade':
            group.sort(key=lambda r: (not r.get('_proactive', False), -r['chip'], -r['now']))
        else:
            group.sort(key=lambda r: -(r['now'] + r['later']))
        st.markdown(f"##### {label} ({len(group)})")
        st.caption(blurb)
        disp = []
        for r in group:
            kind = ''
            if v == 'trade':
                kind = 'proactive sell' if r.get('_proactive') else ('forced (over cap)' if r.get('_forced') else '')
            elif v == 'cut':
                kind = 'forced (over cap)' if r.get('_forced') else ''
            disp.append({
                'Player': r['name'], 'POS': r['pos'], 'Age': r['age'],
                'Now (F1)': r['now'], 'Future': r['later'], 'TV': r['chip'],
                'Ctrl yrs': r['control'], 'Arb': r['arb'],
                'Active': '✓' if r['is_active'] else '',
                'Salary': f"${r['salary']:,}" if r['salary'] else '',
                'Why': (kind + ' — ' if kind else '') + (r['reasons'][0] if r.get('reasons') else ''),
            })
        st.dataframe(pd.DataFrame(disp), use_container_width=True, hide_index=True)

    st.caption("ℹ️ **Now** = present WAR (F1; rating-based for pitchers with no "
               "innings). **Future** = capturable future WAR. **TV** = trade value. "
               "CUT only fires when you're over the cap — otherwise everyone is held.")
    if df is None or df.empty:
        return

    mode = league.team_config.get('mode', 'Competing')
    rcfg = cfg['reserve']
    active, reserve = split_active_reserve(df)

    if _active_flag_col(df) is None:
        st.warning("Export has no active-roster flag (ACT / IS_ACTIVE) — can't split "
                   "active vs reserve. Treating the whole roster as the keep/cut pool. "
                   "Tip: add the **ACT** column to your export to split active vs reserve.")
        # Honor the message: rank the whole roster rather than leaving the board empty.
        reserve = df.copy()

    # Consume Layer-1 weighted_gaps (not re-derived) for the reserve pool.
    growth_by_name = {}
    for _, row in reserve.iterrows():
        rec = recommend_player(row.to_dict(), cfg)
        if rec:
            growth_by_name[rec['player']] = sum(rec['weighted_gaps'].values())

    # ── Phase + caps + tilt controls ──────────────────────────────────────────
    with st.expander("⚙️ Phase, caps & mode tilt", expanded=False):
        phases = list(rc.PHASE_PRESETS.keys())
        phase = st.selectbox("Roster phase", phases,
                             index=phases.index(rcfg['phase']) if rcfg['phase'] in phases else 0,
                             help="Presets set the active/reserve caps and whether "
                                  "your newest draft picks are protected from cuts.")
        preset = rc.PHASE_PRESETS[phase]
        c1, c2, c3 = st.columns(3)
        with c1:
            st.caption(f"Active cap (context): **{preset['active'] if preset['active'] is not None else '—'}**")
        with c2:
            uncapped = preset['reserve'] is None
            uncapped = st.checkbox("Reserve uncapped (no forced cuts)", value=uncapped,
                                   key='rsv_uncapped')
            rcap = (None if uncapped else
                    st.number_input("Reserve cap", 1, 80,
                                    value=int(preset['reserve'] or 15), key='rsv_cap'))
        with c3:
            protect = st.checkbox("Protect newest draft picks", value=preset['protect'],
                                  key='rsv_protect',
                                  help="Picks from the most recent draft year are kept "
                                       "regardless (their grace period — off at Opening Day).")
        st.markdown(f"**Mode:** {mode} — tilt over the three value lenses:")
        mw = rcfg.get('mode_weights') or rc.MODE_WEIGHTS.get(mode, rc.MODE_WEIGHTS['Sustaining'])
        w1, w2, w3 = st.columns(3)
        wn = w1.slider("Now (present WAR)", 0.0, 1.0, float(mw['now']), 0.05, key='rsv_wn')
        wl = w2.slider("Later (future WAR)", 0.0, 1.0, float(mw['later']), 0.05, key='rsv_wl')
        wc = w3.slider("Chip (trade value)", 0.0, 1.0, float(mw['chip']), 0.05, key='rsv_wc')

        with st.expander("Classification thresholds (tune in testing)"):
            cls = rcfg['class']
            k1, k2, k3 = st.columns(3)
            pa = k1.number_input("Prospect age ≤", 18, 30, int(cls['prospect_age_max']), key='rc_pa')
            ps = k2.number_input("Prospect service <", 0.0, 6.0, float(cls['prospect_service_max']), 0.5, key='rc_ps')
            pg = k3.number_input("Prospect ΣGap ≥", 0.0, 10.0, float(cls['prospect_growth_min']), 0.1, key='rc_pg')
            k4, k5 = st.columns(2)
            bf = k4.number_input("Borderline F1 ≥", 0.0, 8.0, float(cls['borderline_f1_min']), 0.5, key='rc_bf')
            bt = k5.number_input("Borderline TV ≥", 0.0, 30.0, float(cls['borderline_tv_min']), 1.0, key='rc_bt')

        if st.button("Save reserve settings", key='rsv_save'):
            _save_reserve_cfg(league, phase=phase, reserve_cap=rcap,
                              protect_picks=protect, active_cap=preset['active'],
                              mode_weights={'now': wn, 'later': wl, 'chip': wc},
                              class_={'prospect_age_max': int(pa),
                                      'prospect_service_max': float(ps),
                                      'prospect_growth_min': float(pg),
                                      'borderline_f1_min': float(bf),
                                      'borderline_tv_min': float(bt)})
            st.success("Saved.")
            st.rerun()

    # Live (possibly-unsaved) config for this render.
    live = {**rcfg, 'phase': phase, 'reserve_cap': rcap, 'protect_picks': protect,
            'mode_weights': {'now': wn, 'later': wl, 'chip': wc},
            'class': {'prospect_age_max': int(pa), 'prospect_service_max': float(ps),
                      'prospect_growth_min': float(pg), 'borderline_f1_min': float(bf),
                      'borderline_tv_min': float(bt)}}

    result = rc.allocate_reserve(reserve.to_dict('records'), growth_by_name, mode, live)

    # ── Summary ────────────────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active", len(active))
    m2.metric("Reserve pool", len(reserve))
    cap_disp = "∞" if result['reserve_cap'] is None else result['reserve_cap']
    m3.metric("Reserve cap", cap_disp)
    m4.metric("Must cut", result['n_cut'], delta=None)
    if result['protected']:
        st.caption(f"🔒 Protected (newest picks, {result['draft_year']}): "
                   + ", ".join(result['protected']))
    for f in result['insurance_flags']:
        st.warning("⚠️ " + f)
    if result['n_cut'] == 0:
        st.success("Reserve pool fits within the cap — no cuts required this phase.")

    recs = result['records']
    if not recs:
        st.info("No reserve-eligible players found.")
        return

    rows = [{
        '': _DECISION_GLYPH.get(r['decision'], ''),
        'Decision': r['decision'], 'Name': r['name'], 'POS': r['pos'],
        'Type': r['type'], 'Age': r['age'], 'Svc': r['service'],
        'Now': r['now'], 'Later': r['later'], 'Chip': r['chip'],
        'KeepScore': r['keep_score'],
    } for r in recs]
    st.caption("Ranked by mode-tilted KeepScore. ✓ keep · ✕ cut · 🔒 protected. "
               "**Click a row to inspect.**")
    _inspect_picker(recs, pd.DataFrame(rows), _render_reserve_card, 'rc_rsv', 460,
                    lambda k: f"{recs[k]['name']} — {recs[k]['pos']} ({recs[k]['decision']})")


def _render_reserve_card(r: dict):
    st.markdown(f"**{r['name']}** — {r['pos']}, age {r['age']} · "
                f"{_DECISION_GLYPH.get(r['decision'],'')} **{r['decision'].upper()}** "
                f"· _{r['type']}_")
    st.dataframe(pd.DataFrame([
        {'Lens': 'Now (present WAR)',  'Value': r['now']},
        {'Lens': 'Later (future WAR)', 'Value': r['later']},
        {'Lens': 'Chip (trade value)', 'Value': r['chip']},
        {'Lens': 'Layer-1 ΣGap',       'Value': r['growth']},
        {'Lens': 'KeepScore (tilted)', 'Value': r['keep_score']},
    ]), use_container_width=True, hide_index=True)
    st.caption(f"Service {r['service']} yr · {r['arb']} · {r['control']} yr control"
               + (f" · drafted {r['draft_year']}" if r['draft_year'] else ""))
    for n in r['reasons']:
        st.caption("• " + n)
