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
# ⚠ ENGINE-EXACT [A57]. These SUPERSEDE the OLS weights (POW 6.8 / EYE 4.9 /
# BABIP 3.2 / GAP 1.6 / AVK 1.4, R2=0.434), which had TWO RANK ERRORS:
#   Eye > BABIP was backwards, and Avoid K's was buried BELOW Gap (~2.8x too low).
# Read off the editor's Resulting Stats panel -- the engine's own expected line,
# no fit, no error term. Units: RUNS per DISPLAY GRADE, 600-PA season.
# Four of five tools are LINEAR in display grade. POWER is not -- see POWER_CURVE.
# ══════════════════════════════════════════════════════════════════════════
# ⚠⚠ TWO WEIGHT SETS, TWO DIFFERENT UNITS. DO NOT MIX THEM.
# `acquisitions.py` divides by 10 and centres on BATTER_LEAGUE_MEANS, so it
# needs the A44/A53 wRC+ convention. `dev_model.py` scores in runs above a
# display-25 baseline. Feeding one into the other is a ~6x scale error --
# and it nearly shipped silently (only a missing 'POW' key raised a
# KeyError instead).
# ══════════════════════════════════════════════════════════════════════════

# UNIT: wRC+ POINTS PER 10 RATING POINTS  [A44/A53]. Used by acquisitions.py.
# ⚠ SUPERSEDED BY A57 but retained because the deployed F1/F2 chain is built
# on this unit. A57 found TWO RANK ERRORS here -- Eye > BABIP is BACKWARDS,
# and Avoid K's is ~2.8x too low (buried below Gap when it is really ~2.5x Gap
# and ties Eye). **The retrain thread must port acquisitions.py to the
# engine-exact set below; until then the suite runs on known-wrong ordering.**
BATTER_WEIGHTS = {
    "POW": 6.8, "EYE": 4.9, "BABIP": 3.2, "GAP": 1.6, "AVK": 1.4,
}

# UNIT: RUNS PER DISPLAY GRADE, 600-PA season  [A57, ENGINE-EXACT].
# Read off the editor's Resulting Stats panel -- the engine's own expected
# line. No fit, no error term. POWER is NOT here: it is the only genuine
# engine nonlinearity and lives in POWER_CURVE.
BATTER_RUNS_PER_GRADE = {
    "BABIP": 0.520,
    "EYE":   0.453,
    "AVK":   0.416,   # the flat regression could not see this channel
    "GAP":   0.166,   # never adds a hit; only upgrades 1B -> 2B (~.30 runs)
}

# POWER is the ONLY genuine engine nonlinearity [A57a] -- convex through display
# 85 with NO roll-over (~+0.5 runs/10 internal at the bottom, +3.9 at the top,
# an 8x spread). A single coefficient is too high below d50 and far too low
# above it. Values = runs above a display-25 baseline, 600-PA season.
# ⚠ REFUTES A22 ("concave, peaking ~POW 62").
POWER_CURVE = {
    25: 0.00, 30: 2.12, 35: 4.71, 40: 8.34, 45: 11.35, 50: 13.48,
    55: 18.18, 60: 21.69, 65: 25.57, 70: 29.54, 75: 33.05, 80: 36.26, 85: 45.88,
}

# ⚠ The other four tools LOOK convex against INTERNAL value, but that is the
# RULER, not the bat: the internal->display map compresses above d50 (bucket
# widths 34 -> 16 internal points), so runs-per-internal steepens for ANY tool.
# In DISPLAY units they are linear at R2 0.99+. Score in DISPLAY grades.

# ⚠ INTERACTIONS ARE REAL [A57c] -- additivity is FALSE for tools sharing the
# balls-in-play channel. hits = (balls in play) x (hit rate on balls in play):
#   BABIP x AvK  = +1.24 runs (SUPER-additive: AvK raises the COUNT, BABIP the RATE)
#   BABIP x POW  = -0.47 runs (SUB-additive: power REMOVES balls from the pool)
#   anything x EYE = 0.00     (walks are a separate column)
# A linear sum UNDERVALUES high-contact bats and OVERVALUES high-BABIP+high-POW
# bats. Magnitude is 2-7% at the corner -- deferred as Phase 2, NOT ignored.
# ⚠ Phase 2 is "add the term AND RE-FIT", never "add a term".
BATTER_INTERACTIONS = {("BABIP", "AVK"): +1.24, ("BABIP", "POW"): -0.47}
APPLY_INTERACTIONS = False

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
# --------------------------------------------------------------------------
# DEFENSIVE GATES -- TWO LEVELS, derived from the live AC league distribution
# (n=105 SS / 134 CF / 132 C / 112 3B / 115 2B / 97 LF / 75 RF / 87 1B).
# Gloves are FIXED [A50] -- current IS truth, never project a defensive rating.
#
#   HARD FLOOR (league p10) = "cannot hold this position." Below it he is
#       RE-BARRED at the fallback. This is a fact about the player.
#   STARTER FLOOR (league median) = "would be below-average here." This only
#       FLAGS. A below-median shortstop with a real bat is still a shortstop,
#       and re-barring him would cost ~55 pts of vsBar and tell you a lie.
#
# Corners (LF/RF/1B) get a hard floor only -- their medians describe bat-first
# players parked there, not defensive capability.
# --------------------------------------------------------------------------
DEFENSIVE_FLOORS = {          # HARD -- re-bars him (league p10)
    "SS": ("IF RNG", 55),
    "CF": ("OF RNG", 55),
    "C":  ("C ABI", 50),
    "3B": ("IF ARM", 55),
    "2B": ("IF RNG", 45),
    "RF": ("OF ARM", 50),
    "LF": ("OF RNG", 40),
}

DEFENSIVE_SECONDARY = {       # HARD, second tool -- both must clear
    "3B": ("IF RNG", 45),     # arm alone is not a third baseman
    "SS": ("IF ARM", 50),
    "CF": ("OF ARM", 45),
}

STARTER_FLOORS = {            # FLAG ONLY -- league median at the position
    "SS": ("IF RNG", 65),
    "CF": ("OF RNG", 60),
    "C":  ("C ABI", 60),
    "3B": ("IF ARM", 60),
    "2B": ("IF RNG", 55),
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
# ⚠ FITTED [A57d], not derived. The engine's event counts run through the
# Quakers factors (HR x1.30 / 2B x0.95 / 3B x0.90), half-home/half-road.
# Replaces the old blanket 1.15 guess -- the only coefficient in the system
# that had never been fit on anything (methodology rule 9).
# The park amplifies POWER (HR-heavy output) and suppresses GAP (a doubles tool
# in a yard that trades doubles for homers). EYE is EXACTLY neutral -- walks are
# park-proof. BABIP/AvK are near-neutral (mostly singles).
PARK_OVERLAY = {"POW": 1.183, "GAP": 0.935, "BABIP": 0.993, "AVK": 0.993, "EYE": 1.000}
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


# ==========================================================================
# VALUE-MODEL RETRAIN CONSTANTS (Open Items #4/#5) -- RESTORED
# ⚠ These were lost when dev_constants.py was overwritten by an A57 edit that
# was made against a stale local copy. Recovered from git commit 6930b85.
# `acquisitions.py` imports PITCHER_WEIGHTS_ACTIVE and the retrain chain; the
# suite fails to start without them. NEVER hand back a shared module without
# reading the deployed version first.
# ==========================================================================

# Team-wins conversion (4,200 team-seasons, actual W-L). Locked [A53 family].
WINS_PER_SD = {"wRC+": 5.84, "ERA+": 5.69, "ZR": 0.76}
TEAM_SD     = {"wRC+": 8.60, "ERA+": 9.96, "ZR": 31.22}
TEAM_PA = 6259
TEAM_IP = 1459

# STU is DERIVED from the arsenal [A50] -- read it, never project it, and do
# NOT let it carry weight in the active chain (it would double-count the pitch
# grades). PITCHER_WEIGHTS keeps STU for reference/display only.
PITCHER_WEIGHTS_ACTIVE = {"MOV": 1.6, "CON": 1.3}

# Centering constants. ⚠ FROZEN at an Aug-2026 snapshot -- no refresh mechanism.
# The AC rating distribution moves slowly within a season but turns over across
# offseasons. Recompute from a current league export each winter.
BATTER_LEAGUE_MEANS = {
    "POW": 37.46, "EYE": 44.82, "BABIP": 45.77, "GAP": 42.83, "AVK": 48.13,
}

# ⚠⚠ UNIT ASSUMPTION -- NOT independently verified, flagged by the retrain
# thread and preserved verbatim in substance:
#   BATTER_WEIGHTS' unit ("wRC+ points per 10 rating points") is documented at
#   A44/A53. PITCHER_WEIGHTS_ACTIVE is documented only as "team-wins weights"
#   (A48/A53) -- NO per-rating-point unit is stated anywhere in the Log or
#   Spec. It is treated here as "ERA+ points per 10 rating points" BY ANALOGY
#   to the batter convention, NOT by citation.
#   >> If pitcher F1 output looks off-scale against known AC WAR totals, CHECK
#      THIS ASSUMPTION FIRST. <<
# NOTE: BATTER_WEIGHTS above is now the A57 ENGINE-EXACT set, whose unit is
# RUNS PER DISPLAY GRADE (600-PA season) -- a DIFFERENT unit from the A44/A53
# wRC+-per-10-points convention this warning was written against. Any code
# mixing the two must convert explicitly.

# ...frozen snapshot continues:
# The AC rating distribution moves slowly within a season but turns over across
# offseasons. Recompute from a current league export each winter.
PITCHER_LEAGUE_MEANS = {"STU": 45.41, "MOV": 48.67, "CON": 40.98}
PITCHER_WEIGHT_UNIT_ASSUMED = True

# Volume at which a rate estimate is treated as fully trustworthy. Below it,
# F1 down-weights toward the ratings-based estimate instead of collapsing.
# ⚠ This is what fixes the IP-collapse: pitcher F1 read -2.05 to -5.54 on every
# starter at spring volume because WAR is a COUNTING stat and 11 IP cannot
# accumulate. At low volume the model must report LOW CONFIDENCE, not -5 WAR.
# ⚠ ASSUMED, not fitted -- a full season of PA/IP, chosen by convention.
FULL_CONFIDENCE_PA = 600.0
FULL_CONFIDENCE_IP = 180.0

# ⚠ ASSUMED, NOT FITTED (methodology rule 9). Shifts every score by a constant,
# so it does not reorder anything -- but it is not measured and must stay
# flagged. Nothing in the registry supports deriving it.
REPLACEMENT_OFFSET_WINS = {"SP": 2.0, "RP": 1.0}
REPLACEMENT_VOLUME      = {"SP": 200.0, "RP": 60.0}   # IP the offset spans


# ==========================================================================
# DEFENSIVE VALUE TERMS  [A58 -- 162-team purpose-built league, 7 seasons,
# TCR=100, neutral parks, NOT burned in. Trades/FA/draft disabled, so no
# organisational confound clock ran at all.]
# ==========================================================================

# RANGE -> RUNS. The dominant defensive term by an order of magnitude.
# Runs per +5 DISPLAY points (defensive ratings sit on the 1-250 internal
# scale, ~16-17 points per bucket, so linear is appropriate -- unlike the
# offensive 1-600 curve).
RANGE_RUNS_PER_5 = {
    "2B": 6.18, "SS": 6.15, "CF": 5.96, "3B": 4.24,
    "RF": 3.62, "LF": 3.59, "1B": 1.40,
}

# ⚠ CATCHER DEFENSIVE ABILITY IS A DEAD NULL [A58a]. p=.921, and it held at
# BOTH N=349 and N=1,044 -- more data did not move it. **TREAT CATCHERS AS
# BAT-ONLY.** C_FRM (p=.070) and C_ARM (p=.065) are suggestive but short of
# significance -- DO NOT PRICE THEM. If C_ARM is ever revisited, use RTO%
# (rate), NEVER raw RTO (count): raw counts correlate at the WRONG SIGN
# because teams allowing more baserunners face more steal attempts.
CATCHER_DEF_RUNS = {"C_ABI": 0.0, "C_FRM": None, "C_ARM": None}

# TDP -> DOUBLE PLAYS per rating point (NOT runs). Survives a range control
# cleanly, p<.001 both positions. ⚠ A 2x error was caught pre-merge: the
# producing thread first labelled these "runs/pt".
TDP_DP_PER_POINT = {"SS": 0.442, "2B": 0.624}

# ERROR ratings -> ERRORS AVOIDED per +5 rating points (NOT runs). p<.001.
# Roughly a TENTH of what range is worth -- a minor correction term.
ERROR_ERRORS_PER_5 = {"2B": -0.65, "SS": -0.84, "3B": -1.25, "RF": -0.68, "CF": -0.63}

# ⚠ ASSUMED, NOT DERIVED (methodology rule 9). Standard sabermetric figures
# carried in by analogy -- an assumption stacked on top of a real regression.
# Flag wherever a runs figure computed from them is displayed.
RUNS_PER_DP = 0.5
RUNS_PER_ERROR = 0.5

# ⚠ ARM IS NEARLY WORTHLESS as a value term. Measured from the parquet's ARM
# runs column: CF +0.31 runs per +5, LF +0.20, RF +0.09, and ~0.00 at
# C/SS/3B/2B -- about 1/20th of range. **Arm is a positional GATE (you need
# one to play 3B/RF/C), not a value term once you are there.**
ARM_RUNS_PER_5 = {"CF": 0.31, "LF": 0.20, "RF": 0.09,
                  "C": 0.0, "SS": 0.0, "3B": 0.0, "2B": 0.0}
