"""
OOTP 27 Suite — Pitching Module (Rotation + Bullpen + Fatigue)
==============================================================
Three tabs, Acquisitions-style. This module answers the one question no other
module does: given the arms I have, HOW do I deploy them?

  🔄 Rotation  — top-6 starters by sp_f1 + a "stretch / spot-start depth" group,
                 STM shown as innings VOLUME (not a gate), projected-IP column.
  💪 Bullpen   — rp_f1 quality gate → closer = highest STU among qualifiers,
                 all other roles ordered by rp_f1 (not raw MOV). Dual-eligibility:
                 SP-capable arms appear here too, tagged.
  🩹 Fatigue   — SPF%/RPF% current-snapshot readout with provisional, editable
                 green/amber/red bands (persisted in pitching_state).

Design decisions (locked in design review, May 2026):
  • Role is an OUTPUT of skills, not an input. SP/RP/CL are fluid — every arm is
    priced as BOTH a starter (sp_f1) and a reliever (rp_f1). No STM bucket, no
    count gate. We do NOT collapse to one number in the staff card; pitcher_f1's
    route-to-SP routing is reserved for single-number callers (trade value).
  • The ONE earned hard gate is top-pitch quality (best >= 50 + one secondary
    >= 40), and it ROUTES rather than discards: an arm failing the rotation gate
    drops to the bullpen pool, never off the staff. Defined once in
    acquisitions.passes_pitch_gate; editable here via pitching_state.
  • STM has no floor — it's a smooth innings-volume lever (WAR/IP flat across
    35-85). Surfaced as a projected-IP column so the volume tradeoff is explicit.
  • Boundary with My Team: My Team owns roster LEGALITY (6/5/14, never 7+ RP) and
    active/reserve. Pitching owns DEPLOYMENT (who starts, who relieves in which
    role, who's gassed). We do not re-run the construction audit here.
  • Reuses the saved roster (league.get_last_roster) + the same engine guard +
    ORG filter as My Team / Lineups. State persists in config.json under
    'pitching_state' via save_config/get_config — not a new SQLite table.

Upgrade path (flagged, not built): the cleanest long-term role assignment is a
v27 refit of per-role WAR models (the v26 ROLE_MODELS had the right instinct —
price every arm in every role — but the coefficients aren't engine-portable).
For now: rp_f1 quality gate + A6 role-fit heuristic (closer = stuff arm).
"""

import numpy as np
import pandas as pd
import streamlit as st

from db import League

from acquisitions import (
    prep_data,
    sp_f1, rp_f1,
    top_pitch_grade, secondary_pitch_count,
    passes_pitch_gate, thin_out_pitch, PITCH_GATE_DEFAULTS,
    cnt_eff_pitches,
    PITCHER_POSITIONS, BATTER_POSITIONS,
    _s,
)
from my_team import sp_capable

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

ROTATION_SIZE = 6   # registry A6: 6-man rotation universally optimal (+3.2 WAR)
BULLPEN_SIZE  = 5   # registry A6: 5 RP is WAR-maximizing; never carry 7+

# Bullpen role templates keyed by bullpen size (structure ported from v26;
# coefficients/ordering are NOT — see role assignment below). Closer is always
# the special role (A6); the remainder are graded relievers.
ROLE_TEMPLATES = {
    3: ['Closer', 'Setup', 'Middle Relief'],
    4: ['Closer', 'Setup', 'Middle Relief', 'Long Relief'],
    5: ['Closer', 'Setup', 'Middle Relief', 'Middle Relief', 'Long Relief'],
    6: ['Closer', 'Setup', 'Setup', 'Middle Relief', 'Middle Relief', 'Long Relief'],
    7: ['Closer', 'Setup', 'Setup', 'Middle Relief', 'Middle Relief',
        'Long Relief', 'Long Relief'],
}

# STM as a VOLUME lever, not a gate. Study (N=19,211 established starters): IP
# rises ~+1.25 per STM-point; WAR/IP is flat. Project innings off an STM-35
# baseline purely to make the volume tradeoff visible — NOT a quality signal.
IP_PER_STM_POINT = 1.25
STM_IP_BASELINE  = 35      # STM at which the projection starts
BASE_IP_AT_FLOOR = 120.0   # rough full-season SP innings at the STM-35 baseline

# Provisional fatigue bands (SPF% / RPF%). No fatigue→performance study exists
# yet, so these are editable + persisted, same philosophy as the Lineups ZR
# floors. Higher % = more rested. Re-calibrate against a real Quakers export.
DEFAULT_FATIGUE_BANDS = {
    'green': 60,   # >= green  → fresh
    'amber': 40,   # >= amber  → monitor; below amber → red (rest recommended)
}


# ══════════════════════════════════════════════════════════════════════════════
# PROJECTIONS
# ══════════════════════════════════════════════════════════════════════════════

def projected_ip(row) -> float:
    """
    Rough projected full-season starter innings from STM, as a VOLUME readout.
    STM is a smooth innings lever (not a quality gate); this exists so a high-F1
    low-STM arm vs a slightly-lower-F1 workhorse tradeoff is explicit on screen.
    """
    stm = _s(row.get('STM', 0))
    return round(BASE_IP_AT_FLOOR + max(0.0, stm - STM_IP_BASELINE) * IP_PER_STM_POINT, 0)


def _con_flag(row) -> str:
    """LOW-CON per registry A6 (PIT_CON < 40 → generally avoid)."""
    con = _s(row.get('PIT_CON', 0))
    return 'LOW-CON' if con < 40 else ''


def _personality_skip(row) -> str:
    """A6 hard rule: Unmotivated / Disruptive = auto-skip, never override."""
    p = str(row.get('TYPE', row.get('Type', ''))).strip()
    if p in ('Unmotivated', 'Disruptive'):
        return p
    return ''


# ══════════════════════════════════════════════════════════════════════════════
# ROTATION BUILD
# ══════════════════════════════════════════════════════════════════════════════

def build_rotation(pits_df: pd.DataFrame, gate: dict) -> dict:
    """
    Rank starter-eligible arms by sp_f1, take top-6 = rotation. Arms that clear
    the top-pitch gate but miss the top-6 = stretch/spot-start depth. Arms that
    FAIL the gate are not stranded — they're flagged as bullpen-routed (the
    bullpen build picks them up). Returns dicts, not just the cut.
    """
    rows = []
    for _, r in pits_df.iterrows():
        gated = passes_pitch_gate(r, gate)
        rows.append({
            'row':        r,
            'name':       str(r.get('Name', '')),
            'age':        int(_s(r.get('Age', 0))),
            'sp_f1':      round(sp_f1(r), 2),
            'rp_f1':      round(rp_f1(r), 2),
            'stu':        int(_s(r.get('STU', 0))),
            'mov':        int(_s(r.get('MOV', 0))),
            'pit_con':    int(_s(r.get('PIT_CON', 0))),
            'stm':        int(_s(r.get('STM', 0))),
            'proj_ip':    projected_ip(r),
            'top_pitch':  int(top_pitch_grade(r)),
            'gated':      gated,
            'thin':       thin_out_pitch(r, gate),
            'con_flag':   _con_flag(r),
            'skip':       _personality_skip(r),
        })

    # Rotation pool = arms that clear the gate AND aren't auto-skip personalities.
    pool = [x for x in rows if x['gated'] and not x['skip']]
    pool.sort(key=lambda x: x['sp_f1'], reverse=True)

    rotation = pool[:ROTATION_SIZE]
    depth    = pool[ROTATION_SIZE:]              # stretch / spot-start, ranked by sp_f1
    routed   = [x for x in rows if not x['gated'] and not x['skip']]   # → bullpen only
    skipped  = [x for x in rows if x['skip']]

    return {
        'rotation': rotation,
        'depth':    depth,
        'routed':   routed,
        'skipped':  skipped,
        'all':      rows,
    }


# ══════════════════════════════════════════════════════════════════════════════
# BULLPEN BUILD
# ══════════════════════════════════════════════════════════════════════════════

def build_bullpen(pits_df: pd.DataFrame, rotation_names: set, gate: dict,
                  bp_size: int = BULLPEN_SIZE) -> dict:
    """
    Q1(i) resolved toward the model:
      • Quality gate: rank by rp_f1 (the validated RP model decides who's pen-worthy).
      • Closer: highest STU among the rp_f1-qualified arms (A6 role-fit — the
        9th-inning role rewards the stuff/strikeout arm).
      • All other roles: ordered by rp_f1, NOT raw MOV. "Sort by MOV" was the
        pre-model v26 heuristic; rp_f1 already weights MOV in a validated way, so
        grading the non-closer tiers by the model strictly beats the raw proxy.

    Pool = every pitcher not in the rotation (dual-eligibility: a stretchable arm
    that started would not be here, but an SP-capable arm that missed the top-6
    IS here, tagged). Auto-skip personalities excluded.
    """
    candidates = []
    for _, r in pits_df.iterrows():
        name = str(r.get('Name', ''))
        if name in rotation_names:
            continue
        if _personality_skip(r):
            continue
        candidates.append({
            'row':       r,
            'name':      name,
            'age':       int(_s(r.get('Age', 0))),
            'rp_f1':     round(rp_f1(r), 2),
            'sp_f1':     round(sp_f1(r), 2),
            'stu':       int(_s(r.get('STU', 0))),
            'mov':       int(_s(r.get('MOV', 0))),
            'pit_con':   int(_s(r.get('PIT_CON', 0))),
            'stm':       int(_s(r.get('STM', 0))),
            'sp_capable': sp_capable(r),
            'con_flag':  _con_flag(r),
        })

    # Quality gate: best rp_f1 arms make the pen.
    candidates.sort(key=lambda x: x['rp_f1'], reverse=True)
    pen = candidates[:bp_size]
    overflow = candidates[bp_size:]   # not stranded — surfaced as next-up depth

    roles = ROLE_TEMPLATES.get(bp_size,
              ['Closer', 'Setup'] + ['Middle Relief'] * max(0, bp_size - 2))[:bp_size]

    assignments = []
    if pen:
        # Closer = highest STU among the qualified arms (A6 role-fit).
        closer = max(pen, key=lambda x: x['stu'])
        non_closers = [x for x in pen if x is not closer]
        # All other roles ordered by rp_f1 (model, not raw MOV).
        non_closers.sort(key=lambda x: x['rp_f1'], reverse=True)

        ordered = [closer] + non_closers
        for role, arm in zip(roles, ordered):
            a = dict(arm)
            a['role'] = role
            assignments.append(a)

    return {
        'bullpen':  assignments,
        'overflow': overflow,
        'bp_size':  bp_size,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FATIGUE
# ══════════════════════════════════════════════════════════════════════════════

def fatigue_band(pct: float, bands: dict) -> str:
    """Map a fatigue % to a band label. Higher % = more rested."""
    if pct >= bands['green']:
        return 'fresh'
    if pct >= bands['amber']:
        return 'monitor'
    return 'rest'


def build_fatigue(pits_df: pd.DataFrame, bands: dict) -> list[dict]:
    """
    Single-snapshot fatigue readout. One export = one moment, so this is a
    current-state readout + flags, not a multi-day workload projection. Shows
    whichever of SPF%/RPF% is populated for each arm.

    Missing/zero handling: a 0 (or absent column) means "no fatigue data for
    this arm in the export," NOT "fully exhausted." Pre-season and fresh-import
    rosters legitimately carry 0s; flagging those as 'rest' would be a false
    alarm. We treat a row with no positive fatigue figure as band='n/a'.
    """
    out = []
    for _, r in pits_df.iterrows():
        spf = _s(r.get('SP_FATIGUE', 0))
        rpf = _s(r.get('RP_FATIGUE', 0))
        pos = str(r.get('POS', ''))
        # Prefer the role-relevant figure, but only among POSITIVE values.
        candidates = [v for v in (spf if pos == 'SP' else rpf if pos in ('RP', 'CL')
                                  else max(spf, rpf),) if v > 0]
        # Fall back to any positive figure if the role-preferred one is blank.
        if not candidates:
            candidates = [v for v in (spf, rpf) if v > 0]

        if not candidates:
            band = 'n/a'
            primary = 0.0
        else:
            primary = candidates[0]
            band = fatigue_band(primary, bands)

        out.append({
            'name':  str(r.get('Name', '')),
            'pos':   pos,
            'age':   int(_s(r.get('Age', 0))),
            'spf':   round(spf, 0),
            'rpf':   round(rpf, 0),
            'band':  band,
        })
    # Most-fatigued first; 'n/a' sinks to the bottom.
    rank = {'rest': 0, 'monitor': 1, 'fresh': 2, 'n/a': 3}
    out.sort(key=lambda x: (rank[x['band']], x['name']))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE (pitching_state in config.json — mirrors lineups.lineup_state)
# ══════════════════════════════════════════════════════════════════════════════

def _load_pitching_state(league: League) -> dict:
    cfg = league.get_config()
    state = cfg.get('pitching_state', {})
    return {
        'gate':          {**PITCH_GATE_DEFAULTS, **state.get('gate', {})},
        'fatigue_bands': {**DEFAULT_FATIGUE_BANDS, **state.get('fatigue_bands', {})},
    }


def _save_pitching_state(league: League, gate: dict, fatigue_bands: dict):
    league.save_config({'pitching_state': {
        'gate':          gate,
        'fatigue_bands': fatigue_bands,
    }})


# ══════════════════════════════════════════════════════════════════════════════
# ROSTER LOADING (mirrors my_team / lineups: engine guard + ORG filter + prep)
# ══════════════════════════════════════════════════════════════════════════════

def _load_roster(league: League, my_team: str):
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

def render_pitching(league: League):
    st.header("🥎 Pitching")

    tc = league.team_config
    my_team = tc.get('my_team', '')
    if not my_team:
        st.warning("Set your team in ⚙️ Settings before using Pitching.")
        return

    df, err = _load_roster(league, my_team)
    if err:
        st.error(err)

    with st.expander("📤 Upload roster CSV" + ("" if df is None else " (replace current)"),
                     expanded=df is None):
        st.caption(
            "Pitching uses the same saved roster as My Team and Lineups. Upload "
            "here only to replace it. Full league or team-only export both work — "
            "it filters to your team via ORG."
        )
        up = st.file_uploader("Roster CSV", type=['csv'], key='pitching_upload')
        if up is not None:
            uid = f"{up.name}:{up.size}"
            if st.session_state.get('_pitching_upload_id') != uid:
                new_df, uerr = _ingest_upload(up, my_team)
                if uerr:
                    st.error(uerr)
                else:
                    league.save_last_roster(new_df)
                    st.session_state['_pitching_upload_id'] = uid
                    st.success(f"Roster saved — {len(new_df)} players from {my_team}.")
                    st.rerun()

    if df is None:
        st.info("Upload a roster CSV (here or in My Team) to begin.")
        return

    pits = df[df['POS'].isin(PITCHER_POSITIONS)].copy()
    if pits.empty:
        st.error("No pitchers found in the roster.")
        return

    state = _load_pitching_state(league)
    gate  = dict(state['gate'])
    bands = dict(state['fatigue_bands'])

    tab_rot, tab_pen, tab_fatigue = st.tabs(
        ["🔄 Rotation", "💪 Bullpen", "🩹 Fatigue"]
    )

    with tab_rot:
        _render_rotation_tab(league, pits, gate)

    with tab_pen:
        _render_bullpen_tab(league, pits, gate)

    with tab_fatigue:
        _render_fatigue_tab(league, pits, bands)

    with st.expander("📐 Methodology & locked rules"):
        _render_methodology()


# ── ROTATION TAB ──────────────────────────────────────────────────────────────

def _render_rotation_tab(league, pits, gate):
    st.subheader("🔄 Rotation (6-Man)")
    st.caption(
        "Top-6 by SP F1. The gate is top-pitch QUALITY (best ≥ "
        f"{gate['top_min']} + {gate['secondary_count']} secondary ≥ "
        f"{gate['secondary_min']}), not stamina or pitch count. STM is shown as "
        "innings VOLUME, never an eligibility filter."
    )

    with st.expander("⚙️ Rotation gate thresholds (provisional — K-T calibration)"):
        st.caption(
            "The one earned hard gate in the suite: the WAR cliff is at the "
            "bottom (0 pitches ≥50 = 1.58 WAR replacement tier). 50/40 fails that "
            "tier and passes everyone above. Arms failing the gate are ROUTED to "
            "the bullpen, never dropped. Re-validate after AC converts to OOTP 27."
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            top_min = st.number_input("Best pitch ≥", value=int(gate['top_min']),
                                      min_value=20, max_value=80, key='pg_top')
        with c2:
            sec_min = st.number_input("Secondary ≥", value=int(gate['secondary_min']),
                                      min_value=20, max_value=80, key='pg_sec')
        with c3:
            sec_cnt = st.number_input("# secondaries", value=int(gate['secondary_count']),
                                      min_value=0, max_value=5, key='pg_cnt')
        cc1, cc2 = st.columns(2)
        if cc1.button("Save thresholds", key='pg_save'):
            new_gate = {'top_min': int(top_min), 'secondary_min': int(sec_min),
                        'secondary_count': int(sec_cnt)}
            bands = _load_pitching_state(league)['fatigue_bands']
            _save_pitching_state(league, new_gate, bands)
            st.success("Saved."); st.rerun()
        if cc2.button("Reset to 50/40/1", key='pg_reset'):
            bands = _load_pitching_state(league)['fatigue_bands']
            _save_pitching_state(league, dict(PITCH_GATE_DEFAULTS), bands)
            st.success("Reset."); st.rerun()

    result = build_rotation(pits, gate)

    if not result['rotation']:
        st.warning(
            "No arms clear the rotation gate. Loosen the thresholds above, or "
            "this staff genuinely has no rotation-quality arsenals — check the "
            "Bullpen tab, every arm routed there."
        )
    else:
        rot_rows = [{
            '#': i + 1, 'Name': x['name'], 'Age': x['age'],
            'SP F1': x['sp_f1'], 'Top Pitch': x['top_pitch'],
            'STU': x['stu'], 'MOV': x['mov'], 'PIT_CON': x['pit_con'],
            'STM': x['stm'], 'Proj IP': x['proj_ip'],
            'Flags': ' '.join(f for f in
                              [x['con_flag'], 'THIN-OUT-PITCH' if x['thin'] else '']
                              if f),
        } for i, x in enumerate(result['rotation'])]
        st.dataframe(pd.DataFrame(rot_rows), use_container_width=True, hide_index=True)
        n = len(result['rotation'])
        if n < ROTATION_SIZE:
            st.caption(f"⚠️ Only {n} gate-clearing starters — rotation is short of 6.")
        st.caption(
            "Ordered by SP F1 (it already weights top-pitch quality, R²=0.095 on "
            "best-pitch alone). Slots 1–6 are by F1 — reorder to taste; the data "
            "doesn't support handedness/rest slotting. 37-GS cap is inherent to "
            "a 6-man rotation."
        )

    if result['depth']:
        st.markdown("##### 🪜 Stretch / spot-start depth")
        st.caption("Clear the gate but missed the top-6. Ranked by SP F1. Also "
                   "appear in the bullpen pool (dual-eligibility).")
        depth_rows = [{
            'Name': x['name'], 'Age': x['age'], 'SP F1': x['sp_f1'],
            'RP F1': x['rp_f1'], 'Top Pitch': x['top_pitch'],
            'STM': x['stm'], 'Proj IP': x['proj_ip'],
            'Flags': ' '.join(f for f in
                              [x['con_flag'], 'THIN-OUT-PITCH' if x['thin'] else '']
                              if f),
        } for x in result['depth']]
        st.dataframe(pd.DataFrame(depth_rows), use_container_width=True, hide_index=True)

    if result['routed']:
        st.markdown("##### ↪️ Routed to bullpen (gate not cleared)")
        st.caption("Best pitch or secondary below the rotation gate — a reliever "
                   "by skill, where one out-pitch is enough. Not dropped; see Bullpen.")
        routed_rows = [{
            'Name': x['name'], 'Age': x['age'], 'RP F1': x['rp_f1'],
            'Top Pitch': x['top_pitch'], 'STU': x['stu'], 'MOV': x['mov'],
            'Flags': x['con_flag'],
        } for x in result['routed']]
        st.dataframe(pd.DataFrame(routed_rows), use_container_width=True, hide_index=True)

    if result['skipped']:
        names = ', '.join(f"{x['name']} ({x['skip']})" for x in result['skipped'])
        st.warning(f"🚫 Auto-skip (A6, never override): {names}")


# ── BULLPEN TAB ───────────────────────────────────────────────────────────────

def _render_bullpen_tab(league, pits, gate):
    st.subheader(f"💪 Bullpen ({BULLPEN_SIZE} Arms)")
    st.caption(
        "Quality gate by RP F1 (who's pen-worthy). Closer = highest STU among "
        "qualifiers (A6 role-fit — the 9th rewards the stuff arm). All other "
        "roles ordered by RP F1, not raw MOV (the model already weights MOV)."
    )

    # Rotation must be computed first so we exclude its members from the pen.
    rot = build_rotation(pits, gate)
    rotation_names = {x['name'] for x in rot['rotation']}
    result = build_bullpen(pits, rotation_names, gate)

    if not result['bullpen']:
        st.warning("No bullpen arms available (all in the rotation or auto-skipped).")
        return

    bp_rows = [{
        'Role': a['role'], 'Name': a['name'], 'Age': a['age'],
        'RP F1': a['rp_f1'], 'STU': a['stu'], 'MOV': a['mov'],
        'PIT_CON': a['pit_con'], 'STM': a['stm'],
        'SP-capable': '✓' if a['sp_capable'] else '',
        'Flags': a['con_flag'],
    } for a in result['bullpen']]
    st.dataframe(pd.DataFrame(bp_rows), use_container_width=True, hide_index=True)
    st.caption(
        "SP-capable ✓ = clears the rotation gate (stretchable to start in a "
        "pinch). Same arm is priced as a starter on the Rotation tab — both "
        "projections exist; we don't collapse to one number here."
    )

    # Honesty note: the closer is the highest-STU arm (A6 role-fit), which can be
    # a lower-rp_f1 reliever than the setup men. Surface that tradeoff so you can
    # override rather than have it pass silently.
    closer = next((a for a in result['bullpen'] if a['role'] == 'Closer'), None)
    best_rp = max(result['bullpen'], key=lambda a: a['rp_f1']) if result['bullpen'] else None
    if closer and best_rp and best_rp['name'] != closer['name']:
        st.caption(
            f"ℹ️ Closer **{closer['name']}** is the top-STU arm (A6: the 9th "
            f"rewards stuff), but **{best_rp['name']}** grades higher overall by "
            f"RP F1 ({best_rp['rp_f1']} vs {closer['rp_f1']}). If you value total "
            "value over the stuff heuristic, that's your closer instead."
        )

    if result['overflow']:
        st.markdown("##### ⏭️ Next-up depth (beyond the top-5)")
        st.caption("Cleared the candidate pool but outside the 5-man pen. Ranked by RP F1.")
        of_rows = [{
            'Name': a['name'], 'Age': a['age'], 'RP F1': a['rp_f1'],
            'STU': a['stu'], 'MOV': a['mov'],
            'SP-capable': '✓' if a['sp_capable'] else '',
            'Flags': a['con_flag'],
        } for a in result['overflow']]
        st.dataframe(pd.DataFrame(of_rows), use_container_width=True, hide_index=True)


# ── FATIGUE TAB ───────────────────────────────────────────────────────────────

def _render_fatigue_tab(league, pits, bands):
    st.subheader("🩹 Fatigue")
    st.caption(
        "Current-snapshot readout of SPF% / RPF% (higher = more rested). One "
        "export is one moment, so this flags who's gassed NOW — not a multi-day "
        "workload projection. Bands are provisional and editable."
    )

    with st.expander("⚙️ Fatigue bands (provisional — no fatigue→performance study yet)"):
        st.caption("Higher % = more rested. Calibrate against a real Quakers "
                   "export; replace the moment a fatigue→outcome study exists.")
        c1, c2 = st.columns(2)
        with c1:
            green = st.number_input("Fresh ≥", value=int(bands['green']),
                                    min_value=0, max_value=100, key='fb_green')
        with c2:
            amber = st.number_input("Monitor ≥ (below = rest)", value=int(bands['amber']),
                                    min_value=0, max_value=100, key='fb_amber')
        cc1, cc2 = st.columns(2)
        if cc1.button("Save bands", key='fb_save'):
            gate = _load_pitching_state(league)['gate']
            _save_pitching_state(league, gate, {'green': int(green), 'amber': int(amber)})
            st.success("Saved."); st.rerun()
        if cc2.button("Reset bands", key='fb_reset'):
            gate = _load_pitching_state(league)['gate']
            _save_pitching_state(league, gate, dict(DEFAULT_FATIGUE_BANDS))
            st.success("Reset."); st.rerun()

    rows = build_fatigue(pits, bands)
    icon = {'fresh': '🟢', 'monitor': '🟡', 'rest': '🔴', 'n/a': '⚪'}
    table = [{
        'Status': icon[r['band']], 'Name': r['name'], 'POS': r['pos'],
        'Age': r['age'], 'SPF%': r['spf'], 'RPF%': r['rpf'],
    } for r in rows]
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    n_na = sum(1 for r in rows if r['band'] == 'n/a')
    if n_na:
        st.caption(f"⚪ {n_na} arm(s) have no fatigue data in this export "
                   "(pre-season or fresh import) — not flagged as tired.")
    n_rest = sum(1 for r in rows if r['band'] == 'rest')
    if n_rest:
        st.warning(f"🔴 {n_rest} arm(s) below the rest threshold — sit them or skip a start.")


# ── METHODOLOGY ───────────────────────────────────────────────────────────────

def _render_methodology():
    st.markdown(
        "**Role is an output of skills, not an input.** SP/RP/CL are fluid — "
        "every arm is priced as both a starter (SP F1, CV R²=0.779) and a "
        "reliever (RP F1, CV R²=0.571). No stamina bucket, no pitch-count gate."
    )
    st.markdown(
        "**Rotation gate (the one earned hard filter):** top-pitch quality, "
        "best ≥ 50 + one secondary ≥ 40 on current grades. The WAR cliff is at "
        "the bottom — pitches at grade ≥ 50: 0 → 1.58 (replacement), 1 → 2.32, "
        "2 → 3.02, 3 → 3.38. A failing arm is ROUTED to the bullpen, never "
        "dropped. STM is a smooth innings lever (WAR/IP flat 35–85), shown as "
        "projected IP, never a gate. Effective-pitch COUNT is an inverted proxy "
        "(more pitches → worse, because fewer-pitch arms have better best-pitches)."
    )
    st.markdown(
        "**Bullpen:** RP F1 quality gate decides the 5; closer = highest STU "
        "among them (A6); other roles ordered by RP F1. SP-capable arms appear "
        "tagged (dual-eligibility)."
    )
    st.markdown(
        "**Hard rules (A6, locked):** 6-man rotation (+3.2 WAR, 37-GS cap); 6 SP "
        "+ 5 RP + 14 POS, never 7+ RP; PIT_CON < 40 = LOW-CON; "
        "Unmotivated/Disruptive = auto-skip; Fragile = −40% value."
    )
    st.markdown(
        "**Upgrade path:** a v27 refit of per-role WAR models (price every arm "
        "in every role) is the cleanest long-term role assignment. The v26 "
        "ROLE_MODELS coefficients aren't engine-portable; for now the RP F1 gate "
        "+ A6 stuff-closer heuristic stands."
    )
    st.markdown(
        "**Boundary with My Team:** My Team owns roster legality (6/5/14, the 7+ "
        "RP error) and active/reserve. Pitching owns deployment — who starts, "
        "who relieves in which role, who's gassed."
    )
