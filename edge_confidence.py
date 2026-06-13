"""
OOTP 27 Suite — Edge Confidence + Total Value  (board composite lens)
====================================================================
Pure logic, no Streamlit — portable / unit-testable like `park_fit.py` and
`roster_construction.py`. Two products:

  1. EDGE STABILITY — the one orthogonal signal the board lacked: how much of a
     prospect's F2 value rides on inputs the 26→27 conversion study proved are
     UNSTABLE — role-contaminated STU (displayed STU swings ±5–14 on SP/RP
     slotting) on the arm side, and EYE on the bat side (hardest shave −2.08 +
     worst delivery 28% + closest to a 20–80 bucket flip). Weighted by the
     DEPLOYED f2_deploy.json coefficients × the player's OWN ratings, so it is a
     real per-player contribution share, not a flat rule. (The importances tell
     us why this matters on the arm side and barely on the bat side: EYE is ~4%
     of batter value, so batter placements are almost always stable — itself the
     finding; STU drives a large share of pitcher value and is the role-contam.)

  2. TOTAL VALUE — the "fully baked" composite: a sum of the board's already-
     additive WAR lenses (disc + glove + park fit) scaled by a bounded confidence
     multiplier. This DOES reorder vs BPA — by design — so it is an OPT-IN
     alternate lens; `career` (BPA) stays the locked default. The board's
     sub-columns remain as its decomposition / checks.

DISCIPLINE
----------
  • Edge Stability and Total Value NEVER touch `career` (the BPA rank) or fold
    into F1 / F2. They are additive board annotations + an opt-in alternate sort.
  • Fail-loud: a missing load-bearing rating yields ok=False + reason, never a
    silent 1.0 / silent 0.
  • Park Fit (A22) and Glove (A12) keep their "never reorders the BPA view" locks.
    Total Value is a SEPARATE lens, not a redefinition of those — register it as a
    new lens; A22 / A12 are unchanged for the default board.

v2 NOTE
-------
  The conversion-noisy pitch GRADES (FB ρ0.885 / CHP ρ0.906) are surfaced as an
  interim flag only (`grade_flags`), NOT yet folded into the stability share — the
  share is restricted to tool features that map DIRECTLY to prepped export columns
  so it needs only f2_deploy coefficients, not acquisitions' engineered-feature
  builder. Folding the engineered PIT_*_VAL grade terms into the share is the v2
  upgrade (send `acquisitions.py` / the feature builder and it becomes exact).
"""

import json
import math
import os


# ── number coercion (local; mirrors acquisitions._s / park_fit._num) ──────────
def _num(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


# ══════════════════════════════════════════════════════════════════════════════
# FRAGILE-INPUT REGISTRY  (from the 26→27 conversion stability study)
# ══════════════════════════════════════════════════════════════════════════════
#
# Tool features that carry on-field skill signal — the fragility DENOMINATOR.
# Restricted to features that map DIRECTLY to prepped export columns (PIT_CON is
# the ingest-renamed CON_1; velo_mid is already on the board row). The fragility
# NUMERATOR is the subset the study proved unstable.

_PIT_TOOLS = ['STU', 'MOV', 'PIT_CON', 'PBABIP', 'HRA', 'STM', 'velo_mid']
_BAT_TOOLS = ['CON', 'GAP', 'POW', 'EYE', 'SPE']

_PIT_FRAGILE = {
    'STU': 'role-contaminated: displayed STU swings ±5–14 on SP/RP slotting',
}
_BAT_FRAGILE = {
    'EYE': 'hardest shave (−2.08) + worst delivery (28%) + closest to a bucket flip',
}

# Raw pitch grades the study flagged non-uniform on conversion (ρ 0.88–0.91).
# Interim supplementary flag only — NOT in the stability share (v2; see module note).
_PITCH_GRADE_NOISE = {'FB': 'FB grade reshuffles on conversion (ρ0.885)',
                      'CH': 'CHP swings non-uniformly (ρ0.906, SD14)'}


# ══════════════════════════════════════════════════════════════════════════════
# DEPLOYED F2 COEFFICIENTS  (single source: f2_deploy.json)
# ══════════════════════════════════════════════════════════════════════════════
_DEPLOY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'f2_deploy.json')
_COEFS_CACHE = None


def load_coefs(path: str = None) -> dict:
    """Load the deployed raw F2 coefficients. Fail-loud if the file is absent
    (never fall back to silent zeros — a missing deploy file should block, not
    quietly disable the confidence column)."""
    global _COEFS_CACHE
    if _COEFS_CACHE is not None and path is None:
        return _COEFS_CACHE
    p = path or _DEPLOY_PATH
    if not os.path.exists(p):
        raise FileNotFoundError(
            f"edge_confidence: f2_deploy.json not found at {p}; "
            "cannot weight the stability share without the deployed coefficients.")
    with open(p, 'r') as f:
        d = json.load(f)
    coefs = {'pitcher': d['pitcher']['raw_coef'], 'batter': d['batter']['raw_coef']}
    if path is None:
        _COEFS_CACHE = coefs
    return coefs


# ══════════════════════════════════════════════════════════════════════════════
# EDGE STABILITY
# ══════════════════════════════════════════════════════════════════════════════
def edge_stability(row: dict, is_pit: bool, coefs: dict = None) -> dict:
    """
    Per-player share of F2 TOOL value that rides on conversion/role-unstable inputs.

        stability = 1 − Σ|coef_f · v_f|(fragile) / Σ|coef_t · v_t|(all tools)  ∈ [0,1]

    1.0 = edge rests entirely on stable tools; lower = more of the edge rides on
    STU(role) / EYE(shave). Uses deployed coefficients × the player's own ratings.

    SUCCESS  → {ok:True, stability, fragile_share, drivers[], grade_flags[], note}
    FAIL-LOUD→ {ok:False, stability:None, reason}   (never a silent 1.0)
    """
    coefs = coefs or load_coefs()
    side = 'pitcher' if is_pit else 'batter'
    c = coefs[side]
    tools = _PIT_TOOLS if is_pit else _BAT_TOOLS
    fragile = _PIT_FRAGILE if is_pit else _BAT_FRAGILE

    # Core tools are load-bearing; velo_mid is optional context.
    core = [t for t in tools if t != 'velo_mid']
    hard_missing = [t for t in core if t not in row or row.get(t) is None]
    if hard_missing:
        return {'ok': False, 'stability': None,
                'reason': "missing load-bearing rating(s): " + ", ".join(hard_missing)}

    contrib = {t: abs(_num(c[t]) * _num(row.get(t))) for t in tools if t in c}
    total = sum(contrib.values())
    if total <= 0:
        return {'ok': False, 'stability': None,
                'reason': "no positive tool contribution (all ratings zero?)"}

    frag = sum(contrib.get(t, 0.0) for t in fragile)
    share = frag / total
    stability = max(0.0, min(1.0, 1.0 - share))

    drivers = [{'rating': t, 'share': round(contrib[t] / total, 3), 'why': fragile[t]}
               for t in fragile if contrib.get(t, 0) > 0]

    grade_flags = []
    if is_pit:
        for g, why in _PITCH_GRADE_NOISE.items():
            gv = _num(row.get(g))
            if gv >= 50:                 # a real grade on a conversion-noisy pitch
                grade_flags.append({'pitch': g, 'grade': int(gv), 'why': why})

    return {'ok': True, 'stability': round(stability, 3),
            'fragile_share': round(share, 3), 'drivers': drivers,
            'grade_flags': grade_flags,
            'note': "share of F2 tool value resting on conversion/role-unstable inputs"}


def confidence_mult(stability, floor: float = 0.85) -> float:
    """Bounded reliability multiplier in [floor, 1.0]. floor=0.85 → worst-case −15%.
    A fail-loud `None` stability returns 1.0 (no silent penalty) — the caller is
    expected to surface the fail reason, not quietly trust the row."""
    if stability is None:
        return 1.0
    floor = max(0.0, min(1.0, float(floor)))
    s = max(0.0, min(1.0, float(stability)))
    return round(floor + (1.0 - floor) * s, 4)


# ══════════════════════════════════════════════════════════════════════════════
# TOTAL VALUE  (opt-in composite — DOES reorder vs BPA, by design)
# ══════════════════════════════════════════════════════════════════════════════
def total_value(career, disc, glove, parkfit, conf, *, is_pit: bool,
                base: str = 'disc') -> float:
    """
    The "fully baked" number: a sum of the board's already-additive WAR lenses,
    scaled by the confidence multiplier.

        batter :  (base + glove + parkfit) × conf
        pitcher:   base × conf        (glove / parkfit are batter-only: A12 / A23)

    base = 'disc' (growth-discounted; the realistic draft value — default) or
    'career' (no-growth floor). glove / parkfit may be None (pitcher / uncalibrated
    park / missing cols) → treated as 0 additive.

    Returns a float WAR. This reorders vs BPA — it is an OPT-IN alternate sort;
    `career` stays the locked default and the sub-columns are its decomposition.
    """
    b = _num(disc) if base == 'disc' else _num(career)
    total = b if is_pit else (b + _num(glove) + _num(parkfit))
    return round(total * _num(conf, 1.0), 2)


# ══════════════════════════════════════════════════════════════════════════════
# COLORBLIND-SAFE STABILITY GLYPH  (diamond fill-ramp; shape only, no color)
# ══════════════════════════════════════════════════════════════════════════════
def stability_glyph(stability) -> str:
    """● solid = stable edge · ◐ mixed · ○ hollow = fragile. Fill-ramp CIRCLES —
    deliberately distinct from the board's Glove ◆/◇ column so the two don't read
    as the same signal. Shape/fill only (colorblind-safe, house style). '' when
    stability is None (fail-loud upstream). Pair with the numeric for precision."""
    if stability is None:
        return ''
    if stability >= 0.90:
        return '●'
    if stability >= 0.75:
        return '◐'
    return '○'


# ── one-call convenience for build_board (keeps the draft.py hook to ~3 lines) ─
def annotate(row: dict, *, is_pit: bool, career, disc, glove, parkfit,
             conf_floor: float = 0.85, base: str = 'disc', coefs: dict = None) -> dict:
    """Compute the full edge/composite bundle for one prospect in a single call.

    Returns {edge, edge_ok, edge_reason, edge_glyph, edge_drivers, grade_flags,
             conf, tval}. Designed to be spread into the board row dict."""
    es = edge_stability(row, is_pit, coefs=coefs)
    conf = confidence_mult(es.get('stability'), floor=conf_floor)
    tval = total_value(career, disc, glove, parkfit, conf, is_pit=is_pit, base=base)
    return {
        'edge':         es.get('stability'),
        'edge_ok':      es.get('ok', False),
        'edge_reason':  es.get('reason', ''),
        'edge_glyph':   stability_glyph(es.get('stability')),
        'edge_drivers': es.get('drivers', []),
        'grade_flags':  es.get('grade_flags', []),
        'conf':         conf,
        'tval':         tval,
    }
