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

from db import compute_control_window, compute_arb_status, service_years as _svc_years
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
# BATTERS are scored on F1 (rating-based present WAR — reliable without stats).
NEED_FLOORS = {
    'Competing':  2.0,
    'Sustaining': 1.5,
    'Rebuilding': 1.0,
}

# PITCHERS are scored on F2 (rating-based projected WAR), NOT F1: pitcher F1 is
# innings-driven and collapses negative at 0 IP (fresh-season / bench arms), which
# would falsely flag every pitching slot as a need. F2 is stats-independent and
# clamped to [0, 9]. Floors are set on the F2 quality scale (scrub 0 · avg ~1.5 ·
# solid ~2.2 · frontline ~3.2 · ace ~3.8) so "is SP/RP a need" asks a real
# arm-quality question regardless of how many innings have been thrown.
PITCHER_NEED_FLOORS = {
    'Competing':  2.2,   # below a "solid" arm
    'Sustaining': 1.8,
    'Rebuilding': 1.5,   # below ~average
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
    pit_floor = PITCHER_NEED_FLOORS.get(mode, PITCHER_NEED_FLOORS['Competing'])
    has_f2 = 'F2' in roster_table.columns
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

        is_pitcher = pos in ('SP', 'RP')

        # Pitchers: score on F2 (rating-based, IP-independent) against the pitcher
        # floor. Position players: score on F1 against the batter floor. Fall back
        # to F1 for pitchers only if the table predates the F2 column.
        if is_pitcher and has_f2:
            best = at_pos['F2'].max()
            floor = pit_floor
        else:
            best = at_pos['F1'].max()
            floor = need_floor

        if best < floor:
            needs.append(pos)

        if is_pitcher:                   # pitching depth ≠ surplus
            continue
        quality_count = (at_pos['F1'] >= SURPLUS_QUALITY_FLOOR).sum()
        if quality_count >= SURPLUS_MIN_COUNT and at_pos['F1'].max() >= SURPLUS_BEST_FLOOR:
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
    'max_proactive_trades': 4,         # rolling cap on rebuild aging-vet sells
}

# Premium up-the-middle positions where losing all reserve cover is a real risk.
PREMIUM_BACKUP_POS = ['C', 'SS', 'CF', '2B']


# Minimum innings for the IP-driven pitcher F1 to be meaningful. Below this the
# present-WAR formula's large negative intercept dominates (no innings to offset
# it) and reads spuriously negative, so we fall back to the rating-based estimate.
_MIN_IP_FOR_F1 = 20.0


def _present_f1(row, pos: str) -> float:
    if pos in PITCHER_POSITIONS:
        ip = _s(row.get('IP', 0))
        if ip >= _MIN_IP_FOR_F1:
            return pitcher_f1(row)        # real present WAR from accumulated innings
        # No meaningful innings → IP-based F1 is unreliable (negative). The
        # rating-based projection is the best available present-ability estimate.
        return f2_war(row)
    if pos in BATTER_POSITIONS:
        return batter_f1(row)
    return 0.0


def _service_years(row) -> float:
    return _svc_years(_s(row.get('ML_YRS', 0)), _s(row.get('ML_DAYS', 0)))


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

# ══════════════════════════════════════════════════════════════════════════════
# WHOLE-ROSTER KEEP / PROMOTE / TRADE / CUT  (the decision board)
# ══════════════════════════════════════════════════════════════════════════════
#
# The reserve allocator above ranks ONLY the reserve pool — it takes your current
# active/reserve split as fixed. That answers "trim the reserve tail" but NOT the
# decisions Jeff actually makes: who to PROMOTE (reserve → active) and who to CUT
# when the roster squeezes (Opening Day cut-down, since draftees are held until the
# next April). This allocator ranks the WHOLE roster and lets the cap line fall
# where it falls — active/reserve is an OUTPUT (a column), never the filter.
#
# Verdicts:
#   PROMOTE    reserve player who'd crack the active top-N on present WAR (F1)
#   HOLD-DOWN  rebuild-mode advisory: a promote-worthy young prospect under the
#              service clock — promoting starts his FA countdown; consider banking
#              the control year. (Advisory only — Jeff decides.)
#   KEEP       above the keep line; stays
#   TRADE      below the keep line but cheap + controllable + real WAR → sell, don't
#              release (chip value)
#   CUT        below the keep line, low trade value → release for nothing
#
# Salary: the league budget is a SOFT ceiling. Under budget → salary is only a
# tiebreaker (younger + cheaper wins between near-equals). Over budget → expensive,
# low-WAR players are surfaced as cut/trade priorities to get back under.

# A reserve player promotes if his present F1 would place him in the active top-N.
# HOLD-DOWN advisory: rebuild + under this service-year line + real future value.
HOLD_DOWN_SERVICE_MAX = 1.0      # < 1 full ML service year (pre-clock-burn)
HOLD_DOWN_FUTURE_MIN  = 1.5      # capturable future WAR worth protecting a year for
TRADE_CHIP_MIN        = 8.0      # trade value at/above this = a real chip (sell)
TRADE_NOW_MIN         = 0.5      # ...with at least this present WAR to be sellable

# Rebuild aging-vet sell rule: a genuinely useful player who is old and near the
# end of team control is win-now value a rebuild doesn't need — sell him for
# prospects rather than hold (KEEP) or release (CUT).
REBUILD_VET_AGE_MIN     = 30     # "aging"
REBUILD_VET_CONTROL_MAX = 2.0    # "short control" — ≤2 yrs to FA
REBUILD_VET_NOW_MIN     = 1.5    # "genuinely useful" present WAR worth selling


def _eff_active_cap(phase_cfg: dict) -> int | None:
    """Active cap for the phase (the cut-down target). None → uncapped phase."""
    return phase_cfg.get('active')


def allocate_roster(roster_rows: list, growth_by_name: dict, mode: str,
                    phase: str, active_flag_by_name: dict,
                    budget: float = 0.0, payroll_by_name: dict = None,
                    max_proactive_trades: int = 4) -> dict:
    """
    Rank the WHOLE roster and assign keep/promote/trade/cut/hold-down.

    roster_rows        — list of row dicts (the entire team: active + reserve).
    growth_by_name     — {name: Layer-1 ΣweightedGap} (future-upside, consumed).
    mode               — 'Rebuilding' | 'Competing' | 'Sustaining'.
    phase              — a key of PHASE_PRESETS (sets the active cap = cut target).
    active_flag_by_name— {name: bool} current active status (shown, not used as a
                         filter). Drives PROMOTE/DEMOTE labelling vs. the optimal 25.
    budget             — team salary ceiling (0 = unset → salary is soft tiebreaker).
    payroll_by_name    — {name: salary} for the budget check.
    max_proactive_trades — cap on PROACTIVE rebuild aging-vet sells (you can only
                         absorb so many returns per window). Ranked by trade value,
                         best first; vets beyond the cap revert to KEEP. Rolling:
                         re-run after a trade and the next vet surfaces. Does NOT
                         limit FORCED over-cap moves (those clear seats, not add).

    Returns {records[], active_cap, n_promote, n_keep, n_trade, n_cut, n_hold,
             over_budget, payroll, budget, mode, phase}.
    """
    payroll_by_name = payroll_by_name or {}
    weights = MODE_WEIGHTS.get(mode, MODE_WEIGHTS['Sustaining'])
    phase_cfg = PHASE_PRESETS.get(phase, PHASE_PRESETS['Opening Day'])
    active_cap = _eff_active_cap(phase_cfg)

    # ── Build value records for the whole roster ──────────────────────────────
    recs = []
    for row in roster_rows:
        name = str(row.get('Name', ''))
        pos = str(row.get('POS', ''))
        if pos not in BATTER_POSITIONS and pos not in PITCHER_POSITIONS:
            continue
        val = player_value(row, growth_by_name.get(name, 0.0))
        recs.append({
            'name': name, **val,
            'is_active': bool(active_flag_by_name.get(name, False)),
            'salary': int(payroll_by_name.get(name, _s(row.get('SALARY', 0)))),
            'type': classify(val, CLASS_DEFAULTS),
        })

    # Does the export distinguish active vs reserve at all? OOTP 26 has no ACT
    # column, so every flag is False — in that case PROMOTE is meaningless (we
    # can't know who's already up), and the top-N are labeled KEEP, not PROMOTE.
    has_active_flags = any(bool(v) for v in active_flag_by_name.values())

    if not recs:
        return {'records': [], 'active_cap': active_cap, 'n_promote': 0,
                'n_keep': 0, 'n_trade': 0, 'n_cut': 0, 'n_hold': 0,
                'over_budget': False, 'payroll': 0, 'budget': int(budget),
                'mode': mode, 'phase': phase}

    # ── Keep-value: mode-tilted now/later/chip, normalized across the roster ──
    nm = {k: _minmax([r[k] for r in recs]) for k in ('now', 'later', 'chip')}
    for r in recs:
        norm = {k: (r[k] - nm[k]['lo']) / nm[k]['span'] for k in nm}
        base = (weights['now'] * norm['now']
                + weights['later'] * norm['later']
                + weights['chip'] * norm['chip'])
        r['keep_score'] = round(base, 4)

    # ── Tiebreaker: younger + cheaper nudges keep-value up (dollar-per-WAR) ────
    # Small additive nudges so they only separate near-equals, never override WAR.
    ages = [r['age'] for r in recs]
    sals = [r['salary'] for r in recs]
    amm = _minmax(ages); smm = _minmax(sals)
    for r in recs:
        youth = 1.0 - (r['age'] - amm['lo']) / amm['span']        # 1=youngest
        cheap = 1.0 - (r['salary'] - smm['lo']) / smm['span']     # 1=cheapest
        r['tiebreak'] = round(0.05 * youth + 0.05 * cheap, 4)
        r['keep_score'] = round(r['keep_score'] + r['tiebreak'], 4)

    # ── PROMOTE: rank everyone by PRESENT F1; the active-cap top-N is the
    #    optimal active roster. A reserve player in that top-N is a promote;
    #    an active player outside it is a demote candidate. ────────────────────
    by_now = sorted(recs, key=lambda r: r['now'], reverse=True)
    optimal_active = set()
    if active_cap is not None:
        optimal_active = {r['name'] for r in by_now[:active_cap]}
    for r in recs:
        r['in_optimal_active'] = r['name'] in optimal_active

    # ── OPTION A keep/cut ──────────────────────────────────────────────────────
    # Two independent questions:
    #   1. Who PLAYS today  → the present-WAR top-N (in_optimal_active, above).
    #   2. Who we KEEP in the org → ranked by the MODE-TILTED keep_score.
    # CUT is FORCED-ONLY: nobody is released unless the roster is over the cap.
    # When forced, the players cut are the lowest by OVERALL PROJECTION (now+later
    # blend, like the draft board) — raw young fliers are held unless they're the
    # weakest bodies on an over-cap roster.
    recs.sort(key=lambda r: r['keep_score'], reverse=True)
    keep_n = active_cap if active_cap is not None else len(recs)

    over_budget = bool(budget) and sum(r['salary'] for r in recs
                                       if r['is_active']) > budget

    # How many MUST be cut: the overage beyond the cap. 0 → no forced cuts.
    overage = max(0, len(recs) - keep_n) if active_cap is not None else 0

    # First pass: tag aging-vet sells and prospect-holds; default everyone to keep.
    aging_vets = []
    for r in recs:
        is_prospect_hold = (
            mode == 'Rebuilding'
            and r['service'] < HOLD_DOWN_SERVICE_MAX
            and r['later'] >= HOLD_DOWN_FUTURE_MIN
            and not r['is_active']
            and r['in_optimal_active']
        )
        is_aging_vet_sell = (
            mode == 'Rebuilding'
            and r['age'] >= REBUILD_VET_AGE_MIN
            and r['control'] <= REBUILD_VET_CONTROL_MAX
            and r['now'] >= REBUILD_VET_NOW_MIN
        )

        if is_prospect_hold:
            r['decision'] = 'hold-down'
        elif has_active_flags and r['in_optimal_active'] and not r['is_active']:
            r['decision'] = 'promote'
        elif is_aging_vet_sell:
            aging_vets.append(r)               # candidate — capped below
            r['decision'] = 'keep'             # default; promoted to trade if in cap
        else:
            r['decision'] = 'keep'

    # Proactive-trade cap: you can only absorb so many returns per window. Sell the
    # most VALUABLE vets first (highest present WAR — best return); the rest hold.
    # Rolling: trade one, re-export, and the next vet surfaces into the open slot.
    aging_vets.sort(key=lambda r: (r['chip'], r['now']), reverse=True)
    for r in aging_vets[:max(0, int(max_proactive_trades))]:
        r['decision'] = 'trade'
        r['_proactive'] = True

    # Second pass: FORCE moves only if over the cap. The weakest 'keep' bodies by
    # overall projection (now + later) come off — lowest first. A useful player who
    # must come off is a TRADE (sell, don't release); a low-value one is a CUT.
    if overage > 0:
        cut_candidates = [r for r in recs if r['decision'] == 'keep']
        cut_candidates.sort(key=lambda r: (r['now'] + r['later']))   # worst first
        for r in cut_candidates[:overage]:
            useful = (r['now'] >= TRADE_NOW_MIN or r['chip'] >= TRADE_CHIP_MIN
                      or r['later'] >= HOLD_DOWN_FUTURE_MIN)
            r['decision'] = 'trade' if useful else 'cut'
            r['_forced'] = True

    # ── Reasons ───────────────────────────────────────────────────────────────
    for r in recs:
        why = []
        d = r['decision']
        if d == 'promote':
            why.append(f"present WAR ({r['now']}) cracks the active top-{active_cap}")
        elif d == 'hold-down':
            why.append(f"rebuild: {r['service']}yr service, {r['later']} future WAR — "
                       "promoting starts the FA clock; consider banking a control year")
        elif d == 'trade':
            if (mode == 'Rebuilding' and r['age'] >= REBUILD_VET_AGE_MIN
                    and r['control'] <= REBUILD_VET_CONTROL_MAX
                    and r['now'] >= REBUILD_VET_NOW_MIN):
                why.append(f"rebuild sell-high: {r['now']} WAR, age {r['age']}, "
                           f"{r['control']}yr control — cash the vet for prospects")
            else:
                why.append(f"below the keep line but useful (now {r['now']}, "
                           f"TV {r['chip']}) — sell, don't release")
        elif d == 'cut':
            why.append(f"over the cap — forced cut, lowest overall projection "
                       f"(now {r['now']} + later {r['later']})")
        else:
            why.append({'prospect': "future value (defensive clock decays, A19)",
                        'borderline': "present value / trade chip",
                        'backup': "present insurance"}[r['type']])
        if over_budget and r['is_active'] and r['salary'] > 0:
            why.append(f"${r['salary']:,} salary — over budget, weigh $/WAR")
        r['reasons'] = why

    counts = {v: sum(1 for r in recs if r['decision'] == v)
              for v in ('promote', 'keep', 'trade', 'cut', 'hold-down')}
    return {
        'records': recs, 'active_cap': active_cap,
        'n_promote': counts['promote'], 'n_keep': counts['keep'],
        'n_trade': counts['trade'], 'n_cut': counts['cut'],
        'n_hold': counts['hold-down'],
        'over_budget': over_budget,
        'payroll': sum(r['salary'] for r in recs if r['is_active']),
        'budget': int(budget), 'mode': mode, 'phase': phase,
    }
