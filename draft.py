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
    PITCHER_POSITIONS, BATTER_POSITIONS,
    _s,
)
from my_team import detect_needs_and_surplus, build_roster_table

# A6: Fragile → −40% projected value.
FRAGILE_VALUE_MULT = 0.60
# A6: never draft RP before Round 4.
RP_ROUND_FLOOR = 4

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
    }


def _save_draft_state(league: League, tier_bands=None, predraft_gate=None,
                      current_round=None):
    cur = _load_draft_state(league)
    payload = {
        'tier_bands':    tier_bands    if tier_bands    is not None else cur['tier_bands'],
        'predraft_gate': predraft_gate if predraft_gate is not None else cur['predraft_gate'],
        'current_round': current_round if current_round is not None else cur['current_round'],
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


def _ingest_draft_upload(uploaded):
    """
    Read + engine-guard + ORG=="-" filter + audit + prep a draft-pool CSV.
    Returns (df, audit_report, error). FAILS LOUD: if the column audit finds a
    missing load-bearing F2 column, returns (None, report, None) so the caller
    can show exactly what's missing instead of scoring on silent zeros.
    """
    try:
        raw = pd.read_csv(uploaded, encoding='utf-8-sig', low_memory=False)
    except Exception as e:
        return None, None, f"Failed to read CSV: {e}"

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


def build_board(pool_df: pd.DataFrame, league: League, state: dict) -> list[dict]:
    """
    Score every prospect and assemble board rows. Primary sort = career WAR (BPA).
    Window WAR / TV / Need are informational. A6 hard rules applied: auto-skip
    Unmotivated/Disruptive, Fragile −40%, BIG-CON-bet flag, predraft SP-capability
    drives the RP-before-R4 warning.
    """
    needs = _need_set(league)
    gate  = state['predraft_gate']
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
        if up is not None:
            uid = f"{up.name}:{up.size}"
            if st.session_state.get('_draft_upload_id') != uid:
                new_df, report, err = _ingest_draft_upload(up)
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
    pot_active = draft_pool_has_potentials(pool)

    tab_board, tab_grades, tab_method = st.tabs(
        ["📋 Board", "🥎 Pitch Grades", "📐 Methodology"]
    )
    with tab_board:
        _render_board_tab(league, rows, state, pot_active)
    with tab_grades:
        _render_grades_tab(rows)
    with tab_method:
        _render_methodology()


# ── BOARD TAB ─────────────────────────────────────────────────────────────────

def _render_board_tab(league, rows, state, pot_active=True):
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
    st.caption(f"**Tiers:** {leg}  ·  ranked by **Career WAR** (BPA)")

    show_skipped = st.checkbox("Show auto-skipped (Unmotivated/Disruptive)", value=False,
                               key='draft_show_skip')
    early_round = int(rnd) < RP_ROUND_FLOOR

    visible = [x for x in rows if (show_skipped or not x['skip'])]
    # Colorblind-safe glyph for a notable growth bet (▲ scales with the gap).
    def _gb_glyph(gap):
        if not pot_active or gap < 0.3: return ''
        if gap >= 1.0: return '▲▲'
        return '▲'
    table = []
    for x in visible:
        # RP-before-R4 inline marker on the row when relevant.
        rp_warn = ' ⛔R4' if (x['rp_ceiling'] and early_round) else ''
        gb = x['growth_bet']
        table.append({
            ' ':            DRAFT_TIER_ICONS[x['tier']],
            'Name':         x['name'] + (' 🚫' if x['skip'] else ''),
            'POS':          x['pos'] + rp_warn,
            'Age':          x['age'],
            'Career WAR':   x['career'],
            'Disc WAR':     (x['disc'] if pot_active else x['career']),
            'Growth-bet':   (f"{_gb_glyph(gb)} +{gb:.2f}".strip() if (pot_active and gb > 0)
                             else ('+0.00' if pot_active else '—')),
            'Window WAR':   x['window'],
            'Proj TV':      x['tv'],
            'Need':         '✓' if x['need'] else '',
            'Flags':        x['flags'],
        })
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True,
                 height=min(620, 80 + 35 * len(table)))

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
        "**Need ✓** = My Team auto-config (read-only). Open any prospect below to "
        "see the per-rating haircut."
    )

    # ── On-demand per-rating delivery inspect (selectbox → legible haircut panel) ─
    if pot_active:
        _render_delivery_inspect(visible)

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
        b1, b2 = st.columns(2)
        if b1.button("Save", key='dt_save'):
            _save_draft_state(league,
                tier_bands={'elite': elite, 'solid': solid, 'flier': flier},
                predraft_gate={'top_min': int(gtop), 'secondary_min': int(gsec),
                               'secondary_count': int(gcnt)})
            st.success("Saved."); st.rerun()
        if b2.button("Reset", key='dt_reset'):
            _save_draft_state(league, tier_bands=dict(DRAFT_TIER_DEFAULTS),
                              predraft_gate=dict(PREDRAFT_PITCH_GATE_DEFAULTS))
            st.success("Reset."); st.rerun()


# ── ON-DEMAND DELIVERY INSPECT ─────────────────────────────────────────────────

def _render_delivery_inspect(visible):
    """
    Selectbox → panel making one prospect's delivery haircut legible: each
    discountable rating's current → potential → discounted value and the factor
    (+ age multiplier) applied. SPE/STM and everything outside the locked study
    are noted as held at current. Pulls Career/Disc from the board rows so the
    fragile −40% (if any) is reflected consistently.
    """
    with st.expander("🔍 Inspect a prospect — per-rating delivery haircut", expanded=False):
        if not visible:
            st.info("No prospects to inspect.")
            return
        idxs = list(range(len(visible)))
        def _label(i):
            x = visible[i]
            return f"{x['name'] or '(unnamed)'} — {x['pos']}, age {x['age']}  ·  Career {x['career']:.2f} → Disc {x['disc']:.2f}"
        i = st.selectbox("Prospect", idxs, index=0, format_func=_label, key='draft_inspect_pick')
        x = visible[i]
        bd = delivery_breakdown(x['row'])

        amult = delivery_age_mult(x['age'])
        gap = x['growth_bet']
        head = (f"**{x['name'] or '(unnamed)'}** · {x['pos']} · age {x['age']}  —  "
                f"Career **{x['career']:.2f}** → Discounted **{x['disc']:.2f}** "
                f"(growth-bet **{'+' if gap >= 0 else ''}{gap:.2f}** WAR)")
        st.markdown(head)
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
            notes.append("**SPE** has no delivery factor and stays at current.")
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
            'Name': x['name'], 'POS': x['pos'], 'Age': x['age'],
            'Career WAR': x['career'], 'Top': x['top_pitch'],
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
