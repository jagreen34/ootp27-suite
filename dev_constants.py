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
# ⚠ DERIVED, NOT FITTED. The multiverse the weights came from is park-NEUTRAL
# (every PF column is exactly 1.000), so no park coefficient can be fit on it.
# Reasoning: HR x1.30 at home, ~0 away -> ~15% over a full season. 2B x0.95 /
# 3B x0.90 average ~0.93, halved -> ~0.96. Park factors are SYMMETRIC (they
# boost the opponent too), so this is an EDGE multiplier, not a production one.
# Replace with a fitted value once AC historical team-seasons are in hand --
# ~30 seasons x 28 teams with real park variation would measure it properly.
PARK_OVERLAY = {"POW": 1.15, "GAP": 0.96}
APPLY_PARK_OVERLAY = False        # ParkD is shown as its own column instead

# Anyone with this arm can stand at third; first base has no real tool gate.
# Position ELIGIBILITY in OOTP is experience, not ability -- the tools are the
# real gate (a clone went 0->55 at 1B in one period).
TOOL_POSITION_GATES = {
    "1B": None,
    "3B": ("IF ARM", 55),
    "2B": ("IF RNG", 50),
    "SS": ("IF RNG", 60),
    "LF": ("OF RNG", 45),
    "RF": ("OF RNG", 50),
    "CF": ("OF RNG", 60),
    "C":  ("C ABI", 55),
}

# A52 -- work ethic: small real accelerant (~15% top-to-bottom, r=+0.072).
# Low WE does NOT gate development (~87% of top band). Tiebreaker, not a cut.
# Baseball IQ (INT) is NULL for development (r=+0.028) -- do not use.
WORK_ETHIC_MULT = {"H": 1.07, "N": 1.00, "L": 0.93}
APPLY_WORK_ETHIC = False   # off by default; effect is inside the noise

# A56 -- development is bimodal (~1/5 pop hard, ~1/5 barely move).
# A projection is the CENTRE of a wide distribution, never a forecast.
BIMODAL_WARNING = True


# --------------------------------------------------------------------------
# ROLE ADJUSTMENTS (pitchers)
# Registry: SP->RP role conversion inflates Stuff ~+5 display (~38 internal).
# A reliever's STU 60 is NOT the same object as a starter's STU 60. Comparing
# them raw overrates every reliever on the board.
# --------------------------------------------------------------------------
RP_STUFF_DEFLATOR = 5.0          # subtract from RP/CL Stuff to compare vs SP
ROLE_POSITIONS = {"SP": "SP", "RP": "RP", "CL": "CL", "P": "SP"}

# ASSUMED, not fitted -- role-typical innings for a volume weight. Off by
# default; enabling bakes an assumption into the score (methodology rule 9).
ROLE_INNINGS = {"SP": 200, "RP": 70, "CL": 70}
APPLY_ROLE_VOLUME = False

# --------------------------------------------------------------------------
# FALLBACK POSITIONS -- where a player goes when he misses a defensive floor.
# Gloves are FIXED [A50], so a floor miss is permanent, not a projection risk.
# The tool re-bars him at the fallback rather than flattering him at a
# position he cannot hold.
# --------------------------------------------------------------------------
POSITION_FALLBACK = {
    "SS": "3B", "CF": "LF", "C": "1B", "2B": "1B",
    "3B": "1B", "LF": "1B", "RF": "1B",
}

# A41 -- an arm with fewer than this many pitches clearing the crossover floor
# has an arsenal that does not exist in usable form. His derived Stuff is
# built on grades that will not play.
MIN_REAL_PITCHES = 2
MIRAGE_PENALTY = 0.65            # score multiplier when the arsenal is a mirage

# A54 -- below the command gate a breaker/cutter erodes 6-13 internal pts/yr.
# Applied to the PROJECTION only (a development claim, not a current fact).
EROSION_PENALTY_GRADES = 1       # display grades docked from the out-pitch
