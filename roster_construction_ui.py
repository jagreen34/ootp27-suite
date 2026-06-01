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
from my_team import build_roster_table, split_active_reserve


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

    tabs = st.tabs(["🧭 Team Needs", "📋 Reserve Roster"])
    with tabs[0]:
        _render_team_needs(league, mode)
    with tabs[1]:
        # Owns the file_uploader (so the section works standalone); the saved
        # roster is shared with My Team / Development.
        _render_reserve(league, cfg, _load_roster(league))


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

    st.markdown(f"**Mode:** {mode} — need floor "
                f"`best-F1 < {rc.NEED_FLOORS.get(mode, rc.NEED_FLOORS['Competing'])}` "
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

    # Per-position F1 context so the verdict is legible.
    rows = []
    all_pos = sorted(rc.BATTER_POSITIONS) + ['SP', 'RP']
    for pos in all_pos:
        at = (tbl[tbl['POS'].isin(['RP', 'CL'])] if pos == 'RP'
              else tbl[tbl['POS'] == pos])
        rows.append({
            'POS': pos,
            'Count': int(len(at)),
            'Best F1': round(float(at['F1'].max()), 2) if not at.empty else 0.0,
            'Verdict': ('NEED' if pos in needs else
                        'SURPLUS' if pos in surplus else '—'),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# RESERVE ROSTER — keep/cut (Layer 3) — relocated from Development
# ══════════════════════════════════════════════════════════════════════════════

_DECISION_GLYPH = {'keep': '✓', 'cut': '✕', 'protected': '🔒'}


def _render_reserve(league: League, cfg: dict, df):
    if df is None or df.empty:
        return

    mode = league.team_config.get('mode', 'Competing')
    rcfg = cfg['reserve']
    active, reserve = split_active_reserve(df)

    if 'IS_ACTIVE' not in df.columns:
        st.warning("Export has no IS_ACTIVE column — can't split active vs reserve. "
                   "Treating the whole roster as the keep/cut pool.")

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
