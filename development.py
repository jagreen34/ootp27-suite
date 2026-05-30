"""
OOTP 27 Suite — Development Module (🌱)
========================================
Layer 1 of three: the in-season **Slider Optimizer**. A per-player development-
slider recommender — a port of the OOTP 26 "mode 10" tool onto v27 coefficients
and v27 findings. Tells you where to point each zero-sum development budget; the
output is **click deltas** ("POW +15") because the OOTP UI is +/- clicks only.

Staged follow-ons (NOT built here): Dev Lab advisor (Layer 2), reserve-roster
keep-or-cut allocator (Layer 3). Both consume this module's `weighted_gaps`.

SCREENSHOT-VALIDATED MECHANICS (OOTP 27, May 2026)
--------------------------------------------------
Batter pool — 7 zero-sum sliders, budget ~350 (7×50), clamp 10–90:
    BABIP, Avoid K's, Gap, Power, Eye, Running, Defense.
    OOTP 27 displays **Contact as a composite parent of BABIP + Avoid K's**
    (Contact ≈ mean(BABIP, AvoidK's); confirmed in-data r=0.984). So:
      • BABIP slider    → BAT_BABIP_RATING / BAT_BABIP_P  (raw 'HT P')
      • Avoid K's slider→ AVK / AVK_P                     (raw "K's"/"K P")
      • CON (Contact)   = parent composite, NO direct slider; it rises as its
                          two children develop. Each child slider's true F1
                          impact = own weight + 0.5×CON weight (total derivative
                          through the parent) — the default 'total_deriv' mode.

Pitcher main pool — 3 zero-sum sliders, budget ~150 (3×50):
    Movement (MOV/MOV_P), Control (PIT_CON/PIT_CON_P), Stamina (STM, no pot).
Pitcher pitch pool — one "[Pitch] Stuff" slider per pitch, SEPARATE zero-sum
    pool, budget ~N×50. Develops each pitch's grade; overall STU is the composite
    parent (like Contact), moved via this pool. Ranked by H3 per-pitch weights.
Each pool also has an "Available"/"Available Stuff" slider OUTSIDE the zero-sum
    budget (priority knob) — ignored by the optimizer.

THREE LOCKED v27 FINDINGS BAKED IN
----------------------------------
1. Defense pinned to 10 (reason shown). The Defense slider moves only underlying
   defensive ratings, which are FROZEN (r 0.96–0.99); position grades develop on
   a separate playing-time channel. Budget on Defense turns a knob connected to
   nothing. Freed points → offense. Override allowed. (A18/A19 + OOTP26 handoff.)
2. Defensive POTENTIALS exist in the export (position-grade FLD_*_P) but the
   allocator IGNORES them on purpose — defense doesn't develop (A19). Read,
   surfaced, declined. Offensive/pitching potentials used normally.
3. SPE and STM have NO potential column → no growth term (score 0). Missing
   potential is handled fail-loud (audit-noted), never invented, never a crash.
   STM, being a no-growth slider the handoff still values, is NEUTRAL-HELD at 50
   by default (not floored), editable.

Build pattern mirrors My Team / Pitching / Draft. Formulas import from
acquisitions.py (single source). State in config.json under 'development_state'.
Colorblind-safe shape glyphs. FAIL LOUD on missing load-bearing columns.
"""

import pandas as pd
import streamlit as st

from db import League
from acquisitions import (
    prep_data, off_f1, _s,
    BATTER_POSITIONS, PITCHER_POSITIONS,
)
from dev_audit import audit_development_columns
import reserve_roster as rr
from my_team import split_active_reserve

# ══════════════════════════════════════════════════════════════════════════════
# WEIGHTS — derived from acquisitions.off_f1 (single source of truth)
# ══════════════════════════════════════════════════════════════════════════════
# off_f1 is linear in each rating, so ΔF1 per +1 rating point == that rating's
# locked coefficient. Deriving the slider weights by probing off_f1 means a future
# coefficient change in acquisitions.py propagates here automatically — no second
# copy of the numbers to drift.

_PROBE_BASE = {'CON': 50, 'GAP': 50, 'POW': 50, 'EYE': 50, 'SPE': 50,
               'AVK': 50, 'BAT_BABIP_RATING': 50}


def _off_coef(rating: str) -> float:
    """Marginal F1 per +1 of `rating`, read straight from off_f1."""
    b0 = off_f1(_PROBE_BASE)
    bumped = dict(_PROBE_BASE); bumped[rating] = bumped[rating] + 1
    return off_f1(bumped) - b0


def batter_weights(weight_mode: str = 'total_deriv') -> dict:
    """
    Per-slider F1 weights for the batter pool, derived from off_f1.
    Returns {slider: {'rating': col, 'pot': col|None, 'weight': float}}.

    weight_mode:
      'total_deriv' (default) — contact-family sliders credited with own weight
          + 0.5×CON weight, because Contact (the parent composite) rises ~0.5 pt
          per child point. This is the honest F1 impact of moving a child.
      'per_rating' — each slider credited with only its own rating's coefficient
          (the literal mode-10 read; ignores the Contact lift).
    """
    con = _off_coef('CON')
    share = 0.5 * con if weight_mode == 'total_deriv' else 0.0
    return {
        'BABIP':     {'rating': 'BAT_BABIP_RATING', 'pot': 'BAT_BABIP_P',
                      'weight': _off_coef('BAT_BABIP_RATING') + share},
        "Avoid K's": {'rating': 'AVK', 'pot': 'AVK_P',
                      'weight': _off_coef('AVK') + share},
        'Gap':       {'rating': 'GAP', 'pot': 'GAP_P', 'weight': _off_coef('GAP')},
        'Power':     {'rating': 'POW', 'pot': 'POW_P', 'weight': _off_coef('POW')},
        'Eye':       {'rating': 'EYE', 'pot': 'EYE_P', 'weight': _off_coef('EYE')},
        'Running':   {'rating': 'SPE', 'pot': None,     'weight': _off_coef('SPE')},
        # 'Defense' handled separately (pinned).
    }


# Pitcher main-pool weights. NOT from the v27 split F1 (sp_f1/rp_f1 is a rate
# model with split coefficients, a negative STM term, and a MOV/CON inversion when
# collapsed). These are the development-appropriate scalar weights from the
# OOTP 26 handoff table / registry priority (MOV dominant, CON a low ceiling play).
# STM carries a weight but has no potential column → it never scores via the gap
# method anyway; the weight is informational. Editable in development_state.
PITCHER_MAIN_WEIGHTS = {
    'Movement': {'rating': 'MOV',     'pot': 'MOV_P',     'weight': 0.1091},
    'Control':  {'rating': 'PIT_CON', 'pot': 'PIT_CON_P', 'weight': 0.0053},
    'Stamina':  {'rating': 'STM',     'pot': None,        'weight': 0.0560},
}

# Pitch-pool per-pitch weights (H3 "Pitch Grade Decomposition", locked,
# triangulated across 3 LLMs). SI > CH > SL dominate independent signal; FB and
# the rest saturate to ≈0. Anti-balance (MIN_eff_t30 negative): concentrate the
# pitch budget on the top 1–2 gaps, do NOT spread evenly.
PITCH_WEIGHTS = {
    'SI': {'rating': 'PIT_SI',    'pot': 'PIT_SI_P',    'weight': 0.134, 'label': 'Sinker'},
    'CH': {'rating': 'PIT_CH',    'pot': 'PIT_CH_P',    'weight': 0.117, 'label': 'Changeup'},
    'SL': {'rating': 'PIT_SL',    'pot': 'PIT_SL_P',    'weight': 0.043, 'label': 'Slider'},
    'FB': {'rating': 'PIT_FB_GR', 'pot': 'PIT_FB_GR_P', 'weight': 0.010, 'label': 'Fastball'},
    'CB': {'rating': 'PIT_CB',    'pot': 'PIT_CB_P',    'weight': 0.010, 'label': 'Curveball'},
    'CT': {'rating': 'PIT_CT',    'pot': 'PIT_CT_P',    'weight': 0.010, 'label': 'Cutter'},
    'SP': {'rating': 'PIT_SP',    'pot': 'PIT_SP_P',    'weight': 0.010, 'label': 'Splitter'},
}

# ── Pool / clamp / behaviour defaults (editable in development_state) ──────────
DEV_DEFAULTS = {
    'weight_mode':       'total_deriv',  # 'total_deriv' | 'per_rating'
    'stm_mode':          'neutral',      # 'neutral' (hold 50) | 'floor' (→10)
    'pitch_concentrate': 2,              # allocate pitch budget to top-K gaps
    'defense_pin':       10,             # pinned Defense slider value
    'clamp_lo':          10,
    'clamp_hi':          90,
    'slider_mid':        50,             # neutral / Reset position (delta basis)
    'veteran_age':       28,             # ≥ this → minimal-gain note
    'reserve':           None,           # populated from rr.RESERVE_DEFAULTS in _load
}

# Colorblind-safe glyphs (shape, never color).
GLYPH_BIG   = '▲▲'   # large weighted gap (primary focus)
GLYPH_SMALL = '▲'    # modest weighted gap
GLYPH_NONE  = '·'    # no growth (at potential / no potential column)
GLYPH_PIN   = '◼'    # pinned (Defense)


# ══════════════════════════════════════════════════════════════════════════════
# ALLOCATOR CORE
# ══════════════════════════════════════════════════════════════════════════════

def allocate_pool(scores: dict, budget: float, clamp_lo: float, clamp_hi: float,
                  fixed: dict | None = None) -> dict:
    """
    Distribute a zero-sum slider budget proportionally to weighted-gap scores.

    scores  — {slider: score>=0}  (score 0 → slider floors, no growth to chase)
    budget  — exact pool total the result must sum to (e.g. 350)
    fixed   — {slider: value} pinned/held BEFORE distributing the remainder
              (e.g. Defense=10, or Stamina held at 50). Fixed values are clamped
              into range and subtracted from the budget; the rest is distributed
              over the non-fixed sliders.

    Returns {slider: position} summing to `budget`, every position in
    [clamp_lo, clamp_hi]. Iterates clamp→renormalize so the total stays exact
    even when clamping bites. Fail-soft: an empty/zero-score free pool spreads
    the remainder evenly.
    """
    fixed = dict(fixed or {})
    for k, v in fixed.items():
        fixed[k] = min(max(float(v), clamp_lo), clamp_hi)

    free = [s for s in scores if s not in fixed]
    remaining = budget - sum(fixed.values())
    n = len(free)
    if n == 0:
        return dict(fixed)

    # Floor every free slider, then distribute the surplus by score share.
    floor_total = clamp_lo * n
    surplus = remaining - floor_total
    if surplus <= 0:
        # Budget can't clear floors — give everyone the floor (best effort).
        return {**fixed, **{s: clamp_lo for s in free}}

    pos = {s: float(clamp_lo) for s in free}
    score_sum = sum(max(0.0, scores[s]) for s in free)
    if score_sum <= 0:
        even = surplus / n
        pos = {s: min(clamp_lo + even, clamp_hi) for s in free}
    else:
        for s in free:
            pos[s] = clamp_lo + surplus * (max(0.0, scores[s]) / score_sum)

    # Clamp→renormalize loop so clamped overflow is redistributed and the sum
    # stays exactly `remaining` across the free sliders.
    for _ in range(50):
        over = {s: pos[s] for s in free if pos[s] > clamp_hi}
        if not over:
            break
        for s in over:
            pos[s] = clamp_hi
        capped = sum(pos[s] for s in free if pos[s] >= clamp_hi)
        adjustable = [s for s in free if pos[s] < clamp_hi]
        target = remaining - capped
        adj_floor = clamp_lo * len(adjustable)
        adj_surplus = target - adj_floor
        adj_scores = sum(max(0.0, scores[s]) for s in adjustable) or 1.0
        if not adjustable or adj_surplus <= 0:
            break
        for s in adjustable:
            pos[s] = clamp_lo + adj_surplus * (max(0.0, scores[s]) / adj_scores)

    # Final rounding correction to hit the integer budget exactly.
    rounded = {s: int(round(v)) for s, v in pos.items()}
    drift = int(round(remaining)) - sum(rounded.values())
    if drift and free:
        order = sorted(free, key=lambda s: scores.get(s, 0), reverse=(drift > 0))
        i = 0
        step = 1 if drift > 0 else -1
        while drift != 0 and order:
            s = order[i % len(order)]
            nv = rounded[s] + step
            if clamp_lo <= nv <= clamp_hi:
                rounded[s] = nv
                drift -= step
            i += 1
            if i > 1000:
                break
    return {**{k: int(round(v)) for k, v in fixed.items()}, **rounded}


def _weighted_gaps(row, slider_map: dict) -> dict:
    """score = weight × max(0, potential − current); 0 if no potential column."""
    gaps = {}
    for slider, m in slider_map.items():
        cur = _s(row.get(m['rating'], 0))
        if m['pot'] is None:
            gaps[slider] = 0.0
        else:
            pot = _s(row.get(m['pot'], 0))
            gaps[slider] = m['weight'] * max(0.0, pot - cur)
    return gaps


def _deltas(positions: dict, mid: int) -> dict:
    """Click deltas from the neutral/Reset position (the actionable output)."""
    return {s: int(round(p - mid)) for s, p in positions.items()}


# ══════════════════════════════════════════════════════════════════════════════
# PER-PLAYER RECOMMENDERS  → consumable record (Layers 2/3 read this)
# ══════════════════════════════════════════════════════════════════════════════

def recommend_batter(row, cfg: dict) -> dict:
    bw = batter_weights(cfg['weight_mode'])
    gaps = _weighted_gaps(row, bw)
    notes = []

    defense_pinned = not bool(row.get('_dev_defense_override', False))
    fixed = {}
    if defense_pinned:
        fixed['Defense'] = cfg['defense_pin']
        notes.append(
            f"Defense pinned to {cfg['defense_pin']}: the slider moves only "
            "underlying defensive ratings, which are frozen (r 0.96–0.99); "
            "position grades develop via playing time, not this slider. "
            f"{cfg['slider_mid'] - cfg['defense_pin']}+ freed points → offense.")
    else:
        gaps['Defense'] = 0.0  # override: let it compete (still no real growth)
        notes.append("Defense override ON — competing for budget despite frozen "
                     "underlying ratings (A19).")

    budget = cfg['slider_mid'] * 7
    positions = allocate_pool(gaps, budget, cfg['clamp_lo'], cfg['clamp_hi'], fixed)
    for s in ('Running',):
        if gaps.get(s, 0) == 0:
            notes.append(f"{s}: no growth term (no potential column) → floored.")
    return {
        'player': str(row.get('Name', '')),
        'pos': str(row.get('POS', '')),
        'is_pit': False,
        'age': int(_s(row.get('AGE', row.get('Age', 0)))),
        'recommended_positions': positions,
        'recommended_deltas': _deltas(positions, cfg['slider_mid']),
        'weighted_gaps': {s: round(v, 4) for s, v in gaps.items()},
        'defense_pinned': defense_pinned,
        'notes': notes,
    }


def recommend_pitcher_main(row, cfg: dict) -> dict:
    gaps = _weighted_gaps(row, PITCHER_MAIN_WEIGHTS)
    notes = []
    fixed = {}
    if cfg['stm_mode'] == 'neutral':
        fixed['Stamina'] = cfg['slider_mid']
        notes.append("Stamina has no potential column → no growth term; "
                     f"neutral-held at {cfg['slider_mid']} (not floored).")
    else:
        fixed['Stamina'] = cfg['clamp_lo']
        notes.append("Stamina has no potential column → no growth term; "
                     f"floored to {cfg['clamp_lo']} (stm_mode='floor'); freed "
                     "points → Movement/Control.")
    budget = cfg['slider_mid'] * 3
    positions = allocate_pool(gaps, budget, cfg['clamp_lo'], cfg['clamp_hi'], fixed)
    if gaps.get('Control', 0) == 0:
        notes.append("Control at/above potential → no growth; freed to Movement.")
    return {
        'recommended_positions': positions,
        'recommended_deltas': _deltas(positions, cfg['slider_mid']),
        'weighted_gaps': {s: round(v, 4) for s, v in gaps.items()},
        'notes': notes,
    }


def _present_pitches(row) -> list:
    """Pitches the arm actually throws (grade > 0), in H3 weight order."""
    out = []
    for code, m in PITCH_WEIGHTS.items():
        if _s(row.get(m['rating'], 0)) > 0:
            out.append(code)
    return out


def recommend_pitch_pool(row, cfg: dict) -> dict:
    present = _present_pitches(row)
    notes = []
    if not present:
        return {'recommended_positions': {}, 'recommended_deltas': {},
                'weighted_gaps': {}, 'notes': ['No pitches found.']}

    gaps = {}
    for code in present:
        m = PITCH_WEIGHTS[code]
        cur = _s(row.get(m['rating'], 0))
        pot = _s(row.get(m['pot'], 0)) if m['pot'] else cur
        gaps[code] = m['weight'] * max(0.0, pot - cur)

    # Anti-balance: concentrate on the top-K weighted gaps; floor the rest.
    k = max(1, int(cfg['pitch_concentrate']))
    ranked = sorted(present, key=lambda c: gaps[c], reverse=True)
    top = [c for c in ranked[:k] if gaps[c] > 0]
    if not top:                       # nobody has a gap — hold everyone neutral
        notes.append("No pitch has a current→potential gap → all held neutral.")
        mid = cfg['slider_mid']
        positions = {c: mid for c in present}
    else:
        scores = {c: (gaps[c] if c in top else 0.0) for c in present}
        budget = cfg['slider_mid'] * len(present)
        positions = allocate_pool(scores, budget, cfg['clamp_lo'],
                                  cfg['clamp_hi'], fixed=None)
        labels = ", ".join(PITCH_WEIGHTS[c]['label'] for c in top)
        notes.append(f"Pitch budget concentrated on top {len(top)}: {labels} "
                     "(anti-balance: engine rewards 1–2 elite pitches over depth).")
    # Map codes → labels for readability in the record.
    lbl = lambda d: {PITCH_WEIGHTS[c]['label']: v for c, v in d.items()}
    return {
        'recommended_positions': lbl(positions),
        'recommended_deltas': lbl(_deltas(positions, cfg['slider_mid'])),
        'weighted_gaps': {PITCH_WEIGHTS[c]['label']: round(gaps[c], 4) for c in present},
        'notes': notes,
    }


def recommend_pitcher(row, cfg: dict) -> dict:
    main = recommend_pitcher_main(row, cfg)
    pitches = recommend_pitch_pool(row, cfg)
    return {
        'player': str(row.get('Name', '')),
        'pos': str(row.get('POS', '')),
        'is_pit': True,
        'age': int(_s(row.get('AGE', row.get('Age', 0)))),
        'main': main,
        'pitch_pool': pitches,
        # Flattened convenience copies for uniform downstream consumption.
        'recommended_positions': {**main['recommended_positions'],
                                  **pitches['recommended_positions']},
        'recommended_deltas': {**main['recommended_deltas'],
                               **pitches['recommended_deltas']},
        'weighted_gaps': {**main['weighted_gaps'], **pitches['weighted_gaps']},
        'defense_pinned': False,
        'notes': main['notes'] + pitches['notes'],
    }


def recommend_player(row, cfg: dict) -> dict | None:
    pos = str(row.get('POS', ''))
    if pos in PITCHER_POSITIONS:
        return recommend_pitcher(row, cfg)
    if pos in BATTER_POSITIONS:
        return recommend_batter(row, cfg)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════════════════════════════

def _load_dev_state(league: League) -> dict:
    cfg = league.get_config()
    state = cfg.get('development_state', {})
    merged = {**DEV_DEFAULTS, **state}
    # Deep-merge the nested reserve config so partial saves keep their defaults.
    rsv = state.get('reserve') or {}
    merged['reserve'] = {**rr.RESERVE_DEFAULTS, **rsv}
    merged['reserve']['class'] = {**rr.CLASS_DEFAULTS, **(rsv.get('class') or {})}
    return merged


def _save_reserve_cfg(league: League, **updates):
    cur = _load_dev_state(league)
    cur['reserve'].update({k: v for k, v in updates.items() if v is not None})
    league.save_config({'development_state':
                        {k: cur[k] for k in DEV_DEFAULTS}})


def _save_dev_state(league: League, **updates):
    cur = _load_dev_state(league)
    cur.update({k: v for k, v in updates.items() if v is not None})
    league.save_config({'development_state': {k: cur[k] for k in DEV_DEFAULTS}})


# ══════════════════════════════════════════════════════════════════════════════
# ROSTER LOAD  (shared with My Team — engine guard + ORG filter, mirrors my_team)
# ══════════════════════════════════════════════════════════════════════════════

_V27_SIG = {'CON_1', 'BABIP_1', 'WAR_1'}
_V26_SIG = {'CON.1', 'BABIP.1', 'WAR.1'}


def _saved_roster(league: League) -> pd.DataFrame | None:
    """Read the saved roster (ORG-filtered) WITHOUT rendering an uploader — for
    secondary tabs, so only the Slider Optimizer tab owns the file_uploader."""
    my_team = league.team_config.get('my_team', '')
    if not my_team:
        st.warning("Set your team in ⚙️ Settings first.")
        return None
    saved = league.get_last_roster()
    if saved is None or saved.empty:
        st.info("Upload a roster in the 🎚️ Slider Optimizer tab first — it's "
                "shared across Development.")
        return None
    df = saved.copy()
    if 'ORG' in df.columns:
        df = df[df['ORG'].astype(str).str.strip() == my_team].copy()
    return df


def _load_roster(league: League) -> pd.DataFrame | None:
    my_team = league.team_config.get('my_team', '')
    if not my_team:
        st.warning("Set your team in ⚙️ Settings first — Development filters to "
                   "your roster by ORG, like My Team.")
        return None

    saved = league.get_last_roster()
    has_saved = saved is not None and not saved.empty

    with st.expander("📤 Upload roster CSV" + (" (replace current)" if has_saved else ""),
                     expanded=not has_saved):
        st.caption("Full league export is fine — filtered to your team by ORG. "
                   "Shared with My Team; uploading here replaces that roster too.")
        up = st.file_uploader("Roster CSV", type=['csv'], key='dev_upload')
        if up is not None:
            uid = f"{up.name}:{up.size}"
            if uid != st.session_state.get('_dev_last_upload_id'):
                try:
                    raw = pd.read_csv(up, encoding='utf-8-sig', low_memory=False)
                    cols = set(raw.columns)
                    if (_V26_SIG & cols) and not (_V27_SIG & cols):
                        st.error("⛔ This looks like an OOTP 26 export, not 27. "
                                 "Pitcher control/BABIP/WAR columns differ; F1 "
                                 "would be wrong. Re-export from OOTP 27.")
                        return saved if has_saved else None
                    if not (_V27_SIG & cols):
                        st.warning("⚠️ Missing the OOTP 27 signature "
                                   "(CON_1/BABIP_1/WAR_1). Verify results.")
                    team_col = next((c for c in ('ORG', 'TM', 'Team') if c in cols), None)
                    if team_col is None:
                        st.error("CSV has no ORG, TM, or Team column.")
                        return saved if has_saved else None
                    team_rows = raw[raw[team_col].astype(str).str.strip() == my_team]
                    if team_rows.empty:
                        st.error(f"No players with {team_col} == '{my_team}'.")
                        return saved if has_saved else None
                    df = prep_data(team_rows.copy())
                    league.save_last_roster(df)
                    st.session_state['_dev_last_upload_id'] = uid
                    st.success(f"Roster saved — {len(df)} players from {my_team}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to read CSV: {e}")
                    return saved if has_saved else None

    if not has_saved:
        st.info("Upload a roster CSV to begin.")
        return None
    df = saved.copy()
    if 'ORG' in df.columns:
        df = df[df['ORG'].astype(str).str.strip() == my_team].copy()
    return df


# ══════════════════════════════════════════════════════════════════════════════
# RENDER
# ══════════════════════════════════════════════════════════════════════════════

def _gap_glyph(score: float, scale: float) -> str:
    if score <= 0:        return GLYPH_NONE
    if score >= scale:    return GLYPH_BIG
    return GLYPH_SMALL


def _delta_str(d: int) -> str:
    return f"{d:+d}" if d else "0"


def render_development(league: League):
    st.header("🌱 Development")

    complete, missing = league.team_config_complete()
    if not complete:
        st.warning(f"Team Config incomplete ({', '.join(missing)} missing). "
                   "Configure in ⚙️ Settings.")

    cfg = _load_dev_state(league)

    tabs = st.tabs(["🎚️ Slider Optimizer", "📋 Reserve Roster", "📐 Methodology"])
    with tabs[0]:
        # The uploader lives here (rendered once). Saved roster is shared with the
        # other data tabs via league.get_last_roster().
        _render_optimizer(league, cfg, _load_roster(league))
    with tabs[1]:
        _render_reserve(league, cfg, _saved_roster(league))
    with tabs[2]:
        _render_methodology(cfg)


def _render_optimizer(league: League, cfg: dict, df):
    if df is None or df.empty:
        return

    rep = audit_development_columns(df)
    with st.expander("🔎 Column audit (fail-loud gate)",
                     expanded=bool(rep['errors'])):
        c1, c2, c3 = st.columns(3)
        c1.metric("Batter pool", "READY" if rep['ok_batter_pool'] else "BLOCKED")
        c2.metric("Pitcher main", "READY" if rep['ok_pitcher_main'] else "BLOCKED")
        c3.metric("Pitch pool", "READY" if rep['ok_pitch_pool'] else "BLOCKED")
        if rep['errors']:
            st.error("**Missing load-bearing columns — pool(s) gated:**\n"
                     + "\n".join(f"- {e}" for e in rep['errors']))
        for n in rep['notes']:
            st.caption("• " + n)

    # ── Controls ──────────────────────────────────────────────────────────────
    with st.expander("⚙️ Optimizer settings"):
        col1, col2 = st.columns(2)
        with col1:
            wm = st.radio("Contact-family weighting", ['total_deriv', 'per_rating'],
                index=0 if cfg['weight_mode'] == 'total_deriv' else 1,
                help="total_deriv credits BABIP/Avoid K's with their own weight "
                     "+ half the Contact (parent) weight, since Contact ≈ "
                     "mean(BABIP, Avoid K's). per_rating uses own weight only.")
            sm = st.radio("Stamina (no potential)", ['neutral', 'floor'],
                index=0 if cfg['stm_mode'] == 'neutral' else 1,
                help="neutral holds STM at 50 (no growth chased, not stripped); "
                     "floor drops it to 10 and gives the points to Movement/Control.")
        with col2:
            pk = st.number_input("Pitch budget: concentrate on top-K", 1, 5,
                value=int(cfg['pitch_concentrate']),
                help="Anti-balance (H3): the engine rewards 1–2 elite pitches over "
                     "balanced depth. K=2 puts the budget on the two biggest gaps.")
        if st.button("Save settings"):
            _save_dev_state(league, weight_mode=wm, stm_mode=sm,
                            pitch_concentrate=int(pk))
            st.success("Saved.")
            st.rerun()

    vet = cfg['veteran_age']
    st.caption(f"Players age ≥ {vet} develop minimally — recommendations there are "
               "low-yield; default/even is fine. Younger players with large "
               "current→potential gaps are where the budget matters.")

    bats = df[df['POS'].isin(BATTER_POSITIONS)].copy()
    pits = df[df['POS'].isin(PITCHER_POSITIONS)].copy()

    sub = st.tabs([f"⚾ Batters ({len(bats)})", f"🥎 Pitchers ({len(pits)})"])
    with sub[0]:
        if not rep['ok_batter_pool']:
            st.error("Batter pool gated by the column audit above.")
        else:
            _render_batters(bats, cfg)
    with sub[1]:
        if not rep['ok_pitcher_main']:
            st.error("Pitcher main pool gated by the column audit above.")
        else:
            _render_pitchers(pits, cfg, rep['ok_pitch_pool'])


_BAT_ORDER = ['Power', 'BABIP', "Avoid K's", 'Eye', 'Gap', 'Running', 'Defense']
_PIT_MAIN_ORDER = ['Movement', 'Control', 'Stamina']


def _inspect_picker(recs: list, table_df: pd.DataFrame, card_fn, key_prefix: str,
                    height: int, label_fn):
    """
    Shared inspect mechanism, mirroring draft.py's board pattern:
      • Row-select on the table itself (Streamlit ≥1.35 on_select) opens the
        player's card in a MODAL dialog over the board.
      • try/except falls back to a plain table on older Streamlit.
      • A selectbox + 'Open plan' button below is the explicit fallback picker
        (and the only path when on_select / st.dialog are unavailable, where it
        degrades to an inline expander). card_fn renders the card in all paths.
    """
    dialog_fn = getattr(st, 'dialog', None) or getattr(st, 'experimental_dialog', None)

    def _open(idx):
        if dialog_fn is not None:
            @dialog_fn("🔍 Development plan")
            def _popup():
                card_fn(recs[idx])
            _popup()
        else:
            with st.container():
                card_fn(recs[idx])

    board_sel = None
    try:
        board_sel = st.dataframe(table_df, use_container_width=True, hide_index=True,
                                 height=height, on_select='rerun',
                                 selection_mode='single-row', key=f'{key_prefix}_table')
    except TypeError:
        st.dataframe(table_df, use_container_width=True, hide_index=True, height=height)

    sel_rows = []
    if board_sel is not None:
        try:
            sel_rows = board_sel['selection']['rows']
        except (KeyError, TypeError):
            sel_rows = []
    if sel_rows and 0 <= sel_rows[0] < len(recs):
        _open(sel_rows[0])

    st.caption("👆 Select a row to open that player's full slider plan "
               "(or use the picker below).")

    idxs = list(range(len(recs)))
    if dialog_fn is not None:
        st.markdown("**🔍 Or pick from the list:**")
        i = st.selectbox("Player", idxs, index=0, format_func=label_fn,
                         key=f'{key_prefix}_pick', label_visibility='collapsed')
        if st.button("Open plan", key=f'{key_prefix}_open'):
            _open(i)
    else:
        with st.expander("🔍 Inspect a player", expanded=False):
            i = st.selectbox("Player", idxs, index=0, format_func=label_fn,
                             key=f'{key_prefix}_pick')
            card_fn(recs[i])


def _render_batters(bats: pd.DataFrame, cfg: dict):
    recs = [recommend_batter(r.to_dict(), cfg) for _, r in bats.iterrows()]
    recs = [r for r in recs if r]
    recs.sort(key=lambda r: sum(r['weighted_gaps'].values()), reverse=True)

    rows = []
    for r in recs:
        d = r['recommended_deltas']
        rows.append({
            'Name': r['player'], 'POS': r['pos'], 'Age': r['age'],
            'Focus': max((s for s in _BAT_ORDER if s != 'Defense'),
                         key=lambda s: r['weighted_gaps'].get(s, 0)),
            **{s: _delta_str(d.get(s, 0)) for s in _BAT_ORDER},
            'ΣGap': round(sum(r['weighted_gaps'].values()), 2),
        })
    st.caption("Click deltas from neutral (Reset → 50, then apply). Defense pinned "
               f"{GLYPH_PIN}. Sorted by total weighted gap.")
    _inspect_picker(recs, pd.DataFrame(rows), lambda r: _render_batter_card(r, cfg),
                    'dev_bat', 460,
                    lambda k: f"{recs[k]['player']} — {recs[k]['pos']}, age {recs[k]['age']}")


def _render_pitchers(pits: pd.DataFrame, cfg: dict, pitch_ok: bool):
    recs = [recommend_pitcher(r.to_dict(), cfg) for _, r in pits.iterrows()]
    recs = [r for r in recs if r]
    recs.sort(key=lambda r: sum(r['weighted_gaps'].values()), reverse=True)

    rows = []
    for r in recs:
        d = r['main']['recommended_deltas']
        pg = r['pitch_pool']['weighted_gaps']
        top_pitch = max(pg, key=pg.get) if pg else '—'
        rows.append({
            'Name': r['player'], 'POS': r['pos'], 'Age': r['age'],
            **{s: _delta_str(d.get(s, 0)) for s in _PIT_MAIN_ORDER},
            'Top pitch focus': top_pitch if (pg and pg.get(top_pitch, 0) > 0) else '—',
            'ΣGap': round(sum(r['weighted_gaps'].values()), 2),
        })
    st.caption("Main-pool click deltas from neutral. Sorted by total weighted gap.")
    if not pitch_ok:
        st.warning("Pitch pool gated by the column audit — main pool only.")
    _inspect_picker(recs, pd.DataFrame(rows), lambda r: _render_pitcher_card(r, cfg),
                    'dev_pit', 420,
                    lambda k: f"{recs[k]['player']} — {recs[k]['pos']}, age {recs[k]['age']}")


def _render_batter_card(r: dict, cfg: dict):
    """Full batter card — used by both the modal and the fallback picker."""
    st.markdown(f"**{r['player']}** — {r['pos']}, age {r['age']}"
                + ("  ·  _veteran: minimal development_"
                   if r['age'] >= cfg['veteran_age'] else ""))
    pos = r['recommended_positions']; d = r['recommended_deltas']; g = r['weighted_gaps']
    st.dataframe(pd.DataFrame([{
        'Slider': s,
        'Set to': pos.get(s),
        'Δ clicks': _delta_str(d.get(s, 0)),
        'Weighted gap': round(g.get(s, 0), 3),
        '': (GLYPH_PIN if (s == 'Defense' and r['defense_pinned'])
             else _gap_glyph(g.get(s, 0), 0.5)),
    } for s in _BAT_ORDER]), use_container_width=True, hide_index=True)
    for n in r['notes']:
        st.caption("• " + n)


def _render_pitcher_card(r: dict, cfg: dict):
    """Full pitcher card (main pool + pitch pool) — used by modal and picker."""
    st.markdown(f"**{r['player']}** — {r['pos']}, age {r['age']}"
                + ("  ·  _veteran: minimal development_"
                   if r['age'] >= cfg['veteran_age'] else ""))
    st.markdown("**Main pool** (Movement / Control / Stamina, budget 150)")
    md = r['main']['recommended_deltas']; mp = r['main']['recommended_positions']
    mg = r['main']['weighted_gaps']
    st.dataframe(pd.DataFrame([{
        'Slider': s, 'Set to': mp.get(s), 'Δ clicks': _delta_str(md.get(s, 0)),
        'Weighted gap': round(mg.get(s, 0), 3),
        '': _gap_glyph(mg.get(s, 0), 0.5),
    } for s in _PIT_MAIN_ORDER]), use_container_width=True, hide_index=True)
    pg = r['pitch_pool']
    if pg['recommended_positions']:
        st.markdown(f"**Pitch pool** (per-pitch Stuff, budget "
                    f"{len(pg['recommended_positions'])}×50)")
        pgd = pg['recommended_deltas']; pgp = pg['recommended_positions']
        pgg = pg['weighted_gaps']
        st.dataframe(pd.DataFrame([{
            'Pitch': k, 'Set to': pgp[k], 'Δ clicks': _delta_str(pgd.get(k, 0)),
            'Weighted gap': round(pgg.get(k, 0), 3),
            '': _gap_glyph(pgg.get(k, 0), 1.0),
        } for k in pgp]), use_container_width=True, hide_index=True)
    for n in r['notes']:
        st.caption("• " + n)


# ══════════════════════════════════════════════════════════════════════════════
# RESERVE ROSTER — keep-or-cut (Layer 3)
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
        phases = list(rr.PHASE_PRESETS.keys())
        phase = st.selectbox("Roster phase", phases,
                             index=phases.index(rcfg['phase']) if rcfg['phase'] in phases else 0,
                             help="Presets set the active/reserve caps and whether "
                                  "your newest draft picks are protected from cuts.")
        preset = rr.PHASE_PRESETS[phase]
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
        mw = rcfg.get('mode_weights') or rr.MODE_WEIGHTS.get(mode, rr.MODE_WEIGHTS['Sustaining'])
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

    result = rr.allocate_reserve(reserve.to_dict('records'), growth_by_name, mode, live)

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
    _inspect_picker(recs, pd.DataFrame(rows), _render_reserve_card, 'dev_rsv', 460,
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


def _render_methodology(cfg: dict):
    st.markdown("#### How the Slider Optimizer works")
    st.markdown(
        "Each development pool is a **zero-sum budget** of +/- clicks. The "
        "optimizer ranks every developable rating by **weighted gap** — "
        "`F1_weight × max(0, potential − current)` — and distributes each pool's "
        "budget proportionally, clamped to 10–90, renormalized to the exact pool "
        "total. Output is **click deltas from neutral** (hit *Reset*, then apply) "
        "because the OOTP UI is click-only. The tool ranks *where to point the "
        "budget*, not how much WAR a focus buys (that magnitude question is a "
        "Dev Lab / Layer-2 study, not needed to rank allocation).")

    st.markdown("**Batter weights** are derived live from `acquisitions.off_f1` "
                "(single source). OOTP 27 makes **Contact a composite parent of "
                "BABIP + Avoid K's** (Contact ≈ mean of the two). So the Avoid K's "
                "slider develops the **Avoid K's** rating (`AVK`), not Contact; "
                "Contact has no direct slider and rises as its children grow. In "
                f"the default `{cfg['weight_mode']}` mode each child is credited "
                "with its own weight + half the Contact weight.")

    st.markdown("**Three locked v27 findings shape the output:**")
    st.markdown(
        "1. **Defense pinned to 10.** The slider moves only underlying defensive "
        "ratings, which are frozen (r 0.96–0.99); position grades develop on a "
        "separate playing-time channel. Budget on Defense is a knob connected to "
        "nothing — freed points go to offense. Override available per player.\n"
        "2. **Defensive potentials ignored on purpose.** The export carries "
        "position-grade potentials (`FLD_*_P`). Defense doesn't develop (A19), so "
        "the allocator reads them and *declines to act* — surfaced in the audit, "
        "never fed into a gap.\n"
        "3. **SPE and STM have no potential column** → no growth term (score 0), "
        "handled fail-loud, never invented. Stamina is neutral-held at 50 by "
        f"default (`stm_mode='{cfg['stm_mode']}'`) rather than stripped to 10.")

    st.markdown("**Pitcher pools.** Main pool (Movement / Control / Stamina) uses "
                "development-appropriate scalar weights (MOV 0.1091 ≫ Control "
                "0.0053) — not the split rate-model F1, which inverts MOV/Control "
                "and signs STM negative. The **pitch pool** develops per-pitch "
                "Stuff and is ranked by the H3 decomposition (SI 0.134, CH 0.117, "
                "SL 0.043; FB and the rest ≈0). Anti-balance: the engine rewards "
                "1–2 elite pitches over balanced depth, so the budget is "
                f"concentrated on the top {cfg['pitch_concentrate']} gaps, not spread.")
    st.caption("Interim caveat: pitch weights and the registry priorities are "
               "calibrated on K-T multiverse data; re-validate after the AC "
               "converts to OOTP 27.")
