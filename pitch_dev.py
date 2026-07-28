"""
OOTP 27 Suite — Pitch Development Lens  (A41 / A43)
==================================================
Pure logic, no Streamlit — portable / unit-testable like `park_fit.py` and
`edge_confidence.py`. Classifies a pitcher's PROJECTED arsenal into pitches whose
potential is realistically deliverable vs. "mirages" the development findings say
almost never arrive — then routes the mirage share into the EXISTING bounded
confidence lens. It never invents a WAR discount.

WHY THIS EXISTS (the deployment gap it closes)
----------------------------------------------
The deployed scorer (`acquisitions.f2_discounted_war` → `_discounted_row`) leaves
the 12 pitch grades at their REAL CURRENT value — the delivery-discount layer only
touches 7 ratings (CON/GAP/POW/EYE + PIT_CON/STU/MOV). So F2 is blind to pitch
DEVELOPMENT entirely: a projected CH 25→80 and a projected CH 55→80 look identical
to the model (both score the current grade), and a draftee arm's whole projected
ceiling contributes nothing. Findings A41/A43 are locked in the registry but were
never wired into scoring. This module is that wiring — as a FLAG + confidence
input, not a value mutation.

WHAT THE FINDINGS SAY (and what they DON'T)
-------------------------------------------
  A41 — a projected pitch is trustworthy only once its CURRENT grade clears a
        floor: changeup ≥ 45 (it lags), every other pitch ≥ 40. Below the floor,
        the projection lands ~4–15% of the time and RARELY reaches potential.
  A43 — four pitch TYPES (curveball, sinker, cutter, splitter) are blocked from a
        low base regardless of training; value them only if already ≥ 40.
        Arsenals also build ONE pitch at a time (serial, not parallel).

  What the findings do NOT give us: a WAR magnitude for a mirage. There is no
  calibrated delivery factor for pitch grades (DELIVERY_FACTORS covers CON/STU/
  MOV/PIT_CON only). So this module DELIBERATELY does not discount F2 value. It
  classifies (fully supported) and feeds the mirage share into the bounded
  confidence multiplier that already exists (edge_confidence.confidence_mult),
  whose 0.85 floor IS a defensible calibrated bound. A hard value discount is a
  FUTURE STUDY (measure mature WAR: mirage-only-ceiling arms vs real-arsenal arms,
  derive a factor, append to DELIVERY_FACTORS). Until then MIRAGE_WAR_FACTOR is
  None and any value-discount path FAILS LOUD rather than shipping a guess.
"""
from __future__ import annotations
import math

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
# A41 / A43 REGISTRY CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
# Post-prep pitch-grade column → its potential column (acquisitions rename map).
# Only the 7 modeled/tracked grades carry a potential column in the export; the
# other 5 (FO/CC/SC/KC/KN) are scored flat by F2 but have no _P column, so they
# cannot be classified as develop-vs-mirage (no projection to judge) — they are
# reported under `no_projection`, never counted as a mirage.
PITCH_POT_COL = {
    'PIT_FB_GR': 'PIT_FB_GR_P',
    'PIT_CH':    'PIT_CH_P',
    'PIT_SI':    'PIT_SI_P',
    'PIT_SL':    'PIT_SL_P',
    'PIT_CB':    'PIT_CB_P',
    'PIT_CT':    'PIT_CT_P',
    'PIT_SP':    'PIT_SP_P',
}

# A41 current-grade floors below which a projection is a mirage.
CH_FLOOR    = 45     # changeup lags — higher bar
OTHER_FLOOR = 40

# A43 pitch types blocked from a low base (value only if already ≥ 40).
BLOCKED_TYPES = {'PIT_CB', 'PIT_SI', 'PIT_CT', 'PIT_SP'}  # curve, sinker, cutter, splitter

# A projection only "counts" as upside worth judging if potential exceeds current
# by at least this much (a flat pot==cur pitch is a current pitch, not a bet).
PROJ_GAP_MIN = 10

# UNCALIBRATED — see module docstring. No study yet ties mirage share to WAR, so
# there is no honest value discount. Leave None; the value-discount path fails loud.
MIRAGE_WAR_FACTOR = None


def _floor_for(col: str) -> int:
    return CH_FLOOR if col == 'PIT_CH' else OTHER_FLOOR


def classify_pitch(col: str, cur, pot) -> str:
    """Classify ONE projected pitch. Returns:
       'real'          — projection clears the A41 floor (and A43 for blocked types)
       'mirage'        — a real projection (gap ≥ PROJ_GAP_MIN) that fails the floor
       'current'       — usable now but no meaningful projected growth
       'none'          — no current grade
       'no_projection' — has a current grade but no potential column to judge
    """
    c = _num(cur, None) if cur not in ('', '-', None) else None
    if c is None or c <= 0:
        return 'none'
    if pot in ('', '-', None):
        return 'no_projection'
    p = _num(pot, None)
    if p is None:
        return 'no_projection'
    gap = p - c
    if gap < PROJ_GAP_MIN:
        return 'current'                       # it is what it is; not a dev bet
    # a genuine projected jump — trustworthy only if it clears the floor
    below_floor = c < _floor_for(col)
    blocked = (col in BLOCKED_TYPES and c < 40)
    return 'mirage' if (below_floor or blocked) else 'real'


def pitch_dev_report(row: dict) -> dict:
    """Per-pitcher arsenal-development classification.

    SUCCESS → {ok:True, real[], mirage[], current[], no_projection[],
               n_real, n_mirage, mirage_share, note}
      mirage_share = n_mirage / (n_real + n_mirage)  ∈ [0,1]  (0 when no projections)
      An arm whose projected ceiling is ALL mirage → share 1.0; all real → 0.0.
    FAIL-LOUD → {ok:False, reason}   (no pitch columns present at all)
    """
    seen_any_col = any(col in row for col in PITCH_POT_COL)
    if not seen_any_col:
        return {'ok': False, 'reason': 'no pitch-grade columns present in row'}

    buckets = {'real': [], 'mirage': [], 'current': [], 'no_projection': []}
    for col, potcol in PITCH_POT_COL.items():
        cur = row.get(col)
        pot = row.get(potcol)
        kind = classify_pitch(col, cur, pot)
        if kind == 'none':
            continue
        entry = {'pitch': col, 'cur': _num(cur), 'pot': _num(pot) if pot not in ('', '-', None) else None}
        buckets[kind].append(entry)

    n_real = len(buckets['real'])
    n_mir = len(buckets['mirage'])
    denom = n_real + n_mir
    share = (n_mir / denom) if denom > 0 else 0.0

    return {
        'ok': True,
        'real': buckets['real'], 'mirage': buckets['mirage'],
        'current': buckets['current'], 'no_projection': buckets['no_projection'],
        'n_real': n_real, 'n_mirage': n_mir,
        'mirage_share': round(share, 3),
        'note': ("share of a pitcher's PROJECTED arsenal that fails the A41/A43 "
                 "development floor; classification only — no WAR discount (uncalibrated)"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE HOOK — route mirage share into the EXISTING bounded multiplier
# ══════════════════════════════════════════════════════════════════════════════
# We do NOT introduce a new magnitude. edge_confidence.confidence_mult already maps
# a [0,1] "stability"-style score → a bounded [floor,1.0] reliability multiplier.
# We convert mirage_share into that same 0-1 shape (1.0 = no mirage upside) and let
# the caller run it through confidence_mult with the suite's existing 0.85 floor.

def pitch_dev_reliability(report: dict) -> float | None:
    """Map a pitch_dev_report → a [0,1] reliability score for confidence_mult.
    1.0 = projected ceiling rests on real pitches; lower = more of it is mirage.
    Returns None on a fail-loud report (caller keeps 1.0, surfaces the reason)."""
    if not report or not report.get('ok'):
        return None
    return round(1.0 - _num(report.get('mirage_share')), 3)


# ══════════════════════════════════════════════════════════════════════════════
# UNCALIBRATED VALUE-DISCOUNT PATH — fails loud on purpose
# ══════════════════════════════════════════════════════════════════════════════
def mirage_value_discount(report: dict) -> dict:
    """A hard WAR discount would need a calibrated MIRAGE_WAR_FACTOR. None exists.
    This returns a fail-loud payload so no caller can silently apply a guessed
    number — matching the suite's 'never silent-fudge F2' discipline."""
    return {
        'ok': False, 'factor': None,
        'reason': ("no calibrated mirage→WAR factor (MIRAGE_WAR_FACTOR is None). "
                   "A41/A43 give development PROBABILITY, not a WAR magnitude. Run "
                   "the mature-WAR study (mirage-only-ceiling arms vs real-arsenal "
                   "arms), derive a factor, append to DELIVERY_FACTORS — do not "
                   "hardcode a guess here."),
    }


# ══════════════════════════════════════════════════════════════════════════════
# COLORBLIND-SAFE GLYPH  (fill-ramp square; distinct from edge ● and glove ◆)
# ══════════════════════════════════════════════════════════════════════════════
def pitch_dev_glyph(report: dict) -> str:
    """■ solid = real arsenal · ◧ mixed · □ hollow = mirage ceiling. SQUARE ramp,
    deliberately distinct from edge_confidence's CIRCLE ramp and the glove DIAMOND
    so three lenses never read as one signal. '' on fail-loud."""
    if not report or not report.get('ok'):
        return ''
    share = _num(report.get('mirage_share'))
    if share <= 0.10:
        return '■'
    if share <= 0.50:
        return '◧'
    return '□'


def mirage_flag(report: dict) -> str:
    """One-word board flag. 'MIRAGE' when the projected ceiling is majority-mirage
    AND there is little real upside underneath — the arm to distrust. '' otherwise."""
    if not report or not report.get('ok'):
        return ''
    if report.get('n_mirage', 0) >= 2 and report.get('n_real', 0) == 0:
        return 'MIRAGE'          # ceiling rests entirely on ≥2 mirage pitches
    if _num(report.get('mirage_share')) >= 0.67:
        return 'mirage?'         # majority mirage but has some real pitch
    return ''


# ── one-call convenience for build_board (keeps the draft.py hook to ~3 lines) ─
def annotate(row: dict, *, is_pit: bool) -> dict:
    """Full pitch-development bundle for one prospect. Batters → all-blank (this
    lens is pitcher-only). Returns keys to spread into the board row dict:
      {pdev_ok, pdev_reason, pdev_real, pdev_mirage, pdev_share, pdev_reliability,
       pdev_glyph, pdev_flag}"""
    if not is_pit:
        return {'pdev_ok': None, 'pdev_reason': 'batter (n/a)', 'pdev_real': '',
                'pdev_mirage': '', 'pdev_share': '', 'pdev_reliability': None,
                'pdev_glyph': '', 'pdev_flag': ''}
    rep = pitch_dev_report(row)
    return {
        'pdev_ok':          rep.get('ok', False),
        'pdev_reason':      rep.get('reason', ''),
        'pdev_real':        rep.get('n_real', '') if rep.get('ok') else '',
        'pdev_mirage':      rep.get('n_mirage', '') if rep.get('ok') else '',
        'pdev_share':       rep.get('mirage_share', '') if rep.get('ok') else '',
        'pdev_reliability': pitch_dev_reliability(rep),
        'pdev_glyph':       pitch_dev_glyph(rep),
        'pdev_flag':        mirage_flag(rep),
    }
