"""
OOTP 27 Suite — Player Card (🪪)
================================
The one-stop per-player view: upload a roster, see everyone's F1 / F2 / projected
growth / roster slot in a sortable table, then click a player for the full card —
F1 & F2, the development arc (delivery-rate expectations), the roster decision the
allocator makes (40-man / 25-man / reserve / cut) with its one-line reason, and the
player's tracked history across saved snapshots.

Single source of truth: reuses `my_team.build_roster_table` (F1/F2/TV),
`roster_construction.allocate_roster` (slot + reason), the Development roster loader,
and `db.snapshot_player_history` (history). This view COMPOSES; it never recomputes,
so it can't drift from the rest of the suite.

History note: the per-player arc "since we started tracking" reads accumulated
snapshots. Snapshots are stamped ONLY by the 📸 button here (or a future save that
calls `save_snapshot`) — the routine roster save overwrites and keeps no history.
So history starts the first time you press 📸 and fills in going forward.
"""

import datetime as _dt
import pandas as pd
import streamlit as st

from db import League
import roster_construction as rc
from development import _load_roster, _saved_roster, _load_dev_state, recommend_player
from my_team import build_roster_table, _active_flag_col

try:
    from acquisitions import BATTER_POSITIONS, PITCHER_POSITIONS, _s
except Exception:
    BATTER_POSITIONS = {'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'}
    PITCHER_POSITIONS = {'SP', 'RP', 'CL'}
    def _s(v, d=0.0):
        try:
            f = float(v); return d if pd.isna(f) else f
        except (TypeError, ValueError):
            return d

# ── Delivery rates (OOTP 27, A-T locked — Spec v15.14 Formula Reference). Fraction of
#    the current→potential gap a player is expected to realize. Expected mature rating
#    = current + (potential − current) × rate. These are DISPLAY-only projection aids.
DELIVERY_RATES = {
    'CON': 0.48, 'GAP': 0.48, 'POW': 0.45, 'EYE': 0.28,        # batter
    'STU': 0.53, 'MOV': 0.40, 'PIT_CON': 0.43,                  # pitcher
}
_POT_COL = {'CON': 'CON_P', 'GAP': 'GAP_P', 'POW': 'POW_P', 'EYE': 'EYE_P',
            'STU': 'STU_P', 'MOV': 'MOV_P', 'PIT_CON': 'PIT_CON_P'}
_BAT_SKILLS = ['CON', 'POW', 'GAP', 'EYE']
_PIT_SKILLS = ['MOV', 'STU', 'PIT_CON']

# ── Allocator decision → human roster-slot label
_SLOT_LABEL = {
    'promote':   '⬆️ → 25-man (promote)',
    'keep':      '✅ 25-man / active',
    'hold-down': '⏸️ Reserve (hold-down)',
    'protected': '🛡️ Protected (40-man)',
    'trade':     '🔁 Trade block',
    'cut':       '✕ Cut',
}


def render_player_card(league: League):
    st.header("🪪 Player Card")
    st.caption("Upload a roster → F1 / F2 / projected growth / roster slot for everyone, "
               "then open a player for the full card. Reuses the same F1, F2 and "
               "roster-allocator the other tabs use — one consistent picture.")

    complete, missing = league.team_config_complete()
    if not complete:
        st.warning(f"Team Config incomplete ({', '.join(missing)} missing). "
                   "Roster slotting uses your mode/phase — configure in ⚙️ Settings.")

    # roster: prefer an active upload; fall back to the saved roster
    df = _load_roster(league)
    if df is None or df.empty:
        df = _saved_roster(league)
    if df is None or df.empty:
        st.info("Upload a roster CSV (the **📤 Upload roster** expander above) to build cards.")
        return

    # ── canonical per-player table (F1/F2/TV/ratings) ────────────────────────────
    try:
        tbl = build_roster_table(df)
    except Exception as e:
        st.error(f"Couldn't build the roster table: {e}")
        return
    if tbl.empty:
        st.info("Roster table is empty after filtering to your team.")
        return

    mode = league.team_config.get('mode', 'Competing')
    decisions = _roster_decisions(league, df, mode)   # {name: (slot_label, reason)}

    # ── 📸 snapshot control (the ONLY thing that accumulates history) ────────────
    with st.expander("📸 Snapshot — stamp today's ratings into the tracked history"):
        c1, c2, c3 = st.columns([2, 1, 2])
        with c1:
            snap_label = st.text_input("Label", value=_default_label(),
                                       key="pc_snap_label",
                                       help="e.g. '1976 Opening Day', 'Post-Draft', 'Deadline'")
        with c2:
            snap_year = st.number_input("Season", min_value=1871, max_value=2100,
                                        value=int(league.team_config.get('season_year', 1976) or 1976),
                                        key="pc_snap_year")
        with c3:
            st.caption("A snapshot records every player's ratings + F1/F2 with today's "
                       "date. History panels below diff oldest→newest. Routine saves do "
                       "NOT snapshot — only this button does.")
        if st.button("📸 Save Snapshot", key="pc_snap_btn", type="primary"):
            try:
                phase = _load_dev_state(league).get('reserve', {}).get('phase')
                sid = league.save_snapshot(df, label=snap_label.strip() or _default_label(),
                                           season_year=int(snap_year), phase=phase)
                st.success(f"Snapshot #{sid} saved ({len(df)} players). "
                           "It'll appear in the history panels immediately.")
            except Exception as e:
                st.error(f"Snapshot failed: {e}")

    # ── summary table ────────────────────────────────────────────────────────────
    disp = []
    for _, r in tbl.iterrows():
        nm = str(r.get('Name', ''))
        f1, f2 = _s(r.get('F1')), _s(r.get('F2'))
        slot, reason = decisions.get(nm, ('—', ''))
        disp.append({
            'Name': nm, 'POS': r.get('POS', ''), 'Age': r.get('Age', ''),
            'F1': round(f1, 2), 'F2': round(f2, 2),
            'Growth (F2−F1)': round(f2 - f1, 2),
            'Arc': _growth_band(f2 - f1),
            'Roster slot': slot, 'Why': reason,
        })
    disp_df = pd.DataFrame(disp).sort_values('F1', ascending=False)
    st.markdown(f"##### Roster — {len(disp_df)} players  ·  mode **{mode}**")
    st.dataframe(disp_df, use_container_width=True, hide_index=True)
    st.caption("F1 = current-value WAR · F2 = projected mature WAR · Growth = F2−F1 "
               "(the development arc) · slot = what the roster allocator does with him.")

    # ── click-to-expand: pick a player, show the full card ───────────────────────
    st.markdown("### 🪪 Player card")
    names = disp_df['Name'].tolist()
    pick = st.selectbox("Player", names, key="pc_pick")
    if pick:
        prow = tbl[tbl['Name'].astype(str) == pick]
        raw  = df[df.get('Name', pd.Series(dtype=str)).astype(str) == pick]
        _render_card(league, pick, prow.iloc[0] if len(prow) else None,
                     raw.iloc[0].to_dict() if len(raw) else {},
                     decisions.get(pick, ('—', '')))


# ══════════════════════════════════════════════════════════════════════════════
# THE CARD
# ══════════════════════════════════════════════════════════════════════════════

def _render_card(league, name, prow, raw, decision):
    if prow is None:
        st.info("Player not found in the built table."); return
    pos = str(prow.get('POS', ''))
    is_pit = pos in PITCHER_POSITIONS
    f1, f2 = _s(prow.get('F1')), _s(prow.get('F2'))
    slot, reason = decision

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("F1 (now)", f"{f1:+.2f}")
    c2.metric("F2 (projected)", f"{f2:+.2f}")
    c3.metric("Growth", f"{f2 - f1:+.2f}", _growth_band(f2 - f1))
    c4.metric("Age", f"{prow.get('Age', '—')}")

    st.markdown(f"**Roster slot:** {slot}" + (f"  ·  _{reason}_" if reason else ""))
    flags = prow.get('Flags', '')
    if isinstance(flags, str) and flags.strip():
        st.caption(f"⚑ {flags}")

    # ── development arc: delivery-rate expectations (single upload) ───────────────
    st.markdown("##### 📈 Development arc — delivery-rate expectations")
    skills = _PIT_SKILLS if is_pit else _BAT_SKILLS
    arc = []
    for sk in skills:
        cur = _s(raw.get(sk))
        potcol = _POT_COL[sk]
        if potcol not in raw or raw.get(potcol) in (None, '') or pd.isna(_s(raw.get(potcol), float('nan'))):
            continue
        pot = _s(raw.get(potcol))
        rate = DELIVERY_RATES[sk]
        exp = cur + (pot - cur) * rate
        arc.append({'Skill': sk, 'Current': round(cur), 'Potential': round(pot),
                    'Gap': round(pot - cur), 'Delivery rate': f"{rate:.0%}",
                    'Expected mature': round(exp),
                    'Status': _delivery_status(cur, pot)})
    if arc:
        st.dataframe(pd.DataFrame(arc), use_container_width=True, hide_index=True)
        st.caption("Expected mature = current + (potential − current) × delivery rate "
                   "(A-T locked rates). It's the realistic landing spot, not the ceiling.")
    else:
        st.caption("No potential columns in this export — arc unavailable "
                   "(re-export with potentials to see the delivery view).")

    # ── tracked history (accumulated snapshots) ──────────────────────────────────
    st.markdown("##### 🕰️ Tracked history")
    hist = league.snapshot_player_history(name)
    if not hist:
        st.info("No snapshots recorded for this player yet. Press **📸 Save Snapshot** "
                "above to start tracking — future snapshots will show gains/losses here.")
        return
    hcols = (['created_at', 'season_year', 'age', 'mov', 'stu', 'pit_con', 'stm', 'pit_war', 'sp_f1']
             if is_pit else
             ['created_at', 'season_year', 'age', 'con', 'pow', 'eye', 'gap', 'spe', 'war', 'off_f1'])
    hdf = pd.DataFrame(hist)
    show = [c for c in hcols if c in hdf.columns]
    hdf_disp = hdf[show].copy()
    hdf_disp['created_at'] = hdf_disp['created_at'].astype(str).str.slice(0, 10)
    st.dataframe(hdf_disp, use_container_width=True, hide_index=True)

    if len(hdf) >= 2:
        first, last = hdf.iloc[0], hdf.iloc[-1]
        track = _PIT_SKILLS_HIST if is_pit else _BAT_SKILLS_HIST
        deltas = []
        for col, lbl in track:
            if col in hdf.columns:
                d = _s(last.get(col)) - _s(first.get(col))
                if abs(d) >= 0.5:
                    deltas.append(f"{lbl} {d:+.0f}")
        span = f"{str(first.get('created_at'))[:10]} → {str(last.get('created_at'))[:10]}"
        if deltas:
            ups = [d for d in deltas if '+' in d]; downs = [d for d in deltas if '-' in d]
            st.markdown(f"**Since first tracked** ({span}):  "
                        + ("📈 " + ", ".join(ups) + "  " if ups else "")
                        + ("📉 " + ", ".join(downs) if downs else ""))
        else:
            st.caption(f"Tracked {span} — no rating moved ≥1 point yet.")
    else:
        st.caption("Baseline recorded. Add another snapshot next season to see the arc.")


# skill columns tracked in the history delta line (snapshot_players column names)
_BAT_SKILLS_HIST = [('con', 'CON'), ('pow', 'POW'), ('eye', 'EYE'), ('gap', 'GAP'), ('spe', 'SPE')]
_PIT_SKILLS_HIST = [('mov', 'MOV'), ('stu', 'STU'), ('pit_con', 'CON'), ('stm', 'STM')]


# ══════════════════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════════════════

def _growth_band(g: float) -> str:
    if g >= 1.0:  return "High"
    if g >= 0.3:  return "Med"
    if g >= 0.0:  return "Low"
    return "Declining"


def _delivery_status(cur: float, pot: float) -> str:
    gap = pot - cur
    if gap <= 2:   return "at ceiling"
    if gap <= 8:   return "some growth"
    return "high upside"


def _default_label() -> str:
    return _dt.date.today().isoformat()


def _roster_decisions(league, df, mode) -> dict:
    """Run the SAME allocator the Roster Construction tab uses; return {name:(slot,reason)}.
    Fail-soft: if the allocator can't run (missing cols), return {} so the table still shows."""
    try:
        cfg = _load_dev_state(league)
        rcfg = cfg.get('reserve', {})
        phase = rcfg.get('phase') if rcfg.get('phase') in rc.PHASE_PRESETS else list(rc.PHASE_PRESETS)[0]
        rows = df.to_dict('records')
        active_flag = {str(r.get('Name', '')):
                       str(r.get('IS_ACTIVE', r.get('ACT', ''))).strip().lower()
                       in ('yes', 'true', '1', 'y', 't') for r in rows}
        payroll = {str(r.get('Name', '')): _s(r.get('SALARY', 0)) for r in rows}
        tbl = build_roster_table(df)
        f2_by = {str(t['Name']): _s(t.get('F2', 0)) for _, t in tbl.iterrows()} if 'F2' in tbl.columns else {}
        growth = {}
        for row in rows:
            rec = recommend_player(row, cfg)
            nm = str(row.get('Name', ''))
            growth[nm] = sum(rec['weighted_gaps'].values()) if rec else max(0.0, f2_by.get(nm, 0.0))
        budget = _s(league.team_config.get('budget', 0))
        res = rc.allocate_roster(rows, growth, mode, phase=phase,
                                 active_flag_by_name=active_flag, budget=float(budget),
                                 payroll_by_name=payroll,
                                 max_proactive_trades=int(rcfg.get('max_proactive_trades', 4)))
        out = {}
        for r in res.get('records', []):
            dec = r.get('decision', '')
            label = _SLOT_LABEL.get(dec, dec)
            if dec == 'keep' and not r.get('is_active'):
                label = '🗂️ Reserve (40-man)'
            reason = (r.get('reasons') or [''])[0]
            out[str(r.get('name', ''))] = (label, reason)
        return out
    except Exception as e:
        st.caption(f"⚠️ Roster slotting unavailable ({e}); showing F1/F2 only.")
        return {}
