"""
OOTP 27 Suite — Roster Construction (shared primitive layer)
============================================================
The cross-cutting roster-construction layer. It DEFINES TEAM-NEED ONCE and owns the
reserve keep/cut allocator, so Draft / Lineups / My Team / Development all CONSUME
the same definitions instead of each re-deriving them (the duplication this
extraction exists to prevent — see the "Roster Construction extraction" open item
and dev handoff in Log A21).

Pure logic only — no Streamlit. The thin renderer lives in `roster_construction_ui`.
Imports only from `acquisitions` (F1 / TV / F2 / position taxonomy) and `db`
(service-time helpers) — the same dependencies the old `reserve_roster.py` had.

Contents
--------
  • Team-need primitive   — detect_needs_and_surplus(roster_table, mode)
  • Reserve keep/cut       — allocate_reserve(...), player_value(...), classify(...)
  • Phase caps / mode tilt / classification thresholds (Jeff's AC rules)

History: this module absorbs the former `reserve_roster.py` (Layer-3 keep/cut) and
the team-need detector that used to live in `my_team.py`. `reserve_roster.py` is now
a thin compatibility shim re-exporting from here.
"""

import pandas as pd

from db import compute_control_window, compute_arb_status
from acquisitions import (
    _s, batter_f1, pitcher_f1, trade_value, f2_war, window_war,
    BATTER_POSITIONS, PITCHER_POSITIONS,
)

# ══════════════════════════════════════════════════════════════════════════════
# TEAM-NEED PRIMITIVE  (single source of truth — was my_team.detect_needs_and_surplus)
# ══════════════════════════════════════════════════════════════════════════════
#
# Need:    best-F1 player at the position is below a mode-specific floor (or no one
#          plays it — every position needs a starter).
# Surplus: ≥ 2 quality bodies (F1 ≥ floor) AND a real starter (best F1 ≥ best-floor).
#          Surplus is position-players only — on a 25-man you need exactly 6 SP + 5
#          RP, so "extra" pitching is depth, not surplus (CL folds into RP).

# Best-F1 at a position must clear this floor to NOT be flagged a need.
NEED_FLOORS = {
    'Competing':  2.0,
    'Sustaining': 1.5,
    'Rebuilding': 1.0,
}

SURPLUS_QUALITY_FLOOR = 3.0   # bodies at the position must clear this F1
SURPLUS_BEST_FLOOR    = 4.0   # AND the best at the position must clear this
SURPLUS_MIN_COUNT     = 2


def detect_needs_and_surplus(roster_table: 'pd.DataFrame',
                             mode: str) -> tuple[list, list]:
    """
    Auto-detect need / surplus positions from a built roster TABLE (the frame
    `my_team.build_roster_table` produces — one row per player with 'POS' and
    'F1' columns). Returns (needs, surplus), both sorted alphabetically.

    This is the ONE definition of team-need. Draft (board Need tag), Acquisitions
    (Fit scoring auto-fill), My Team (Auto-Config), and the Roster Construction
    section all read it from here.
    """
    if roster_table is None or roster_table.empty:
        return [], []

    need_floor = NEED_FLOORS.get(mode, NEED_FLOORS['Competing'])
    needs, surplus = [], []

    all_positions = list(BATTER_POSITIONS) + ['SP', 'RP']  # CL folds into RP

    for pos in all_positions:
        if pos == 'RP':
            at_pos = roster_table[roster_table['POS'].isin(['RP', 'CL'])]
        else:
            at_pos = roster_table[roster_table['POS'] == pos]

        if at_pos.empty:
            needs.append(pos)            # nobody here → a need
            continue

        best_f1 = at_pos['F1'].max()
        quality_count = (at_pos['F1'] >= SURPLUS_QUALITY_FLOOR).sum()

        if best_f1 < need_floor:
            needs.append(pos)

        if pos in ('SP', 'RP'):          # pitching depth ≠ surplus
            continue
        if quality_count >= SURPLUS_MIN_COUNT and best_f1 >= SURPLUS_BEST_FLOOR:
            surplus.append(pos)

    return sorted(needs), sorted(surplus)


def need_set(roster_table: 'pd.DataFrame', mode: str) -> set:
    """Convenience: just the set of need positions (Draft board uses this)."""
    needs, _ = detect_needs_and_surplus(roster_table, mode)
    return set(needs)


# ══════════════════════════════════════════════════════════════════════════════
# RESERVE KEEP/CUT — Layer-3 allocator  (was reserve_roster.py)
# ══════════════════════════════════════════════════════════════════════════════
#
# Jeff runs NO minor leagues — a reserve roster + 40-man. Every developing prospect
# occupies a scarce seat a backup/swingman could hold. This ranks the claimants for
# reserve seats and recommends keep/cut BY MODE.
#
# Consumes (no re-derivation):
#   • Layer-1 weighted_gaps (passed in as growth_total)   — developmental upside
#   • present value (batter_f1 / pitcher_f1)               — current WAR
#   • future value (f2_war → window_war)                   — capturable future WAR
#   • trade value (trade_value)                            — chip lens
#   • service clock (compute_control_window / arb)         — control + cost

# Phase presets: (active_cap, reserve_cap, protect_newest_picks).
# reserve_cap None = effectively uncapped for that phase (no forced cuts).
PHASE_PRESETS = {
    'Opening Day':   {'active': 25,   'reserve': 15,   'protect': False},
    'September':     {'active': 40,   'reserve': None, 'protect': False},
    'Aug 31 – EOS':  {'active': 25,   'reserve': 15,   'protect': True},
    'Offseason':     {'active': None, 'reserve': 15,   'protect': True},
    'Spring':        {'active': 40,   'reserve': 60,   'protect': True},
}

# Mode-tilt weights over the three value lenses (each lens min-max normalized to
# [0,1] across the reserve pool first, so weights are pure relative priority).
MODE_WEIGHTS = {
    'Rebuilding': {'now': 0.20, 'later': 0.65, 'chip': 0.15},
    'Competing':  {'now': 0.55, 'later': 0.20, 'chip': 0.25},
    'Sustaining': {'now': 0.40, 'later': 0.40, 'chip': 0.20},
}

# Classification thresholds (editable — Jeff tunes these in testing).
CLASS_DEFAULTS = {
    'prospect_age_max':     24,    # ≤ this age to qualify as a prospect
    'prospect_service_max': 1.0,   # < this ML service-year count
    'prospect_growth_min':  0.50,  # Layer-1 ΣweightedGap above this = real upside
    'borderline_f1_min':    2.0,   # present F1 at/above this = near the active margin
    'borderline_tv_min':    8.0,   # trade value at/above this = a real chip
}

RESERVE_DEFAULTS = {
    'phase':              'Opening Day',
    'active_cap':         25,
    'reserve_cap':        15,
    'protect_picks':      False,
    'mode_weights':       None,        # None → use MODE_WEIGHTS[mode]
    'class':              dict(CLASS_DEFAULTS),
    'current_draft_year': None,        # None → infer max(Draft) on the roster
}

# Premium up-the-middle positions where losing all reserve cover is a real risk.
PREMIUM_BACKUP_POS = ['C', 'SS', 'CF', '2B']


def _present_f1(row, pos: str) -> float:
    if pos in PITCHER_POSITIONS:
        return pitcher_f1(row)
    if pos in BATTER_POSITIONS:
        return batter_f1(row)
    return 0.0


def _service_years(row) -> float:
    return _s(row.get('ML_YRS', 0)) + _s(row.get('ML_DAYS', 0)) / 76.0


def player_value(row, growth_total: float) -> dict:
    """Three value lenses + raw context for one player. Units differ (the caller
    normalizes before blending); kept separate so the card can show them.

    This is the canonical 'value of a roster player' primitive — present WAR (now),
    capturable future WAR (later), and trade value (chip)."""
    pos = str(row.get('POS', ''))
    age = _s(row.get('AGE', row.get('Age', 0)))
    f1 = _present_f1(row, pos)
    control = compute_control_window(_s(row.get('YEARS_LEFT', 0)),
                                     _s(row.get('ML_YRS', 0)),
                                     _s(row.get('ML_DAYS', 0)))
    tv = trade_value(f1, control, pos) if pos else 0.0
    later = window_war(f2_war(row), age)        # capturable future WAR
    return {
        'pos': pos, 'age': int(age), 'service': round(_service_years(row), 2),
        'arb': compute_arb_status(_s(row.get('ML_YRS', 0)), _s(row.get('ML_DAYS', 0))),
        'control': round(control, 1),
        'now': round(f1, 2),               # present annual WAR
        'later': round(later, 2),          # capturable future WAR
        'chip': round(tv, 1),              # trade value
        'growth': round(growth_total, 2),  # Layer-1 ΣweightedGap (consumed)
    }


def classify(val: dict, cls: dict) -> str:
    """prospect | borderline | backup — informational + drives reasons."""
    if (val['age'] <= cls['prospect_age_max']
            and val['service'] < cls['prospect_service_max']
            and val['growth'] >= cls['prospect_growth_min']):
        return 'prospect'
    if val['now'] >= cls['borderline_f1_min'] or val['chip'] >= cls['borderline_tv_min']:
        return 'borderline'
    return 'backup'


def _minmax(vals: list) -> dict:
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return {'lo': lo, 'span': span}


def allocate_reserve(reserve_rows: list, growth_by_name: dict, mode: str,
                     cfg: dict) -> dict:
    """
    reserve_rows  — list of row dicts (your team's IS_ACTIVE=No players).
    growth_by_name— {name: Layer-1 ΣweightedGap} (consumed, not re-derived).
    mode          — 'Rebuilding' | 'Competing' | 'Sustaining'.
    cfg           — the 'reserve' sub-dict of development_state.

    Returns {records[], reserve_cap, protected[], n_keep, n_cut, draft_year,
             insurance_flags[]}. Each record: name/pos/type/value-lenses/
             keep_score/decision(keep|cut|protected)/reasons[].
    """
    cls = {**CLASS_DEFAULTS, **cfg.get('class', {})}
    weights = cfg.get('mode_weights') or MODE_WEIGHTS.get(mode, MODE_WEIGHTS['Sustaining'])

    # Build per-player value records.
    recs = []
    draft_years = []
    for row in reserve_rows:
        name = str(row.get('Name', ''))
        pos = str(row.get('POS', ''))
        if pos not in BATTER_POSITIONS and pos not in PITCHER_POSITIONS:
            continue
        val = player_value(row, growth_by_name.get(name, 0.0))
        dy = _s(row.get('Draft', 0))
        if dy:
            draft_years.append(int(dy))
        recs.append({
            'name': name, **val, 'draft_year': int(dy) if dy else None,
            'type': classify(val, cls),
        })

    if not recs:
        return {'records': [], 'reserve_cap': cfg.get('reserve_cap'),
                'protected': [], 'n_keep': 0, 'n_cut': 0, 'draft_year': None,
                'insurance_flags': []}

    # Normalize the three lenses across the pool, then mode-tilt into keep_score.
    nm = {k: _minmax([r[k] for r in recs]) for k in ('now', 'later', 'chip')}
    for r in recs:
        norm = {k: (r[k] - nm[k]['lo']) / nm[k]['span'] for k in nm}
        r['keep_score'] = round(weights['now'] * norm['now']
                                + weights['later'] * norm['later']
                                + weights['chip'] * norm['chip'], 4)

    # Newest draft picks (protected when the phase says so).
    draft_year = (cfg.get('current_draft_year')
                  or (max(draft_years) if draft_years else None))
    protect = cfg.get('protect_picks', False)
    protected = ([r['name'] for r in recs if r['draft_year'] == draft_year]
                 if (protect and draft_year is not None) else [])

    # Rank and apply the seat cap.
    recs.sort(key=lambda r: r['keep_score'], reverse=True)
    cap = cfg.get('reserve_cap')
    prot_set = set(protected)
    if cap is None:                       # uncapped phase — keep everyone
        for r in recs:
            r['decision'] = 'protected' if r['name'] in prot_set else 'keep'
    else:
        slots = max(0, cap - len(prot_set))
        kept = 0
        for r in recs:
            if r['name'] in prot_set:
                r['decision'] = 'protected'
            elif kept < slots:
                r['decision'] = 'keep'; kept += 1
            else:
                r['decision'] = 'cut'

    # Reasons per record.
    for r in recs:
        why = []
        if r['decision'] == 'protected':
            why.append(f"newest-draft-pick grace ({draft_year})")
        why.append({'prospect': "prospect: future value (defensive clock decays, A19)",
                    'borderline': "borderline: present value / trade chip",
                    'backup': "backup: present insurance"}[r['type']])
        if r['decision'] == 'cut':
            why.append("below the reserve cap on mode-tilted value")
        r['reasons'] = why

    kept_recs = [r for r in recs if r['decision'] in ('keep', 'protected')]
    n_keep = len(kept_recs)
    n_cut = sum(1 for r in recs if r['decision'] == 'cut')

    # Positional-insurance guard: a premium position you'd be left without any
    # kept reserve cover for (the assignment-flavored constraint).
    kept_pos = {r['pos'] for r in kept_recs}
    cut_pos = {r['pos'] for r in recs if r['decision'] == 'cut'}
    flags = [f"Cutting leaves no reserve cover at {p}"
             for p in PREMIUM_BACKUP_POS if p in cut_pos and p not in kept_pos]

    return {'records': recs, 'reserve_cap': cap, 'protected': protected,
            'n_keep': n_keep, 'n_cut': n_cut, 'draft_year': draft_year,
            'insurance_flags': flags}
