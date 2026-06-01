"""
OOTP 27 Suite — Park Fit Δ (hitter), display-only value lens
=============================================================
Registry A22 (hitter) / A23 (pitcher NULL). Pure logic, no Streamlit — portable
and unit-testable like `roster_construction.py` / the old `reserve_roster.py`.

WHAT IT IS
----------
A22 found that an HR-1.30 home park RE-WEIGHTS hitter value on RAW run production.
The engine's WAR is ~park-neutral for power, so the home-park premium is *exactly
what neutral WAR strips out* — that gap is the arbitrage. This module surfaces that
premium as an ADDITIVE side lens beside neutral Career/Projected WAR.

DISCIPLINE (methodology #6 — additive only)
-------------------------------------------
  • NEVER folds into F1 / F2.
  • NEVER reorders the BPA / neutral-WAR rank — default sort stays neutral WAR.
  • Rendered as a side column; the GAP is the signal.

PITCHER SIDE = NULL (A23)
-------------------------
There is deliberately no pitcher coefficient, no pitcher Park Fit Δ, no pitcher
column. `park_fit_delta` is hitter-only; `attach_park_fit_column` writes a blank
cell for pitchers. Do NOT add a pitcher path here.

PARK-PARAMETERIZED FROM DAY ONE
-------------------------------
`park_fit_delta(row, park_profile)` — `park_profile` carries the park's factors.
Today exactly ONE profile is calibrated: Jeff's park (HR 1.30 / AVG 0.98 / 2B 0.95
/ 3B 0.90). Any other profile FAILS LOUD (`ok=False`, visible reason). We never
silently reuse this park's numbers for a different park, and we NEVER extrapolate
by negating coefficients — the re-weight is asymmetric (a 0.7 park is NOT the
mirror of a 1.30 park; A22/A23 OFAT future-study note). New parks are added by
running the OFAT study and APPENDING a row to CALIBRATED_PROFILES — not by editing
the formula.

CONFIDENCE
----------
  SPE — LOCKED (the demotion is the robust finding)
  POW — PROVISIONAL / DISPLAY-ONLY (concave premium; the +1.97 POW-75 tail was
        placebo-falsified, so it is NOT hardcoded as a hard tail)
  GAP / 2B / 3B — DROPPED / not used
"""

import math

# ── Number coercion (kept local so the formula core is testable without pulling
#    in acquisitions/streamlit). Mirrors acquisitions._s behaviour.
def _num(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _present(row, col) -> bool:
    """A column is usable for one row iff the key exists and the value coerces to
    a real number. (Pool-level fail-loud lives in park_fit_columns_ok.)"""
    if col not in row:
        return False
    v = row.get(col)
    if v is None:
        return False
    try:
        return not math.isnan(float(v))
    except (TypeError, ValueError):
        return False


# ══════════════════════════════════════════════════════════════════════════════
# CALIBRATED PROFILES  (A22 — coefficients are INPUTS, not magic numbers)
# ══════════════════════════════════════════════════════════════════════════════
#
# The future OFAT parametric study (Log A22/A23 "FUTURE STUDY") just APPENDS rows
# here — one calibrated profile per park it characterizes. The matcher below keys
# on the (HR, AVG, 2B, 3B) factor tuple; an un-matched profile fails loud.
#
# runs = intercept
#      + pow_lin * (POW - pow_center)
#      + pow_sq  * (POW - pow_center)**2
#      + spe_lin * (SPE - spe_center)
# Park Fit Δ WAR = runs / rpw * (PA / 650)
#
# rpw = runs-per-win. 10.3 is a CONVENTIONAL constant (NOT a dead-ball-era estimate
# — A22). Premium WAR scales inversely with it.

_FACTOR_KEYS = ('HR', 'AVG', '2B', '3B')
_MATCH_TOL = 0.005   # park factors are ~2-decimal; tolerance absorbs float repr

CALIBRATED_PROFILES = [
    {
        'name': "Jeff's park (HR 1.30)",
        # The exact bundled profile A22 was fit on. Match is on this tuple.
        'factors': {'HR': 1.30, 'AVG': 0.98, '2B': 0.95, '3B': 0.90},
        'coeffs': {
            'intercept':  2.283,
            'pow_lin':    0.2509,    # POW — PROVISIONAL / DISPLAY-ONLY
            'pow_sq':    -0.00782,   # POW concave (peaks ~POW 62); PROVISIONAL
            'pow_center': 45.0,
            'spe_lin':   -0.2188,    # SPE — LOCKED (demotion; ≈ -0.0212 WAR/650/pt)
            'spe_center': 51.0,
        },
        'rpw': 10.3,
        'confidence': {
            'SPE': 'LOCKED',
            'POW': 'PROVISIONAL / DISPLAY-ONLY',
            'GAP': 'DROPPED / not used',
            '2B':  'DROPPED / not used',
            '3B':  'DROPPED / not used',
        },
        'source': 'Log A22 (May 31, 2026)',
    },
]


def list_calibrated_profiles() -> list:
    """Human-readable summary of every calibrated profile (for UI / debugging)."""
    return [{'name': p['name'], 'factors': dict(p['factors']),
             'rpw': p['rpw'], 'source': p['source']} for p in CALIBRATED_PROFILES]


def match_profile(park_profile: dict) -> dict | None:
    """Return the calibrated entry whose factor tuple matches `park_profile`
    within tolerance, else None. Missing keys never match (→ fail loud)."""
    if not park_profile:
        return None
    for entry in CALIBRATED_PROFILES:
        f = entry['factors']
        if all(k in park_profile and park_profile.get(k) is not None
               and abs(_num(park_profile.get(k)) - f[k]) <= _MATCH_TOL
               for k in _FACTOR_KEYS):
            return entry
    return None


def profile_from_team_config(tc: dict) -> dict:
    """Map Team Config park factors → the canonical {HR, AVG, 2B, 3B} profile.

    Team Config stores HR split by handedness (park_hr_l / park_hr_r); A22 has no
    handedness term (GAP/2B/3B dropped, no L/R split), so we collapse HR to the
    mean. For Jeff's symmetric 1.30/1.30 park this is exactly 1.30. The collapse is
    a known simplification, surfaced via the confidence labels — not a silent one.
    """
    hr_l = _num(tc.get('park_hr_l', tc.get('HR_L', 1.0)), 1.0)
    hr_r = _num(tc.get('park_hr_r', tc.get('HR_R', 1.0)), 1.0)
    return {
        'HR':  round((hr_l + hr_r) / 2.0, 3),
        'AVG': round(_num(tc.get('park_avg', tc.get('AVG', 1.0)), 1.0), 3),
        '2B':  round(_num(tc.get('park_2b', tc.get('2B', 1.0)), 1.0), 3),
        '3B':  round(_num(tc.get('park_3b', tc.get('3B', 1.0)), 1.0), 3),
        '_hr_l': round(hr_l, 3), '_hr_r': round(hr_r, 3),   # kept for display only
    }


# ══════════════════════════════════════════════════════════════════════════════
# CORE — hitter Park Fit Δ
# ══════════════════════════════════════════════════════════════════════════════

_REQUIRED_COLS = ('PA', 'POW', 'SPE')


def park_fit_columns_ok(df) -> tuple[bool, list]:
    """Pool-level fail-loud audit. Returns (ok, missing_columns). Call this once
    before rendering a Park Fit Δ column so a missing dependency surfaces loudly
    instead of as a silent-zero column."""
    cols = set(getattr(df, 'columns', []))
    missing = [c for c in _REQUIRED_COLS if c not in cols]
    return (len(missing) == 0, missing)


def park_fit_delta(row: dict, park_profile: dict) -> dict:
    """Hitter Park Fit Δ for one player-row at the given park profile.

    SUCCESS  → {'ok': True, 'delta_war', 'runs', 'pa', 'pow', 'spe',
                'profile', 'confidence', 'note'}
    FAIL-LOUD→ {'ok': False, 'delta_war': None, 'error', ...}  (never silent-zero,
               never this-park's-numbers-for-another-park)

    Hitter-only. For pitchers (A23 NULL) the caller must not render a value — see
    `attach_park_fit_column`, which blanks pitcher rows.
    """
    entry = match_profile(park_profile)
    if entry is None:
        req = {k: (park_profile.get(k) if park_profile else None) for k in _FACTOR_KEYS}
        return {
            'ok': False, 'delta_war': None,
            'error': "no calibrated coefficients for this park profile",
            'profile_requested': req,
            'detail': ("A22 coefficients are calibrated for HR 1.30 / AVG 0.98 / "
                       "2B 0.95 / 3B 0.90 only. The re-weight is asymmetric — a 0.7 "
                       "park is NOT the mirror of a 1.30 park, so negating the "
                       "coefficients is invalid. Run the OFAT study and APPEND a "
                       "row to CALIBRATED_PROFILES to support this park."),
        }

    missing = [c for c in _REQUIRED_COLS if not _present(row, c)]
    if missing:
        return {
            'ok': False, 'delta_war': None,
            'error': "missing load-bearing column(s): " + ", ".join(missing),
            'profile': entry['name'],
        }

    c = entry['coeffs']
    pow_ = _num(row.get('POW'))
    spe = _num(row.get('SPE'))
    pa = _num(row.get('PA'))
    dpow = pow_ - c['pow_center']
    runs = (c['intercept']
            + c['pow_lin'] * dpow
            + c['pow_sq'] * dpow * dpow
            + c['spe_lin'] * (spe - c['spe_center']))
    delta_war = runs / entry['rpw'] * (pa / 650.0)
    return {
        'ok': True,
        'delta_war': round(delta_war, 2),
        'runs': round(runs, 2),
        'pa': pa, 'pow': int(pow_), 'spe': int(spe),
        'profile': entry['name'],
        'confidence': entry['confidence'],
        'note': "display-only; additive beside neutral WAR; never reorders rank (A22)",
    }


# Columns the per-650 RATE needs (PA is irrelevant — it's normalized to 650).
_RATE_COLS = ('POW', 'SPE')


def park_fit_rate_columns_ok(df) -> tuple[bool, list]:
    """Pool-level fail-loud audit for the per-650 RATE view (POW/SPE only)."""
    cols = set(getattr(df, 'columns', []))
    missing = [c for c in _RATE_COLS if c not in cols]
    return (len(missing) == 0, missing)


def park_fit_rate(row: dict, park_profile: dict) -> dict:
    """Hitter Park Fit Δ as a **full-season (per-650-PA) RATE** — the pure
    profile-fit signal, independent of how much the player has actually played.

    This is the number that answers "who fits the park best" (a who-should-play
    decision). It is `park_fit_delta` with PA forced to 650, so the `× PA/650`
    volume term drops out and only the `runs/rpw` profile term remains. Use this
    everywhere a roster-fit / draft-fit comparison is wanted (Draft, My Team,
    Acquisitions). The PA-weighted `park_fit_delta` is only for "total park WAR
    realized at current usage" — a reporting figure, not a decision one.

    Same return shape and fail-loud behaviour as `park_fit_delta`; needs only
    POW/SPE (PA is irrelevant). Hitter-only; pitcher gating is the caller's job
    (A23 NULL)."""
    r = dict(row)
    r['PA'] = 650
    return park_fit_delta(r, park_profile)

def attach_park_fit_column(df, park_profile: dict, *,
                           pos_col: str = 'POS',
                           src_df=None,
                           col_name: str = 'Park Fit Δ'):
    """Return (df_with_column, status) — a THIN wiring helper for Draft / My Team /
    Acquisitions roster-fit views.

    The column is purely ADDITIVE: it is appended, never used to sort. Callers keep
    their existing default sort (neutral WAR / BPA). The GAP between neutral WAR and
    Park Fit Δ is the signal.

    Behaviour:
      • Un-calibrated park profile → returns df UNCHANGED + status describing the
        fail-loud reason (so the UI shows a notice, not a bogus column).
      • Missing PA/POW/SPE in the data → df UNCHANGED + status listing the missing
        columns (never a silent-zero column).
      • Pitcher rows → blank cell (A23 NULL).

    `src_df`: optional source frame to pull PA/POW/SPE from when `df` is a display
    table that doesn't carry them (matched by row order; must align with `df`).
    """
    status = {'ok': False, 'reason': '', 'profile': None,
              'confidence': None, 'col_name': col_name}

    # Profile gate (fail loud).
    entry = match_profile(park_profile)
    if entry is None:
        req = {k: (park_profile.get(k) if park_profile else None) for k in _FACTOR_KEYS}
        status['reason'] = ("No calibrated Park Fit Δ coefficients for this park "
                            f"profile {req}. A22 covers HR 1.30 / AVG 0.98 / 2B 0.95 "
                            "/ 3B 0.90 only; coefficients are not extrapolated.")
        return df, status

    status.update({'profile': entry['name'], 'confidence': entry['confidence']})

    if df is None or len(df) == 0:
        status['reason'] = "empty table"
        return df, status

    # Where do PA/POW/SPE come from?
    feed = src_df if src_df is not None else df
    ok, missing = park_fit_columns_ok(feed)
    if not ok:
        status['reason'] = ("Park Fit Δ needs " + ", ".join(_REQUIRED_COLS)
                            + "; missing: " + ", ".join(missing)
                            + ". Column withheld (no silent-zero).")
        return df, status

    # Lazy import of the position taxonomy (single source of truth in acquisitions)
    # so the formula core above stays importable without acquisitions/streamlit.
    try:
        from acquisitions import BATTER_POSITIONS, PITCHER_POSITIONS
    except Exception:
        BATTER_POSITIONS = {'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'}
        PITCHER_POSITIONS = {'SP', 'RP', 'CL'}

    out = df.copy()
    feed_records = feed.to_dict('records')
    vals = []
    for i in range(len(out)):
        frow = feed_records[i] if i < len(feed_records) else {}
        pos = str(frow.get(pos_col, out.iloc[i].get(pos_col, '') if pos_col in out.columns else ''))
        if pos in PITCHER_POSITIONS or pos not in BATTER_POSITIONS:
            vals.append(None)          # A23 NULL for pitchers; blank for unknown
            continue
        res = park_fit_delta(frow, park_profile)
        vals.append(res['delta_war'] if res['ok'] else None)

    out[col_name] = vals
    status['ok'] = True
    status['reason'] = (f"Park Fit Δ ({entry['name']}) — additive, hitters only; "
                        "does not reorder the table.")
    return out, status
