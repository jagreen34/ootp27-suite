"""
dev_constants.py -- EVERY tunable number in the development/valuation model,
each tagged with the registry finding it came from.

WHY THIS FILE EXISTS: these constants moved four times in two weeks
(A31 -> A45 -> A46 -> A56). If a finding is revised, edit HERE ONLY.
Never inline a magic number anywhere else in the suite.

Registry: OOTP27_Research_Log_v15_42 / Production Spec v15_42 / Eval Guide v8
"""

REGISTRY_VERSION = "v15.42"

# --------------------------------------------------------------------------
# A50 -- INTERNAL (1-600) <-> DISPLAY (20-80) MAP.  Editor-verified, FIXED
# (not pool-relative; A33's pool-relativity is the card bar + 1-100 export).
#
# TWO TABLES, USED IN OPPOSITE DIRECTIONS -- this is the #1 source of error.
#   display -> internal : use MIDPOINTS (best estimate of where he sits)
#   internal -> display : use LOWER BOUNDS (the actual bucket he lands in)
# Using midpoints in both directions under-projects by up to a full grade.
# --------------------------------------------------------------------------
DISPLAY_TO_INTERNAL_MID = {
    20: 75, 25: 173, 30: 222, 35: 273, 40: 325, 45: 368, 50: 397,
    55: 418, 60: 435, 65: 451, 70: 468, 75: 484, 80: 520,
}

INTERNAL_LOWER_BOUNDS = [
    (20, 1), (25, 150), (30, 197), (35, 248), (40, 299), (45, 351),
    (50, 385), (55, 410), (60, 427), (65, 443), (70, 460), (75, 476), (80, 493),
]

# A50 note: bucket 20 spans 149 internal points; buckets above 50 span 16-17.
# ~9x compression at the bottom. A fixed internal gain renders as ~1 grade low
# on the scale and 2-4 grades mid/high. GRADE-VELOCITY != TALENT-VELOCITY.

# --------------------------------------------------------------------------
# A56 -- BATTER AGE BUDGET (internal points still available from a given age).
# Development ACCUMULATES; no lifetime cap, only an age wall.
# Per-season: ~20 at 17-19, peak ~30 at 21, taper by 23, cliff 24-25.
# Owned-from-18 ~156 vs ~88 from 21 (~1.8x).
# SCOPE: TCR=0-derived. The AC runs TCR=100, where A51 finds delivery runs
# HIGHER with ~2x the pop rate -> treat these as a FLOOR, not a forecast.
# --------------------------------------------------------------------------
BATTER_AGE_BUDGET = {
    17: 177, 18: 157, 19: 137, 20: 117, 21: 89,
    22: 59, 23: 31, 24: 11, 25: 3,
}

# A39 -- PITCHER AGE BUDGET (MOV/CON only). Arms DO ramp at 17 (~1/2-2/3
# budget); bats do not. Cliff onset 24-25, MOV spent ~26-27, CTL ~1yr longer.
PITCHER_AGE_BUDGET = {
    17: 118, 18: 157, 19: 137, 20: 117, 21: 89,
    22: 59, 23: 31, 24: 11, 25: 3,
}

# --------------------------------------------------------------------------
# A44 / A53 -- BATTER TOOL VALUE, wRC+ points per 10 rating points.
# A53 resolved the individual-vs-team divergence as a roster-construction
# confound -> USE THIS (the wRC+ ordering) for individual player value.
# NEVER score CON or CON-P: it is a ~50/50 composite of BABIP + AvoidK whose
# halves differ ~2.3x in value. Score HT (BABIP) and K's separately.
# --------------------------------------------------------------------------
BATTER_WEIGHTS = {
    "POW":   6.8,   # #1 on individual wRC+ AND #1 on team wins
    "EYE":   4.9,
    "BABIP": 3.2,   # the one rep-sensitive channel; front-loads, dead by 24
    "GAP":   1.6,
    "AVK":   1.4,   # near-inert; weakest team separator on the board
}

# A48/A53 team-wins weights -- pitcher tools. STU is DERIVED (engine-computed
# from the arsenal): read it, never project or inject it.
PITCHER_WEIGHTS = {"STU": 1.7, "MOV": 1.6, "CON": 1.3}

# Only MOV and CON take the age budget. Pitch grades barely develop (A48).
PITCHER_DEVELOPING_TOOLS = ("MOV", "CON")

# --------------------------------------------------------------------------
# A54 -- COMMAND GATE. Break-even internal ~310-320, which sits in the
# display-40 bucket (299-350), lower third.
#   CON >= 45 : out-pitch HOLDS or grows even full-time -> work him freely
#   CON == 40 : neutral / straddles
#   CON <= 35 : out-pitch BLEEDS 6-13 pts/season under a starter load
# Velocity does NOT moderate this; command carries the whole effect.
# Relief is NOT a preservation lever (erodes as much as starting) and it
# STALLS changeup growth. Manage via command, not role.
# --------------------------------------------------------------------------
COMMAND_GATE = 40
COMMAND_GATE_SAFE = 45

# A41 -- pitch-grade crossover: trust a projected pitch only when the CURRENT
# grade clears the floor. Everything below is a mirage.
PITCH_FLOOR = 40
PITCH_FLOOR_CHANGEUP = 45
PITCH_COLUMNS = ["FB", "CH", "CB", "SL", "SI", "CT", "SP", "FO", "CC", "KN"]

# A48 -- erosion behaviour by pitch, for arms BELOW the command gate.
PITCH_EROSION = {
    "SL": "erodes", "CB": "erodes", "CT": "erodes",   # CT behaves as a breaker
    "SI": "mild",                                      # mildest eroder
    "CH": "grows",                                     # grows with starter reps
    "FB": "flat",
}

# --------------------------------------------------------------------------
# A50 -- DEFENSIVE FLOORS. Gloves are FIXED (no potential field exists);
# current IS truth. Apply these as hard screens, never to projections.
# --------------------------------------------------------------------------
DEFENSIVE_FLOORS = {
    "SS": ("IF RNG", 60),
    "CF": ("OF RNG", 60),
    "C":  ("C ABI", 55),
    "3B": ("IF ARM", 55),
    "2B": ("IF RNG", 50),
}

# --------------------------------------------------------------------------
# PARK -- Quakers home park. HR x1.30 rewards POW; 2B x0.95 / 3B x0.90 taxes
# GAP. NOTE: the K-T multiverse is park-NEUTRAL (all park factors exactly
# 1.000), so BATTER_WEIGHTS are park-blind. This overlay is a judgement
# adjustment, NOT a measured coefficient. Off by default.
# --------------------------------------------------------------------------
PARK_OVERLAY = {"POW": 1.15, "GAP": 0.90}
APPLY_PARK_OVERLAY = False

# A52 -- work ethic: small real accelerant (~15% top-to-bottom, r=+0.072).
# Low WE does NOT gate development (~87% of top band). Tiebreaker, not a cut.
# Baseball IQ (INT) is NULL for development (r=+0.028) -- do not use.
WORK_ETHIC_MULT = {"H": 1.07, "N": 1.00, "L": 0.93}
APPLY_WORK_ETHIC = False   # off by default; effect is inside the noise

# A56 -- development is bimodal (~1/5 pop hard, ~1/5 barely move).
# A projection is the CENTRE of a wide distribution, never a forecast.
BIMODAL_WARNING = True

# ============================================================================
# VALUE-MODEL RETRAIN (Open Items #4/#5, VALUE_MODEL_RETRAIN_HANDOFF.md)
# Replaces off_f1/sp_f1/rp_f1's stale WAR-fit coefficients with a routed
# wRC+ / ERA+ / ZR chain. NO NEW REGRESSION -- BATTER_WEIGHTS/PITCHER_WEIGHTS
# above are already locked (A44/A53 wRC+ weights; A48/A53 team-wins weights).
# This section supplies the RECOMBINATION constants: how a weighted rating
# score becomes a metric-point delta, and how that delta becomes WAR.
# ============================================================================

# Team-wins-per-SD -- LOCKED, team_seasons_all.csv, 4,200 team-seasons,
# joint standardized model R^2=0.754. Offense and run-prevention are within
# 3% of each other; carry both ERA+ (team construction) and FIP- (individual
# acquisition -- an arm won't bring his old defense with him).
WINS_PER_SD = {"wRC+": 5.84, "ERA+": 5.69, "ZR": 0.76}

# Team-level SD of each target metric -- team_seasons_all.csv, n=4,200.
TEAM_SD = {"wRC+": 8.60, "ERA+": 9.96, "ZR": 31.22}

# League-average team PA / IP -- team_seasons_all.csv, n=4,200. The volume
# denominator: an individual's rate stat becomes a team-wins contribution
# scaled by his share of a team's plate appearances / innings.
TEAM_PA = 6259
TEAM_IP = 1459

# AC-NATIVE league-mean ratings -- player_search export, ORG != '-' (rostered
# players only), n=620 batters / 512 pitchers, Aug 2026 snapshot. This is the
# centering point for the weighted-score -> metric-point-delta conversion.
# Deliberately NOT the K-T multiverse mean: K-T is park-neutral by
# construction (Handoff Sec 9); this is the real AC pool, with the Quakers'
# and every other park's own factors already inside the wRC+/ERA+ outcomes
# the weights were fit against.
BATTER_LEAGUE_MEANS = {
    "POW": 37.46, "EYE": 44.82, "BABIP": 45.77, "GAP": 42.83, "AVK": 48.13,
}
PITCHER_LEAGUE_MEANS = {"STU": 45.41, "MOV": 48.67, "CON": 40.98}

# WARNING -- UNIT ASSUMPTION, NOT independently verified. BATTER_WEIGHTS'
# unit ("wRC+ points per 10 rating points") is documented at A44/A53.
# PITCHER_WEIGHTS is documented only as "team-wins weights" (A48/A53) -- no
# per-rating-point unit is stated anywhere in the Log/Spec. Treated here as
# "ERA+ points per 10 rating points" BY ANALOGY to the batter convention,
# not by citation. If pitcher F1 output looks off-scale against known AC WAR
# totals, check this assumption first.
#
# Also unreconciled: A27 (locked current-value pitcher screen) orders
# MOV -> CON -> best-two-pitches -> STM and explicitly excludes STU as a
# derived roll-up, not a primary input. PITCHER_WEIGHTS (A48/A53, used here
# per the retrain handoff) puts STU first. Both are locked findings; nothing
# in the registry reconciles the two screens. Using PITCHER_WEIGHTS per the
# handoff's explicit instruction -- flagged, not resolved.
PITCHER_WEIGHT_UNIT_ASSUMED = True

# Replacement-level offset, full-season-volume, wins below a league-AVERAGE
# player at that role. WARNING -- ASSUMED, NOT AC-DERIVED. Standard
# sabermetric convention (SP ~2 WAR/200 IP, RP ~1 WAR/60 IP below average
# defines replacement). The suite's OLD sp_war_estimate() anchors a
# different number (bare-minimum arsenal = 1.58 WAR, A14/A15) but that was
# calibrated against the retired WAR-fit GB model at implicit full-season
# volume and is NOT directly portable into this chain -- noted, not merged.
# Batters need no separate constant: POS_ADJ_CONSTANTS (A26, UNCHANGED,
# "reconstructs absolute WAR") already supplies the average-to-replacement
# positional shift and stays wired in unchanged via pos_adj().
REPLACEMENT_OFFSET_WINS = {"SP": 2.0, "RP": 1.0}
REPLACEMENT_VOLUME = {"SP": 200.0, "RP": 60.0}   # IP the offset is defined over

# Volume needed for FULL confidence in the rate estimate (display threshold,
# not a hard cutoff -- the number is always real, never suppressed). Below
# this, F1 should be shown alongside its confidence, not trusted at face
# value. This is the fix for the F1 IP-collapse (Open Items #4): at low IP
# the estimate now shrinks toward a real, bounded number instead of reading
# -2 to -5, and confidence tells the caller how much to trust it.
FULL_CONFIDENCE_PA = 300
FULL_CONFIDENCE_IP = 80
