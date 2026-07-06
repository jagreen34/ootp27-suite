"""
OOTP 27 Suite — Player Card (🪪)
================================
Upload a roster → per-player F1 / F2 / development outlook / roster slot in a sortable
table, then pick a player for the full card: F1 & F2, the AGE-CONDITIONED development
arc (delivery rate × age runway), the roster decision the allocator makes with its
reason, and tracked history across saved snapshots.

Composes the canonical functions (build_roster_table, allocate_roster, prep_data,
snapshot_player_history) — never recomputes, so it can't drift from the rest of the suite.

Two things this version fixes over the first cut:
  1. **Prep the roster up front.** build_roster_table / allocate_roster need prep_data's
     derived columns (PIT_CON, CON_P, POS dummies, _ORD). Without it pitcher F2 read 0 and
     prospects were cut on later=0. prep_data is idempotent, so we call it unconditionally.
  2. **Age-conditioned development arc** (replaces the flat rate AND the meaningless F2−F1
     "growth" column). expected_mature = current + gap × delivery_rate × runway(age, skill).
"""

import datetime as _dt
import pandas as pd
import streamlit as st

from db import League
import acquisitions as acq
import roster_construction as rc
from development import _load_roster, _saved_roster, _load_dev_state, recommend_player
from my_team import build_roster_table

BATTER_POSITIONS = getattr(acq, 'BATTER_POSITIONS', {'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'})
PITCHER_POSITIONS = getattr(acq, 'PITCHER_POSITIONS', {'SP', 'RP', 'CL'})
_s = acq._s

# ── Delivery rates (OOTP 27, A-T locked — Spec v15.14). Fraction of the current→potential
#    gap realized at full runway.
DELIVERY_RATES = {'CON': 0.48, 'GAP': 0.48, 'POW': 0.45, 'EYE': 0.28,
                  'STU': 0.53, 'MOV': 0.40, 'PIT_CON': 0.43}
_BAT_SKILLS = ['CON', 'POW', 'GAP', 'EYE']
_PIT_SKILLS = ['MOV', 'STU', 'PIT_CON']

_SLOT_LABEL = {
    'promote':   '⬆️ → 25-man (promote)', 'keep': '✅ 25-man / active',
    'hold-down': '⏸️ Reserve (hold-down)', 'protected': '🛡️ Protected (40-man)',
    'trade':     '🔁 Trade block', 'cut': '✕ Cut',
}


def _runway(age: int, skill: str, is_pit: bool) -> float:
    """Age multiplier on the delivered gap. Heuristic derived from the locked aging
    findings (batter peak 25 / decline 29+; SP MOV/STU decline 28, PIT_CON holds 32;
    EYE never declines) — NOT a fitted coefficient; replace with a snapshot-fit curve
    once history accumulates. Runs 1.0 (full runway) → 0 (at peak) → negative (decline)."""
    a = age if age and age > 0 else 25
    if   a <= 21: base = 1.0
    elif a <= 25: base = 1.0 - 0.30 * (a - 21) / 4.0        # 1.00 → 0.70
    elif a <= 28: base = 0.70 - 0.50 * (a - 25) / 3.0       # 0.70 → 0.20
    elif a <= 31: base = 0.0 - 0.30 * (a - 28) / 3.0        # 0.00 → -0.30
    else:         base = -0.30 - 0.30 * min(a - 31, 6) / 6.0  # -0.30 → -0.60
    if skill == 'EYE':                                     # never declines (holds to 37)
        return round(max(0.0, base), 3)
    if is_pit and skill in ('MOV', 'STU') and a >= 28:     # arm decline starts at 28
        base = min(base, -0.10 - 0.40 * min(a - 28, 9) / 9.0)
    if is_pit and skill == 'PIT_CON' and a <= 32:          # control holds to 32 (Jarry)
        base = max(base, 0.0)
    return round(base, 3)


def _dev_arc(raw: dict, is_pit: bool):
    """Per-skill age-conditioned arc + a one-word outlook. Returns (rows, outlook, net)."""
    age = int(_s(raw.get('AGE', raw.get('Age', 0))))
    skills = _PIT_SKILLS if is_pit else _BAT_SKILLS
    rows, net = [], 0.0
    for sk in skills:
        cur = _s(raw.get(sk))
        pot = _s(raw.get(sk + '_P'))
        if cur == 0 and pot == 0:
            continue
        rate = DELIVERY_RATES[sk]
        rw = _runway(age, sk, is_pit)
        delivered = (pot - cur) * rate * rw
        exp = cur + delivered
        net += delivered
        rows.append({'Skill': sk, 'Current': round(cur), 'Potential': round(pot),
                     'Gap': round(pot - cur), 'Delivery': f"{rate:.0%}",
                     'Age runway': f"{rw:+.2f}", 'Expected mature': round(exp),
                     'Outlook': ('▲ gain' if delivered >= 1 else
                                 '▼ decline' if delivered <= -1 else '– hold')})
    if not rows:
        outlook = '—'
    elif age <= 24 and net >= 3:  outlook = 'Developing ↑'
    elif net >= 1:                outlook = 'Some upside'
    elif net <= -1:               outlook = 'Declining ↓'
    else:                         outlook = 'At peak'
    return rows, outlook, net


def render_player_card(league: League):
    st.header("🪪 Player Card")
    st.caption("Upload a roster → F1 / F2 / development outlook / roster slot for everyone, "
               "then pick a player below for the full card. Reuses the suite's own F1, F2 and "
               "roster allocator, so the numbers match the other tabs.")

    complete, missing = league.team_config_complete()
    if not complete:
        st.warning(f"Team Config incomplete ({', '.join(missing)}). Slotting uses your "
                   "mode/phase — set them in ⚙️ Settings.")

    df = _load_roster(league)
    if df is None or df.empty:
        df = _saved_roster(league)
    if df is None or df.empty:
        st.info("Upload a roster CSV (📤 expander above) to build cards.")
        return

    # CRITICAL: prep once, up front — every downstream (build_roster_table, allocate_roster,
    # the arc) needs the derived columns. prep_data is idempotent, so this is always safe.
    try:
        df = acq.prep_data(df.copy())
    except Exception as e:
        st.error(f"Couldn't prepare the roster ({e}).")
        return

    try:
        tbl = build_roster_table(df)
    except Exception as e:
        st.error(f"Couldn't build the roster table: {e}")
        return
    if tbl.empty:
        st.info("Roster table is empty after filtering to your team.")
        return

    mode = league.team_config.get('mode', 'Competing')
    # Roster phase drives the slotting. Default to a NON-cutting phase so the card is a
    # viewing tool (prospects aren't force-cut); user can switch to Opening Day for the
    # trim-to-25 analysis. Cut logic itself lives in the Roster Construction tab.
    phases = list(rc.PHASE_PRESETS.keys())
    default_phase = 'Offseason' if 'Offseason' in phases else phases[0]
    colp1, colp2 = st.columns([1, 3])
    with colp1:
        phase = st.selectbox("Roster phase", phases,
                             index=phases.index(default_phase), key="pc_phase",
                             help="Sets the active/reserve caps. Non-cutting phases "
                                  "(Offseason/September) show placement without forced cuts; "
                                  "Opening Day trims to 25 active + 15 reserve.")
    with colp2:
        cap = rc.PHASE_PRESETS[phase].get('active')
        st.caption(f"Active cap: **{cap if cap is not None else '—'}** · "
                   f"forced cuts fire only when the roster exceeds the cap.")
    decisions = _roster_decisions(league, df, mode, phase)
    raw_by_name = {str(r.get('Name', '')): r for r in df.to_dict('records')}

    # 📸 snapshot (the ONLY thing that accumulates history)
    with st.expander("📸 Snapshot — stamp today's ratings into the tracked history"):
        c1, c2 = st.columns([3, 1])
        with c1:
            snap_label = st.text_input("Label", value=_dt.date.today().isoformat(), key="pc_lbl",
                                       help="e.g. 'Opening Day', 'Post-Draft', 'Deadline'")
        with c2:
            snap_year = st.number_input("Season", 1871, 2100,
                                        int(league.team_config.get('season_year', 1976) or 1976),
                                        key="pc_yr")
        st.caption("Records every player's ratings + F1/F2 today. History panels diff "
                   "oldest→newest. Only this button snapshots — routine saves overwrite.")
        if st.button("📸 Save Snapshot", key="pc_snap", type="primary"):
            try:
                sid = league.save_snapshot(df, label=snap_label.strip() or _dt.date.today().isoformat(),
                                           season_year=int(snap_year))
                st.success(f"Snapshot #{sid} saved ({len(df)} players).")
            except Exception as e:
                st.error(f"Snapshot failed: {e}")

    # summary table (NO F2−F1 growth column — replaced by the age-conditioned outlook)
    disp = []
    for _, r in tbl.iterrows():
        nm = str(r.get('Name', ''))
        is_pit = str(r.get('POS', '')) in PITCHER_POSITIONS
        _, outlook, _ = _dev_arc(raw_by_name.get(nm, {}), is_pit)
        slot, reason = decisions.get(nm, ('—', ''))
        disp.append({'Name': nm, 'POS': r.get('POS', ''), 'Age': r.get('Age', ''),
                     'F1 (now)': round(_s(r.get('F1')), 2), 'F2 (proj)': round(_s(r.get('F2')), 2),
                     'Dev outlook': outlook, 'Roster slot': slot, 'Why': reason})
    disp_df = pd.DataFrame(disp).sort_values('F2 (proj)', ascending=False)
    st.markdown(f"##### Roster — {len(disp_df)} players · mode **{mode}**")
    st.dataframe(disp_df, use_container_width=True, hide_index=True)
    st.caption("**F1** = current MLB WAR (playing-time driven — reads low/negative for young "
               "players with no MLB reps; that's expected, judge them on F2). **F2** = projected "
               "mature WAR (the prospect lens). **Dev outlook** = age-conditioned development.")

    # ── the card (driven by the dropdown, not a table click) ─────────────────────
    st.markdown("### 🪪 Player card")
    st.caption("👇 Pick a player here to open their card (the table above isn't clickable).")
    pick = st.selectbox("Player", disp_df['Name'].tolist(), key="pc_pick")
    if pick:
        prow = tbl[tbl['Name'].astype(str) == pick]
        _render_card(league, pick, prow.iloc[0] if len(prow) else None,
                     raw_by_name.get(pick, {}), decisions.get(pick, ('—', '')))


def _render_card(league, name, prow, raw, decision):
    if prow is None:
        st.info("Player not found."); return
    pos = str(prow.get('POS', ''))
    is_pit = pos in PITCHER_POSITIONS
    f1, f2 = _s(prow.get('F1')), _s(prow.get('F2'))
    slot, reason = decision
    arc_rows, outlook, net = _dev_arc(raw, is_pit)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("F1 (now)", f"{f1:+.2f}")
    c2.metric("F2 (projected)", f"{f2:+.2f}")
    c3.metric("Dev outlook", outlook)
    c4.metric("Age", f"{prow.get('Age', '—')}")
    if f1 < 0 and f2 > 0.5:
        st.info("ℹ️ Negative F1 with positive F2 = a **prospect** — no MLB reps yet, so present "
                "WAR reads negative. Judge him on F2 and the arc, not F1.")
    st.markdown(f"**Roster slot:** {slot}" + (f"  ·  _{reason}_" if reason else ""))

    st.markdown("##### 📈 Development arc — delivery rate × age runway")
    if arc_rows:
        st.dataframe(pd.DataFrame(arc_rows), use_container_width=True, hide_index=True)
        st.caption("Expected mature = current + (potential − current) × delivery rate × age "
                   "runway. Runway is 1.0 for young players, tapers toward 0 near peak (28), and "
                   "goes negative past decline (29+) — so a nominal 'potential' on an older player "
                   "correctly shows as decline. EYE never declines; arm ratings decline from 28, "
                   "control holds to 32. (Runway is a heuristic from the aging findings, not a "
                   "fitted curve.)")
    else:
        st.caption("No potential columns in this export — arc unavailable.")

    st.markdown("##### 🕰️ Tracked history")
    hist = league.snapshot_player_history(name)
    if not hist:
        st.info("No snapshots yet. Press **📸 Save Snapshot** above to start tracking — "
                "gains/losses will show here once you've stamped two or more.")
        return
    hdf = pd.DataFrame(hist)
    cols = (['created_at', 'season_year', 'age', 'mov', 'stu', 'pit_con', 'pit_war', 'sp_f1']
            if is_pit else
            ['created_at', 'season_year', 'age', 'con', 'pow', 'eye', 'gap', 'war', 'off_f1'])
    show = [c for c in cols if c in hdf.columns]
    hd = hdf[show].copy()
    if 'created_at' in hd: hd['created_at'] = hd['created_at'].astype(str).str.slice(0, 10)
    st.dataframe(hd, use_container_width=True, hide_index=True)
    if len(hdf) >= 2:
        track = ([('mov', 'MOV'), ('stu', 'STU'), ('pit_con', 'CON'), ('stm', 'STM')] if is_pit
                 else [('con', 'CON'), ('pow', 'POW'), ('eye', 'EYE'), ('gap', 'GAP'), ('spe', 'SPE')])
        f, l = hdf.iloc[0], hdf.iloc[-1]
        deltas = [f"{lbl} {_s(l.get(c)) - _s(f.get(c)):+.0f}" for c, lbl in track
                  if c in hdf.columns and abs(_s(l.get(c)) - _s(f.get(c))) >= 0.5]
        span = f"{str(f.get('created_at'))[:10]} → {str(l.get('created_at'))[:10]}"
        st.markdown(f"**Since first tracked** ({span}): " +
                    (", ".join(deltas) if deltas else "no rating moved ≥1 point yet."))
    else:
        st.caption("Baseline recorded. Add another snapshot next season to see the arc.")


def _roster_decisions(league, df, mode, phase=None) -> dict:
    """Same allocator the Roster Construction tab uses → {name:(slot,reason)}. df MUST be prepped."""
    try:
        cfg = _load_dev_state(league)
        rcfg = cfg.get('reserve', {})
        if phase not in rc.PHASE_PRESETS:
            phase = rcfg.get('phase') if rcfg.get('phase') in rc.PHASE_PRESETS else list(rc.PHASE_PRESETS)[0]
        rows = df.to_dict('records')
        active = {str(r.get('Name', '')): str(r.get('IS_ACTIVE', r.get('ACT', ''))).strip().lower()
                  in ('yes', 'true', '1', 'y', 't') for r in rows}
        payroll = {str(r.get('Name', '')): _s(r.get('SALARY', 0)) for r in rows}
        growth = {}
        for row in rows:
            rec = recommend_player(row, cfg)
            growth[str(row.get('Name', ''))] = sum(rec['weighted_gaps'].values()) if rec else 0.0
        res = rc.allocate_roster(rows, growth, mode, phase=phase, active_flag_by_name=active,
                                 budget=float(_s(league.team_config.get('budget', 0))),
                                 payroll_by_name=payroll,
                                 max_proactive_trades=int(rcfg.get('max_proactive_trades', 4)))
        out = {}
        for r in res.get('records', []):
            dec = r.get('decision', '')
            label = _SLOT_LABEL.get(dec, dec)
            if dec == 'keep' and not r.get('is_active'):
                label = '🗂️ Reserve (40-man)'
            out[str(r.get('name', ''))] = (label, (r.get('reasons') or [''])[0])
        return out
    except Exception as e:
        st.caption(f"⚠️ Roster slotting unavailable ({e}); showing F1/F2 only.")
        return {}
