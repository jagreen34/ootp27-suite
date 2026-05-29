"""
Development module — fail-loud column audit (Layer-1 gate).
Mirrors draft.py::audit_draft_columns. Gates the Slider Optimizer: a missing
load-bearing potential/rating blocks that pool rather than feeding a silent zero.

Returns a structured report; the renderer shows it and refuses to allocate a pool
whose required inputs are absent. Surfaced (not fatal): ratings with no potential
column (no growth invented), defensive potentials present-but-ignored-on-purpose,
and v27 inputs that have no corresponding slider under the locked mapping.
"""

# ── Locked v27 slider → (current, potential, source) maps ─────────────────────
# Batter weights are DERIVED from off_f1 at runtime (single source of truth);
# here we only assert the columns exist. Defense is pinned, no columns needed.
BATTER_SLIDER_COLS = {
    'BABIP':     ('BAT_BABIP_RATING', 'BAT_BABIP_P'),   # raw pot label 'HT P'
    "Avoid K's": ('CON',              'CON_P'),
    'Gap':       ('GAP',              'GAP_P'),
    'Power':     ('POW',              'POW_P'),
    'Eye':       ('EYE',              'EYE_P'),
    'Running':   ('SPE',              None),             # no potential → score 0
    # 'Defense' pinned to 10, intentionally column-free.
}

# Pitcher main pool. STM has no potential column in the export (confirmed).
PITCHER_MAIN_COLS = {
    'Movement': ('MOV',     'MOV_P'),
    'Control':  ('PIT_CON', 'PIT_CON_P'),
    'Stamina':  ('STM',     None),                       # no potential → see note
}

# Pitch pool: grade + potential per pitch. Ranking weights (H3) live in the
# allocator, not here; the audit only confirms which pitches carry a pot column.
PITCH_COLS = {
    'SI': ('PIT_SI', 'PIT_SI_P'), 'CH': ('PIT_CH', 'PIT_CH_P'),
    'SL': ('PIT_SL', 'PIT_SL_P'), 'FB': ('PIT_FB_GR', 'PIT_FB_GR_P'),
    'CB': ('PIT_CB', 'PIT_CB_P'), 'CT': ('PIT_CT', 'PIT_CT_P'),
    'SP': ('PIT_SP', 'PIT_SP_P'),
}

# Defensive potentials that EXIST but the allocator must ignore on purpose (A19:
# defense frozen up / declines down / learned by playing time, not sliders).
DEF_POT_COLS = ['FLD_P_P', 'FLD_C_P', 'FLD_1B_P', 'FLD_2B_P', 'FLD_3B_P',
                'FLD_SS_P', 'FLD_LF_P', 'FLD_CF_P', 'FLD_RF_P']

# v27 inputs present in the export with NO slider under the locked 1:1 mapping
# (matches the OOTP 26 tool, whose weight tables omit these). Surfaced so it's a
# visible choice, not a silent drop.
NO_SLIDER_INPUTS = {
    'AVK': 'AVK_P',   # batter Avoid-K's RATING (Avoid-K's SLIDER maps to CON)
    'STU': 'STU_P',   # pitcher Stuff (main pool is MOV/CON/STM; no Stuff slider)
}


def audit_development_columns(df) -> dict:
    """
    Inspect a prepped (post-rename) roster. Never raises on missing columns —
    returns a report the renderer uses to gate each pool independently.
    """
    cols = set(map(str, df.columns))
    rep = {
        'ok_batter_pool': True, 'ok_pitcher_main': True, 'ok_pitch_pool': True,
        'errors': [], 'notes': [], 'no_growth': [], 'ignored_def_pots': [],
        'no_slider_present': [],
    }

    def chk(slider, cur, pot, pool_flag):
        if cur not in cols:
            rep['errors'].append(f"{slider}: current rating '{cur}' MISSING")
            rep[pool_flag] = False
            return
        if pot is None:
            rep['no_growth'].append(slider)              # by design (SPE/STM)
        elif pot not in cols:
            # A potential we EXPECT but can't find — fail loud, don't invent.
            rep['errors'].append(
                f"{slider}: potential '{pot}' MISSING — pool gated, no growth invented")
            rep[pool_flag] = False

    for s, (cur, pot) in BATTER_SLIDER_COLS.items():
        chk(s, cur, pot, 'ok_batter_pool')
    for s, (cur, pot) in PITCHER_MAIN_COLS.items():
        chk(s, cur, pot, 'ok_pitcher_main')

    # Pitch pool: at least the H3-relevant grades+pots must exist; per-pitch
    # absence is fine (player simply lacks that pitch). Gate only if NO pitch
    # carries a usable grade+pot pair at all.
    usable_pitches = [p for p, (g, pp) in PITCH_COLS.items()
                      if g in cols and pp in cols]
    if not usable_pitches:
        rep['ok_pitch_pool'] = False
        rep['errors'].append("Pitch pool: no pitch grade+potential pairs found")
    else:
        rep['notes'].append(
            f"Pitch pool ranks on present pairs: {', '.join(usable_pitches)}")

    # Surfaced choices ----------------------------------------------------------
    if 'STM' in cols and 'STM_P' not in cols:
        rep['notes'].append(
            "Stamina has no potential column → no growth term. See STM handling "
            "decision (floor-to-10 vs neutral-hold).")
    rep['ignored_def_pots'] = [c for c in DEF_POT_COLS if c in cols]
    if rep['ignored_def_pots']:
        rep['notes'].append(
            f"{len(rep['ignored_def_pots'])} defensive-potential columns present "
            "(position-grade); allocator IGNORES them on purpose (A19).")
    for rating, pot in NO_SLIDER_INPUTS.items():
        if rating in cols:
            rep['no_slider_present'].append(
                f"{rating}" + (f"/{pot}" if pot in cols else ""))
    if rep['no_slider_present']:
        rep['notes'].append(
            "Present but no slider under locked mapping (unused, matches OOTP 26): "
            + ", ".join(rep['no_slider_present']))
    if rep['no_growth']:
        rep['notes'].append(
            "No potential column (stay at current, score 0): "
            + ", ".join(rep['no_growth']))
    return rep
