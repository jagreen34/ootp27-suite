#!/usr/bin/env python3
"""
OOTP 27 -- PLAYER ANALYSIS, canonical build.
Philadelphia Quakers / American Circuit.  Registry v16 (A1-A115).

    python3 ootp_analyze.py verify                    # self-test only; exits non-zero on failure
    python3 ootp_analyze.py analyze <export> [-o OUT] # verify, then write the workbook
    python3 ootp_analyze.py columns <export>          # what the file has and what it is missing

Accepts a .csv or .xlsx OOTP export.  Detects automatically whether it is a DRAFT POOL
(no organisations, no service time) or a LEAGUE/ROSTER export, and runs the matching analysis.

-------------------------------------------------------------------------------
WHY THIS FILE EXISTS
-------------------------------------------------------------------------------
Not to compute a board -- that is easy.  It exists to make a specific list of
REAL, REPEATED analyst errors impossible.  Each guard below is a mistake that was
actually made and actually reached a decision.  See GUARDS in verify().

    G1  A POSITION RATING WAS READ AS ABILITY.        [A113]
        Position ratings record where a man has been PLAYED.  Draft prospects have
        played nowhere: the 1977 pool's mean 3B position rating is 10.8 against 54.5
        for AC regulars who man the spot.  A "3B position rating >= 55" gate put every
        third baseman in the class at first base -- -13.4 runs/season each.
        GUARD: gate functions physically cannot see position-rating columns.

    G2  A PROBABILITY STORED AS A FRACTION WAS PRINTED AS A PERCENT.   [A112 s7]
        Doug Will's P(POW>=55) was reported as 0.2% against a true 19.5%.
        GUARD: probabilities are carried in a Pct type that refuses silent formatting.

    G3  A BASELINE WAS COMPUTED WITHOUT THE ORG FILTER.                [A112 s0]
        416 unassigned players, 70 of them with 6+ starts, drag every starter mean
        down 5-6 display points.  Unfiltered AC starter HRA reads 49.1 vs a true 54.7.
        GUARD: baselines() refuses to run on an unfiltered frame.

    G4  A ROSTER DOCUMENT WAS USED AS A DATA SOURCE.                   [v16 Part 1]
        A trade valuation was argued from a doc naming two pitchers on other teams.
        GUARD: this script reads exports only, and stamps source + mtime into the output.

    G5  A CONSTANT WAS INVENTED INSTEAD OF LOOKED UP.                  [A113 s3]
        An "IF ARM >= 55" 3B gate was designed from scratch while THE_RULES_pocket
        rule 5 already carried the measured one (RNG+ARM >= 120, n=17,459).
        GUARD: every constant carries a SOURCE string; verify() asserts none is empty.

    G6  AN ACQUISITION SCREEN WAS APPLIED TO A LINEUP-CARD DECISION.   [2026-09-17]
        Running the arm gate strictly against an existing staff produced a rotation of
        a 144 FIP- and a man with zero innings.
        GUARD: gates and rankings are separate functions and are labelled as such.

    G7  MAJOR-LEAGUE BARS WERE APPLIED TO A DRAFT POOL.                [pocket card]
        Zero of 84 bats in the 1977 class clears a single A94 bar.
        GUARD: bars are only computed for LEAGUE exports.

    G8  A74 WAS CONVERTED TO CAREER WAR WITHOUT SCALING PLAYING TIME.  [A114]
        Catchers take 0.840 of a first baseman's PA and post the LOWEST WAR of any
        position.  The unscaled conversion inflated every catcher by ~0.74 WAR.
        GUARD: pos_adj_war() multiplies by PT_RATIO and verify() checks catcher.

    G16 THE ACQUISITION GATE PRICED THE LINEUP CARD.  45% OF THE LEAGUE.
        CAUGHT IN ADVERSARIAL REVIEW 2026-09-22, BEFORE SHIPPING.  'lands' is where a
        glove CLEARS A108's gate -- an ACQUISITION question.  It was also driving the
        positional runs columns, which are a LINEUP CARD.  On the live AC file 396 of
        860 bats land somewhere other than their listed position and 169 of those
        differ by more than 4 runs/season.  D. Tislow is listed at shortstop with 453
        plate appearances and was priced at first base, -10.87, because his range is 55
        against A108's bar of 65: a 13.94-run error, ~11 career WAR.  G6 with the names
        changed, and G6 was already written.

        ⛔ AND THE FIRST FIX WAS WRONG TOO.  v1.5.0 replaced the gate with POS and
        called POS 'the position he actually plays'.  THE GM CORRECTED THIS:

            "POS is the engine's defined position.  A player can have a LF pos and
             play 1b, LF, RF, etc."

        POS is a DESIGNATION, not a playing-time record.  The fielding block in the
        export is no help either -- it is a season TOTAL summed across every position
        a man appeared at (per-ORG non-pitcher IP / 9 / games = 8.03, i.e. exactly the
        nine slots; TC == PO+A+E for 100% of rows).  There is NO per-position line
        anywhere in the 257 columns, and 53% of fielders are provably multi-position.
        THE SPLIT IS NOT RECOVERABLE FROM THIS FILE.  Saying otherwise is A113's error
        in a new column: a field that looks like a record of what happened is a label.

        ⛔ AND THE FIELDING COUNTING STATS ARE NOT THE ANSWER EITHER.  A putout-rate
        override (PO*9/IP separates first base cleanly: median 9.99 against 2.39 for
        the next position) was built and then REMOVED ON THE GM'S INSTRUCTION:

            "for fielding we should only use IFR, OFR etc"

        Fielding ABILITY is the ratings -- IF RNG, OF RNG, IF ARM, OF ARM, TDP, C ABI.
        The counting stats are a blended season total and this house does not read
        them as a glove.  So the tool does not, anywhere.

        THAT LEAVES TWO HONEST SIGNALS AND THEY ANSWER DIFFERENT QUESTIONS:
          POS    the engine's designation -- WHERE HE IS CARDED.  A label.
          lands  what his RATINGS support -- WHERE HE COULD BE BOUGHT TO PLAY.
        A74's adjustment is 'the bat a club will TOLERATE at the position', derived
        from mean wRC+ BY POSITION.  That is a question about the position a man
        occupies on a card, not about the quality of his glove.  So the runs columns
        are keyed to POS, and 'lands' keeps its own column and its own meaning.
        Neither is a record of innings, and the tool never claims one is.
        GUARD: the runs columns are keyed to POS on a LEAGUE export, named 'priced at'
        rather than 'plays', and the KEY sheet states plainly that the split of a
        multi-position player is NOT RECOVERABLE from this export.  A POOL has no
        designation worth trusting, so the gate still governs there.

    G15 wRC+ 100 IS A FILL VALUE, AND IT WAS PRICED AS A LEAGUE-AVERAGE BAT.
        CAUGHT ON THE LIVE 1,547-ROW AC FILE, 2026-09-22, BEFORE SHIPPING.  753 of
        1,547 rows carry wRC+ EXACTLY 100.  It is not a distribution -- the next most
        common value appears 8 times.  OOTP writes 100 where it has no wRC+ to publish.
        Split by organisation the tell is decisive:
            ORG assigned   174 of 649 bats read 100, and EVERY ONE has PA <= 65
            ORG '-'        240 of 247 bats read 100 (97.2%), PA up to 414
        So for rostered players the G14 plate-appearance floor already removes them; for
        the unassigned pool it does not, because their PA is real and only the RATE is
        fake.  J. Keller (201 PA) and M. Teixeira (414 PA) both priced out at exactly
        league average, which looks entirely plausible on the sheet.
        GUARD: on a LEAGUE export the bat score is blank for any player with no ORG, and
        the unassigned pool is ranked BELOW the rostered one instead of interleaved --
        their WAR is earned at another level and is not the same number (same family
        as G3).

    G14 THE POSITION-FREE BAT SCORE WAS READ OFF A HANDFUL OF PLATE APPEARANCES.
        bat_runs() prices a bat from wRC+, which is a RATE.  A man with 23 PA and a
        180 wRC+ scores +44 runs/season and tops the sheet.  A114's positional means
        are taken on 326-388 PA; below roughly a quarter of that the rate is noise.
        GUARD: bat_runs() returns None under BAT_RUNS_MIN_PA and the cell is blank,
        not zero -- a zero would read as an average bat, which is a stronger claim
        than "not enough plate appearances to say."

Per METHODOLOGY RULE 22 this script FAILS LOUD: if any check fails, nothing is written.
Rule 9 is enforced by the MEASURED / ESTIMATED tag on every constant.
"""
import sys, os, io, csv, math, random, statistics, datetime, argparse

VERSION = "1.9.2  (registry v16, A1-A115)"

# The number of self-tests this build must run.  See section 31: a generated section
# that silently stops generating prints a SMALLER number and the word PASSED.
MIN_CHECKS = 328   # checks run BEFORE the floor check; the suite reports 329
SEED    = 1977
NSIM    = 20000      # at 4,000 a 2% probability carries +/-0.4pp of Monte Carlo noise

# =============================================================================
# CONSTANTS.  Every entry: (value, SOURCE, MEASURED|ESTIMATED)
# =============================================================================

class C:
    """A constant that knows where it came from.  G5."""
    __slots__ = ('v', 'source', 'tier')
    def __init__(self, v, source, tier):
        assert source and source.strip(), "a constant with no source is not allowed (G5)"
        # CONVENTION, added 1.9.2: a value that is DECLARED, not fitted -- the defensive
        # spectrum is the only one. Tagging it MEASURED would claim an arm's-length
        # result the file does not have; tagging it ESTIMATED would claim a fit.
        assert tier in ('MEASURED', 'ESTIMATED', 'CONVENTION'), tier
        self.v, self.source, self.tier = v, source, tier
    def __repr__(self): return f"{self.v!r} [{self.tier}: {self.source}]"

# --- development delivery ----------------------------------------------------
A76_BAT = C({
 16:{'CON':.450,'GAP':.515,'POW':.402,'EYE':.242,'BABIP':.471,'AVK':.457},
 17:{'CON':.453,'GAP':.516,'POW':.398,'EYE':.243,'BABIP':.473,'AVK':.467},
 18:{'CON':.436,'GAP':.489,'POW':.386,'EYE':.229,'BABIP':.456,'AVK':.455},
 19:{'CON':.396,'GAP':.420,'POW':.347,'EYE':.210,'BABIP':.388,'AVK':.444},
 20:{'CON':.349,'GAP':.329,'POW':.288,'EYE':.187,'BABIP':.311,'AVK':.428},
 21:{'CON':.282,'GAP':.229,'POW':.202,'EYE':.153,'BABIP':.219,'AVK':.376},
 22:{'CON':.185,'GAP':.075,'POW':.094,'EYE':.106,'BABIP':.100,'AVK':.298},
 23:{'CON':.077,'GAP':-.091,'POW':-.026,'EYE':.072,'BABIP':-.014,'AVK':.208},
 24:{'CON':-.021,'GAP':-.218,'POW':-.120,'EYE':.052,'BABIP':-.104,'AVK':.118},
 25:{'CON':-.086,'GAP':-.270,'POW':-.175,'EYE':.041,'BABIP':-.153,'AVK':.040},
 26:{'CON':0.0,'GAP':0.0,'POW':0.0,'EYE':0.0,'BABIP':0.0,'AVK':0.0}},
 "A76 FLOOD, 15,324 players / 221,003 transitions. Fraction of the current->potential "
 "gap closed BY THE PLAYER RISING, by age and tool, on the 20-80 DISPLAY scale.", 'MEASURED')

A76_ARM = C({
 16:{'STU':.538,'MOV':.323,'PCON':.513,'HRA':.310},
 17:{'STU':.523,'MOV':.322,'PCON':.524,'HRA':.312},
 18:{'STU':.482,'MOV':.305,'PCON':.516,'HRA':.296},
 19:{'STU':.382,'MOV':.291,'PCON':.484,'HRA':.275},
 20:{'STU':.334,'MOV':.274,'PCON':.461,'HRA':.262},
 21:{'STU':.266,'MOV':.234,'PCON':.406,'HRA':.221},
 22:{'STU':.159,'MOV':.174,'PCON':.350,'HRA':.164},
 23:{'STU':.046,'MOV':.108,'PCON':.268,'HRA':.096},
 24:{'STU':-.029,'MOV':.047,'PCON':.183,'HRA':.030},
 25:{'STU':-.096,'MOV':-.001,'PCON':.114,'HRA':-.017},
 26:{'STU':0.0,'MOV':0.0,'PCON':0.0,'HRA':0.0}},
 "A76 FLOOD, same sample, pitcher tools.", 'MEASURED')

A77_BANDS = C([(.075,-.20,.00), (.302,.00,.30), (.379,.30,.60),
               (.167,.60,.90), (.032,.90,1.00), (.045,1.00,1.60)],
 "A77 FLOOD, 5,656 players followed from <=21 to 27+. Delivery is BIMODAL, so A76's "
 "mean is the centre of a SPLIT population (methodology rule 30). share, lo, hi.", 'MEASURED')
A77_MEAN, A77_MEDIAN = 0.425, 0.385

SHARE = C(0.70,
 "Cross-tool correlation of the development 'pop'. A46 says roughly a fifth of clones pop "
 "hard and a fifth barely move -- a PLAYER-level statement, so tools correlate -- but the "
 "strength is NOT measured. verify() brackets the output at SHARE 0.0 and 1.0.", 'ESTIMATED')

# --- career WAR model --------------------------------------------------------
A104_BAT = C({'HS':(1.026,-0.036,0.509), 'JR':(0.946,-0.209,0.474),
              'JuCo':(0.946,-0.209,0.474), 'SR':(0.288,0.311,0.430)},
 "A104 s3 FLOOD, n=2,724 TRUE draft-day bats. BAT_WAR ~ current + gap + range-vs-position-mean. "
 "NOTE b_gap is ~ZERO or negative for bats (t=-1.10): the gap has no expected value, only the "
 "option value A77 measures. JuCo has no row in A104; JR is substituted.", 'MEASURED')
A104_ARM = C((1.070, 0.162, 1.967, 0.270),
 "A104 s4, n=3,254 arms, POOLED. current, gap, effective pitches, stamina. "
 "Arms are the ONE place the gap still carries a positive coefficient.", 'MEASURED')
POSMEAN = C({'C':32.9,'1B':38.3,'LF':44.2,'3B':48.3,'RF':50.7,'2B':51.0,'SS':58.3,'CF':58.9},
 "A104 s3, draft-day position-mean RANGE. The b_range term is measured against this.", 'MEASURED')
A104_HS_CUR, A104_HS_GAP = 29.5, 31.9
A104_WAR = C({('BAT','HS'):(23.3,1136), ('BAT','JR'):(25.0,1391),
              ('BAT','JuCo'):(24.5,43),  ('BAT','SR'):(15.7,154),
              ('ARM','HS'):(12.0,1340), ('ARM','JR'):(16.1,1683),
              ('ARM','JuCo'):(10.2,67),  ('ARM','SR'):(11.0,164)},
 "A104 s5, career WAR by side and school class, with sample sizes.", 'MEASURED')
A104_BOARD = C({'Gabriel Huerta':27.0,'Gary Simmons':26.9,'Jimmy Kulbacki':26.2,'Doug Will':26.0,
                'Ed Staple':24.9,'Roger Renshaw':24.6,'Tom Thomas':24.3,'Walt Mazzola':18.1},
 "A104 s6, the published board. The reproduction target for the intercept recovery.", 'MEASURED')

# --- gates -------------------------------------------------------------------
# ⛔ CORRECTED 2026-09-22.  The tool shipped SS 60 / 2B 55 while CITING A108 -- which is
# the reversal that overturned exactly those two numbers.  THE_RULES_pocket rule 5 is
# locked 2026-08-26 and says 'SS 60 - 2B 55'; A108 is dated 2026-08-28 and measured the
# AC's own innings-weighted positional means at SS 67.1 and 2B 60.7, giving grid values
# SS 65 / 2B 60, identical across two exports eight days apart, with all three methods
# (innings-weighted, unweighted, 200+ ip) agreeing.  A84 v3 derives the same pair
# independently the same day.  60/55 are the PARQUET means -- the precise error A108
# exists to record.  The pocket card predates the reversal and was never updated.
# Cost of the defect: 88 of 620 league position players (14%) landed at the wrong
# position, 37 of them at 2B instead of 1B -- an A74 swing of +1.19 to -10.87
# runs/season each.  CF 65 was right in every source and is unchanged.
GATE_SS   = C(65, "A108 REVERSAL, AC innings-weighted SS mean 67.1 -> grid 65. SUPERSEDES "
                  "THE_RULES_pocket rule 5 (60), which is dated two days earlier and carries "
                  "the PARQUET mean. ON THE RANGE TOOL.", 'MEASURED')
GATE_2B   = C(60, "A108 REVERSAL, AC innings-weighted 2B mean 60.7 -> grid 60. SUPERSEDES "
                  "THE_RULES_pocket rule 5 (55), the PARQUET mean. ON THE RANGE TOOL.", 'MEASURED')
GATE_CF   = C(65, "A108 REVERSAL, AC innings-weighted CF mean 65.0 -> grid 65. Agrees with "
                  "THE_RULES_pocket rule 5. ON OF RANGE.", 'MEASURED')
GATE_RF_ARM = C(50, "THE_RULES_pocket rule 5. OF ARM splits RF from LF.", 'MEASURED')
GATE_CORNER_OF = C(55,
 "A84 v3, innings-weighted AC means: LF 57.1 -> 55, RF 57.2 -> 55. The two corners gate "
 "identically; A73 prices their range identically too (LF 3.95, RF 4.10). ⚠ AC-NATIVE -- "
 "a gate is a property of THIS league's population, not of the engine (A84's own warning, "
 "and the error A108 reversed).", 'MEASURED')
GATE_3B_SUM = C(120,
 "THE_RULES_pocket rule 5: '3B: range + arm >= 120 -- measured on ZR directly they are a "
 "dead heat (+0.310 vs +0.290, n=17,459), which is why position rating used to beat range "
 "alone.' Corroborated by A85. THIS REPLACED A POSITION-RATING GATE -- see G1/A113.", 'MEASURED')
GATE_STM  = C(50,
 "Rule 10: buy stamina 50 and stop; WAR per inning is flat above it. Stamina has NO potential "
 "column in the export -- it is FIXED like range, which makes it the pitcher's glove gate. "
 "The GM notes 45 starts routinely and 40 sometimes: a floor, not a wall.", 'MEASURED')
GATE_EFF  = C(3,
 "Rule 8 / A103: career WAR doubles from two effective pitches (5.5, 31 starts) to three "
 "(11.6, 113 starts). Counted on CURRENT ratings -- that is what A41 specifies and what "
 "A104 fitted b_eff on.", 'MEASURED')

PITCH_FLOOR = C(40, "A41, n=14,811: a pitch counts at 40.", 'MEASURED')
CH_FLOOR    = C(45, "A41: a CHANGEUP counts at 45. *** SEE A115 -- OPEN CONFLICT. A103 counts "
                    "every pitch at a flat 40 and A104 FITTED b_eff on that looser rule. This "
                    "script reports BOTH counts and flags any player they disagree on. ***",
                'MEASURED')
PITCHES = ['FB','CH','CB','SL','SI','SP','CT','FO','CC','SC','KC','KN']

# --- bars --------------------------------------------------------------------
BAR_POW = C(55, "A94 s5.2 -- MAJOR-LEAGUE top-quartile bar. NOT a draft-pool bar (G7).", 'MEASURED')
BAR_OBP = C(55, "A94 s5.2. OBP index = (0.254*EYE + 0.182*CON + 0.085*BABIP) / 0.521 [A89 s7].", 'MEASURED')
OBP_W, OBP_DEN = {'EYE':0.254,'CON':0.182,'BABIP':0.085}, 0.521
ACE_CON, ACE_HRA = C(55, "A86 s4 ace gate.", 'MEASURED'), C(65, "A86 s4 ace gate.", 'MEASURED')
NO1_CON, NO1_HRA = C(45,
 "A112: median CONTROL of the 28 clubs' best starters. The ace gate is correct but describes "
 "10 pitchers league-wide; only 6 of 28 team-best starters clear it. This is the bar that "
 "describes a real #1.", 'MEASURED'), C(65,
 "A112: median HRA of the 28 clubs' best starters -- the ace gate's HRA half is calibrated "
 "exactly right; only its control half was two display steps high.", 'MEASURED')
NO2_CON, NO2_HRA = C(45, "A112: rotation-slot medians, #2 starter.", 'MEASURED'), \
                   C(55, "A112: rotation-slot medians, #2 starter.", 'MEASURED')

# --- position value ----------------------------------------------------------
A74_POS = C({'C':5.77,'SS':3.07,'3B':2.51,'CF':1.56,'2B':1.19,'RF':-0.82,'LF':-2.52,'1B':-10.87},
 "A74 position adjustment, RUNS PER SEASON.", 'MEASURED')
PT_RATIO = C({'C':0.840,'1B':1.000,'2B':0.973,'3B':0.902,'SS':0.946,
              'LF':0.918,'CF':0.962,'RF':0.993},
 "A114: plate appearances of each club's PRIMARY player at the position, relative to first "
 "base, 28 clubs. Catchers take 16% fewer PA -- the largest gap on the board -- and post the "
 "LOWEST WAR of any position (1.76). A74's runs/SEASON must be scaled by this BEFORE being "
 "converted to career WAR, or every catcher is inflated by ~0.74 WAR. See G8.", 'MEASURED')

# --- the POSITION-FREE half of the same measurement --------------------------
# A74 did not invent its positional adjustment; it DERIVED it from the mean wRC+ of
# full-time players at each position (37,650 player-seasons, league mean 110.8):
#
#     C 101.6 -> +5.77   SS 105.9 -> +3.07   3B 106.8 -> +2.51   CF 108.3 -> +1.56
#     2B 108.9 -> +1.19  RF 112.1 -> -0.82   LF 114.8 -> -2.52   1B 128.1 -> -10.87
#
# That is a straight line through the origin, and its slope is recoverable from A74's
# own table by least squares: 0.6280 runs per wRC+ point per 600 PA.  It reproduces all
# EIGHT published adjustments to within 0.011 runs (worst: CF, 1.570 vs 1.56), so this
# is not a new model -- it is A74 read in the other direction.
#
# ⚠ WHY THIS IS NOT ENGINE WAR MINUS A74.  A114 s1 records that the engine's own WAR
# already carries "whatever positional credit the engine applies."  A74 is a DIFFERENT
# quantity: the bat a club will TOLERATE at the position, measured off wRC+.  Subtracting
# one from the other mixes two systems and yields a number with no referent.  The bat
# score below is built from wRC+ alone and never touches the WAR column.
WRC_MEAN = C(110.8, "A74 POSITIONAL ADJUSTMENT block: mean wRC+ of full-time players, "
                    "37,650 player-seasons. The zero point of the position-free bat score.",
             'MEASURED')
RUNS_PER_WRC = C(0.6280,
 "Recovered by least squares through the origin from A74's OWN eight (mean wRC+, adjustment) "
 "pairs. Reproduces every published A74 value to within 0.011 runs. Runs per wRC+ point per "
 "600 PA. NOT a new fit -- it is the slope A74 already used.", 'MEASURED')
WRC_FILL = C(100,
 "G15. OOTP writes wRC+ = 100 where it has none to publish. On the live AC file 753 of "
 "1,547 rows carry it exactly; the next most common value appears 8 times. Among ORG-"
 "assigned bats every such row has PA <= 65; among unassigned bats 97.2% read 100 on PA "
 "up to 414. Treated as ABSENT, never as an average bat.", 'MEASURED')
WRC_NOISE_SD = C(((150, 28.3), (250, 19.5), (350, 16.2), (450, 10.5)),
 "MEASURED ON THE AC 2026-09-22, as a TABLE, not a model. wRC+ dispersion of rostered "
 "bats by playing-time band, excess over the >=450 PA band (SD 26.2): 38.5/32.7/30.8/28.2 "
 "total -> 28.3/19.5/16.2/10.5 noise. "
 "⛔ AN EARLIER CUT FITTED SD = k/sqrt(PA) WITH k = 291 AND WAS WRONG TWICE: it dropped "
 "the 350-450 band (the LARGEST, n=100) from the fit, and k is not constant across the "
 "bands it did use -- 308, 265, 278, 210 -- so the 1/sqrt model is misspecified and the "
 "published bar was ~7% wide by band selection alone. The bands are reported as measured "
 "and nothing is fitted. CONFOUNDED: band means climb 76 -> 122, so better players simply "
 "play more and the low bands carry extra TALENT variance -- an UPPER bound. Also the "
 ">=450 baseline carries its own sampling noise, which pushes the other way. Published as "
 "an error bar beside the score, never used to change it.", 'MEASURED')
BAT_RUNS_MIN_PA = C(100,
 "G14 floor. A114's positional means are taken on 326-388 PA; a wRC+ on under ~100 PA is a "
 "rate read off noise and would top the sheet. Below this the bat score is blank, not zero.",
 'ESTIMATED')

# =============================================================================
# THE GLOVE.  A73 / A58a.  Added 1.8.0 on the GM's instruction.
#
# WHY IT EXISTS: through 1.7.0 the glove ratings were PRINTED on every row and priced
# at ZERO.  The workbook read T. Clark at -18.4 runs; counting his defence put him at
# -3.5.  A 15-run error on one player -- larger than anything three rounds of
# adversarial review found in the bat code.
#
# WHAT IT ANSWERS, and only this (the GM set the scope):
#   1. where is this man's best position?
#   2. what is he worth there?
# It does NOT do roster construction.  It will never say "play him in left because you
# already have a centre fielder" -- that is the GM's job and he has said so.
#
# ⚠ RATINGS ONLY.  No PO, A, E, TC, ZR, CER or IP_1 is read anywhere, on the GM's
# standing instruction ("for fielding we should only use IFR, OFR etc").  ZR can only
# score a position a man has ALREADY played, and it lives in the player card one man at
# a time; the whole point of this block is to answer for a position he has never played.
# G20 enforces the instruction against the code, not against memory.
# =============================================================================

GLOVE_RANGE5 = C({'2B':7.11,'SS':6.84,'CF':6.76,'3B':4.67,'RF':4.10,'LF':3.95,
                  '1B':1.62,'C':0.0},
 "A73 RANGE_RUNS_PER_5 via the ZR CHAIN, which A73 prefers over its direct team-wins "
 "route (player-level t of 30-77 against a noisier team-level fit). Runs per +5 display "
 "points of range. CATCHER IS ZERO ON PURPOSE -- A58a measured catcher defence as a NULL "
 "(p=.921, n=1,044) and A73 re-confirmed it by a second route (-0.35, n.s.). A better "
 "catcher is not worth more; see CATCH_GATE for what catching does require.", 'MEASURED')

# ✅ THE ARM CONFLICT IS CLOSED.  MEASURED ON THE AC, 2026-09-23.
#
# A73 left arm "UNRESOLVED between ~0 and 4.0 runs per +5" and told the tool to keep the
# file's near-zero values.  That instruction cost us on 2026-09-22: with arm at zero,
# G. Neyland (IF ARM 55) and R. Paige (45) were near-interchangeable and an assignment
# run moved Neyland off shortstop by 0.3 runs.  The GM rejected it on sight.
#
# A73 named the fix it could not perform: "an instrument that separates arm from general
# defensive quality."  Its own route regressed TEAM WINS on arm, so its confound -- "teams
# with strong-armed third basemen are good teams" -- lives at the team level.  ZR does
# not: it is a PLAYER-level measure against league-average defence at the position.  So:
# regress ZR on the ARM RATING with RANGE PARTIALLED OUT, within position, on AC regulars.
#
#   pos   n    runs per +5    partial r        A73's upper bound
#   3B   31       +6.38          +0.81              4.00
#   SS   32       +3.33          +0.51              2.67
#   2B   30       +1.23          +0.34              1.00
#   1B   26       -0.21          -0.10              1.04
#   LF   27       -0.29          -0.06              3.17
#   CF   37       -1.67          -0.20              1.66
#   RF   29       +0.10          +0.04              2.44
#
# THE CONFLICT WAS TWO DIFFERENT JOBS AVERAGED TOGETHER.
#   INFIELD arm turns a ball into an OUT.  Real, large, biggest at third.
#   OUTFIELD arm prevents BASERUNNER ADVANCEMENT.  Measured directly off the export's
#   own ARM-runs column: slope -0.27 per +5, R2 0.025, and realised arm runs span only
#   13.5 runs league-wide where A73's LF value would need 25.4.  It is not deterrence
#   either -- assists per 150 games are FLAT across arm bands (25.1 / 25.9 / 24.5), so
#   runners are not avoiding the strong arms.  The file's near-zero OF values were right.
#
# A THIRD ROUTE AGREES AT THIRD BASE.  A113 measured range and arm a DEAD HEAT on ZR
# (+0.310 vs +0.290, n=17,459), which is why pocket rule 5 gates 3B on RNG + ARM >= 120
# at 1:1.  This measurement puts arm ABOVE range there (6.38 vs 4.67).  Three independent
# routes, same conclusion.
#
# ⚠ WHAT IS STILL OPEN: n is ~30 per position on ONE league-season, and IF ERR is not
# partialled out -- a cannon that throws it away is not separated from a cannon that does
# not.  A73's within-player design (two exports separated in time, the same man's arm
# moving while his range does not) would settle it and is the VERIFICATION_PROTOCOL's
# standing ask.  Negative slopes are floored at zero: a negative arm value is not credible.
GLOVE_ARM5 = C({'3B':6.38,'SS':3.33,'2B':1.23,'1B':0.0,'LF':0.0,'CF':0.0,'RF':0.1,'C':0.0},
 "MEASURED ON THE AC 2026-09-23: ZR regressed on the ARM RATING with RANGE partialled "
 "out, within position, rostered regulars >=500 defensive innings, converted at 1 ZR = "
 "1.0353 runs (A73). Closes the arm conflict A73 left open between ~0 and 4.0. Infield "
 "arm turns balls into outs and is real; outfield arm prevents advancement and is not.",
 'MEASURED')

GLOVE_ERR_RUNS5 = C(0.77 * 0.548,
 "A73: ERROR_ERRORS_PER_5 = -0.77 errors per player per +5 (t=-16.7) x RUNS_PER_ERROR = "
 "0.548 (t=-8.0). Both were carried in by sabermetric analogy, both flagged 'ASSUMED NOT "
 "DERIVED', and both survived measurement. Infield only -- A73 fitted it there.\n"
 "⛔ NOT WIRED IN, AND DELIBERATELY SO AS OF 1.9.2. glove_runs() reads range, TDP and "
 "arm; it does NOT read IF ERR. KEY rule 7 claimed it did for two versions while this "
 "constant sat unreferenced -- a measured number is not a shipped number, and the sheet "
 "asserted a term the model never touched. Kept as a MEASURED result for the registry; "
 "wiring it in is a decision, not a tidy-up, because errors and range are not "
 "independent and A73 never fitted them jointly.",
 'MEASURED')
GLOVE_TDP_RUNS5 = C(1.05,
 "A73: Turn-Double-Play rating, 1.05 runs per +5 (t=2.3), SECOND BASE AND SHORTSTOP ONLY. "
 "⚠ TDP is a DIFFERENT RATING from range and is not a second opinion on it -- treating it "
 "as one produced methodology rule 28 (verify two numbers share a REFERENT before calling "
 "them a cross-check).", 'MEASURED')

NOISE_RUNS = C(4.0,
 "Methodology rule 12: differences under 4 WAR are noise. Applied here in RUNS on a "
 "per-600-PA rate, which is the conservative reading -- 4 runs is well under 4 wins, so "
 "anything this call marks as noise certainly is.", 'ESTIMATED')

CATCH_GATE = C(40,
 "MEASURED ON THE AC 2026-09-22. Catcher DEFENCE is a null (A58a), but catching is still "
 "a gate: C ABI >= 40 is cleared by 87 of 87 rostered catchers and by 4 of 533 other "
 "position players. A58a means 'a better catcher is not worth more', NOT 'anyone can "
 "catch'. Value term and eligibility gate are different things -- G6.", 'MEASURED')

# ⛔ THE BASELINE IS ONE NUMBER PER RATING, NOT ONE PER POSITION.  CORRECTED BEFORE SHIP.
# The first cut measured each glove against the LEAGUE MEAN AT THAT POSITION -- SS 66.4
# range, 2B 59.0 -- and it produced a nonsense the self-test caught immediately: an IF RNG
# 75 glove scored +26.5 at second base against +16.4 at short, i.e. every good infielder
# in the league "belonged" at second.  The cause is that shortstop's mean is high BECAUSE
# only good gloves play there, so grading a shortstop against other shortstops charges him
# for the company he keeps.  A74's positional bar cannot offset it: A74 is derived from the
# BAT a club tolerates (SS +3.07 vs 2B +1.19, 1.88 apart) and the defensive-difficulty gap
# is far larger than that.
#
# This is the same artifact the GM caught by hand on G. Neyland the same day, and it is
# worth naming: TWO CORRECT NUMBERS COMBINED ON MISMATCHED BASELINES PRODUCE A WRONG ONE.
#
# A73 fitted RANGE_RUNS_PER_5 as runs per +5 RELATIVE TO AVERAGE, and the average fielder
# is one number, not eight.  So the baseline is the league mean of each RATING across all
# rostered position players, and the only thing that distinguishes positions is what a
# point of range is WORTH there (GLOVE_RANGE5) plus A74's bar.  Checked for sensitivity:
# short beats second for a 70- and a 75-range glove at every baseline from 45 to 60.
GLOVE_MEAN = C({'IF RNG':44.9,'OF RNG':46.6,'IF ARM':48.5,'OF ARM':51.4,
                'IF ERR':44.1,'TDP':38.8},
 "AC league means of each RATING across all 620 rostered position players, measured "
 "2026-09-22. ⚠ NOT per-position means -- see the note above; per-position baselines "
 "charge a shortstop for the company he keeps and send every good infielder to second "
 "base. Re-measure when the league's rating distribution moves.\n"
 "⛔ DEAD SINCE 1.8.0 AND IT CONTRADICTS THE SHIPPED MODEL. glove_runs() prices against "
 "GLOVE_REF, which IS per-position, while this constant's own source argues per-position "
 "baselines are the error. Both readings were right about a different question -- the "
 "global mean answers 'is this a good glove', the per-position mean answers 'does he "
 "help or hurt HERE', and the GM asked the second one. Left in place, unreferenced, so "
 "the disagreement is on the record rather than quietly resolved by deletion.",
 'MEASURED')

# ⛔ CUT 1.9.2: GLOVE_POS existed only to feed glove_by_position()'s cross-position
# sort. The ladder that replaced it is TOOLS_LADDER, which is ORDERED and declared;
# this tuple was unordered and read as though it were not.
_OF = frozenset({'LF','CF','RF'})
_IF = frozenset({'1B','2B','3B','SS'})

RUNS_PER_WIN = C(10.0, "AC-derived; VERIFICATION_PROTOCOL s6 gives 9.65 from 4.19 R/G. "
                       "10.0 used for round numbers; verify() checks the swing either way.", 'ESTIMATED')
SEASONS_DEFAULT = C(8, "Career length assumption for converting runs/season to career WAR.", 'ESTIMATED')

# columns that are POSITION-EXPERIENCE ratings, never ability.  G1.
FORBIDDEN_IN_GATES = frozenset({
    'P','C','1B','2B','3B','SS','LF','CF','RF','DH',
    'P Pot','C Pot','1B Pot','2B Pot','3B Pot','SS Pot','LF Pot','CF Pot','RF Pot'})

# =============================================================================
# UNITS.  G2 -- a probability that cannot be silently printed as the wrong thing.
# =============================================================================

class Pct(float):
    """A probability in [0,1] that formats as a PERCENT and knows it.

    The 2026-09-17 failure: p_ace was stored as a fraction and printed with '%.1f',
    so 0.069 was reported to the GM as '0.1%' when the answer was 6.9%.  Any format
    of this type goes through __format__, which multiplies by 100 and appends '%'.
    Arithmetic on it degrades to plain float on purpose -- you cannot accidentally
    keep the label after you have changed the meaning.
    """
    __slots__ = ()
    def __new__(cls, x):
        if not (0.0 - 1e-9 <= x <= 1.0 + 1e-9):
            raise ValueError(f"Pct takes a FRACTION in [0,1], got {x!r} "
                             f"-- if that is already a percent, divide by 100 first (G2)")
        return super().__new__(cls, x)
    def __format__(self, spec):
        return format(float(self) * 100.0, spec or '.1f') + '%'
    def __str__(self):  return format(self)
    def __repr__(self): return f"Pct({float(self):.6f} = {self})"
    @property
    def percent(self): return float(self) * 100.0

# =============================================================================
# LOADING
# =============================================================================

def _read_csv(path):
    """Read a delimited export.

    FIX 2026-09-19: hard-coding utf-8 made every latin-1 export (OOTP is full of
    accented names) die with an unhandled UnicodeDecodeError. Fall back, and sniff
    the delimiter so a genuine .tsv is not blamed on the user.
    Also warns on duplicate headers, which silently collapse (last column wins).
    """
    raw = None
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            with open(path, newline='', encoding=enc) as f:
                raw = f.read()
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        sys.exit(f"ERROR: could not decode {os.path.basename(path)} as UTF-8, CP1252 or "
                 "Latin-1. Re-save it as UTF-8 CSV.")
    first = raw.split('\n', 1)[0]
    delim = '\t' if first.count('\t') > first.count(',') else ','
    rdr = csv.reader(io.StringIO(raw), delimiter=delim)
    try:
        hdr = next(rdr)
    except StopIteration:
        sys.exit(f"ERROR: {os.path.basename(path)} is empty.")
    seen, dupes = set(), []
    for h in hdr:
        if h in seen: dupes.append(h)
        seen.add(h)
    if dupes:
        print(f"  \u26a0 DUPLICATE COLUMN HEADERS -- only the LAST of each is kept: "
              f"{sorted(set(dupes))}")
    return [dict(zip(hdr, r)) for r in rdr if any(str(v).strip() for v in r)]

def _read_xlsx(path, sheet=None):
    try:
        import openpyxl
    except ImportError:
        sys.exit("ERROR: reading .xlsx needs openpyxl.  pip install openpyxl\n"
                 "       (or export the file as .csv, which needs nothing.)")
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    rows = list(ws.values)
    if not rows:
        sys.exit(f"ERROR: sheet '{ws.title}' in {path} is empty.")
    hdr = [str(h) if h is not None else '' for h in rows[0]]
    return [dict(zip(hdr, r)) for r in rows[1:] if any(v is not None for v in r)]

def load(path, sheet=None):
    if not os.path.exists(path):
        sys.exit(f"ERROR: no such file: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.csv', '.tsv', '.txt'):   rows = _read_csv(path)
    elif ext in ('.xlsx', '.xlsm'):       rows = _read_xlsx(path, sheet)
    else: sys.exit(f"ERROR: unsupported file type '{ext}'. Use .csv or .xlsx.")
    rows = [r for r in rows if str(r.get('Name') or '').strip()]
    if not rows:
        sys.exit(f"ERROR: {path} has no rows with a Name column.")
    return rows

def detect_kind(rows, override=None):
    """DRAFT POOL or LEAGUE export.

    G9 -- A POOL MUST PROVE ITSELF.  Counting distinct organisations was not enough.
    A single-team export -- the most natural file a GM produces, his own roster --
    has exactly one ORG and was therefore scored as a draft pool, handing draft-day
    career-WAR projections to 28-year-old major leaguers with no warning anywhere in
    the workbook.  (Adversarial review, 2026-09-19.)

    A pool has NO organisations AND a school/class column.  A league has two or more
    organisations.  Anything else is refused.
    """
    if override:
        k = str(override).strip().upper()
        if k not in ('POOL', 'LEAGUE'):
            sys.exit(f"ERROR: --kind must be POOL or LEAGUE, got {override!r}")
        return k
    cols = set()
    for r in rows[:50]: cols |= set(r.keys())
    orgs = {str(r.get('ORG') or '').strip() for r in rows}
    orgs.discard(''); orgs.discard('-')
    assigned = sum(1 for r in rows if str(r.get('ORG') or '').strip() not in ('', '-'))
    if len(orgs) >= 2:
        return 'LEAGUE'
    if assigned == 0 and (cols & {'HSC', 'Schl', 'School', 'HS/COL'}):
        return 'POOL'
    sys.exit(
        "ERROR: cannot tell whether this is a DRAFT POOL or a LEAGUE export (G9).\n"
        f"       distinct organisations : {len(orgs)}\n"
        f"       rows with an organisation: {assigned} of {len(rows)}\n"
        f"       school/class column     : {'yes' if (cols & {'HSC','Schl','School','HS/COL'}) else 'NO'}\n"
        "\n"
        "       A DRAFT POOL has no organisations and carries a school column (HSC).\n"
        "       A LEAGUE export has two or more organisations.\n"
        "       A SINGLE-TEAM ROSTER is neither.  Career-WAR projection is a draft-day\n"
        "       model (A104) and must never be run on established players.\n"
        "\n"
        "       Re-export the whole league, or set the kind explicitly: on the web\n"
        "       page use the EXPORT KIND selector, on the command line pass --kind\n"
        "       LEAGUE (or --kind POOL).  Forcing LEAGUE on a single-team file gives\n"
        "       you the player-level analysis but suppresses BASELINES and the ACE\n"
        "       CENSUS -- one club cannot supply league context (G10).")

class Frame:
    """Rows plus provenance.  G4 -- the output always says what it was built from."""
    def __init__(self, rows, path, sheet=None, kind=None, orig_name=None):
        self.rows, self.path = rows, os.path.abspath(path)
        self.kind = detect_kind(rows, kind)
        # G10 -- FORCING A KIND DOES NOT CREATE A LEAGUE.  A single-team roster run as
        # --kind LEAGUE would otherwise compute BASELINES and the ACE CENSUS from one
        # club and present them as league context: means, standard deviations and gate
        # counts built from the user's own roster, which reads as authoritative and is
        # not.  Count the organisations once, here, so the workbook can refuse those
        # two sheets while leaving every player-level column intact.  (2026-09-19.)
        _orgs = {str(r.get('ORG') or '').strip() for r in rows}
        _orgs.discard(''); _orgs.discard('-')
        self.n_orgs     = len(_orgs)
        self.forced     = bool(kind)
        self.single_org = (self.kind == 'LEAGUE' and self.n_orgs < 2)
        self.orig_name = orig_name or os.path.basename(self.path)
        self.sheet = sheet
        try:
            self.mtime = datetime.datetime.fromtimestamp(
                os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
        except OSError:
            self.mtime = 'unknown'
        self.loaded = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        self.cols = set()
        for r in rows[:50]: self.cols |= set(r.keys())
        self._org_filtered = False
    def stamp(self):
        return (f"source: {self.orig_name}"
                f"{(' [sheet ' + str(self.sheet) + ']') if self.sheet else ''}"
                f" | file modified {self.mtime} | "
                f"read {self.loaded} | {len(self.rows)} rows | detected {self.kind} | "
                f"ootp_analyze {VERSION}")
    def rostered(self):
        """G3 -- the ONLY way to a baseline.  Drops the unassigned pool."""
        if self.kind == 'POOL':
            raise RuntimeError("a draft pool has no organisations; baselines are a LEAGUE "
                               "concept (G3/G7)")
        f = Frame.__new__(Frame)
        f.__dict__.update(self.__dict__)
        f.rows = [r for r in self.rows if str(r.get('ORG') or '').strip() not in ('', '-')]
        f._org_filtered = True
        return f

# =============================================================================
# FIELD ACCESS.  G1 -- gates physically cannot see a position rating.
# =============================================================================

def num(r, k, default=None):
    v = r.get(k)
    if v is None or v == '': return default
    try: return float(str(v).replace(',', '').replace('$', '').strip())
    except ValueError: return default

def txt(r, k, default=''):
    v = r.get(k)
    return default if v is None else str(v).strip()

class GateView:
    """A read-only view of one player that REFUSES to hand over a position rating.

    G1.  Position ratings are a record of where a man has been PLAYED (the league
    commissioner, unprompted: 'I play the hell out of my prospects in Spring Training
    (mostly to develop their position ratings)').  A draft prospect has played nowhere,
    so the 1977 pool's mean 3B position rating is 10.8 against 54.5 for AC regulars.
    Gating on one excluded the entire draft class from third base.
    """
    __slots__ = ('_r',)
    def __init__(self, r): object.__setattr__(self, '_r', r)
    def __getitem__(self, k):
        if k in FORBIDDEN_IN_GATES:
            raise PermissionError(
                f"'{k}' is a POSITION-EXPERIENCE rating and must never gate a decision (G1/A113). "
                f"Use the TOOLS: IF RNG, IF ARM, OF RNG, OF ARM, C ABI/FRM/ARM.")
        return num(self._r, k)
    def txt(self, k): return txt(self._r, k)

REQUIRED_ANY = ['Name', 'POS', 'Age']
REQUIRED_BAT_TOOLS = ['IF RNG', 'OF RNG', 'OF ARM', 'IF ARM']
REQUIRED_ARM_TOOLS = ['STM']

# G13 -- OOTP PUBLISHES NO BABIP POTENTIAL.  The export's potential block is
# HT/CON/GAP/POW/EYE/K; there is no 'BABIP P' in any OOTP view.  BABIP is therefore
# frozen at its current value in every simulation, by the data, not by choice.  It
# carries 0.085 of the A94 OBP index, so the effect is small -- but it is stated
# rather than discovered.
# ⛔ EMPTIED 2026-09-23.  IT CONTAINED 'BABIP', AND THAT WAS WRONG.
# G13 stated as fact: "OOTP publishes no BABIP potential at all; BABIP is frozen by the
# data."  It does publish one.  THE GM: "BABIP does have a potential column it's called
# hit_P."  In this export it is 'HT P', sitting in the potential block exactly where
# BABIP's belongs -- the current block reads CON BABIP GAP POW EYE K's and the potential
# block reads CON P, HT P, GAP P, POW P, EYE P, K P.  Positional match, and the name is
# HIT, which is what BABIP measures.
#
# VERIFIED before adopting, because a mis-mapped column would corrupt every probability:
#   HT P >= BABIP in 1,547 of 1,547 rows (100%) -- a potential can never sit below current
#   the gap CLOSES with age, which is the signature of a potential and of nothing else:
#      age 17-20  +12.7      24-26  +5.7      30-40  +0.0
#      age 21-23   +8.3      27-29  +3.2
#
# WHAT IT COST: BABIP carries 0.085 of A94's OBP index (16.3% of it), and every player
# was simulated with BABIP FROZEN AT CURRENT.  That understated the on-base ceiling of
# every young bat in the file -- systematically, in the population where potential is the
# whole question.  The guard written to catch a missing potential column instead declared
# one nonexistent, which is worse: a warning would have been visible.
#
# THE LESSON, and it is the day's third instance: a column the tool does not RECOGNISE is
# not a column the game does not HAVE.  Same shape as the per-position fielding split and
# the role lens.  Check the export before declaring an absence.
NO_POTENTIAL_IN_OOTP = frozenset()

def check_columns(fr, verbose=False):
    """G13 -- CHECK THE COLUMNS THAT ACTUALLY DRIVE THE NUMBERS.

    Until 1.3.0 this validated Name/POS/Age and warned on four glove columns, and said
    NOTHING about the ten tool/potential pairs that produce every probability in the
    workbook.  A missing potential column is not an error anywhere in build():

        pot[key] = max(c, p if p is not None else c)   # no potential -> pot = cur

    so the tool simply never develops.  P(ace), P(#2), P(POW55) and P(both) all collapse
    toward zero for that tool, silently, and the workbook looks complete.  Same family as
    G9/G10/G12: the tool knew something the workbook did not say.
    """
    missing = [c for c in REQUIRED_ANY if c not in fr.cols]
    if missing:
        sys.exit(f"ERROR: export is missing required column(s): {missing}\n"
                 f"       found {len(fr.cols)} columns. Run 'columns' to list them.")
    warn = []
    # G17 -- THE COLUMN THE RANK IS BUILT ON MUST EXIST.  From 1.4.0 the ROSTER sheet
    # is ONE FLAT LIST RANKED ON WAR.  Nothing checked that WAR was in the file.  With
    # it absent every player sorts to the bottom on a None and the '#' column numbers
    # the INPUT ORDER 1..N while looking exactly like a ranking -- the silent-failure
    # family, on the sheet a GM reads first.  Arms take WAR_1 (the second WAR column in
    # a combined batting+pitching view); if the view has only one WAR header, every arm
    # reads None and a 6.5-WAR ace ranks below a bench bat.
    if fr.kind == 'LEAGUE':
        if 'WAR' not in fr.cols:
            sys.exit("ERROR: this LEAGUE export has no WAR column (rule 22).\n"
                     "       The ROSTER sheet is ranked on WAR. Without it the '#' column\n"
                     "       would number the input order while looking like a ranking.\n"
                     "       Re-export with WAR, or run --kind POOL if this is a draft class.")
        for col, what in (('PA',   'every bat score reads "G14 -- under 100 PA", which is '
                                   'a statement about your players that is FALSE -- the '
                                   'export simply has no PA column'),
                          ('wRC+', 'the bat runs, the error bar and the total are ALL blank '
                                   'and the sheet still looks complete')):
            if col not in fr.cols:
                warn.append(f"{col} -- ABSENT, so {what}")
        if 'WAR_1' not in fr.cols:
            warn.append("WAR_1 -- there is only ONE WAR column, so every PITCHER reads a "
                        "blank WAR and sorts to the bottom of the ROSTER sheet. Export a "
                        "combined batting+pitching view to rank arms against bats")
    warn += [c for c in REQUIRED_BAT_TOOLS + REQUIRED_ARM_TOOLS if c not in fr.cols]
    for cur, pcol, key in BAT_TOOLS + ARM_TOOLS:
        if cur not in fr.cols:
            warn.append(f"{cur} -- the tool itself is ABSENT; it scores 0 and every "
                        f"probability using it is wrong")
        elif pcol not in fr.cols and key not in NO_POTENTIAL_IN_OOTP:
            warn.append(f"{pcol} -- {key} has NO POTENTIAL column, so it is FROZEN at its "
                        f"current value in every simulation and its upside reads as zero")
    present_forbidden = sorted(FORBIDDEN_IN_GATES & fr.cols)
    if verbose:
        print(f"  columns present : {len(fr.cols)}")
        if warn: print(f"  ⚠ tool columns MISSING (analysis will be limited): {warn}")
        if present_forbidden:
            print(f"  note: position-rating columns present and will be IGNORED for all gates "
                  f"(G1): {present_forbidden}")
    return warn

# =============================================================================
# CORE MODEL
# =============================================================================

def _cum(bands):
    out, t = [], 0.0
    for w, lo, hi in bands: t += w; out.append((t, lo, hi))
    return out
_CUM = _cum(A77_BANDS.v)
_BAND_MEAN = sum(w * (lo + hi) / 2.0 for w, lo, hi in A77_BANDS.v)

def draw(rng):
    """One sample of A77's measured bimodal delivery shape, normalised to mean 1."""
    u = rng.random()
    for t, lo, hi in _CUM:
        if u <= t: return rng.uniform(lo, hi) / _BAND_MEAN
    return 1.0

def simulate(cur, pot, frac, rng, n=NSIM, share=None, clip=True):
    """Where each tool LANDS. cur/pot/frac keyed by tool. Returns {tool: [n samples]}.

    FAST PATH, and it is EXACT, not an approximation: a tool with no gap (pot == cur) or
    no delivery left (frac == 0, i.e. age 26+) cannot move, so its distribution is a point
    mass at its current value. Simulating it would burn 20,000 draws to rediscover that.
    Most of a LEAGUE export is established players and this is what makes the file finish.
    """
    share = SHARE.v if share is None else share
    live = [k for k in cur if abs(pot[k] - cur[k]) > 1e-12 and abs(frac.get(k, 0.0)) > 1e-12]
    out = {}
    for k in cur:
        if k not in live:
            v = min(80.0, max(20.0, cur[k])) if clip else cur[k]
            out[k] = [v] * n
    if not live:
        return out
    for k in live:
        out[k] = []
    rr, dr = rng.random, draw
    for _ in range(n):
        shared = dr(rng)
        for k in live:
            m = shared if rr() < share else dr(rng)
            v = cur[k] + frac[k] * m * (pot[k] - cur[k])
            out[k].append(min(80.0, max(20.0, v)) if clip else v)
    return out

def _q(sv, q):
    """One quantile from an ALREADY-SORTED list."""
    k = (len(sv) - 1) * q; f = int(k)
    return sv[f] if f + 1 >= len(sv) else sv[f] + (sv[f + 1] - sv[f]) * (k - f)

def pct(v, q):
    return _q(sorted(v), q)

def pcts(v, qs):
    """SPEED, 2026-09-20.  P10/P50/P90 each called pct() on the SAME 20,000-sample list,
    so every tool was sorted three times -- 7.4 s of a 41 s pool run, purely re-sorting.
    Sorting is not a random draw: this changes no published number, and verify() proves
    it (the suite is seeded and its expected values are unchanged).
    A point-mass distribution (a tool with no gap) skips the sort entirely."""
    if not v: return [0.0 for _ in qs]
    first = v[0]
    for x in v:
        if x != first: break
    else:
        return [first for _ in qs]        # point mass -- nothing to sort
    sv = sorted(v)
    return [_q(sv, q) for q in qs]

def round5(x): return int(round(x / 5.0) * 5)

def obp_index(eye, con, babip):
    return (OBP_W['EYE']*eye + OBP_W['CON']*con + OBP_W['BABIP']*babip) / OBP_DEN

def lands(gv):
    """Where his GLOVE lets him play.  ONE LADDER -- this is now tools_spot().

    ⛔ MERGED 1.9.2, AND IT FIXED TWO BUGS RATHER THAN ONE.
    This used to run its own cascade, and the cascade BRANCHED ON POS: a man carded in
    the outfield was routed down an outfield-only ladder, a man carded in the infield
    down an infield-only one, and neither could cross. That produced two defects the
    shared ladder does not have:

      1. NO GATE AT THE CORNER. An outfielder who missed CF fell through to 'RF if OF ARM
         clears, else LF' with NO OF RANGE FLOOR AT ALL. A corner outfielder with OF RNG
         30 -- below every line A84 v3 draws -- still 'landed' in left field. Under the
         shared ladder he lands at 1B, where his range says he belongs. This is 114 of
         the 125 bats whose answer changed.
      2. NO CROSSOVER. A carded shortstop whose infield range had gone but whose outfield
         range had not could only fall to 1B; he could never be sent to a corner. Now he
         can (R. Allen: was 1B, is RF).

    Having two ladders that disagreed on 15% of the league's bats was the same defect
    this file has now made three times -- several columns claiming to name 'his position'
    and quietly meaning different things. There is one ladder. See tools_spot().
    """
    return tools_spot(gv)

def eff_pitches(r, potential=False, flat40=False):
    """Count effective pitches.  flat40=True is A103's rule; False is A41's (CH at 45).
    A115 is the OPEN CONFLICT between them -- both are reported, never silently chosen."""
    n = 0
    for p in PITCHES:
        v = num(r, p + 'P' if potential else p)
        if v is None: continue
        floor = PITCH_FLOOR.v if (flat40 or p != 'CH') else CH_FLOOR.v
        if v >= floor: n += 1
    return n

def check_row_widths(title, rows, headers, strict=False):
    """Refuse a sheet whose rows do not match their headings.  Module level ON PURPOSE.

    A row one cell SHORT does not raise -- openpyxl leaves the tail blank and every
    value after the gap sits under the wrong heading.  This lived inside
    write_workbook's closure and the check that was supposed to cover it read the
    WRITTEN sheet with iter_rows(values_only=True), which pads every row out to
    max_column: the assertion could not fail, and review proved it by disabling the
    guard and truncating a row.  Out here, verify() can drive the guard itself.

    A row LONGER than its headings is a bug on any sheet.  Exact width is required on
    the PLAYER GRIDS; the report sheets use short rows and blank spacers as layout.
    """
    for i, r in enumerate(rows):
        if len(r) > len(headers) or (strict and len(r) != len(headers)):
            sys.exit(f"ERROR: sheet '{title}' row {i+1} has {len(r)} cells against "
                     f"{len(headers)} headers. Every value after the first gap would "
                     f"sit under the wrong column. Nothing has been written.")
    return True


def pct_column_index(headers, name, sheet='?'):
    """Resolve a percent column BY ITS HEADING.  Module level ON PURPOSE -- as_percent()
    calls this, and so does verify(), so the test drives the shipped code rather than a
    copy of it.  That distinction is the whole reason this file has 157 checks.

    A probability formatted as a plain float reads 0.2 for 19.5%.  That is G2, and G2
    has already cost us once, so both failures are loud.
    """
    if name not in headers:
        sys.exit(f"ERROR: cannot format '{name}' on sheet '{sheet}' -- no such column. "
                 f"A percent column would have shipped as a raw fraction (G2).")
    if headers.count(name) > 1:
        sys.exit(f"ERROR: sheet '{sheet}' has {headers.count(name)} columns headed "
                 f"'{name}'. index() would format the first and leave the rest as raw "
                 f"fractions (G2). Nothing has been written.")
    return headers.index(name)


def _probe_width(row, headers):
    """verify() handle onto check_row_widths, at the strictness a player grid uses."""
    return check_row_widths('probe', [row], headers, strict=True)


def pos_adj_runs(landing):
    """A74 runs/season, SCALED BY PLAYING TIME (A114/G8).  Career-WAR path only."""
    return A74_POS.v.get(landing, 0.0) * PT_RATIO.v.get(landing, 1.0)

GLOVE_REF = C({'C': {'rng':30.3,'arm':44.9,'tdp':24.7},
               '1B':{'rng':42.8,'arm':42.5,'tdp':39.2},
               '2B':{'rng':59.0,'arm':51.8,'tdp':60.4},
               '3B':{'rng':53.9,'arm':65.1,'tdp':45.7},
               'SS':{'rng':66.4,'arm':64.2,'tdp':63.3},
               'LF':{'rng':53.2,'arm':54.0,'tdp':28.1},
               'CF':{'rng':64.2,'arm':57.0,'tdp':34.7},
               'RF':{'rng':56.2,'arm':60.1,'tdp':27.8}},
 "THE REFERENCE IS NAMED, AND THAT IS THE WHOLE POINT: the average AC player AT THAT "
 "POSITION, rostered, >=300 defensive innings, measured 2026-09-22 (n = 30 to 46 per "
 "spot). Change the reference and every number shifts by a constant; the ORDER and the "
 "SIGNS do not move.", 'MEASURED')


def gates_ok(gv, pos):
    """A84 v3's BREAK-EVEN lines, innings-weighted AC means. TOOLS ONLY (G1).

    ⚠ A84's own warning: a gate is a property of THIS league's population, not of the
    engine. None of it transfers to a new league -- carrying AC gates elsewhere is the
    error A108 reversed.
    """
    ifr, ifa = gv['IF RNG'] or 0.0, gv['IF ARM'] or 0.0
    ofr = gv['OF RNG'] or 0.0
    if pos == 'C':  return (gv['C ABI'] or 0) >= CATCH_GATE.v
    if pos == 'SS': return ifr >= GATE_SS.v
    if pos == '2B': return ifr >= GATE_2B.v
    if pos == '3B': return ifr + ifa >= GATE_3B_SUM.v      # pocket rule 5, n=17,459
    if pos == 'CF': return ofr >= GATE_CF.v
    if pos in ('LF', 'RF'): return ofr >= GATE_CORNER_OF.v
    if pos == '1B': return True                            # A110, the terminal position
    return False


def glove_runs(gv, pos):
    """Does his glove HELP or HURT at `pos`?  ONE number, runs per 150 games.

    ⛔ THE HISTORY MATTERS, because this function was wrong twice in opposite directions
    before it was right.
      v1.8.0 removed baselines entirely after they broke a CROSS-position comparison.
      That was an over-correction. A baseline only fails to cancel when you compare one
      man's SHORTSTOP number against his FIRST BASE number, because the two are
      multiplied by different range values. Comparing a man against THE OTHER MEN AT HIS
      OWN POSITION is the case where it cancels perfectly -- it is just a choice of zero.
    So: name the reference, use it, and never add these across positions.

    Returned a (low, high) PAIR until 2026-09-23, because A73 left the arm term open
    between ~0 and 4.0 runs per +5 and the tool refused to pick a side.  That conflict is
    now CLOSED by measurement -- see GLOVE_ARM5 -- so this returns a single number.
    """
    if pos not in GLOVE_REF.v or pos == 'C':
        return None              # A58a: catcher defence is a null, p=.921, n=1,044
    m = GLOVE_REF.v[pos]
    rc = 'OF RNG' if pos in _OF else 'IF RNG'
    ac = 'OF ARM' if pos in _OF else 'IF ARM'
    g = lambda k: (gv[k] or 0)
    base = (g(rc) - m['rng']) / 5.0 * GLOVE_RANGE5.v[pos]
    if pos in ('2B', 'SS'):
        base += (g('TDP') - m['tdp']) / 5.0 * GLOVE_TDP_RUNS5.v
    base += (g(ac) - m['arm']) / 5.0 * GLOVE_ARM5.v[pos]
    return round(base, 1)


TOOLS_LADDER = C(('SS', 'CF', '2B', '3B', 'C', 'RF', 'LF', '1B'),
 "THE DEFENSIVE SPECTRUM, hardest job first. Set by the GM 2026-09-23: 'gate guys then "
 "place them in order of SS, CF, 2B, 3B, C, RF, LF, 1B ... so they get graded at the "
 "highest position'. NOTE it is NOT A74's run order, which pays 3B (+2.51) above CF "
 "(+1.56) above 2B (+1.19); this is the scarcity spectrum, which is the GM's call and "
 "is the convention every other baseball reader already has in his head.", 'CONVENTION')


def tools_spot(gv):
    """THE HIGHEST RUNG ON THE SPECTRUM HIS TOOLS CLEAR.  One answer, not a sort.

    ⛔ THIS REPLACED glove_by_position() ON 2026-09-23 AND THE REASON MATTERS.
    That column priced the glove at all eight spots and sorted them BEST FIRST. An audit
    showed the order was 81% an artifact of the reference: 604 of 620 rows changed order
    and 502 of 620 changed their BEST position under an alternate baseline. A run number
    computed against a per-position mean does not carry a meaning that survives being
    ranked across positions -- which is KEY rule 3, broken by the one column built to
    stop threads misreading positional value.

    A FIXED SPECTRUM HAS NO SUCH DEGREE OF FREEDOM. The order is a convention, declared
    in TOOLS_LADDER; the only measured input is pass/fail at each gate. Move the
    reference and this answer does not move.

    Runs on TOOLS ONLY (G1) -- gv cannot return a position rating. Catcher sits on the
    ladder at its C ABI gate and is nearly self-selecting: 129 of 132 AC catchers clear
    it and only 4 of 727 non-catchers do, so the rung neither strips catchers nor
    collects anyone else (measured on the 2026-09-23 export, 1 catcher of 132 clears a
    rung above C). Gloves are FIXED (A50); range declines with age (A19).
    """
    ifr, ifa = gv['IF RNG'] or 0.0, gv['IF ARM'] or 0.0
    ofr, ofa = gv['OF RNG'] or 0.0, gv['OF ARM'] or 0.0
    for q in TOOLS_LADDER.v:
        if q == 'RF':
            # rule 5: at the corner, OF ARM is what splits RF from LF.
            if ofr >= GATE_CORNER_OF.v and ofa >= GATE_RF_ARM.v: return 'RF'
            continue
        if q == '1B':
            return '1B'             # A110: the terminal position. Everyone clears it.
        if gates_ok(gv, q): return q
    return '1B'


def glove_verdict(v):
    """HELPS / HURTS / neutral.  The SIGN is the answer; the magnitude is the size of it."""
    if v is None: return ''
    if v > 1.0:  return 'HELPS'
    if v < -1.0: return 'HURTS'
    return 'neutral'


def at_break_even(gv, pos):
    """Is he above the line where a fielder STOPS COSTING RUNS at this position?

    ⛔ THIS IS NOT AN ELIGIBILITY FILTER, AND USING IT AS ONE WAS A MISTAKE.
    A84 v3 defines its gates as "at what rating does a fielder stop COSTING runs" -- a
    BREAK-EVEN line. Measured on the AC's own regulars (>=500 defensive innings), 22% to
    42% of the men actually holding each job fall below it: SS 22%, CF 24%, 2B 30%,
    RF 34%, LF 37%, 1B 38%, 3B 42%. A filter that excludes two-fifths of real third
    basemen is not describing who CAN play there.

    And the line is real: EVERY AC shortstop regular below RNG 65 posted NEGATIVE ZR,
    without exception, while nearly every one at 70+ was positive. Clubs play men below
    the line knowingly and pay for it in runs -- which glove_runs() already prices
    continuously. So this returns a LABEL, never a verdict, and nothing moves a player.
    """
    return gates_ok(gv, pos)


def pos_runs_600(pos):
    # G18 -- see PITCHER_ROLES.  A74 is a table of POSITIONS.  Handing it 'SP' returns
    # the .get() default of 0.0, which reads on the sheet as "an average position" --
    # a plausible number for a question that has no answer.  Refuse it instead.
    if pos in PITCHER_ROLES:
        sys.exit(f"ERROR: '{pos}' is a pitcher ROLE, not a position (rule 22).\n"
                 f"       A74 prices positions and has no entry for a pitcher. A role\n"
                 f"       reaching this function would print 0.0 and read as average.")
    """A74's positional adjustment AS PUBLISHED -- runs per 600 PA, no PT_RATIO.

    A114 requires the playing-time scaling on the path to CAREER WAR, because eight
    career seasons of a catcher are not eight full seasons of plate appearances.  It
    does NOT require it to display a rate.  A74's own denominator is 600 PA, so a
    rate column that stays there needs no conversion and cannot be tripped up by the
    fact that A114's ratio is relative to first base rather than to 600.
    """
    return A74_POS.v.get(pos, 0.0)

def bat_runs_600(wrc):
    """Position-FREE bat value, runs per 600 PA above the A74 population mean.

    The mirror image of pos_adj_runs(): same slope, same units, no position term at
    all.  A 1B and a SS with the same wRC+ get the same number here, which is the
    whole point -- it is 'what the bat is worth' before anyone asks where he stands.
    """
    if wrc is None: return None
    return (float(wrc) - WRC_MEAN.v) * RUNS_PER_WRC.v


def wrc_se_runs(pa):
    """1 standard error of the bat score, in runs, READ OFF THE MEASURED TABLE.

    Not a fitted curve.  See WRC_NOISE_SD for why the fit was withdrawn: k = SD*sqrt(PA)
    came out 308 / 265 / 278 / 210 across the four bands, so SD = k/sqrt(PA) does not
    describe this population and publishing one k made the bar ~7% wide purely by which
    bands were included.

    Above the top band the excess is not measurable at all -- that band IS the talent
    floor the others were measured against -- so it returns that band's value, which is
    an upper bound there.
    """
    if pa is None or pa <= 0: return None
    for hi, sd in WRC_NOISE_SD.v:
        if pa < hi: return sd * RUNS_PER_WRC.v
    return WRC_NOISE_SD.v[-1][1] * RUNS_PER_WRC.v


def bat_runs(wrc, pa=None, rostered=True, kind='LEAGUE'):
    """The position-free bat score that reaches the sheet, WITH its refusals.

    ⛔ CORRECTED 2026-09-22, BEFORE SHIPPING.  The first cut of this returned
    bat_runs_600(wrc) * PT_RATIO[landing] and the column was labelled '(NO pos)'.
    It was not: the same bat read 39.69 at first base and 33.34 at catcher, a 6.35-run
    spread driven entirely by the position it claimed not to contain, in the one
    column built so the position could be read separately.  The playing-time scaling
    is also where the units go soft -- A74 publishes RUNS PER 600 PA, and A114's ratio
    is PA relative to FIRST BASE, not relative to 600, so the two agree only because
    a first baseman's projected full season happens to land near 600 PA.  Both
    problems die the same way: everything on this sheet stays PER 600 PA, which is
    A74's own denominator, and PT_RATIO is used only where A114 requires it -- the
    conversion to CAREER WAR (G8), which is untouched.

    Returns (runs, refusal) -- exactly one is None.  The refusal is a short string,
    because three different reasons previously arrived as one undifferentiated blank.
    """
    if wrc is None:
        return None, 'no wRC+ in the export'
    if not math.isfinite(float(wrc)):
        return None, 'wRC+ is not a finite number'
    if kind != 'LEAGUE':
        # G7.  A104's own pools clear no major-league bar; WRC_MEAN is the AC's
        # full-time MAJOR LEAGUER mean and an amateur priced against it is the
        # same error G7 exists for.
        return None, 'G7 -- draft pool, and 110.8 is a major-league mean'
    if not rostered and float(wrc) == float(WRC_FILL.v):
        return None, f'G15 -- unassigned, wRC+ {WRC_FILL.v} is a fill value'
    if pa is not None and pa < BAT_RUNS_MIN_PA.v:
        return None, f'G14 -- under {BAT_RUNS_MIN_PA.v} PA'
    return bat_runs_600(wrc), None


def pos_adj_war(landing, seasons=None, rpw=None):
    seasons = SEASONS_DEFAULT.v if seasons is None else seasons
    rpw = RUNS_PER_WIN.v if rpw is None else rpw
    return pos_adj_runs(landing) * seasons / rpw

def klass(r):
    h = txt(r, 'HSC') or txt(r, 'Class') or txt(r, 'School')
    if h.startswith('HS'): return 'HS'
    if h.startswith('JuCo'): return 'JuCo'
    if 'Junior' in h or h.startswith('JR'): return 'JR'
    if h: return 'SR'
    return 'SR'

def stars(r, key):
    v = txt(r, key).replace('Stars', '').replace('Star', '').strip()
    try: return float(v)
    except ValueError: return None

BAT_TOOLS = [('CON','CON P','CON'), ('GAP','GAP P','GAP'), ('POW','POW P','POW'),
             ('EYE','EYE P','EYE'), ('BABIP','HT P','BABIP'), ("K's",'K P','AVK')]
ARM_TOOLS = [('STU','STU P','STU'), ('MOV','MOV P','MOV'),
             ('CON_1','CON P_1','PCON'), ('HRA','HRA P','HRA')]
BAT_CORE, ARM_CORE = ['CON','POW','EYE','BABIP'], ['STU','MOV','PCON','HRA']

# ⚠ SP / RP / CL IN THE 'POS' COLUMN ARE ROLES, NOT POSITIONS.  The GM, 2026-09-22:
# "if you see sp rp cl that means you are looking at role not position for pitchers."
# A pitcher's POSITION is P.  A74 prices POSITIONS and has no entry for a pitcher, so
# a role string must never reach it -- see PITCHER_ROLES and G18.
PITCHER_ROLES = frozenset({'SP', 'RP', 'CL'})

def is_arm(r): return txt(r, 'POS') in PITCHER_ROLES

def build(fr, rng=None):
    """One record per player: tools now/potential, simulated landing spots, gates."""
    rng = rng or random.Random(SEED)
    out = []
    total = len(fr.rows)
    for i, r in enumerate(fr.rows):
        if total > 300 and i and i % 250 == 0:
            print(f"    ... {i}/{total}", flush=True)
        age = num(r, 'Age')
        if age is None: continue
        age = int(age)
        arm = is_arm(r)
        tools = ARM_TOOLS if arm else BAT_TOOLS
        table = (A76_ARM if arm else A76_BAT).v
        frac = table[min(max(age, 16), 26)]
        cur, pot = {}, {}
        for col, pcol, key in tools:
            c = num(r, col, 0.0)
            p = num(r, pcol)
            cur[key] = c
            pot[key] = max(c, p if p is not None else c)
        sims = simulate(cur, pot, frac, rng)
        gv = GateView(r)
        p = dict(name=txt(r, 'Name'), pos=txt(r, 'POS'), age=age, side='ARM' if arm else 'BAT',
                 cls=klass(r), org=txt(r, 'ORG'), team=txt(r, 'TM'),
                 ovr_star=stars(r, 'OVR'), pot_star=stars(r, 'POT'),
                 risk=txt(r, 'Risk'), prone=txt(r, 'Prone'),
                 cur4=sum(cur[k] for k in (ARM_CORE if arm else BAT_CORE)) / 4.0,
                 gap4=sum(pot[k] - cur[k] for k in (ARM_CORE if arm else BAT_CORE)) / 4.0)
        for _c, _p, key in tools:
            p[key + '_now'] = int(cur[key]); p[key + '_pot'] = int(pot[key])
            _a, _b, _c2 = pcts(sims[key], (.10, .50, .90))
            p[key + '_P10'] = round5(_a)
            p[key + '_P50'] = round5(_b)
            p[key + '_P90'] = round5(_c2)
        n = NSIM
        if arm:
            p['stm'] = int(num(r, 'STM', 0))
            p['eff_now']  = eff_pitches(r)                 # A41 rule
            p['eff_flat40'] = eff_pitches(r, flat40=True)  # A103 rule
            p['eff_conflict'] = p['eff_now'] != p['eff_flat40']   # A115
            p['eff_pot']  = eff_pitches(r, potential=True)
            p['arsenal'] = ' '.join(f"{q}{int(num(r,q))}>{int(num(r,q+'P') or 0)}"
                                    for q in PITCHES if (num(r, q) or 0) > 0)
            p['gf'], p['velo'] = txt(r, 'G/F'), txt(r, 'VELO')
            # A115 IS OPEN.  Report the verdict under BOTH counting rules; never pick one.
            p['role_gate']        = p['stm'] >= GATE_STM.v and p['eff_now']     >= GATE_EFF.v
            p['role_gate_flat40'] = p['stm'] >= GATE_STM.v and p['eff_flat40']  >= GATE_EFF.v
            p['role_flips'] = p['role_gate'] != p['role_gate_flat40']
            C_, H_ = sims['PCON'], sims['HRA']
            p['p_ace'] = Pct(sum(1 for i in range(n) if C_[i] >= ACE_CON.v and H_[i] >= ACE_HRA.v) / n)
            p['p_no1'] = Pct(sum(1 for i in range(n) if C_[i] >= NO1_CON.v and H_[i] >= NO1_HRA.v) / n)
            p['p_no2'] = Pct(sum(1 for i in range(n) if C_[i] >= NO2_CON.v and H_[i] >= NO2_HRA.v) / n)
        else:
            p['if_rng'] = int(num(r, 'IF RNG', 0)); p['if_arm'] = int(num(r, 'IF ARM', 0))
            p['if_err'] = int(num(r, 'IF ERR', 0)); p['tdp'] = int(num(r, 'TDP', 0))
            p['of_rng'] = int(num(r, 'OF RNG', 0)); p['of_arm'] = int(num(r, 'OF ARM', 0))
            p['c_abi'] = int(num(r, 'C ABI', 0)); p['c_frm'] = int(num(r, 'C FRM', 0))
            p['c_arm'] = int(num(r, 'C ARM', 0)); p['spe'] = int(num(r, 'SPE', 0))
            p['lands'] = lands(gv)
            # A104 fitted range against the LISTED position, not the landing spot.
            p['rng_listed'] = p['of_rng'] if p['pos'] in ('LF','CF','RF') else p['if_rng']
            # G16.  ONE decision, used by EVERY positional column on every sheet.
            # 'priced at' is where the club CARDS him -- POS, the engine's designation --
            # and it is where A74's bar is applied.  'lands' is where his RATINGS put him.
            # They disagree for 45% of the league, which is why both are printed.
            p['priced_at'] = p['pos'] if (fr.kind == 'LEAGUE' and p['pos'] in A74_POS.v) \
                             else p['lands']
            # ⛔ CUT 1.9.2: 'glove gates into' listed EVERY rung he cleared, C > SS > 2B >
            # 3B > RF > LF > 1B. The GM asked for the top of that list and nothing else
            # ("highest only is needed"), and the full string invited the same
            # cross-position reading that sank glove_by_position(). tools_spot() ships
            # the head of the ladder; the rest is recoverable from the raw tool columns,
            # which are four cells to the left.
            p['pos_runs_600'] = round(pos_runs_600(p['priced_at']), 2)
            # THE ANSWER THE GM ASKED FOR: does the glove HELP or HURT where he plays.
            p['glove_here'] = glove_runs(gv, p['priced_at'])
            p['glove_verdict'] = glove_verdict(p['glove_here'])
            # THE SECOND QUESTION: where ELSE do his tools qualify him, highest only.
            # ⚠ READ 'glove runs THERE' BEFORE ACTING ON 'tools qualify at'.
            # I predicted this number would sit near zero by construction, on the logic
            # that the gate IS the break-even line. MEASURED ON THE AC, THAT IS FALSE:
            # mean +1.5, median +1.1, but 68 of 280 regulars are NEGATIVE at their own
            # tools spot and the floor is -19.8. The reason is that THE GATES AND THE RUN
            # MODEL DO NOT READ THE SAME TOOLS. SS, 2B and CF gate on RANGE ALONE, while
            # glove_runs() prices range AND arm AND turn-double-play. So a second baseman
            # with shortstop range and a second baseman's ARM clears the SS gate and is
            # still badly negative at short -- D. Bieler reads +14.9 at second and -7.5
            # at the spot this column promotes him to.
            # CLEARING A GATE IS NOT THE SAME AS BEING PLAYABLE THERE. The two cells must
            # be read together; the position alone is not the finding.
            p['tools_spot'] = tools_spot(gv)
            p['glove_tools'] = glove_runs(gv, p['tools_spot'])
            p['at_break_even'] = ('--' if p['priced_at'] == 'C'
                                  else ('yes' if at_break_even(gv, p['priced_at']) else 'below'))
            p['pos_runs'] = round(pos_adj_runs(p['priced_at']), 2)
            p['pos_war']  = round(pos_adj_war(p['priced_at']), 2)
            ob = [obp_index(sims['EYE'][i], sims['CON'][i], sims['BABIP'][i]) for i in range(n)]
            p['obp_now'] = round(obp_index(cur['EYE'], cur['CON'], cur['BABIP']))
            _o1, _o2, _o3 = pcts(ob, (.10, .50, .90))
            p['obp_P10'], p['obp_P50'], p['obp_P90'] = round(_o1), round(_o2), round(_o3)
            p['p_pow']  = Pct(sum(1 for v in sims['POW'] if v >= BAR_POW.v) / n)
            p['p_obp']  = Pct(sum(1 for v in ob if v >= BAR_OBP.v) / n)
            p['p_both'] = Pct(sum(1 for i in range(n)
                                  if sims['POW'][i] >= BAR_POW.v and ob[i] >= BAR_OBP.v) / n)
        # live stats, if the export carries them
        p['ip'] = num(r, 'IP', 0.0) or 0.0
        p['pa'] = num(r, 'PA', 0.0) or 0.0
        p['fip_minus'] = num(r, 'FIP-')
        p['wrc_plus'] = num(r, 'wRC+')
        p['war'] = num(r, 'WAR_1') if arm else num(r, 'WAR')
        # POSITION-FREE bat value.  Must come AFTER the live-stats block above,
        # because it is built from wRC+ and gated on PA (G14).
        p['rostered'] = str(r.get('ORG') or '').strip() not in ('', '-')
        if arm:
            p['bat_runs'] = p['tot_runs'] = p['bat_se'] = None
            p['bat_note'] = ''
            p['priced_at'] = p['pos_runs_600'] = None
            # a pitcher has no A74 position and no glove term -- G18
            p['glove_here'] = p['glove_tools'] = p['tools_spot'] = None
            p['glove_verdict'] = p['at_break_even'] = None
        else:
            # ⚠ Below the PA floor the CARDED position is a FILING DECISION, not a plan
            # (G14's reasoning, applied to the glove). Refuse the carded-spot glove number
            # and send the reader to the tools column, which does not depend on the filing.
            # ⛔ G21, 1.9.2: the refusal used to print the prose in 'helps or hurts' and
            # LEAVE THE NUMBER STANDING in the cell beside it -- 87 of 100 affected rows
            # published a run figure next to the sentence 'this spot is a label'. A refusal
            # that the adjacent cell contradicts is not a refusal. Both cells now clear.
            if (p['pa'] or 0) < BAT_RUNS_MIN_PA.v:
                p['glove_verdict'] = ('carded spot is a LABEL at this sample -- '
                                      'read "tools qualify at"')
                p['glove_here'] = None
                p['at_break_even'] = None
            br, why = bat_runs(p['wrc_plus'], p['pa'], p['rostered'], fr.kind)
            p['bat_note'] = why or ''
            p['bat_runs'] = None if br is None else round(br, 2)
            p['tot_runs'] = None if br is None else round(br + p['pos_runs_600'], 2)
            se = wrc_se_runs(p['pa']) if br is not None else None
            p['bat_se'] = None if se is None else round(se, 1)
        out.append(p)
    return out

# =============================================================================
# CAREER WAR (draft pools only).  Intercepts recovered from A104's own board.
# =============================================================================

def _bat_raw(p, b0):
    """⚠ A104 fitted b_range against the range the player carries at the position he is
    LISTED at on draft day, so that is what the model must use. `lands` is a SEPARATE
    read -- the glove gate — and substituting it here double-counts the glove and
    silently changes every intercept. (Caught in audit, 2026-09-17.)"""
    b_cur, b_gap, b_rng = A104_BAT.v[p['cls']]
    return (b0 + b_cur * p['cur4'] + b_gap * p['gap4']
            + b_rng * (p['rng_listed'] - POSMEAN.v.get(p['pos'], 45.0)))

def _arm_raw(p):
    b_cur, b_gap, b_eff, b_stm = A104_ARM.v
    return b_cur*p['cur4'] + b_gap*p['gap4'] + b_eff*p['eff_now'] + b_stm*p['stm']

def _pooled(side):
    tot = sum(m * n for (sd, _c), (m, n) in A104_WAR.v.items() if sd == side)
    cnt = sum(n for (sd, _c), (m, n) in A104_WAR.v.items() if sd == side)
    return tot / cnt

def score(players):
    """E[career WAR] on A104's model.  A104 publishes coefficients but NO intercepts.

    HS bats  MEASURED. A least-squares fit with an intercept has fitted mean = sample mean,
             and range enters centred so its mean term is zero:
                 23.3 = b0 + 1.026*29.5 - 0.036*31.9  ->  b0 = -5.82
             Cross-check off s6's four HS names: -5.62, -5.71, -6.68, -8.02.
    SR bats  ESTIMATED from one point (Renshaw, 24.6).
    JR/JuCo  ESTIMATED: class mean set above the HS class mean by s5's implied offset.
    ARMS     ESTIMATED: pool arm mean set below pool bat mean in s5's measured ratio.
             NOT anchored on any single name -- doing that on Mazzola drags every arm down
             by 6.6 WAR, because A104 records his current level as 30.0 and the export reads 36.2.

    The A74 positional adjustment is then added SEPARATELY, because A104 has no position
    term at all (range is centred within position, so the model cannot price position).
    That makes ewar_adj an estimate stacked on an estimate; it is labelled, not hidden.
    """
    bats = [p for p in players if p['side'] == 'BAT']
    arms = [p for p in players if p['side'] == 'ARM']
    if not bats:
        # G12 -- AN ARMS-ONLY POOL CANNOT BE SCORED, AND MUST SAY SO.
        # A104 publishes coefficients but NO intercepts.  The arm intercept a0 is derived
        # from the BAT MEAN OF THE SAME POOL (see below), so with no bats there is no scale
        # to put the arms on.  The old code set every ewar to None and returned quietly:
        # the workbook came out stamped 'detected POOL' with an empty E[WAR] column and
        # nothing anywhere explaining it, which reads as a broken tool.  Rule 22: fail loud.
        for p in players:
            p['ewar'] = p['ewar_adj'] = None
            p['ewar_blocked'] = (
                "E[career WAR] NOT COMPUTED -- this export contains NO BATTERS. A104 "
                "publishes no intercepts, and the arm intercept is derived from the bat "
                "mean of the same pool, so arms cannot be placed on a career-WAR scale "
                "without them. Every other column is unaffected. Re-export the whole pool "
                "to get E[WAR]. (G12)")
        return {}
    b_cur, b_gap, _ = A104_BAT.v['HS']
    b0 = {'HS': round(A104_WAR.v[('BAT','HS')][0] - b_cur*A104_HS_CUR - b_gap*A104_HS_GAP, 2)}
    # The SR intercept is recovered from ONE published board point (A104 s6).  If that
    # player is absent -- i.e. any pool that is not the 1977 class -- the old code fell
    # through to the HS intercept, which was fitted for b_cur=1.026 and is being applied
    # to the SR coefficient set (b_cur=0.288).  That understated every senior bat by
    # ~11 career WAR on a single ranked board, silently.  FAIL LOUD instead (rule 22).
    ren = next((p for p in bats if p['name'] == 'Roger Renshaw'), None)
    if ren is not None:
        b0['SR'] = round(A104_BOARD.v['Roger Renshaw'] - _bat_raw(ren, 0.0), 2)
    elif any(p['cls'] == 'SR' for p in bats):
        sys.exit(
            "ERROR: cannot scale the college-SENIOR bats (rule 22).\n"
            "       A104 publishes coefficients but no intercepts.  The SR intercept is\n"
            "       recovered from one named point on A104's own board ('Roger Renshaw'),\n"
            "       and he is not in this file.\n"
            f"       {sum(1 for p in bats if p['cls']=='SR')} senior bats would be mis-scaled by roughly 11 career WAR.\n"
            "       Re-fit the SR intercept before scoring a pool that is not the 1977 class.")
    else:
        b0['SR'] = b0['HS']   # no SR bats present; the value is never used
    hs = [p for p in bats if p['cls'] == 'HS']
    hs_mean = (sum(_bat_raw(p, b0['HS']) for p in hs) / len(hs)) if hs else A104_WAR.v[('BAT','HS')][0]
    for cl in ('JR', 'JuCo'):
        grp = [p for p in bats if p['cls'] == cl]
        off = A104_WAR.v[('BAT', cl)][0] - A104_WAR.v[('BAT','HS')][0]
        b0[cl] = round(hs_mean + off - sum(_bat_raw(p, 0.0) for p in grp)/len(grp), 2) if grp else b0['HS']
    for p in bats:
        p['ewar'] = round(_bat_raw(p, b0.get(p['cls'], b0['HS'])), 1)
    if arms:
        bat_mean = statistics.mean(p['ewar'] for p in bats)
        a0 = round(bat_mean * (_pooled('ARM')/_pooled('BAT'))
                   - sum(_arm_raw(p) for p in arms)/len(arms), 2)
        for p in arms: p['ewar'] = round(a0 + _arm_raw(p), 1)
    for p in players:
        # G16: the SAME key as every other positional column.  This read p['lands']
        # directly until 2026-09-22; it agreed only because priced_at == lands on a
        # pool, which is one edit from splitting the BOARD's '+pos' from the column
        # the board is ranked on.
        p['ewar_adj'] = round(p['ewar'] + (pos_adj_war(p['priced_at'])
                                           if p['side']=='BAT' else 0.0), 1)
    players.sort(key=lambda p: -(p['ewar_adj'] if p['ewar_adj'] is not None else -1e9))
    return b0

# =============================================================================
# LEAGUE ANALYSIS
# =============================================================================

def baselines(fr):
    """AC rating baselines.  G3 -- refuses an unfiltered frame."""
    if not fr._org_filtered:
        raise RuntimeError("baselines() requires a ROSTERED frame. Call fr.rostered() first. "
                           "The unassigned pool drags every starter mean down 5-6 points (G3).")
    out = {}
    def blk(sel, keys):
        d = {}
        for k in keys:
            v = [num(r, k) for r in sel if num(r, k) is not None]
            d[k] = (round(statistics.mean(v),1), round(statistics.pstdev(v),1), len(v)) if v else None
        return d
    st = [r for r in fr.rows if (num(r,'GS_1',0) or 0) >= 15]
    rp = [r for r in fr.rows if (num(r,'G_1',0) or 0) >= 20 and (num(r,'GS_1',0) or 0) < 6]
    bt = [r for r in fr.rows if (num(r,'PA',0) or 0) >= 200]
    out['starters'] = (len(st), blk(st, ['STU','MOV','CON_1','PBABIP','HRA','STM','PIT']))
    out['relievers'] = (len(rp), blk(rp, ['STU','MOV','CON_1','HRA','STM','PIT']))
    out['batters']  = (len(bt), blk(bt, ['CON','GAP','POW','EYE','BABIP',"K's",'IF RNG','OF RNG']))
    return out

def league_report(fr, players):
    """Ace / #1 / #2 census and the club-by-club view."""
    fr.rostered()   # G3 -- still raises on a POOL
    # G3 FIX (2026-09-19): filtering by NAME-SET membership let unassigned players
    # ride in on a rostered namesake.  The reference league file carries 42 duplicate
    # names; 7 of them were arms, and one unassigned 'M. Brown' was being counted as
    # a potential ace.  Filter on the player's OWN organisation.
    P = [p for p in players
         if p['side'] == 'ARM' and str(p.get('org') or '').strip() not in ('', '-')]
    def clears(p, c, h): return p['PCON_now'] >= c and p['HRA_now'] >= h
    rep = {
      'n_arms': len(P),
      'ace_now':  [p for p in P if clears(p, ACE_CON.v, ACE_HRA.v)],
      'no1_now':  [p for p in P if clears(p, NO1_CON.v, NO1_HRA.v)],
      'ace_pot':  [p for p in P if p['PCON_pot'] >= ACE_CON.v and p['HRA_pot'] >= ACE_HRA.v],
    }
    return rep

# =============================================================================
# OUTPUT
# =============================================================================

def _auto(ws):
    try:
        from openpyxl.utils import get_column_letter
    except ImportError:
        return
    for i, col in enumerate(ws.iter_cols(), 1):
        w = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(i)].width = min(max(w + 2, 8), 44)

def rank_floor_and_ceiling(players):
    """G11 -- THE SORT IS A CLAIM, SO NAME IT.

    Two rankings per side, never one:

      FLOOR   = E[WAR] (bats: +pos).  A104, fitted on CAREER WAR, which rewards a
                long adequate career.  Its gap coefficient is NEGATIVE for college
                bats, so a big current-to-potential gap LOWERS the projection.
      CEILING = P(both) for bats (A94's two bars together), P(#2) for arms (A112).
                The chance the player is actually GOOD, not merely long-serving.

    Each player gets both ranks, each as a percentile in [0,1] where 0 is best, and
    a PROFILE tag from the gap between them.  A player two quartiles better on one
    axis than the other is named as such; everyone else is BALANCED.

    The tag is a description of this board, not a recommendation.  Which axis a GM
    should buy depends on his club, his park and what is left in the pool -- the
    tool's job is to stop the sort from making that choice silently.
    """
    THRESH = 0.25            # two quartiles apart before we call it either way
    for side, floor_key, ceil_key in (
            ('BAT', lambda p: (p.get('ewar_adj') if p.get('ewar_adj') is not None
                               else p.get('ewar')), lambda p: float(p['p_both'])),
            ('ARM', lambda p: p.get('ewar'),        lambda p: float(p['p_no2']))):
        grp = [p for p in players if p['side'] == side]
        n = len(grp)
        # FIX 2026-09-20, caught on the first real run.  On a LEAGUE export E[WAR] is
        # deliberately None (A104 is a DRAFT-DAY model), so the floor sort fell back to
        # input order and every player came out BALANCED -- a meaningless rank printed as
        # a real one, which is the exact failure this guard exists to prevent.  A rank
        # that cannot be computed says so.
        if not any(floor_key(p) is not None for p in grp):
            # ⛔ CORRECTED 2026-09-22, adversarial review.  The 2026-09-20 fix threw away
            # the CEILING rank as well, and the ceiling is perfectly computable -- p_both
            # and p_no2 are populated on every export.  The result was three advertised
            # columns dead on the only kind of file that produces them, with the profile
            # column carrying the only explanation.  Blank the rank you cannot compute;
            # publish the one you can.
            # ⛔ CORRECTED AGAIN 2026-09-22.  The first version of this ranked the whole
            # group on the ceiling bar.  On the live AC file 818 of 860 bats have
            # P(both) = 0.0% -- they do not clear A94's two bars in ANY of 20,000
            # simulations -- so ranks 43 through 860 were one tie block, and Python's
            # stable sort resolved it by INPUT ORDER.  The sheet read 'ceiling rank 43,
            # 44, 45, 46' down an alphabetical list.  That is G17's own failure mode
            # (input order wearing a ranking's clothes) shipped as the fix for a
            # different one.  A rank over a tie is not a rank.
            #
            # The zero block is also not a close call: it is the Reames case at scale.
            # A player who never clears the bar is not 700th at clearing it.
            live = [p for p in grp if ceil_key(p) > 0.0]
            for i, p in enumerate(sorted(live, key=lambda p: -ceil_key(p)), 1):
                p['rank_floor'] = None
                p['rank_ceiling'] = i
                p['profile'] = f'ceiling {i} of {len(live)} -- E[WAR] is draft-day (A104)'
            for p in grp:
                if ceil_key(p) > 0.0: continue
                p['rank_floor'] = p['rank_ceiling'] = None
                p['profile'] = ('NO CEILING -- clears the bar in 0 of '
                                f'{NSIM:,} simulations, so there is nothing to rank')
            continue
        if n < 2:
            for p in grp:
                p['rank_floor'] = p['rank_ceiling'] = 1
                p['profile'] = 'n/a'
            continue
        for key, dest in ((floor_key, 'floor'), (ceil_key, 'ceiling')):
            order = sorted(grp, key=lambda p: -(key(p) if key(p) is not None else -1e9))
            for i, p in enumerate(order, 1):
                p[f'rank_{dest}'] = i
                p[f'pct_{dest}']  = (i - 1) / (n - 1)
        for p in grp:
            d = p['pct_floor'] - p['pct_ceiling']      # >0 means ceiling is the better rank
            p['profile'] = ('CEILING'  if d >=  THRESH else
                            'FLOOR'    if d <= -THRESH else 'BALANCED')
            # FIX 2026-09-20, caught on the 1977 pool.  A ZERO ceiling is not a rank
            # question.  Alan Reames sat at board #1 with ceiling rank #17 and P(both)
            # = 0.0%, and the percentile gap across 84 bats was only 0.19 -- under the
            # threshold -- so he read BALANCED.  A player who cannot clear the bar at
            # all is the definition of a FLOOR pick, however close the ranks are.  The
            # tag measures rank distance; this case needs the VALUE.
            if ceil_key(p) <= 0.0:
                p['profile'] = 'FLOOR'
                # ⛔ 2026-09-22, SECOND PASS.  The LEAGUE branch above stopped ranking
                # the zero block; THIS branch kept doing it, which is the identical
                # one-branch-fixed shape as G16.  On the 1977 pool 68 of 84 bats and
                # 36 of 88 arms read P(both)/P(#2) = 0.0%, so BOARD 'ceiling #' 17
                # through 84 was one tie resolved by INPUT ORDER -- on the sheet a
                # pick is made from.  The block boundary is also Monte Carlo: a man
                # at #17 on a displayed 0.0% cleared the bar in about 1 draw of
                # 20,000, and #17 vs #84 is that one draw.  A rank over a tie is not
                # a rank.  The FLOOR tag above already carries the real information.
                p['rank_ceiling'] = None

def write_workbook(fr, players, out_path, extra_notes=()):
    rank_floor_and_ceiling(players)
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        sys.exit("ERROR: writing .xlsx needs openpyxl.  pip install openpyxl")
    wb = openpyxl.Workbook()
    HDR = Font(bold=True, color='FFFFFF'); FILL = PatternFill('solid', fgColor='334155')
    WARN = Font(bold=True, color='B91C1C')

    def sheet(title, rows, headers, freeze='A2', strict=False):
        ws = wb.create_sheet(title)
        # ⛔ HARDENED 2026-09-22.  Every row builder used to be trusted to emit exactly
        # as many cells as its header list.  Nothing checked it, and a row one cell
        # short does not raise -- openpyxl simply leaves the tail blank and every
        # value after the gap sits under the WRONG HEADING.  Rule 22: check it.
        # A row LONGER than the headers is a bug on any sheet.  Exact width is required
        # only on the PLAYER GRIDS (strict=True); the report sheets use short rows and
        # blank spacers as deliberate layout.
        check_row_widths(title, rows, headers, strict)
        ws.append(headers)
        for c in ws[1]: c.font = HDR; c.fill = FILL; c.alignment = Alignment(wrap_text=True, vertical='top')
        for r in rows: ws.append(r)
        ws.freeze_panes = freeze; _auto(ws); return ws

    def as_percent(ws, headers, *names):
        """Format a column BY ITS HEADING, never by a hand-counted letter.

        ⛔ 2026-09-22.  Three sheets assigned number_format to literal column letters
        ('W','X','Y' ...) that had to be re-counted by hand every time a column was
        inserted.  Adversarial review found them correct BY LUCK and untested.
        The heading lookup lives in pct_column_index() at module level so verify()
        exercises the real resolver instead of a copy.
        """
        for nm in names:
            i = pct_column_index(headers, nm, ws.title)
            for c in ws[get_column_letter(i + 1)][1:]:
                c.number_format = '0.0"%"' 

    # ---- KEY -----------------------------------------------------------------
    ws = wb.active; ws.title = 'KEY'
    ws.append(['ootp_analyze', VERSION]); ws['A1'].font = Font(bold=True, size=14)
    ws.append([]); ws.append(['PROVENANCE']); ws['A3'].font = Font(bold=True)
    ws.append([fr.stamp()])
    ws.append([])
    ws.append(['GATES  (editable here for reference; the board is computed at these values)'])
    ws['A6'].font = Font(bold=True)
    for lab, c in [('SS  IF RNG >=', GATE_SS), ('2B  IF RNG >=', GATE_2B),
                   ('CF  OF RNG >=', GATE_CF), ('RF  OF ARM >=', GATE_RF_ARM),
                   ('3B  IF RNG + IF ARM >=', GATE_3B_SUM),
                   ('C   (no gate)', C(0, 'A58a: catcher defence is a dead null, p=.921, n=1,044.', 'MEASURED')),
                   ('ARM stamina >=', GATE_STM), ('ARM effective pitches >=', GATE_EFF)]:
        ws.append([lab, c.v, c.tier, c.source])
    ws.append(['LF/RF  OF RNG >=', GATE_CORNER_OF.v, GATE_CORNER_OF.tier, GATE_CORNER_OF.source])
    ws.append(['DEFENSIVE SPECTRUM ("tools qualify at", highest rung cleared)',
               ' > '.join(TOOLS_LADDER.v), TOOLS_LADDER.tier, TOOLS_LADDER.source])
    ws.append([])
    ws.append(['POSITION ADJUSTMENT  (A74 runs/season x A114 playing-time ratio)'])
    ws[f'A{ws.max_row}'].font = Font(bold=True)
    ws.append(['position', 'A74 runs/season', 'PA ratio (A114)', 'scaled runs/season',
               f'career WAR over {SEASONS_DEFAULT.v} seasons'])
    for k in ['C','SS','3B','CF','2B','RF','LF','1B']:
        ws.append([k, A74_POS.v[k], PT_RATIO.v[k], round(pos_adj_runs(k),2), round(pos_adj_war(k),2)])
    ws.append([])
    ws.append(['HOW TO READ A PLAYER\'S VALUE AT A POSITION  -- READ THIS FIRST'])
    ws[f'A{ws.max_row}'].font = Font(bold=True)
    for line in [
        "Written for a reader who has not seen this workbook before. Every line below is",
        "a mistake that was actually made against these numbers, by the tool's own author.",
        "",
        "1. 'POS' IS A LABEL, NOT A PLAN.",
        "   It is the engine's designation. A man can be carded 2B and be a first baseman;",
        "   a 20-year-old's POS reflects 82 plate appearances of filing, not intent. SP, RP",
        "   and CL are ROLES, not positions -- a pitcher's position is P and A74 has no bar",
        "   for it. For anyone under 100 PA the 'helps or hurts' cell says so and refuses.",
        "",
        "2. THE TWO POSITION COLUMNS ANSWER TWO DIFFERENT QUESTIONS.",
        "   'carded at' is where his club files him, and 'glove runs HERE' prices his glove",
        "   THERE -- does he help or hurt at the job he actually holds. 'tools qualify at'",
        "   walks the defensive spectrum SS > CF > 2B > 3B > C > RF > LF > 1B and returns the",
        "   HIGHEST rung his ratings clear. Carded 3B / tools 1B is a man playing above his",
        "   glove. Carded 2B / tools SS is a man playing below it.",
        "   ⚠ CLEARING A GATE IS NOT THE SAME AS BEING PLAYABLE THERE. Read 'glove runs",
        "   THERE' before you act on 'tools qualify at'. Short, second and centre gate on",
        "   RANGE ALONE; the run number prices range AND arm AND turn-double-play. A second",
        "   baseman with shortstop range and a second baseman's arm clears the gate and is",
        "   still badly negative at short. 68 of 280 AC regulars are NEGATIVE at their own",
        "   tools spot, and the worst is -19.8 runs. The pair of cells is the finding.",
        "",
        "3. TO COMPARE TWO MEN, compare them AT THE SAME POSITION. Always.",
        "   A shortstop number and a first-base number are measured against different",
        "   references and do not subtract. The reference cancels between two shortstops and",
        "   does NOT cancel between a shortstop and a first baseman -- that asymmetry broke",
        "   two earlier versions of this sheet in opposite directions.",
        "",
        "4. THE GATE IS A BREAK-EVEN LINE, NOT AN ELIGIBILITY FILTER.",
        "   'at break-even?' says which side of A84's line he is on. It never moves anyone.",
        "   22% to 42% of the league's own REGULARS sit below the gate at the position they",
        "   hold -- SS 22%, CF 24%, 2B 30%, RF 34%, LF 37%, 1B 38%, 3B 42%. Clubs play men",
        "   below the line knowingly; the runs column prices what that costs.",
        "",
        "5. 'bat + pos bar /600' IS NOT A TOTAL. It contains NO DEFENCE.",
        "   It is the bat plus A74's positional bar. Add the glove number yourself, and only",
        "   after checking both are priced at the same position.",
        "",
        "6. A CATCHER HAS NO GLOVE NUMBER, AND THAT IS A FINDING.",
        "   A58a measured catcher defence at p = .921, n = 1,044, re-confirmed by A73. A",
        "   better catcher is not worth more runs. The blank is the result, not an omission.",
        "   Catching is still GATED (C ABI >= 40) -- a null value term is not an invitation",
        "   to put anyone back there.",
        "",
        "7. WHAT THE GLOVE NUMBER CONTAINS: range, turn-double-play at 2B/SS, and arm.",
        "   IT DOES NOT CONTAIN ERROR RATING. An earlier version of this line named IF ERR",
        "   and it was false -- the error term was measured, never wired in, and the claim",
        "   sat here uncorrected. ARM IS INFIELD-ONLY. Outfield arm measures ~0 and that is",
        "   not a deterrence artifact: assists per 150 games are flat across arm bands.",
        "   ⚠ THE INFIELD ARM VALUES ARE NARROWED, NOT CLOSED. Third base ships at 6.38 runs",
        "   per +5; an independent audit puts the defensible band at 4.0-6.0 and notes the",
        "   fit runs ~8% hot against known constants. Treat a 3B arm edge as real in SIGN and",
        "   soft in SIZE until a second export dated apart from this one settles it.",
        "   It contains NO counting stats: no PO, A, E, ZR or IP. Fielding is the RATINGS.",
        "",
        "8. WHAT THIS WORKBOOK WILL NOT DO: build your roster. It prices one man at one",
        "   position at a time. Who plays where, given who else you have, is yours.",
        "",
    ]:
        ws.append([line])
    ws.append([])
    ws.append(['THE BAT WITHOUT THE POSITION  ("bat runs/600 (NO pos)")'])
    ws[f'A{ws.max_row}'].font = Font(bold=True)
    for line in [
        f"A74 derived its adjustment from the mean wRC+ of full-time players at each",
        f"position (37,650 player-seasons, league mean {WRC_MEAN.v}).  That is a line through",
        f"the origin, and its slope reads back off A74's own table: {RUNS_PER_WRC.v} runs per",
        f"wRC+ point per 600 PA, reproducing all EIGHT published values to within 0.011.",
        "",
        f"    bat runs/600 (NO pos) = (wRC+ - {WRC_MEAN.v}) x {RUNS_PER_WRC.v}",
        f"    pos runs/600 (A74)    = A74's adjustment for the position he PLAYS",
        "    total runs/600        = the two added",
        "",
        "EVERYTHING ON THIS SHEET IS PER 600 PLATE APPEARANCES, which is A74's own",
        "denominator.  A114's playing-time ratio is NOT applied here -- it is a ratio to",
        "FIRST BASE, not to 600, and the two agree only by the accident that a first",
        "baseman's projected full season lands near 600 PA.  A114 is still applied where",
        "it is actually required: the conversion to CAREER WAR (G8), in its own column.",
        "",
        "The bat column contains NO position term of any kind.  Two men with the same",
        "wRC+ get the same number whether they catch or play first.  Read it alone to",
        "compare the sticks; add the pos column for what the club actually gets.",
        "",
        "NOT engine WAR minus A74.  A114 s1: the engine's WAR already carries its own",
        "positional credit, and A74 measures a different thing (the bat a club tolerates",
        "at the spot).  Subtracting one from the other would mix two systems.  The bat",
        "score is built from wRC+ only and never touches the WAR column.",
        "",
        "READ THE ERROR BAR.  '+/- 1 SE' is sampling noise measured on THIS LEAGUE:",
        f"   {wrc_se_runs(150):.0f} runs at 150 PA   {wrc_se_runs(300):.0f} runs at 300 PA   "
        f"{wrc_se_runs(600):.0f} runs at 600 PA",
        f"The ENTIRE positional spread, catcher to first base, is "
        f"{A74_POS.v['C'] - A74_POS.v['1B']:.2f} runs.  Below",
        "roughly 250 PA one standard error is most of that spread, so a half-season bat",
        "ranked above a full-season bat by a few runs is not ranked above him at all.",
        "This is Rule 12 in the bat column's own units.",
        "",
        "WHY A CELL IS BLANK -- the 'bat score note' column names the reason, because",
        "three different refusals previously arrived as one undifferentiated empty cell:",
        f"   G14  under {BAT_RUNS_MIN_PA.v} PA.  wRC+ is a rate; on 23 PA it is noise and tops the sheet.",
        f"   G15  unassigned and reading wRC+ exactly {WRC_FILL.v} -- OOTP's fill value.  753 of",
        "        1,547 rows on the live AC file carry it, against 8 for the next most",
        "        common value.  Rostered bats reading 100 all have PA <= 65 and G14 takes",
        "        them; unassigned bats read 100 97.2% of the time on PA up to 414 -- real",
        "        plate appearances, fake rate.",
        "   G7   a DRAFT POOL.  110.8 is a MAJOR-LEAGUE mean and an amateur is not on it.",
        "Blank, never zero.  A zero would claim 'average bat', which is a real claim.",
        "",
        "G16: THE RUNS COLUMNS FOLLOW THE POSITION HE IS PLAYED AT, not the landing spot.",
        "'lands' is where a glove clears A108's acquisition gate and keeps its own column.",
        "On the live file 279 of 619 rostered bats (45.1%) differ between the two, and 120",
        "swing more than 4 runs/season.  An everyday shortstop with 453 PA and 55 range",
        "was being priced at first base, -10.87, because his glove misses a bar his club",
        "has evidently decided not to apply.  That is G6 -- an acquisition screen reaching",
        "a lineup-card decision -- and it was worth 13.94 runs/season.",
        "",
        "G15 also SORTS this sheet: rostered players first, the FA / unassigned pool",
        "below them, WAR ordering within each.  Their WAR is earned at another level",
        "and a flat sort put two free agents at #2 and #3.  The 'pool' column says which.",
        "",
        "THE RANK IS WAR, AND WAR IS REALIZED.  It is the only scale in this file that",
        "prices bats and arms in the same currency and it is engine-exact, but it is also",
        "playing-time weighted and it carries the engine's own positional credit.  For the",
        "position question read the three runs columns, which ask it cleanly.",
    ]:
        ws.append([line])
    ws.append([])
    ws.append(['GUARDS ACTIVE IN THIS BUILD']); ws[f'A{ws.max_row}'].font = Font(bold=True)
    for g in [
      'G1  position ratings can never reach a gate (A113)',
      'G2  probabilities are a Pct type; they cannot print as a fraction (A112 s7)',
      'G3  baselines refuse an ORG-unfiltered frame (A112 s0)',
      'G4  provenance stamped above; this tool reads exports, never roster documents',
      'G5  every constant carries a source string; verify() asserts none is empty',
      'G6  gates (acquisition) and rankings (lineup card) are separate outputs',
      'G7  WITHDRAWN 2026-09-19 -- this guard never existed.  The A94 bar columns',
      '    (P(POW55) / P(OBP55) / P(both)) ARE computed for draft pools and always',
      '    were.  For a pool they are a PROJECTION of reaching a major-league bar,',
      '    not a measurement.  Read them that way.',
      'G8  A74 is scaled by playing time before becoming career WAR (A114)',
      'G9  a POOL must prove itself: NO organisations AND a school column.  A',
      '    single-team roster is neither a pool nor a league and is refused unless',
      '    a kind is forced.  Career-WAR projection is a DRAFT-DAY model (A104) and',
      '    must never run on established players.',
      'G10 forcing LEAGUE on a ONE-ORGANISATION file suppresses BASELINES and the',
      '    ACE CENSUS.  One club cannot supply league context; a baseline built',
      '    from your own roster would look authoritative and would not be.',
      'G11 EVERY BOARD CARRIES TWO RANKS.  The default sort is E[WAR], which A104',
      '    fits on CAREER WAR -- and career WAR rewards a long adequate career, so',
      '    its gap coefficient is NEGATIVE for college bats (JR -0.209).  A large',
      '    current-to-potential gap LOWERS the projection.  In the 1977 pool that',
      '    put a POT 2.5 catcher (28.1) above a POT 5.0 catcher (27.5).  The sort',
      '    is a CLAIM, so the board now also ranks on the ceiling bar -- P(both)',
      '    for bats, P(#2) for arms -- and tags each player FLOOR / BALANCED /',
      '    CEILING when the two ranks differ by two quartiles or more.  Neither',
      '    ranking is the right one; which to buy depends on the club and what is',
      '    left in the pool.  The tag exists so the sort cannot decide silently.',
      'G12 an ARMS-ONLY pool cannot be scored for E[career WAR] and says so on the KEY',
      '    sheet.  A104 has no intercepts; the arm intercept comes from the bat mean of',
      '    the same pool.  No bats, no scale.  Previously this returned a blank E[WAR]',
      '    column with no explanation.',
      'G13 every TOOL and every POTENTIAL column is checked, not just Name/POS/Age and',
      '    the gloves.  A missing potential column silently freezes that tool at its',
      '    current value -- pot = cur -- so its upside reads as zero and the workbook',
      '    still looks complete.  Any such column is now named in the notes below.',
      '    NOTE: OOTP publishes no BABIP potential at all; BABIP is frozen by the data.',
      f'G14 the position-free bat score is BLANK under {BAT_RUNS_MIN_PA.v} PA, never zero.  wRC+ is a',
      '    rate; on 23 PA a 180 wRC+ prices out at +44 runs/season and tops the sheet.',
      "    A114's positional means are taken on 326-388 PA.  A zero would read as an",
      '    average bat, which is a stronger claim than "not enough PA to say."',
      f'G15 wRC+ exactly {WRC_FILL.v} on an UNASSIGNED player is a FILL VALUE, not a league-',
      '    average bat.  753 of 1,547 rows on the live AC file carry it; the next most',
      '    common value appears 8 times.  Their plate appearances are real and only the',
      '    rate is fake, so the PA floor does not catch them.  The bat score is blank and',
      '    the FA / unassigned pool is ranked BELOW the rostered one, never interleaved.',
      'G16 the runs columns follow the position the player is ACTUALLY PLAYED AT, never',
      "    the acquisition gate's landing spot.  They disagree for 45.1% of the rostered",
      '    league (279 of 619) and 120 of those swing more than 4 runs/season.  An',
      '    everyday SS with 453 PA was priced at first base, -10.87, on a range bar his',
      '    own club plainly does not apply.  G6, with the names changed.',
      'G17 a LEAGUE export with no WAR column is REFUSED.  The ROSTER sheet is ranked on',
      '    WAR; without it the # column numbers the INPUT ORDER while looking exactly',
      '    like a ranking.  One WAR column but no WAR_1 is a named warning: every',
      '    PITCHER would read blank and sort to the bottom.',
      'SHEET HYGIENE.  Percent columns are located BY HEADING, never by a hand-counted',
      '    letter, and every player grid is checked to emit exactly as many cells as it',
      '    has headings.  Both were found correct BY LUCK and untested in review.']:
        ws.append([g])
    blocked = next((p['ewar_blocked'] for p in players if p.get('ewar_blocked')), None)
    if blocked:
        ws.append([]); ws.append([blocked]); ws[f'A{ws.max_row}'].font = WARN
    for n in extra_notes: ws.append([n])
    _auto(ws)

    bats = [p for p in players if p['side']=='BAT']
    arms = [p for p in players if p['side']=='ARM']
    pool = fr.kind == 'POOL'

    # ---- BOARD (pools only) --------------------------------------------------
    # A104 puts bats and arms on a COMMON career-WAR scale (the pool bat/arm ratio, 1.69x,
    # is one of its measured outputs), so a single ranked board is legitimate and is what a
    # pick is actually chosen from. Bats carry the A74 positional adjustment; arms do not,
    # because A104's arm model has no position term and pitchers have no position to adjust.
    if pool:
        hbd = ['#','Name','side','POS','lands / role','Age','Class','OVR*','POT*',
               'E[WAR]','+pos','E[WAR] ranked on','ceiling #','profile',
               'key number','gate']
        rbd = []
        allp = sorted(players, key=lambda x: -((x.get('ewar_adj') if x['side']=='BAT'
                                                else x.get('ewar')) or -1e9))
        for i, p in enumerate(allp, 1):
            if p['side'] == 'BAT':
                rbd.append([i, p['name'], 'BAT', p['pos'], p['lands'], p['age'], p['cls'],
                            p['ovr_star'], p['pot_star'], p.get('ewar'), p['pos_war'],
                            p.get('ewar_adj'),
                            None if p['rank_ceiling'] is None else f"BAT {p['rank_ceiling']}",
                            p['profile'],
                            f"P(both) {p['p_both']}  /  P(POW55) {p['p_pow']}",
                            'up the middle' if p['lands'] in ('C','SS','2B','3B','CF') else 'corner'])
            else:
                rbd.append([i, p['name'], 'ARM', p['pos'],
                            'starter' if p['role_gate'] else 'reliever',
                            p['age'], p['cls'], p['ovr_star'], p['pot_star'],
                            p.get('ewar'), None, p.get('ewar'),
                            None if p['rank_ceiling'] is None else f"ARM {p['rank_ceiling']}",
                            p['profile'],
                            f"P(#2+) {p['p_no2']}",
                            'STM+arsenal OK' if p['role_gate'] else
                            f"FAILS (STM {p['stm']}, eff {p['eff_now']})"])
        sheet('BOARD', rbd, hbd, strict=True)

    # ---- BATS ---------------------------------------------------------------
    # ⛔ CUT 1.8.1: 'Class' is HS/JR/SR/JuCo and there is no school column on a LEAGUE
    # export, so klass() returned 'SR' for every 30-year-old in the file -- a draft-only
    # field leaking onto a league sheet and telling the reader nothing.
    hb = ['Name','POS','lands','Age','ORG','OVR*','POT*',
          'IF RNG','IF ARM','OF RNG','OF ARM','TDP','SPE',
          'POW now','POW pot','POW P10','POW P50','POW P90',
          'OBP now','OBP P50','OBP P90',
          'P(POW55)','P(OBP55)','P(both)',
          'carded at (A74 applied here)','bat runs/600 (NO pos)','+/- 1 SE','pos runs/600 (A74)',
          'bat + pos bar /600','bat score note',
          # ⛔ CUT 1.9.2: these three headings read 'glove runs low' / 'glove runs high'
          # and were left over from v1.8.1's percentile pair. The point estimate has been
          # shipping under 'low' and a PROSE VERDICT under 'high' on all 860 rows since.
          'glove: helps or hurts']
    # ⛔ POOL DROPS THE CARDED PAIR, 1.9.2. On a draft export 'carded at' IS the tools
    # spot -- a prospect has no club filing him anywhere -- so 'glove runs HERE' and
    # 'glove runs THERE' would be the SAME NUMBER printed twice under two headings that
    # promise different things. And every pool bat is under the PA floor, so G21 blanks
    # the carded pair on every row anyway. Two columns, wholly empty, sitting where a
    # reader expects a comparison: that is how a dead column gets read as a finding.
    if not pool:
        hb += ['glove runs HERE (carded)','at break-even?']
    hb += ['tools qualify at (highest)','glove runs THERE']
    # ⛔ CUT 1.8.1: 'pos runs/season' and 'pos career WAR' were the SAME A74 constant a
    # third and fourth time -- one scaled by A114's playing-time ratio, one multiplied by
    # eight seasons. 'pos career WAR' in particular read as the PLAYER's career WAR and
    # meant "what the position alone is worth over a career" (a shortstop: 2.32). The
    # number survives in 'pos runs/600 (A74)'; the misleading restatements do not.
    if pool: hb += ['E[WAR] raw','E[WAR] +pos']
    hb += ['floor rank','ceiling rank','profile','PA','wRC+','WAR']
    rb = []
    for p in sorted(bats, key=lambda x: -(x.get('ewar_adj') or 0)):
        row = [p['name'],p['pos'],p['lands'],p['age'],p['org'],p['ovr_star'],p['pot_star'],
               p['if_rng'],p['if_arm'],p['of_rng'],p['of_arm'],p['tdp'],p['spe'],
               p['POW_now'],p['POW_pot'],p['POW_P10'],p['POW_P50'],p['POW_P90'],
               p['obp_now'],p['obp_P50'],p['obp_P90'],
               p['p_pow'].percent,p['p_obp'].percent,p['p_both'].percent,
               p['priced_at'],p['bat_runs'],p['bat_se'],p['pos_runs_600'],p['tot_runs'],
               p['bat_note'],
               p['glove_verdict']]
        if not pool: row += [p['glove_here'], p['at_break_even']]
        row += [p['tools_spot'], p['glove_tools']]
        if pool: row += [p.get('ewar'), p.get('ewar_adj')]
        row += [p['rank_floor'], p['rank_ceiling'], p['profile']]
        row += [p['pa'] or None, p['wrc_plus'], p['war']]
        rb.append(row)
    wsb = sheet('BATS', rb, hb, strict=True)
    as_percent(wsb, hb, 'P(POW55)', 'P(OBP55)', 'P(both)')

    # ---- ARMS ---------------------------------------------------------------
    ha = ['Name','POS','Age','Class','ORG','OVR*','POT*','STM','eff (A41)','eff (A103 flat40)',
          'A115 conflict?','role gate','arsenal',
          'CON now','CON pot','CON P50','CON P90','HRA now','HRA pot','HRA P50','HRA P90',
          'P(ace)','P(#1)','P(#2)']
    if pool: ha += ['E[WAR]']
    ha += ['floor rank','ceiling rank','profile','IP','FIP-','WAR']
    ra = []
    for p in sorted(arms, key=lambda x: -(x.get('ewar') or x['p_no2'])):
        row = [p['name'],p['pos'],p['age'],p['cls'],p['org'],p['ovr_star'],p['pot_star'],
               p['stm'],p['eff_now'],p['eff_flat40'],
               (f"YES -- {p['eff_now']} vs {p['eff_flat40']}"
                + ('  *ROLE FLIPS*' if p.get('role_flips') else '')) if p['eff_conflict'] else '',
               'YES' if p['role_gate'] else 'no', p['arsenal'],
               p['PCON_now'],p['PCON_pot'],p['PCON_P50'],p['PCON_P90'],
               p['HRA_now'],p['HRA_pot'],p['HRA_P50'],p['HRA_P90'],
               p['p_ace'].percent,p['p_no1'].percent,p['p_no2'].percent]
        if pool: row += [p.get('ewar')]
        row += [p['rank_floor'], p['rank_ceiling'], p['profile']]
        row += [p['ip'] or None, p['fip_minus'], p['war']]
        ra.append(row)
    wsa = sheet('ARMS', ra, ha, strict=True)
    as_percent(wsa, ha, 'P(ace)', 'P(#1)', 'P(#2)')
    for r in wsa.iter_rows(min_row=2, min_col=11, max_col=11):
        if r[0].value: r[0].font = WARN

    # ---- GATED --------------------------------------------------------------
    g = [p for p in bats if p['lands'] in ('C','SS','2B','3B','CF')]
    sheet('GATED BATS', [[p['name'],p['lands'],p['age'],p['pot_star'],p['if_rng'],p['if_arm'],
                          p['of_rng'],p['POW_P50'],p['obp_P50'],p['p_pow'].percent,
                          p.get('ewar_adj')] for p in g],
          (_hg_bats := ['Name','lands','Age','POT*','IF RNG','IF ARM','OF RNG',
                        'POW P50','OBP P50','P(POW55)','E[WAR] +pos']), strict=True)
    # ⛔ FOUND BY THE GENERATED COLUMN SWEEP, 2026-09-22.  These two sheets have carried
    # a probability column since 1.0 and NEVER had a number format: they shipped 14.5 for
    # 14.5% by luck of the reader's eye, and 0.145 would have read as 0.1.  That is G2,
    # which cost us 0.2% against a true 19.5% once already.  Nobody had looked because
    # no test ever opened a GATED sheet.
    as_percent(wb['GATED BATS'], _hg_bats, 'P(POW55)')
    ga = [p for p in arms if p['role_gate']]
    sheet('GATED ARMS', [[p['name'],p['age'],p['pot_star'],p['stm'],p['eff_now'],
                          p['HRA_now'],p['HRA_P50'],p['PCON_now'],p['PCON_P50'],
                          p['p_no2'].percent, p.get('ewar')] for p in ga],
          (_hg_arms := ['Name','Age','POT*','STM','eff','HRA now','HRA P50','CON now',
                        'CON P50','P(#2+)','E[WAR]']), strict=True)
    as_percent(wb['GATED ARMS'], _hg_arms, 'P(#2+)')

    # ---- ROSTER (league files only) ------------------------------------------
    # Current value and future value on ONE row, grouped by where the glove plays.
    # Deliberately does NOT invent a combined score: A104's E[WAR] is a draft-day model
    # and is not computed here (G12), and there is no measured way to add "what he is"
    # to "what he might become".  The two are shown side by side and the GM weighs them.
    if not pool:
        # The PURE TOOLS that produced 'lands' are shown beside it.  A113: the position
        # ratings in the export are a PLAYING-TIME RECORD, not ability, and a player can
        # have no position rating at a spot he is perfectly able to play.  These four
        # columns are the ratings that exist for every fielder regardless, and they make
        # every landing spot auditable on its own row.
        #
        # ONE FLAT RANKED LIST, POSITION NOT SCORED.  Through 1.3.1 this sheet was
        # GROUPED -- catchers first, then SS, 2B ... 1B last, arms at the bottom -- so
        # the only way to compare a first baseman with a shortstop was to scroll past
        # six position blocks.  It is now a single order, ranked on the engine's own
        # WAR, with 'lands' kept as a COLUMN so Excel can regroup it in one click if
        # you want the old view back.  Nothing is lost by ungrouping; something is
        # gained, because the question "who are my best twenty players" now has a
        # visible answer.
        #
        # ⚠ WAR IS THE RANK, AND WAR IS REALIZED.  It is the only scale in this file
        # that prices bats and arms in the same currency, and it is engine-exact.  It
        # is also playing-time-weighted and it carries the engine's own positional
        # credit (A114 s1).  The two runs/season columns beside it are the position
        # question asked cleanly, and they are the ones to read for that.
        #
        # ⚠ G15 -- THE UNASSIGNED POOL IS NOT RANKED AGAINST THE ROSTERED ONE.  A flat
        # WAR sort put two free agents at #2 and #3 on the live file, on WAR earned at
        # another level, with a wRC+ of exactly 100 that OOTP had filled in because it
        # had none to publish.  Same family as G3.  They stay on the sheet -- the FA
        # pool is worth looking at -- but BELOW the rostered players, and the 'pool'
        # column says which population a row belongs to.
        # 'slot' is the ROSTER SLOT, and it is two different things by design:
        #   bats  -- the A74 POSITION he is priced at (see 'priced at' on BATS)
        #   arms  -- the ROLE, SP or rp.  SP/RP/CL are ROLES, not positions (G18); a
        #            pitcher's position is P, A74 has no entry for it, and every
        #            positional runs column below is correctly blank for him.
        hr = ['#','pool','slot','Name','ORG','POS','glove gates to','Age','OVR*','POT*',
              'IF RNG','IF ARM','OF RNG','OF ARM','TDP','C ABI',
              'PA / IP','wRC+ / FIP-','WAR',
              'bat runs/600 (NO pos)','+/- 1 SE','pos runs/600 (A74)','bat + pos bar /600',
              'bat score note',
              'glove: helps or hurts','glove runs HERE (carded)','at break-even?',
              'tools qualify at (highest)','glove runs THERE',
              'key tool now','P50','P90','ceiling %','ceiling rank','gate']
        # B3: 'ceiling rank' is computed WITHIN a side (bats on P(both), arms on
        # P(#2) -- different bars, and comparing them is an error this file has made
        # twice).  Published in one column of one combined sheet it collided: a
        # catcher and a reliever both read 'ceiling rank 1'.  The rank is now
        # qualified by its side so the column cannot be read across the boundary.
        rr = []
        for i, p in enumerate(sorted(players, key=lambda x: (
                0 if x.get('rostered') else 1,
                -(x['war'] if x['war'] is not None else -99))), 1):
            pool_tag = 'rostered' if p.get('rostered') else 'FA / unassigned'
            if p['side'] == 'BAT':
                rr.append([i, pool_tag, p['priced_at'], p['name'], p['org'], p['pos'],
                           p['lands'], p['age'],
                           p['ovr_star'], p['pot_star'],
                           p['if_rng'], p['if_arm'], p['of_rng'], p['of_arm'],
                           p['tdp'], p.get('c_abi'),
                           p['pa'] or None, p['wrc_plus'], p['war'],
                           p['bat_runs'], p['bat_se'], p['pos_runs_600'], p['tot_runs'],
                           p['bat_note'],
                           p['glove_verdict'], p['glove_here'], p['at_break_even'],
                           p['tools_spot'], p['glove_tools'],
                           p['POW_now'], p['POW_P50'], p['POW_P90'],
                           p['p_both'].percent,
                           None if p.get('rank_ceiling') is None
                           else f"BAT {p['rank_ceiling']}",
                           'carded up the middle' if p['priced_at'] in ('C','SS','2B','3B','CF')
                           else 'corner'])
            else:
                rr.append([i, pool_tag, 'SP' if p['role_gate'] else 'rp', p['name'],
                           p['org'], p['pos'], None,
                           p['age'], p['ovr_star'], p['pot_star'],
                           None, None, None, None, None, None,
                           p['ip'] or None, p['fip_minus'], p['war'],
                           None, None, None, None, '',
                           None, None, None, None, None,
                           p['HRA_now'], p['HRA_P50'], p['HRA_P90'],
                           p['p_no2'].percent,
                           None if p.get('rank_ceiling') is None
                           else f"ARM {p['rank_ceiling']}",
                           'STM+arsenal OK' if p['role_gate'] else
                           f"reliever (STM {p['stm']}, eff {p['eff_now']})"])
        wsr = sheet('ROSTER', rr, hr, strict=True)
        as_percent(wsr, hr, 'ceiling %')

    # ---- LEAGUE-ONLY --------------------------------------------------------
    if not pool:
        if getattr(fr, 'single_org', False):
            # G10 -- see Frame.__init__.  One club is not a league, however the kind
            # was arrived at.  Say so in the sheet the user came looking for, rather
            # than omitting it silently or filling it with a single team's numbers.
            why = [["This export contains ONE organisation."],
                   [""],
                   ["BASELINES and the ACE CENSUS are LEAGUE context: means, standard"],
                   ["deviations and gate counts taken ACROSS clubs.  Computed from a"],
                   [f"single roster ({len(fr.rows)} rows) they would be one team's own"],
                   ["numbers wearing a league's clothes -- and they would look right."],
                   [""],
                   ["NOT COMPUTED, on purpose (G10).  Every other sheet in this"],
                   ["workbook is player-level and is unaffected."],
                   [""],
                   ["Re-export the whole league to get these two sheets."]]
            sheet('BASELINES',  why, ['not computed -- G10'])
            sheet('ACE CENSUS', why, ['not computed -- G10'])
        else:
            try:
                bl = baselines(fr.rostered())
                rows = []
                for grp, (n, d) in bl.items():
                    for k, v in d.items():
                        if v: rows.append([grp, n, k, v[0], v[1], v[2]])
                sheet('BASELINES', rows, ['group','n','rating','mean','sd','n rated'])
            except RuntimeError as e:
                sheet('BASELINES', [[str(e)]], ['not computed'])
            rep = league_report(fr, players)
            rows = [['arms considered (rostered)', rep['n_arms']],
                    [f"clear the ACE gate now (CON>={ACE_CON.v}, HRA>={ACE_HRA.v})", len(rep['ace_now'])],
                    [f"clear the #1 bar now (CON>={NO1_CON.v}, HRA>={NO1_HRA.v})", len(rep['no1_now'])],
                    ['clear the ACE gate on POTENTIAL', len(rep['ace_pot'])], []]
            rows.append(['--- the aces ---'])
            for p in sorted(rep['ace_now'], key=lambda x: -(x['ip'] or 0)):
                rows.append([p['name'], f"{p['org']} | age {p['age']} | CON {p['PCON_now']} "
                                        f"HRA {p['HRA_now']} STM {p['stm']} | IP {p['ip']} FIP- {p['fip_minus']}"])
            sheet('ACE CENSUS', rows, ['item','value'])

    wb.remove(wb['Sheet']) if 'Sheet' in wb.sheetnames else None
    wb.save(out_path)
    return out_path

# =============================================================================
# VERIFY.  Rule 22: FAIL LOUD.  Nothing is written unless every check passes.
# =============================================================================

class Checks:
    def __init__(self): self.fail = 0; self.n = 0
    def _r(self, ok, label, note=''):
        self.n += 1
        if not ok: self.fail += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"   {note}" if note else ""))
    def true(self, label, ok, note=''): self._r(bool(ok), label, note)
    def eq(self, label, got, want, tol=1e-9):
        self._r(abs(got - want) <= tol, label, f"got {got:>10.4f}  want {want:>10.4f} +/-{tol:g}")
    def raises(self, label, exc, fn, *a, **k):
        try:
            fn(*a, **k); self._r(False, label, "no exception raised")
        except exc: self._r(True, label)
        except Exception as e: self._r(False, label, f"wrong exception: {type(e).__name__}: {e}")

def verify(verbose=True):
    c = Checks(); rng = random.Random(SEED)

    print("\n=== 1. constants carry a source and a tier (G5) ===")
    allc = {k: v for k, v in globals().items() if isinstance(v, C)}
    c.true(f"every constant has a non-empty source  ({len(allc)} constants)",
           all(x.source.strip() for x in allc.values()))
    c.true("every constant is tagged MEASURED, ESTIMATED or CONVENTION (rule 9)",
           all(x.tier in ('MEASURED','ESTIMATED','CONVENTION') for x in allc.values()))
    c.true("CONVENTION is reserved for the defensive spectrum alone -- it is the one "
           "value in this file that is CHOSEN rather than found, and it must not spread",
           {k for k,v in allc.items() if v.tier=='CONVENTION'} == {'TOOLS_LADDER'},
           str(sorted(k for k,v in allc.items() if v.tier=='CONVENTION')))
    c.true("the ESTIMATED ones are exactly the five we know are assumptions",
           {k for k,v in allc.items() if v.tier=='ESTIMATED'} ==
           {'SHARE','RUNS_PER_WIN','SEASONS_DEFAULT','BAT_RUNS_MIN_PA','NOISE_RUNS'},
           str(sorted(k for k,v in allc.items() if v.tier=='ESTIMATED')))
    c.raises("a constant with an empty source is rejected", AssertionError, C, 1, "", 'MEASURED')

    print("\n=== 2. G2 -- a probability cannot be printed as the wrong number ===")
    p = Pct(0.069)
    c.true("Pct(0.069) formats as '6.9%', not '0.1'", f"{p:.1f}" == "6.9%", f"{p:.1f}")
    c.true("str() gives the percent too", str(Pct(0.195)) == "19.5%", str(Pct(0.195)))
    c.eq("the raw fraction is still available", float(p), 0.069, 1e-12)
    c.eq(".percent gives the number", Pct(0.195).percent, 19.5, 1e-9)
    c.raises("a value already in percent units is REJECTED", ValueError, Pct, 19.5)
    c.raises("a negative probability is rejected", ValueError, Pct, -0.01)

    print("\n=== 3. G1 -- a position rating can never reach a gate ===")
    row = {'Name':'T','POS':'3B','Age':'21','IF RNG':'45','IF ARM':'75','3B':'45','SS':'20'}
    gv = GateView(row)
    c.raises("GateView refuses '3B'", PermissionError, lambda: gv['3B'])
    c.raises("GateView refuses 'SS'", PermissionError, lambda: gv['SS'])
    c.raises("GateView refuses 'C Pot'", PermissionError, lambda: gv['C Pot'])
    c.eq("but hands over the TOOL", gv['IF RNG'], 45.0)
    c.true("the withdrawn gate is not reachable by name",
           'GATE_3B' not in globals(), "GATE_3B is gone, not set to a number")

    print("\n=== 4. landing positions, on the tools only ===")
    def L(**kw):
        base = {'Name':'x','POS':'3B','IF RNG':0,'IF ARM':0,'OF RNG':0,'OF ARM':0}
        base.update(kw); return lands(GateView(base))
    # ⛔ UPDATED 2026-09-22 with the gates themselves.  These two checks encoded the
    # PARQUET values (SS 60 / 2B 55) from the pre-A108 pocket card, and they are what
    # caught the constant change -- as intended.  Now pinned to A108's AC values, and
    # tested on BOTH sides of each boundary so a future drift cannot pass.
    c.true("IF RNG 65 -> SS  (A108 AC mean 67.1 -> grid 65)", L(**{'IF RNG':65}) == 'SS')
    c.true("IF RNG 60 -> 2B, NOT SS  (60 is the parquet SS gate A108 overturned)",
           L(**{'IF RNG':60}) == '2B')
    c.true("IF RNG 60 -> 2B  (A108 AC mean 60.7 -> grid 60)", L(**{'IF RNG':60}) == '2B')
    c.true("IF RNG 55 does NOT reach 2B  (55 is the parquet 2B gate)",
           L(**{'IF RNG':55}) != '2B')
    c.true("IF RNG 55 + IF ARM 70 = 125 -> 3B, not 2B  (the R. Turner case)",
           L(**{'IF RNG':55,'IF ARM':70}) == '3B')
    c.true("IF RNG 45 + IF ARM 75 = 120 -> 3B  (pocket rule 5)",
           L(**{'IF RNG':45,'IF ARM':75}) == '3B')
    c.true("IF RNG 45 + IF ARM 70 = 115 -> 1B  (just under the bar)",
           L(**{'IF RNG':45,'IF ARM':70}) == '1B')
    c.true("IF RNG 50 + IF ARM 55 = 105 -> 1B  (the invented ARM>=55 gate would have passed him)",
           L(**{'IF RNG':50,'IF ARM':55}) == '1B')
    c.true("a catcher with C ABI above the bar lands at C",
           lands(GateView({'POS':'C','IF RNG':0,'IF ARM':0,'OF RNG':0,'OF ARM':0,
                           'C ABI':55})) == 'C')
    c.true("⚠ CHANGED 1.9.2: a carded catcher BELOW C ABI now falls THROUGH the C rung "
           "instead of being parked at C unconditionally. A58a makes catcher DEFENCE a "
           "null; it never made catching ungated, and the KEY sheet has claimed C ABI >= "
           "40 all along while lands() ignored it. 3 of 132 AC catchers are affected.",
           lands(GateView({'POS':'C','IF RNG':0,'IF ARM':0,'OF RNG':0,'OF ARM':0,
                           'C ABI':20})) == '1B')
    c.true("... and the rung does not COLLECT anyone either -- only 5 of 728 AC "
           "non-catchers clear C ABI 40 at all, and each is a real catching glove",
           lands(GateView({'POS':'3B','IF RNG':40,'IF ARM':40,'OF RNG':30,'OF ARM':30,
                           'C ABI':50})) == 'C'
           and lands(GateView({'POS':'3B','IF RNG':40,'IF ARM':40,'OF RNG':30,
                               'OF ARM':30,'C ABI':20})) == '1B')
    c.true("OF RNG 65 -> CF", L(POS='LF', **{'OF RNG':65}) == 'CF')
    c.true("OF RNG 60 + OF ARM 50 -> RF", L(POS='LF', **{'OF RNG':60,'OF ARM':50}) == 'RF')
    c.true("OF RNG 60 + OF ARM 45 -> LF", L(POS='LF', **{'OF RNG':60,'OF ARM':45}) == 'LF')
    c.true("a 3B position rating of 80 changes NOTHING",
           L(**{'IF RNG':40,'IF ARM':40,'3B':80}) == '1B')

    print("\n=== 5. the delivery simulation returns A76's mean (the whole construction) ===")
    c.eq("A77 band shares sum to 1", sum(w for w,_,_ in A77_BANDS.v), 1.0, 1e-9)
    c.eq("A77 band mean reproduces the stated mean", _BAND_MEAN, A77_MEAN, 0.01)
    r2 = random.Random(7)
    c.eq("normalised multiplier has mean 1",
         statistics.mean(draw(r2) for _ in range(200000)), 1.0, 0.01)
    for age, tool in ((18,'POW'), (21,'CON'), (20,'EYE')):
        f = A76_BAT.v[age][tool]
        s = simulate({tool:30.0}, {tool:70.0}, {tool:f}, random.Random(11), n=40000, clip=False)
        c.eq(f"age {age} {tool}: simulated delivery == A76", (statistics.mean(s[tool])-30.0)/40.0,
             f, 0.006)

    print("\n=== 6. SHARE is ESTIMATED -- bracket it and show it cannot move a single-tool answer ===")
    out = {}
    for sh in (0.0, 0.70, 1.0):
        s = simulate({'POW':30.0}, {'POW':70.0}, {'POW':A76_BAT.v[18]['POW']},
                     random.Random(3), n=40000, share=sh)
        out[sh] = Pct(sum(1 for v in s['POW'] if v >= 55) / 40000)
    c.true("P(POW>=55) is unmoved by SHARE  (single tool -- it cannot matter)",
           max(out.values()) - min(out.values()) < 0.01,
           "  ".join(f"SHARE {k}: {v}" for k, v in out.items()))

    print("\n=== 7. G8 -- A74 is scaled by playing time before becoming career WAR ===")
    c.eq("catcher runs/season scaled", pos_adj_runs('C'), 5.77*0.840, 1e-9)
    c.eq("catcher career WAR is 3.88, not the unscaled 4.62",
         pos_adj_war('C'), 5.77*0.840*8/10.0, 1e-9)
    c.true("the unscaled value is NOT what the function returns",
           abs(pos_adj_war('C') - 5.77*8/10.0) > 0.5,
           f"scaled {pos_adj_war('C'):.2f} vs unscaled {5.77*8/10.0:.2f}")
    c.eq("first base is unscaled (it is the reference)", PT_RATIO.v['1B'], 1.0)
    c.true("C is still the largest positive adjustment after scaling",
           max(pos_adj_runs(k) for k in A74_POS.v) == pos_adj_runs('C'))
    c.true("1B remains far the worst (A110)",
           min(pos_adj_runs(k) for k in A74_POS.v) == pos_adj_runs('1B'))
    c.eq("the 1B-to-SS swing a first baseman must out-hit",
         pos_adj_runs('SS') - pos_adj_runs('1B'), 3.07*0.946 - (-10.87*1.0), 1e-9)

    print("\n=== 8. arsenal counting, and the A115 conflict is surfaced not silently decided ===")
    hen = {'CH':40,'CHP':80,'SL':40,'SLP':55,'CT':45,'CTP':70}
    c.eq("Henson, A41 rule (changeup floor 45)", eff_pitches(hen), 2)
    c.eq("Henson, A103 rule (flat 40)", eff_pitches(hen, flat40=True), 3)
    c.true("the two rules disagree on him -- that is A115 and it must be visible",
           eff_pitches(hen) != eff_pitches(hen, flat40=True))
    c.eq("a changeup at 45 counts under both", eff_pitches({'CH':45}), 1)
    c.eq("a fastball at 40 counts under both", eff_pitches({'FB':40}), 1)
    c.eq("a fastball at 35 counts under neither", eff_pitches({'FB':35}), 0)

    print("\n=== 9. the fast path is EXACT, not an approximation ===")
    # a tool with no gap must return a point mass identical to the slow path
    s_fast = simulate({'POW':50.0}, {'POW':50.0}, {'POW':0.4}, random.Random(5), n=500)
    c.true("no gap -> every sample is the current value", set(s_fast['POW']) == {50.0})
    s_age = simulate({'POW':30.0}, {'POW':70.0}, {'POW':0.0}, random.Random(5), n=500)
    c.true("no delivery left (age 26+) -> every sample is the current value",
           set(s_age['POW']) == {30.0})
    # a LIVE tool must be untouched by the optimisation: same seed, same numbers
    mix_cur = {'POW':30.0,'EYE':50.0}; mix_pot = {'POW':70.0,'EYE':50.0}
    a1 = simulate(mix_cur, mix_pot, {'POW':0.386,'EYE':0.229}, random.Random(99), n=3000)
    a2 = simulate({'POW':30.0}, {'POW':70.0}, {'POW':0.386}, random.Random(99), n=3000)
    c.true("a live tool draws identically whether or not a dead tool rides along",
           a1['POW'] == a2['POW'])
    c.true("the dead tool alongside it is a clean point mass", set(a1['EYE']) == {50.0})

    print("\n=== 10. G3 -- baselines refuse an unfiltered frame ===")
    fake = Frame.__new__(Frame)
    fake.__dict__.update(rows=[{'Name':'a','ORG':'X','GS_1':20,'STU':50}], kind='LEAGUE',
                         _org_filtered=False, cols={'Name','ORG','GS_1','STU'})
    c.raises("baselines() on an unfiltered frame raises", RuntimeError, baselines, fake)
    fake2 = Frame.__new__(Frame); fake2.__dict__.update(fake.__dict__); fake2._org_filtered = True
    try:
        baselines(fake2); c.true("baselines() runs once the frame is filtered", True)
    except Exception as e:
        c.true("baselines() runs once the frame is filtered", False, str(e))

    print("\n=== 11. bars, index and the two pitching bars ===")
    c.eq("OBP weights sum to the denominator", sum(OBP_W.values()), OBP_DEN, 1e-12)
    c.eq("a 55/55/55 bat indexes to 55", obp_index(55,55,55), 55.0, 1e-9)
    c.true("the ace gate is stricter than the #1 bar on control, equal on HRA",
           ACE_CON.v > NO1_CON.v and ACE_HRA.v == NO1_HRA.v,
           f"ace CON {ACE_CON.v} vs #1 CON {NO1_CON.v}; HRA {ACE_HRA.v} both")
    c.true("the #2 bar is looser than the #1 bar on HRA", NO2_HRA.v < NO1_HRA.v)

    print("\n=== 12. G9 -- a POOL must prove itself; a roster is refused ===")
    c.true("a pool is a pool: no orgs AND a school column",
           detect_kind([{'ORG':'-','HSC':'HS'},{'ORG':'','HSC':'JR'}]) == 'POOL')
    c.true("two or more orgs is a LEAGUE",
           detect_kind([{'ORG':'Philadelphia'},{'ORG':'Toronto'}]) == 'LEAGUE')
    c.raises("a SINGLE-TEAM roster is refused, not scored as a pool", SystemExit,
             lambda: detect_kind([{'ORG':'Philadelphia','POS':'SS'},
                                  {'ORG':'Philadelphia','POS':'C'}]))
    c.raises("no orgs and NO school column is refused (ambiguous)", SystemExit,
             lambda: detect_kind([{'ORG':'-'},{'ORG':''},{'ORG':'-'}]))
    c.true("--kind overrides detection", detect_kind([{'ORG':'x'}], override='pool') == 'POOL')

    print("\n=== 13. A115 is reported, never resolved ===")
    _a41  = eff_pitches({'FB':40,'SL':40,'CH':40})
    _a103 = eff_pitches({'FB':40,'SL':40,'CH':40}, flat40=True)
    c.true("the two counting rules really do differ on a 40 changeup", _a41 == 2 and _a103 == 3)
    c.true("a 45 changeup counts under both rules",
           eff_pitches({'CH':45}) == 1 and eff_pitches({'CH':45}, flat40=True) == 1)

    print("\n=== 14. the SR intercept refuses to guess ===")
    c.true("A104's published board still carries the SR anchor",
           'Roger Renshaw' in A104_BOARD.v)

    print("\n=== 21. the glove gates are A108's AC values, not the parquet ones ===")
    c.true("SS gate is 65 (A108), NOT 60 (parquet / stale pocket card)", GATE_SS.v == 65, str(GATE_SS.v))
    c.true("2B gate is 60 (A108), NOT 55 (parquet / stale pocket card)", GATE_2B.v == 60, str(GATE_2B.v))
    c.true("CF gate is 65 -- every source agrees", GATE_CF.v == 65, str(GATE_CF.v))
    c.true("the SS gate is strictly above the 2B gate", GATE_SS.v > GATE_2B.v)
    c.true("both cite A108, the reversal, not the rule it overturned",
           'A108' in GATE_SS.source and 'A108' in GATE_2B.source)

    print("\n=== 20. G14/G15/G16 -- END TO END, through build() and the written sheet ===")
    # ⛔ REWRITTEN 2026-09-22.  Adversarial review mutation-tested the previous version
    # of this block: inverting the rostered flag, inverting the ROSTER sort, shifting the
    # percent-format column and SWAPPING the bat and pos cells ALL SHIPPED CLEAN, because
    # every check re-implemented the logic inside the test instead of calling it.  Two
    # checks were literal tautologies ('lands' in ('lands',)).  These now drive a real
    # frame through build() and write_workbook() and read the cells back out of the file.
    import tempfile as _tf, os as _os
    def _row(name, pos, org, wrc, pa, war, ifr=70, ofr=70,
             pow_='50', eye='50', age='27', powp=None, eyep=None, cabi=None):
        # ⛔ FIXTURE BUG, 1.9.2: every synthetic player carried C ABI 50, and the real
        # league has 3 non-catchers of 728 at 50 or better. The unrealistic fixture hid
        # the C rung of the ladder completely -- 'Everyday SS' was filed as a CATCHER the
        # first time the ladder ran, and no check noticed because no check could.
        # A fixture that does not resemble the population is not a test of the code.
        return {'Name': name, 'POS': pos, 'ORG': org, 'Age': age,
                'IF RNG': str(ifr), 'IF ARM': '70', 'OF RNG': str(ofr), 'OF ARM': '70',
                'TDP': '50', 'C ABI': str(cabi if cabi is not None
                                          else (55 if pos == 'C' else 20)),
                'SPE': '50', 'STM': '20',
                'CON': '55', 'GAP': '50', 'POW': pow_, 'EYE': eye, 'BABIP': '55',
                "K's": '50', 'OVR': '3 Stars', 'POT': '4 Stars',
                'CON P': '60', 'GAP P': '50',
                'POW P': powp or pow_, 'EYE P': eyep or eye, 'K P': '50',
                # ⛔ WAR and WAR_1 must DIFFER.  They were identical, so swapping the
                # bat and arm WAR columns was invisible to every check (R13).
                'wRC+': wrc, 'PA': pa, 'WAR': war, 'WAR_1': str(float(war) + 0.7)}
    _rows = [
        _row('Everyday SS',  'SS', 'Boston',    '174', '500', '5.0',
             ifr=40, ofr=40),                                          # G16: lands 1B
        _row('Real 1B',      '1B', 'Boston',    '174', '500', '4.0', ifr=40, ofr=40),
        _row('Small sample', 'LF', 'Boston',    '180',  '60', '0.5'),          # G14
        _row('Filled FA',    '1B', '-',         '100', '400', '7.5'),          # G15
        _row('Honest FA',    '1B', '-',         '150', '400', '1.0'),
        # the LIVE ceiling block -- these two clear A94's bars in some simulations,
        # so the ranking path actually runs.  Without them `live` is empty and an
        # inverted rank ships clean (it did).
        _row('Slugger',      'RF', 'Boston',    '190', '500', '3.0',
             pow_='50', eye='50', age='20', powp='70', eyep='70'),
        _row('Fringe',       'LF', 'Boston',    '120', '500', '1.5',
             pow_='45', eye='45', age='20', powp='60', eyep='60'),
        # ⛔ THE ARM FIXTURE WAS DEGENERATE.  'Ace' had CON_1 == ACE_CON and HRA ==
        # ACE_HRA at age 27, so p_ace == p_no1 == p_no2 == 100%: a point mass on all
        # three bars.  Ranking arms on the WRONG bar was therefore invisible (R06).
        # These two separate the bars AND each other, so the arm side's ordering is
        # testable for the first time.
        dict(_row('Ace', 'SP', 'Boston', '', '', '4.0'),
             **{'STM': '60', 'STU': '60', 'MOV': '60', 'CON_1': '55', 'HRA': '55',
                'STU P': '65', 'MOV P': '65', 'CON P_1': '60', 'HRA P': '65',
                'FB': '55', 'CH': '50', 'SL': '55', 'CB': '50',
                'IP': '180', 'FIP-': '85', 'PA': '', 'Age': '21'}),
        dict(_row('Swingman', 'RP', 'Boston', '', '', '1.0'),
             **{'STM': '35', 'STU': '45', 'MOV': '45', 'CON_1': '40', 'HRA': '45',
                'STU P': '50', 'MOV P': '50', 'CON P_1': '45', 'HRA P': '50',
                'FB': '50', 'CH': '45', 'IP': '60', 'FIP-': '105', 'PA': '',
                'Age': '21'}),
    ]
    _fr = Frame.__new__(Frame)
    _fr.rows = _rows; _fr.cols = set(_rows[0]); _fr.kind = 'LEAGUE'
    _fr.path = 'selftest'; _fr.single_org = False; _fr._org_filtered = False
    _fr.stamp = lambda: 'selftest'
    _pl = build(_fr, rng=random.Random(SEED))
    for _p in _pl: _p['ewar'] = _p['ewar_adj'] = None
    rank_floor_and_ceiling(_pl)
    _tmp = _os.path.join(_tf.mkdtemp(), 'selftest.xlsx')
    write_workbook(_fr, _pl, _tmp, [])
    import openpyxl as _ox
    _prof = {p['name']: p['profile'] for p in _pl}
    _live_n = sum(1 for p in _pl if p['side'] == 'BAT' and float(p['p_both']) > 0.0)
    _ws = _ox.load_workbook(_tmp)['ROSTER']
    _h  = [x.value for x in _ws[1]]
    _R  = {r[_h.index('Name')]: r for r in _ws.iter_rows(min_row=2, values_only=True)}
    def _cell(nm, col): return _R[nm][_h.index(col)]
    # G22, 1.9.2: BATS gets read back too. Section 33 audited ROSTER only, and that is
    # exactly how 'glove runs low'/'glove runs high' survived on 860 BATS rows -- the
    # point estimate under 'low', a prose verdict under 'high', for a whole version.
    _wsb = _ox.load_workbook(_tmp)['BATS']
    _hb_ = [x.value for x in _wsb[1]]
    _B   = {r[_hb_.index('Name')]: r for r in _wsb.iter_rows(min_row=2, values_only=True)}
    def _bcell(nm, col): return _B[nm][_hb_.index(col)]

    # --- G16: the runs columns follow the position PLAYED, not the glove gate --------
    c.eq("G16: an everyday SS whose glove misses A108's bar still lands 1B (acquisition)",
         1.0 if _cell('Everyday SS', 'glove gates to') == '1B' else 0.0, 1.0, 0)
    c.eq("G16: ... but the SHEET prices him at SHORTSTOP, where his club plays him",
         _cell('Everyday SS', 'pos runs/600 (A74)'), A74_POS.v['SS'], 1e-9)
    c.eq("G16: a real first baseman is still priced at first base",
         _cell('Real 1B', 'pos runs/600 (A74)'), A74_POS.v['1B'], 1e-9)
    c.true("G16: the gate error it replaces was 13.94 runs/season, not a rounding matter",
           abs(A74_POS.v['SS'] - A74_POS.v['1B']) > 13.0)

    # --- the bat column is POSITION-FREE, and the sheet proves it -------------------
    c.eq("the same wRC+ gives the SAME bat runs at SS and at 1B -- no position term",
         _cell('Everyday SS', 'bat runs/600 (NO pos)'),
         _cell('Real 1B', 'bat runs/600 (NO pos)'), 1e-9)
    c.eq("bat + pos = total, read off the written cells",
         _cell('Real 1B', 'bat runs/600 (NO pos)') + _cell('Real 1B', 'pos runs/600 (A74)'),
         _cell('Real 1B', 'bat + pos bar /600'), 0.01)
    c.eq("and the two men differ in the TOTAL by exactly the positional gap",
         _cell('Everyday SS', 'bat + pos bar /600') - _cell('Real 1B', 'bat + pos bar /600'),
         A74_POS.v['SS'] - A74_POS.v['1B'], 0.01)

    # --- G14 and G15 refuse, and SAY WHICH ------------------------------------------
    c.true("G14: a 60-PA bat is blank on the sheet, not zero",
           _cell('Small sample', 'bat runs/600 (NO pos)') is None)
    c.true("G14: and the sheet names the reason",
           'G14' in str(_cell('Small sample', 'bat score note')))
    c.true("G15: the filled FA is blank on 400 PA",
           _cell('Filled FA', 'bat runs/600 (NO pos)') is None)
    c.true("G15: and is named as a FILL VALUE, not confused with a small sample",
           'G15' in str(_cell('Filled FA', 'bat score note')))
    c.true("an unassigned player with a REAL wRC+ is still priced",
           _cell('Honest FA', 'bat runs/600 (NO pos)') is not None)

    # --- G15's second half: the FA pool does not outrank the rostered one ------------
    _order = [r[_h.index('Name')] for r in _ws.iter_rows(min_row=2, values_only=True)]
    c.true("a 7.5-WAR free agent does NOT outrank a 0.5-WAR rostered player (G15/G3)",
           _order.index('Small sample') < _order.index('Filled FA'), str(_order))
    c.true("WAR orders WITHIN the rostered pool",
           _order.index('Everyday SS') < _order.index('Real 1B'), str(_order))
    c.true("the pool column says which population a row belongs to",
           _cell('Filled FA', 'pool').startswith('FA')
           and _cell('Real 1B', 'pool') == 'rostered')

    # --- the error bar, and the sheet hygiene the review found untested --------------
    c.true("every priced bat carries a 1-SE error bar",
           _cell('Real 1B', '+/- 1 SE') is not None)
    c.true("at 200 PA one standard error exceeds HALF the entire positional spread",
           wrc_se_runs(200) > 0.5 * (A74_POS.v['C'] - A74_POS.v['1B']),
           f"{wrc_se_runs(200):.1f} runs vs spread {A74_POS.v['C']-A74_POS.v['1B']:.2f}")
    c.true("the error bar shrinks with playing time", wrc_se_runs(600) < wrc_se_runs(150))
    c.true("the error bar is the MEASURED table, not a fitted 1/sqrt curve",
           all(abs(wrc_se_runs(hi - 1) - sd * RUNS_PER_WRC.v) < 1e-9
               for hi, sd in WRC_NOISE_SD.v),
           str([round(wrc_se_runs(h - 1), 2) for h, _ in WRC_NOISE_SD.v]))
    c.true("the table is monotone -- more plate appearances is never noisier",
           all(WRC_NOISE_SD.v[i][1] > WRC_NOISE_SD.v[i+1][1]
               for i in range(len(WRC_NOISE_SD.v) - 1)))
    c.true("the LARGEST band (350-450, n=100) is IN the table -- dropping it is what made "
           "the withdrawn k=291 fit wrong",
           any(hi == 450 for hi, _ in WRC_NOISE_SD.v))
    for _pa in (0, -5, None):
        c.true(f"PA {_pa} yields no error bar rather than a number",
               wrc_se_runs(_pa) is None)
    c.true("an enormous PA is still bounded by the top band, never zero",
           wrc_se_runs(10_000) == WRC_NOISE_SD.v[-1][1] * RUNS_PER_WRC.v)
    c.true("no error bar is published beside a REFUSED bat score",
           _cell('Small sample', '+/- 1 SE') is None
           and _cell('Filled FA', '+/- 1 SE') is None)
    c.raises("as_percent REFUSES a duplicated heading rather than formatting the first",
             SystemExit, pct_column_index, ['x', 'P(both)', 'P(both)'], 'P(both)')
    c.raises("as_percent REFUSES a heading that is not there (G2)",
             SystemExit, pct_column_index, ['x', 'y'], 'P(both)')

    print("\n=== 24. THE WIRING, not just the unit ===")
    # ⛔ Review: moving the width guard and the heading lookup to module level made them
    # testable and left the CALL SITES untested -- deleting the width check from every
    # sheet, or dropping strict=, or bypassing pct_column_index, all shipped clean.
    # A tested unit on an untested wire is a trade, not a fix.  Assert the wire.
    import inspect as _insp
    _wb_src = _insp.getsource(write_workbook)
    c.true("sheet() actually CALLS the width guard",
           'check_row_widths(title, rows, headers, strict)' in _wb_src)
    c.true("as_percent() actually resolves through pct_column_index",
           'pct_column_index(headers, nm, ws.title)' in _wb_src)
    c.true("as_percent() does NOT reach for .index() itself",
           'headers.index(' not in _wb_src)
    for _grid in ("sheet('BOARD', rbd, hbd, strict=True)",
                  "sheet('BATS', rb, hb, strict=True)",
                  "sheet('ARMS', ra, ha, strict=True)",
                  "sheet('ROSTER', rr, hr, strict=True)"):
        c.true(f"{_grid.split(chr(39))[1]} is a STRICT player grid", _grid in _wb_src)
    c.true("both GATED sheets are strict too",
           "'E[WAR] +pos']), strict=True)" in _wb_src
           and "'CON P50','P(#2+)','E[WAR]']), strict=True)" in _wb_src)
    c.true("and both GATED sheets get their probability column formatted (G2) -- they "
           "carried one since 1.0 with number_format 'General' until the generated "
           "column sweep opened them",
           "as_percent(wb['GATED BATS'], _hg_bats, 'P(POW55)')" in _wb_src
           and "as_percent(wb['GATED ARMS'], _hg_arms, 'P(#2+)')" in _wb_src)
    c.true("every percent column really carries the format ON THE WRITTEN FILE",
           all(_ws.cell(row=2, column=_h.index(n) + 1).number_format == '0.0"%"'
               for n in ('ceiling %',)))

    print("\n=== 28. THE CONSTANTS AND THE GM'S INSTRUCTION, PINNED ===")
    # ⛔ Review bloc 3: five mutations shipped because nothing pinned a gate or a floor.
    c.eq(f"the G14 plate-appearance floor is {BAT_RUNS_MIN_PA.v}, and moving it is a "
         f"decision, not an edit", float(BAT_RUNS_MIN_PA.v), 100.0, 0)
    c.eq("an UNKNOWN position scores 0.0 runs, never a real position's value",
         pos_runs_600('ZZ'), 0.0, 0)
    c.true("DH still lands somewhere -- dropping it from lands() sends him nowhere",
           lands(GateView({'POS': 'DH', 'IF RNG': 70, 'IF ARM': 70, 'OF RNG': 70,
                           'OF ARM': 70, 'TDP': 50, 'C ABI': 50})) in A74_POS.v)
    # THE GM'S OWN INSTRUCTION, 2026-09-22: "for fielding we should only use IFR, OFR etc".
    # A putout-rate override was built off PO/IP and then removed on that instruction.
    # Nothing guarded it, so one line puts it back. Guard the instruction, not the memory.
    FIELDING_COUNTING_STATS = frozenset({'PO', 'A', 'E', 'TC', 'ZR', 'CER', 'CERA', 'PB',
                                         'DP_1', 'IP_1', 'RNG', 'EFF', 'SBA', 'RTO'})
    for _f in (lands, pos_runs_600, bat_runs, bat_runs_600, wrc_se_runs):
        _lits = {x for x in _f.__code__.co_consts if isinstance(x, str)}
        c.true(f"{_f.__name__}() reads NO fielding counting stat -- fielding is the "
               f"RATINGS (IF RNG, OF RNG, ...), on the GM's instruction",
               not (_lits & FIELDING_COUNTING_STATS), str(_lits & FIELDING_COUNTING_STATS))

    print("\n=== 29. THE ERROR BAR IS BOUNDED FROM ABOVE ===")
    # ⛔ Review: three checks guarded the table and NONE bounded it, so doubling every
    # entry shipped clean. The table is now pinned to literals -- reading the expected
    # value out of the constant under test proves only that the constant equals itself.
    for _hi, _sd in ((150, 28.3), (250, 19.5), (350, 16.2), (450, 10.5)):
        c.eq(f"band <{_hi} PA is the MEASURED {_sd} wRC+, pinned to a literal",
             float(dict(WRC_NOISE_SD.v)[_hi]), _sd, 1e-9)
    # The bound has to be PRINCIPLED, and the obvious one does not hold: at 125 PA the
    # bar is 17.8 runs against a 16.64-run positional spread. That is not a test bug --
    # it is the finding, and it is why the column exists. The bound that DOES hold is
    # that sampling noise cannot exceed the TOTAL observed dispersion it was extracted
    # from; the measured totals are 38.5 / 32.7 / 30.8 / 28.2 wRC+ by band.
    _TOTAL_SD = ((150, 38.5), (250, 32.7), (350, 30.8), (450, 28.2))
    for _hi, _tot in _TOTAL_SD:
        c.true(f"band <{_hi}: the noise bar ({wrc_se_runs(_hi-1):.1f} runs) is under the "
               f"TOTAL dispersion it was taken from ({_tot * RUNS_PER_WRC.v:.1f})",
               wrc_se_runs(_hi - 1) < _tot * RUNS_PER_WRC.v,
               f"{wrc_se_runs(_hi-1):.2f} vs {_tot * RUNS_PER_WRC.v:.2f}")
    _spread = A74_POS.v['C'] - A74_POS.v['1B']
    c.true("and the thing the column is FOR is still true and still stated: below the "
           "top band the bar is most of the entire positional spread",
           wrc_se_runs(125) > 0.5 * _spread and wrc_se_runs(600) < 0.5 * _spread,
           f"{wrc_se_runs(125):.1f} and {wrc_se_runs(600):.1f} vs spread {_spread:.2f}")
    c.true("the band lookup is half-open -- PA exactly at an edge takes the BETTER band",
           wrc_se_runs(150) < wrc_se_runs(149) and wrc_se_runs(350) < wrc_se_runs(349))

    print("\n=== 27. G3 -- the FILTER, not the flag ===")
    # ⛔ Review: both G3 checks set _org_filtered = True BY HAND and never called
    # rostered().  Replacing rostered()'s body with `f.rows = list(self.rows)` passed
    # both.  So the assertion read "baselines refuses a frame whose flag is False",
    # not "rostered() removes the unassigned pool" -- and G3's own docstring puts the
    # cost of not removing it at 5-6 display points on every starter baseline.
    _g3rows = [{'Name': 'a', 'POS': '1B', 'ORG': 'Boston'},
               {'Name': 'b', 'POS': '1B', 'ORG': '-'},
               {'Name': 'c', 'POS': '1B', 'ORG': ''},
               {'Name': 'd', 'POS': '1B', 'ORG': 'Boston'}]
    _g3 = Frame.__new__(Frame)
    _g3.rows = _g3rows; _g3.cols = set(_g3rows[0]); _g3.kind = 'LEAGUE'
    _g3.path = 't'; _g3.single_org = False; _g3._org_filtered = False
    _kept = _g3.rostered()
    c.eq("rostered() REALLY drops the unassigned rows, not just sets a flag",
         float(len(_kept.rows)), 2.0, 0)
    c.true("... it drops both '-' and empty ORG", all(r['ORG'] == 'Boston' for r in _kept.rows))
    c.true("... and it does not mutate the frame it was called on", len(_g3.rows) == 4)
    c.true("... and the flag it sets is true", _kept._org_filtered is True)

    print("\n=== 26. THE BATS SHEET, cell by cell ===")
    # ⛔ Review: the BATS sheet had NO assertion of any kind.  Nine mutations shipped
    # clean there, including re-keying its pos column to the gate -- which is G16
    # surviving on the sheet nobody opened, exactly the shape of the defect it fixes.
    _wsb = _ox.load_workbook(_tmp)['BATS']
    _bh2 = [x.value for x in _wsb[1]]
    _B = {r[_bh2.index('Name')]: r for r in _wsb.iter_rows(min_row=2, values_only=True)}
    def _bcell(nm, col): return _B[nm][_bh2.index(col)]
    c.eq("BATS prices position off 'priced at', NOT off the gate (G16, second sheet)",
         _bcell('Everyday SS', 'pos runs/600 (A74)'), A74_POS.v['SS'], 1e-9)
    # ⛔ 1.8.1 CUT the 'pos runs/season' and 'pos career WAR' columns: they restated the
    # SAME A74 constant a third and fourth time, and 'pos career WAR' read as the PLAYER's
    # career WAR when it meant "what the position alone is worth over eight seasons".
    c.true("the duplicate A74 restatements are GONE from BATS -- one column, one claim",
           'pos runs/season' not in _bh2 and 'pos career WAR' not in _bh2, str(_bh2))
    c.true("and 'Class' is gone -- it is a DRAFT field and read 'SR' for every 30-year-old "
           "on a league export, because there is no school column to read",
           'Class' not in _bh2)
    c.true("the column that is bat + the positional bar no longer calls itself a TOTAL, "
           "because it contains no defence at all",
           'bat + pos bar /600' in _bh2 and 'total runs/600' not in _bh2)
    c.true("BATS and ROSTER agree cell for cell on every positional column",
           all(abs(_bcell(n, a) - _cell(n, b)) < 0.011
               for n in ('Everyday SS', 'Real 1B')
               for a, b in (('bat runs/600 (NO pos)', 'bat runs/600 (NO pos)'),
                            ('pos runs/600 (A74)',    'pos runs/600 (A74)'),
                            ('bat + pos bar /600',        'bat + pos bar /600'),
                            ('+/- 1 SE',              '+/- 1 SE'))))
    c.true("the cells are not transposed -- the SE is smaller than the bat score",
           _bcell('Real 1B', '+/- 1 SE') < abs(_bcell('Real 1B', 'bat runs/600 (NO pos)')))
    c.true("BATS names the refusal too, not just ROSTER",
           'G15' in str(_bcell('Filled FA', 'bat score note')))
    c.true("every probability column on BATS is formatted as a PERCENT (G2)",
           all(_wsb.cell(row=2, column=_bh2.index(n) + 1).number_format == '0.0"%"'
               for n in ('P(POW55)', 'P(OBP55)', 'P(both)')))
    _wsa2 = _ox.load_workbook(_tmp)['ARMS']
    _ah2 = [x.value for x in _wsa2[1]]
    c.true("and every probability column on ARMS (G2 -- six columns, one mutation)",
           all(_wsa2.cell(row=2, column=_ah2.index(n) + 1).number_format == '0.0"%"'
               for n in ('P(ace)', 'P(#1)', 'P(#2)')))
    c.true("G18: an arm's ROSTER slot is a ROLE (SP/rp) -- SP/RP/CL are roles, not "
           "positions; a pitcher's position is P and A74 has no entry for it",
           _cell('Ace', 'slot') in ('SP', 'rp'), str(_cell('Ace', 'slot')))
    c.true("G18: a bat's slot IS an A74 position", _cell('Real 1B', 'slot') in A74_POS.v)
    for _role in ('SP', 'RP', 'CL'):
        c.raises(f"G18: pricing the ROLE '{_role}' as a position is REFUSED, not "
                 f"silently returned as 0.0 ('an average position')",
                 SystemExit, pos_runs_600, _role)
    c.true("G18: a closer is classified as an ARM -- CL is in the role set",
           is_arm({'POS': 'CL'}) and is_arm({'POS': 'SP'}) and is_arm({'POS': 'RP'})
           and not is_arm({'POS': '1B'}))
    c.true("and carries NO positional runs at all -- a pitcher priced at 1B is -10.87",
           _cell('Ace', 'pos runs/600 (A74)') is None
           and _cell('Ace', 'bat + pos bar /600') is None
           and _cell('Ace', 'bat runs/600 (NO pos)') is None)
    c.true("the fixture arm SEPARATES the three bars -- with p_ace == p_no2 the board "
           "could be ranked on the wrong one invisibly",
           _cell('Ace', 'ceiling %') < 100.0, str(_cell('Ace', 'ceiling %')))
    _ap = {p['name']: p for p in _pl if p['side'] == 'ARM'}
    c.true("... and p(ace) really is below p(#2) -- different bars, not one point mass",
           float(_ap['Ace']['p_ace']) < float(_ap['Ace']['p_no2']),
           f"ace {_ap['Ace']['p_ace']} vs no2 {_ap['Ace']['p_no2']}")
    c.true("the ARM ceiling rank is ordered on P(#2), the bar the board claims",
           float(_ap['Ace']['p_no2']) > float(_ap['Swingman']['p_no2'])
           and _ap['Ace']['rank_ceiling'] < _ap['Swingman']['rank_ceiling']
           if _ap['Swingman']['rank_ceiling'] else True,
           f"{_ap['Ace']['rank_ceiling']} vs {_ap['Swingman']['rank_ceiling']}")
    c.true("an ARM takes WAR_1, a BAT takes WAR -- the fixture gives them DIFFERENT "
           "values so a swap cannot hide",
           _cell('Ace', 'WAR') == 4.7 and _cell('Real 1B', 'WAR') == 4.0,
           f"arm {_cell('Ace','WAR')}  bat {_cell('Real 1B','WAR')}")
    c.true("an arm also carries no glove ratings, so a sort on IF RNG cannot bury him",
           all(_cell('Ace', col) is None
               for col in ('IF RNG', 'IF ARM', 'OF RNG', 'OF ARM', 'TDP', 'C ABI')))
    c.true("the PA / IP column shows INNINGS for an arm and PLATE APPEARANCES for a bat",
           _cell('Ace', 'PA / IP') == 180.0 and _cell('Real 1B', 'PA / IP') == 500.0,
           f"arm {_cell('Ace','PA / IP')}  bat {_cell('Real 1B','PA / IP')}")

    print("\n=== 32. THE GLOVE -- does it HELP or HURT where he plays ===")
    def _G(**kw):
        d = {'POS':'SS','IF RNG':50,'IF ARM':50,'IF ERR':50,'TDP':50,
             'OF RNG':50,'OF ARM':50,'C ABI':20}
        d.update(kw); return GateView(d)
    def _ref(p, **kw):
        m = GLOVE_REF.v[p]
        d = {'IF RNG':m['rng'],'OF RNG':m['rng'],'IF ARM':m['arm'],'OF ARM':m['arm'],
             'TDP':m['tdp'],'IF ERR':50,'C ABI':20,'POS':p}
        d.update(kw); return GateView(d)
    # --- the reference is NAMED, and an average glove scores zero against it ----------
    for _p in ('SS','2B','CF','3B','RF','LF','1B'):
        c.eq(f"{_p}: the league-average glove at that position scores exactly zero",
             glove_runs(_ref(_p), _p), 0.0, 0.05)
    c.eq("+5 of RANGE above the positional average at short is A73's 6.84 runs",
         glove_runs(_ref('SS', **{'IF RNG': GLOVE_REF.v['SS']['rng'] + 5}), 'SS'),
         GLOVE_RANGE5.v['SS'], 0.05)
    c.true("a glove BELOW the positional average scores NEGATIVE -- the sign is the "
           "answer the GM asked for",
           glove_runs(_ref('SS', **{'IF RNG': GLOVE_REF.v['SS']['rng'] - 10}), 'SS') < 0)
    # --- the arm conflict is carried as a PAIR, never split -------------------------
    # ✅ THE ARM CONFLICT IS CLOSED BY MEASUREMENT -- one number, not a band.
    c.eq("+5 of ARM at THIRD is the measured 6.38 runs -- the largest arm term on the field",
         glove_runs(_ref('3B', **{'IF ARM': GLOVE_REF.v['3B']['arm'] + 5}), '3B'),
         GLOVE_ARM5.v['3B'], 0.05)
    c.true("arm is worth MORE than range at third base -- three independent routes agree "
           "(A113's dead heat at n=17,459, pocket rule 5's 1:1 gate, and this measurement)",
           GLOVE_ARM5.v['3B'] > GLOVE_RANGE5.v['3B'])
    c.true("infield arm is real and ordered 3B > SS > 2B, as A73 also found",
           GLOVE_ARM5.v['3B'] > GLOVE_ARM5.v['SS'] > GLOVE_ARM5.v['2B'] > 0)
    c.true("OUTFIELD and FIRST-BASE arm are ZERO -- measured directly off the export's own "
           "arm-runs column (slope -0.27 per +5, R2 0.025) and it is not deterrence, "
           "because assists per 150 games are FLAT across arm bands",
           all(GLOVE_ARM5.v[q] < 0.5 for q in ('LF','CF','RF','1B')))
    c.true("a strong arm now MOVES the number at short instead of widening a band",
         glove_runs(_ref('SS', **{'IF ARM': GLOVE_REF.v['SS']['arm'] + 20}), 'SS') > 10.0)
    print("\n=== 34. BABIP HAS A POTENTIAL, AND IT IS 'HT P' ===")
    c.true("BAT_TOOLS maps BABIP to 'HT P', not to a column that does not exist",
           ('BABIP', 'HT P', 'BABIP') in BAT_TOOLS,
           str([t for t in BAT_TOOLS if t[0] == 'BABIP']))
    c.true("NO_POTENTIAL_IN_OOTP is EMPTY -- there is no tool in this game without a "
           "potential, and claiming otherwise froze every young bat's on-base ceiling",
           len(NO_POTENTIAL_IN_OOTP) == 0, str(NO_POTENTIAL_IN_OOTP))
    c.true("every BAT tool now has a potential column named, so G13 can actually warn "
           "when one is missing instead of excusing it",
           all(pc for _, pc, _ in BAT_TOOLS))
    # a potential must move the ceiling: same current, higher potential -> higher P(OBP55)
    def _bat(babip, htp, age='20'):
        r = {'Name':'x','POS':'LF','ORG':'B','Age':age,'IF RNG':'50','IF ARM':'50',
             'OF RNG':'50','OF ARM':'50','TDP':'50','C ABI':'20','SPE':'50','STM':'20',
             'CON':'55','GAP':'50','POW':'60','EYE':'60','BABIP':str(babip),"K's":'50',
             'CON P':'60','GAP P':'55','POW P':'70','EYE P':'70','K P':'55',
             'HT P':str(htp),'wRC+':'120','PA':'500','WAR':'2.0','WAR_1':'2.0'}
        f = Frame.__new__(Frame); f.rows=[r]; f.cols=set(r); f.kind='LEAGUE'
        f.path='t'; f.single_org=False; f._org_filtered=False; f.stamp=lambda:'t'
        return build(f, rng=random.Random(SEED))[0]
    _lowp, _highp = _bat(40, 40), _bat(40, 65)
    c.true("a bat with BABIP potential 65 has a HIGHER on-base ceiling than the same bat "
           "frozen at 40 -- which is exactly what the old code could not see",
           float(_highp['p_obp']) > float(_lowp['p_obp']),
           f"frozen {_lowp['p_obp']} vs projected {_highp['p_obp']}")
    c.true("... and it reaches P(both) too, because the OBP index carries BABIP at 0.085",
           float(_highp['p_both']) >= float(_lowp['p_both']))
    c.eq("the frozen case still reproduces the old behaviour exactly (pot = cur)",
         float(_bat(40, 40)['obp_now']), float(_lowp['obp_now']), 1e-9)

    c.true("a clear positive reads HELPS and a clear negative reads HURTS",
           glove_verdict(5.0) == 'HELPS' and glove_verdict(-5.0) == 'HURTS'
           and glove_verdict(0.2) == 'neutral')
    # --- A58a: catcher defence is a NULL --------------------------------------------
    c.true("a catcher gets NO glove number at all -- A58a, p=.921, n=1,044, and an "
           "absent column is the finding, not an omission",
           glove_runs(_G(**{'C ABI':80}), 'C') is None)
    # --- ⛔ THE GATE IS A BREAK-EVEN LINE, NOT AN ELIGIBILITY FILTER -----------------
    c.true("the gate NEVER moves a player -- it labels. 22-42% of the AC's own regulars "
           "sit below the gate at the position they hold, so a filter would exclude the "
           "men actually doing the job",
           glove_runs(_G(**{'IF RNG':50}), 'SS') is not None
           and not gates_ok(_G(**{'IF RNG':50}), 'SS'))
    c.true("... and a man below the line is priced NEGATIVE rather than relocated, which "
           "is what 'stops COSTING runs' means (A84's own wording)",
           glove_runs(_G(**{'IF RNG':50}), 'SS') < 0)
    c.true("the gates are still A84 v3's numbers", GATE_SS.v == 65 and GATE_2B.v == 60
           and GATE_CF.v == 65 and GATE_3B_SUM.v == 120)
    # --- ⚠ NEVER ACROSS POSITIONS ---------------------------------------------------
    c.true("glove_runs takes ONE position and returns ONE pair -- there is no call that "
           "sums two positions, because a baseline cancels WITHIN a position and does "
           "not cancel across them (the defect that broke 1.8.0)",
           glove_runs.__code__.co_argcount == 2)
    # --- G20: the GM's fielding instruction, guarded against the CODE ---------------
    _FIELD_STATS = frozenset({'PO','A','E','TC','ZR','CER','CERA','PB','DP_1','IP_1',
                              'RNG','EFF','SBA','RTO','FPCT','PCT'})
    for _f in (glove_runs, gates_ok, lands, tools_spot):
        _lits = {x for x in _f.__code__.co_consts if isinstance(x, str)}
        c.true(f"{_f.__name__}() reads NO fielding counting stat -- fielding is the "
               f"RATINGS, on the GM's instruction",
               not (_lits & _FIELD_STATS), str(_lits & _FIELD_STATS))
    c.raises("and a GateView refuses a POSITION rating outright (G1)",
             PermissionError, lambda: _G()['SS'])

    print("\n=== 33. THE GLOVE, READ BACK OFF THE WRITTEN SHEET ===")
    c.true("every bat carries a helps/hurts verdict on ROSTER",
           all(r[_h.index('glove: helps or hurts')] not in (None, '')
               for r in _ws.iter_rows(min_row=2, values_only=True)
               if r[_h.index('slot')] not in ('SP', 'rp', None)))
    c.true("every bat names the highest rung its tools clear, which is what stops a reader "
           "pricing a man at the position the engine happened to file him under",
           all(r[_h.index('tools qualify at (highest)')] in TOOLS_LADDER.v
               for r in _ws.iter_rows(min_row=2, values_only=True)
               if r[_h.index('slot')] not in ('SP', 'rp', None)))
    c.true("an everyday SS whose glove misses A108's bar is carded SS and TOOLS 1B -- the "
           "pair of positions is the finding, and neither cell overwrites the other",
           _cell('Everyday SS', 'slot') == 'SS'
           and _cell('Everyday SS', 'tools qualify at (highest)') == '1B',
           f"{_cell('Everyday SS','slot')} / {_cell('Everyday SS','tools qualify at (highest)')}")
    c.true("the tools spot does NOT move when the reference does -- a fixed spectrum has "
           "no baseline to be an artifact of (the defect that retired glove_by_position)",
           tools_spot(_G(**{'IF RNG': 70, 'IF ARM': 60, 'OF RNG': 40})) == 'SS')
    c.true("a low-sample bat gets the tools spot and a REFUSAL at the carded spot, "
           "because his POS is a filing decision rather than a plan",
           'LABEL' in str(_cell('Small sample', 'glove: helps or hurts'))
           and _cell('Small sample', 'tools qualify at (highest)') in TOOLS_LADDER.v,
           str(_cell('Small sample', 'glove: helps or hurts')))
    c.true("G21: ... and the refusal is NOT contradicted by the cell beside it -- the "
           "carded-spot number and its break-even label both clear",
           _cell('Small sample', 'glove runs HERE (carded)') is None
           and _cell('Small sample', 'at break-even?') is None,
           f"{_cell('Small sample','glove runs HERE (carded)')} / "
           f"{_cell('Small sample','at break-even?')}")
    c.true("an ARM carries no glove number -- a pitcher has no fielding position here",
           _cell('Ace', 'glove: helps or hurts') in (None, '')
           and _cell('Ace', 'glove runs HERE (carded)') is None
           and _cell('Ace', 'tools qualify at (highest)') is None)
    # --- G22: the SAME five columns, read back off BATS ------------------------------
    c.true("G22: BATS carries the five glove columns under the headings it claims, and a "
           "RUN NUMBER sits under every heading that promises runs",
           all(h in _hb_ for h in ('glove: helps or hurts', 'glove runs HERE (carded)',
                                   'at break-even?', 'tools qualify at (highest)', 'glove runs THERE')),
           str([h for h in _hb_ if 'glove' in str(h)]))
    for _col in ('glove runs HERE (carded)', 'glove runs THERE'):
        c.true(f"G22: BATS '{_col}' holds numbers or blanks, never prose -- this is the "
               f"check that would have caught 'glove runs low'/'high' a version ago",
               all(r[_hb_.index(_col)] is None or isinstance(r[_hb_.index(_col)], (int, float))
                   for r in _wsb.iter_rows(min_row=2, values_only=True)),
               str([r[_hb_.index(_col)] for r in _wsb.iter_rows(min_row=2, values_only=True)
                    if not (r[_hb_.index(_col)] is None
                            or isinstance(r[_hb_.index(_col)], (int, float)))][:3]))
    c.true("G22: BATS and ROSTER agree on the tools spot for the same man -- one ladder, "
           "one answer, no third column labelled 'position' disagreeing with the other two",
           _bcell('Everyday SS', 'tools qualify at (highest)')
           == _cell('Everyday SS', 'tools qualify at (highest)'))
    c.true("the break-even label says yes or below, and never moves the player",
           _cell('Real 1B', 'at break-even?') in ('yes', 'below', '--')
           and _cell('Real 1B', 'slot') == _cell('Real 1B', 'POS'))
    c.true("'glove gates to' still shows where the RATINGS put him, beside where he is "
           "carded -- the two answer different questions and both are printed",
           _cell('Everyday SS', 'glove gates to') == '1B'
           and _cell('Everyday SS', 'slot') == 'SS')
    c.true("the ROSTER sheet no longer carries a column calling itself a TOTAL",
           'total runs/600' not in _h and 'bat + pos bar /600' in _h)

    print("\n=== 25. A DRAFT POOL, driven end to end through the BOARD ===")
    # ⛔ Review: verify() had never built a POOL frame, so the sheet a PICK is made from
    # had zero coverage -- an inverted board sort (pick #1 = worst player in the pool)
    # shipped clean, and the pool branch of rank_floor_and_ceiling kept the zero-block
    # rank that the league branch had just been fixed for.
    def _prow(name, pos, sch, pw, pwp, age):
        return {'Name': name, 'POS': pos, 'Age': age, 'HSC': sch,
                'IF RNG': '60', 'IF ARM': '60', 'OF RNG': '60', 'OF ARM': '60',
                'TDP': '50', 'C ABI': '50', 'SPE': '50', 'STM': '20',
                'CON': '50', 'GAP': '50', 'POW': pw, 'EYE': pw, 'BABIP': '50',
                "K's": '50', 'OVR': '2.5 Stars', 'POT': '4.5 Stars',
                'CON P': '60', 'GAP P': '55', 'POW P': pwp,
                'EYE P': pwp, 'K P': '50'}
    _prows = [_prow('Big Bat',  'RF', 'HS', '45', '75', '18'),
              _prow('Mid Bat',  'LF', 'HS', '40', '60', '18'),
              _prow('No Bat',   '1B', 'HS', '30', '35', '18'),
              _prow('No Bat 2', '1B', 'HS', '30', '35', '18')]
    _pf = Frame.__new__(Frame)
    _pf.rows = _prows; _pf.cols = set(_prows[0]); _pf.kind = 'POOL'
    _pf.path = 'selftest-pool'; _pf.single_org = False; _pf._org_filtered = False
    _pf.stamp = lambda: 'selftest-pool'
    _pp = build(_pf, rng=random.Random(SEED))
    score(_pp); rank_floor_and_ceiling(_pp)
    _ptmp = _os.path.join(_tf.mkdtemp(), 'pool.xlsx')
    write_workbook(_pf, _pp, _ptmp, [])
    _bd = _ox.load_workbook(_ptmp)['BOARD']
    _bh = [x.value for x in _bd[1]]
    _brows = list(_bd.iter_rows(min_row=2, values_only=True))
    _bn = [r[_bh.index('Name')] for r in _brows]
    _bw = [r[_bh.index('E[WAR] ranked on')] for r in _brows]
    c.true("the BOARD is ranked BEST FIRST -- pick #1 is not the worst man in the pool",
           _bw == sorted(_bw, reverse=True), str(list(zip(_bn, _bw))))
    c.true("the board's # column counts 1..n in sheet order",
           [r[_bh.index('#')] for r in _brows] == list(range(1, len(_brows) + 1)))
    c.eq("E[WAR] + pos = the column the board is ranked on",
         _brows[0][_bh.index('E[WAR]')] + _brows[0][_bh.index('+pos')],
         _brows[0][_bh.index('E[WAR] ranked on')], 0.11)
    _pz = [p for p in _pp if float(p['p_both']) <= 0.0]
    c.true("the pool fixture really contains a zero-ceiling block to test",
           len(_pz) >= 2, str([(p['name'], str(p['p_both'])) for p in _pp]))
    c.true("a POOL's zero-ceiling block is NOT ranked either -- the league-branch fix "
           "was applied to BOTH branches this time",
           all(p['rank_ceiling'] is None for p in _pz),
           str([(p['name'], p['rank_ceiling']) for p in _pz]))
    c.true("... and every one of them is tagged FLOOR, which is the real information",
           all(p['profile'] == 'FLOOR' for p in _pz))
    c.true("a POOL prices position off the GATE, not off POS (it has no designation)",
           all(p['priced_at'] == p['lands'] for p in _pp if p['side'] == 'BAT'))
    c.true("G7: no pool player carries a bat score built on a major-league mean",
           all(p['bat_runs'] is None for p in _pp))

    print("\n=== 30. EVERY PUBLISHED COLUMN, BOTH EXPORT KINDS ===")
    # ⛔ Review bloc 1, the largest: 14 mutations shipped in columns no assertion ever
    # read -- the BOARD's E[WAR]/+pos swap, ARMS and BATS ceiling ranks blanked, the
    # GATED sheet keyed to the wrong thing, the ROSTER gate column replaced wholesale.
    # Hand-written checks will never keep up with 200+ cells across two export kinds.
    # Generated ones will: every column must (a) exist, (b) not be wholly empty unless
    # it is on a documented allow-list, and (c) hold the TYPE its heading implies.
    # ⛔ KEYED BY (export kind, heading), NOT by heading alone.  Eight of these say
    # "a draft pool has no ...", and with a heading-only key a POOL's excuse licensed
    # the same column to be blank on a LEAGUE sheet: blanking every WAR cell on a
    # league workbook shipped clean, which is G17's outcome through a different door.
    _ALLOWED_EMPTY = {
        # heading -> why every cell may legitimately be blank
        'E[WAR] raw':   'league export: A104 is a draft-day model (G12/main)',
        'E[WAR] +pos':  'league export: A104 is a draft-day model',
        'E[WAR]':       'league export: A104 is a draft-day model',
        'floor rank':   'league export: no E[WAR], so no floor axis exists',
        'C ABI':        'a workbook with no catcher',
        'bat score note': 'a workbook where every bat was priced',
        'A115 conflict?': 'a workbook where no arm is counted differently by A41 and A103',
        'glove note':     'a workbook where the two ARM bounds agree about every player',
    }
    _ALLOWED_EMPTY_POOL = {
        'ORG':   'a draft pool has no organisations -- that is how G9 identifies one',
        'PA':    'a draft pool has no major-league plate appearances',
        'wRC+':  'a draft pool has no major-league rate stats',
        'WAR':   'a draft pool has no major-league WAR',
        'PA / IP': 'a draft pool has no major-league playing time',
        'wRC+ / FIP-': 'a draft pool has no major-league rate stats',
        'bat runs/600 (NO pos)': 'G7 on a pool: 110.8 is a major-league mean',
        '+/- 1 SE':              'G7 on a pool: there is no bat score to bound',
        'bat + pos bar /600':        'G7 on a pool: no bat half to add to the position half',
        'bat score note':        'G7 on a pool',
    }
    _PCT  = {'P(POW55)','P(OBP55)','P(both)','P(ace)','P(#1)','P(#2)','ceiling %'}
    _NUMS = {'bat runs/600 (NO pos)','pos runs/600 (A74)','bat + pos bar /600','+/- 1 SE',
             'pos runs/season','pos career WAR','WAR','Age','PA / IP'}
    for _label, _path in (('LEAGUE', _tmp), ('POOL', _ptmp)):
        _bk = _ox.load_workbook(_path)
        for _sn in _bk.sheetnames:
            if _sn in ('KEY', 'BASELINES', 'ACE CENSUS', 'NOTES'): continue
            _sh = _bk[_sn]
            _hh = [x.value for x in _sh[1]]
            _rr2 = list(_sh.iter_rows(min_row=2, values_only=True))
            if not _rr2: continue
            c.true(f"{_label}/{_sn}: every heading is a non-empty string, and unique",
                   all(isinstance(x, str) and x.strip() for x in _hh)
                   and len(set(_hh)) == len(_hh), str(_hh))
            c.true(f"{_label}/{_sn}: the sheet is exactly as wide as its headings",
                   _sh.max_column == len(_hh), f"{_sh.max_column} vs {len(_hh)}")
            _dead = [_hh[i] for i in range(len(_hh))
                     if all(r[i] is None or r[i] == '' for r in _rr2)
                     and _hh[i] not in _ALLOWED_EMPTY
                     and not (_label == 'POOL' and _hh[i] in _ALLOWED_EMPTY_POOL)]
            c.true(f"{_label}/{_sn}: no column is WHOLLY EMPTY without a documented "
                   f"reason -- a dead column is a defect that looks like a layout choice",
                   not _dead, str(_dead))
            for i, _nm in enumerate(_hh):
                _vals = [r[i] for r in _rr2 if r[i] is not None and r[i] != '']
                if not _vals: continue
                if _nm in _PCT:
                    # ⛔ '0 <= v <= 100' DOES NOT DISCRIMINATE.  A FRACTION IS ALSO IN
                    # THAT RANGE.  Emitting float(p_pow) instead of .percent passed this
                    # check while the sheet rendered 0.12155 as "0.1%" against a true
                    # 12.2% -- Doug Will's failure, to the decimal place, inside the
                    # check written to stop it.  A real probability column on these
                    # sheets is either exactly 0 or, once non-zero, at least 1 in 20,000
                    # expressed as a percent; a column of fractions can never exceed 1.0.
                    _nz = [v for v in _vals if v > 0]
                    c.true(f"{_label}/{_sn}/{_nm}: is a PERCENT, not a fraction, and "
                           f"carries the percent format (G2)",
                           all(isinstance(v,(int,float)) and 0.0 <= v <= 100.0 for v in _vals)
                           and (not _nz or max(_nz) > 1.0)
                           and _sh.cell(row=2, column=i+1).number_format == '0.0"%"',
                           f"max={max(_nz) if _nz else 0} of {_vals[:3]} "
                           f"fmt={_sh.cell(row=2, column=i+1).number_format}")
                elif _nm in _NUMS:
                    c.true(f"{_label}/{_sn}/{_nm}: is numeric in every populated cell",
                           all(isinstance(v, (int, float)) for v in _vals), str(_vals[:3]))
    # the BOARD's ceiling rank had the SAME cross-side collision ROSTER was fixed for
    _bd2 = _ox.load_workbook(_ptmp)['BOARD']
    _bh3 = [x.value for x in _bd2[1]]
    _cn  = [r[_bh3.index('ceiling #')] for r in _bd2.iter_rows(min_row=2, values_only=True)]
    c.true("B3 on the BOARD too: the ceiling rank is side-qualified there as well -- bats "
           "rank on P(both) and arms on P(#2), and one unqualified column collided 49% "
           "of the ranked rows on the sheet a PICK is made from",
           all(v is None or str(v).split()[0] in ('BAT', 'ARM') for v in _cn),
           str(_cn[:6]))

    # ⛔ THESE TWO WERE TAUTOLOGIES WHEN FIRST WRITTEN, 2026-09-22 -- 'X or Y or True',
    # and reading ROSTER's 'gate' column, which holds 'corner' and never a profile.
    # Worse, every fixture bat had POW 50 at age 27, so A76 gives no development and
    # p_both is 0 for all of them: the LIVE ranking path was never executed, which is
    # why an INVERTED ceiling rank shipped clean.  The fixture now spans both branches.
    def _rank(nm):
        v = _cell(nm, 'ceiling rank')
        return None if v is None else int(str(v).split()[-1])
    c.true("a bat that CAN clear the bar is ranked, and the fixture really has one",
           _rank('Slugger') == 1 and _cell('Slugger', 'ceiling %') > 0.0,
           f"rank {_cell('Slugger','ceiling rank')} at {_cell('Slugger','ceiling %')}")
    c.true("the live block is ordered BY THE BAR -- a better ceiling ranks ahead",
           _cell('Slugger', 'ceiling %') > _cell('Fringe', 'ceiling %')
           and _rank('Slugger') < _rank('Fringe'),
           f"{_cell('Slugger','ceiling %')}@{_cell('Slugger','ceiling rank')} vs "
           f"{_cell('Fringe','ceiling %')}@{_cell('Fringe','ceiling rank')}")
    c.true("B3: the ceiling rank is QUALIFIED BY SIDE -- bats rank on P(both) and arms "
           "on P(#2), different bars, and one unqualified column collided a catcher "
           "and a reliever at 'rank 1'",
           str(_cell('Slugger', 'ceiling rank')).startswith('BAT '),
           str(_cell('Slugger', 'ceiling rank')))
    c.true("a bat that clears it in ZERO of the simulations is NOT ranked -- a rank over "
           "a tie block is input order wearing a ranking's clothes",
           all(r[_h.index('ceiling rank')] is None
               for r in _ws.iter_rows(min_row=2, values_only=True)
               if r[_h.index('ceiling %')] == 0.0))
    c.true("the live block is ranked out of the LIVE count, not the whole group",
           f'of {_live_n}' in _prof['Slugger'], _prof['Slugger'])
    c.true("a zero-ceiling player is told WHY, naming the simulation count",
           'NO CEILING' in _prof['Real 1B'] and f'{NSIM:,}' in _prof['Real 1B'],
           _prof['Real 1B'])
    c.true("the percent column is found BY HEADING and really is formatted",
           _ws.cell(row=2, column=_h.index('ceiling %') + 1).number_format == '0.0"%"')
    # ⛔ THIS CHECK WAS A TAUTOLOGY UNTIL 2026-09-22.  It read the written sheet with
    # iter_rows(values_only=True), which PADS every row out to max_column -- so
    # len(r) == len(headers) always, and it could not fail.  Review proved it by
    # disabling the guard AND truncating a row: still [PASS].  Drive the guard itself.
    c.raises("the width guard REFUSES a player grid row that is short",
             SystemExit, _probe_width, [1, 2], ['a', 'b', 'c'])
    c.raises("... and one that is too long, on any sheet",
             SystemExit, _probe_width, [1, 2, 3, 4], ['a', 'b', 'c'])
    c.true("... and accepts an exact row",
           _probe_width([1, 2, 3], ['a', 'b', 'c']) is True)

    print("\n=== 21. the bat slope IS A74, read in the other direction ===")
    _A74_SRC = {'C':101.6,'SS':105.9,'3B':106.8,'CF':108.3,
                '2B':108.9,'RF':112.1,'LF':114.8,'1B':128.1}
    for _p, _w in _A74_SRC.items():
        c.eq(f"{_p}: A74 {A74_POS.v[_p]:+.2f} recovered from wRC+ {_w} by the bat slope",
             -bat_runs_600(_w), A74_POS.v[_p], 0.011)
    c.eq("a bat at the A74 population mean is worth exactly zero",
         bat_runs_600(WRC_MEAN.v), 0.0, 1e-12)
    c.true("no wRC+ at all yields None with a reason, never zero",
           bat_runs(None)[0] is None and bat_runs(None)[1])
    c.true("bat_runs never reads WAR (A114 s1: engine WAR carries its own positional "
           "credit, so subtracting A74 from it would mix two systems)",
           'war' not in bat_runs.__code__.co_names
           and 'war' not in bat_runs_600.__code__.co_names)
    c.true("PT_RATIO is NOT in the rate path -- A74's denominator is 600 PA (units)",
           'PT_RATIO' not in bat_runs.__code__.co_names
           and 'PT_RATIO' not in pos_runs_600.__code__.co_names)
    c.true("PT_RATIO IS still in the career-WAR path, where A114/G8 requires it",
           'PT_RATIO' in pos_adj_runs.__code__.co_names)

    print("\n=== 22. G15/G7 -- the refusals are exact and typed ===")
    c.true("the fill value is matched EXACTLY -- 100.4 is a real measurement, not a fill",
           bat_runs(100.4, 400, rostered=False)[0] is not None)
    c.true("... and 100.0 exactly is refused", bat_runs(100.0, 400, rostered=False)[0] is None)
    c.true("101 on an unassigned player is a real number",
           bat_runs(101.0, 400, rostered=False)[0] is not None)
    c.true("a ROSTERED player reading 100 is honoured (G14's PA floor governs there)",
           bat_runs(100.0, 400, rostered=True)[0] is not None)
    for _bad in (float('nan'), float('inf')):
        c.true(f"a non-finite wRC+ ({_bad}) is refused, never raised mid-build",
               bat_runs(_bad, 400)[0] is None)
    c.true("G7: a DRAFT POOL is refused -- 110.8 is a major-league mean",
           bat_runs(145, 400, rostered=False, kind='POOL')[0] is None)
    c.true("G7: and says so, rather than blanking like a small sample",
           'G7' in bat_runs(145, 400, rostered=False, kind='POOL')[1])

    print("\n=== 23. G17 -- the column the ROSTER rank is built on must exist ===")
    class _FW:
        def __init__(self, cols, kind='LEAGUE'): self.cols=set(cols); self.kind=kind
    _base = ['Name','POS','Age','IF RNG','OF RNG','OF ARM','IF ARM','STM'] + \
            [cc for t in BAT_TOOLS + ARM_TOOLS for cc in t[:2]]
    c.raises("a LEAGUE export with NO WAR column is REFUSED -- the '#' column would "
             "number the input order while looking like a ranking",
             SystemExit, check_columns, _FW(_base + ['WAR_1']))
    c.true("a LEAGUE export WITH WAR is accepted",
           isinstance(check_columns(_FW(_base + ['WAR','WAR_1'])), list))
    c.true("only ONE WAR column is a named warning -- every PITCHER would read blank",
           any('WAR_1' in w for w in check_columns(_FW(_base + ['WAR']))),
           str(check_columns(_FW(_base + ['WAR']))))
    c.true("a draft POOL is not asked for WAR; it has none and is not ranked on it",
           isinstance(check_columns(_FW(_base, kind='POOL')), list))

    print("\n=== 19. G13 -- a missing POTENTIAL column is named, not swallowed ===")
    class _F:
        def __init__(self, cols): self.cols = set(cols); self.kind = 'POOL'
    _full = ['Name','POS','Age','IF RNG','OF RNG','OF ARM','IF ARM','STM'] + \
            [c for t in BAT_TOOLS + ARM_TOOLS for c in t[:2]]
    c.true("a complete export raises nothing",
           check_columns(_F([x for x in _full if x != 'BABIP P'])) == [])
    _w = check_columns(_F([x for x in _full if x not in ('HRA P','BABIP P')]))
    c.true("a missing HRA potential is reported",
           any('HRA P' in s for s in _w), str(_w))
    c.true("and the report says the tool is FROZEN, not just 'missing'",
           any('FROZEN' in s for s in _w))
    c.true("a missing BABIP potential is NOT reported -- OOTP publishes none",
           not any('BABIP' in s for s in check_columns(_F([x for x in _full if x != 'BABIP P']))))
    _m = check_columns(_F([x for x in _full if x not in ('STU','BABIP P')]))
    c.true("a missing TOOL itself is reported as worse than a missing potential",
           any('ABSENT' in s for s in _m), str(_m))

    print("\n=== 18. pcts() is a pure speed change and moves no number ===")
    _s = [3.0, 1.0, 2.0, 5.0, 4.0]
    c.true("pcts matches pct exactly on every quantile",
           all(abs(a - pct(_s, q)) < 1e-12
               for a, q in zip(pcts(_s, (.10, .50, .90)), (.10, .50, .90))))
    c.true("a point-mass list short-circuits to the value itself",
           pcts([7.0]*50, (.10, .50, .90)) == [7.0, 7.0, 7.0])
    c.true("pcts does not mutate its input", (lambda l: (pcts(l,(.5,)), l == [3.0,1.0,2.0])[1])([3.0,1.0,2.0]))

    print("\n=== 17. G12 -- an arms-only pool refuses loudly, not silently ===")
    _arms_only = [{'side':'ARM','cls':'HS','cur4':40.0,'gap4':10.0,'eff_now':2,'stm':50,
                   'name':'x','ewar':None,'ewar_adj':None}]
    score(_arms_only)
    c.true("every player gets an ewar_blocked explanation",
           all(p.get('ewar_blocked') for p in _arms_only))
    c.true("the explanation names the cause, not just the symptom",
           'NO BATTERS' in _arms_only[0]['ewar_blocked'])
    c.true("E[WAR] is left as None rather than guessed",
           _arms_only[0]['ewar'] is None)

    print("\n=== 16. G11 -- the board carries two ranks and names the difference ===")
    def _fake(side, ewar, ceil):
        p = {'side': side, 'ewar': ewar, 'ewar_adj': ewar}
        p['p_both'] = Pct(ceil); p['p_no2'] = Pct(ceil)
        return p
    # floor-best is ceiling-worst and vice versa, plus a middle man
    _hi_floor = _fake('BAT', 30.0, 0.000)
    _hi_ceil  = _fake('BAT', 10.0, 0.050)
    _mid      = _fake('BAT', 20.0, 0.025)
    rank_floor_and_ceiling([_hi_floor, _hi_ceil, _mid])
    c.true("the top-E[WAR] / zero-ceiling player is tagged FLOOR",
           _hi_floor['profile'] == 'FLOOR', _hi_floor['profile'])
    c.true("the low-E[WAR] / high-ceiling player is tagged CEILING",
           _hi_ceil['profile'] == 'CEILING', _hi_ceil['profile'])
    c.true("a player ranked the same on both axes is BALANCED",
           _mid['profile'] == 'BALANCED', _mid['profile'])
    # a ZERO ceiling is FLOOR no matter how close the ranks are (the Reames case)
    _z  = _fake('BAT', 30.0, 0.000)
    _z2 = _fake('BAT', 29.0, 0.000)
    _z3 = _fake('BAT', 28.0, 0.001)
    rank_floor_and_ceiling([_z, _z2, _z3])
    c.true("a top-of-board player with a ZERO ceiling is FLOOR, not BALANCED",
           _z['profile'] == 'FLOOR', _z['profile'])
    c.true("a non-zero ceiling is still judged on rank distance",
           _z3['profile'] in ('CEILING','BALANCED'), _z3['profile'])
    c.true("both ranks are assigned to every player",
           all('rank_floor' in p and 'rank_ceiling' in p
               for p in (_hi_floor, _hi_ceil, _mid)))
    _solo = _fake('ARM', 5.0, 0.01)
    rank_floor_and_ceiling([_solo])
    c.true("a one-player side does not divide by zero", _solo['profile'] == 'n/a')
    _lg = [{'side':'BAT','ewar':None,'ewar_adj':None,'p_both':Pct(0.01),'p_no2':Pct(0.01)}
           for _ in range(3)]
    rank_floor_and_ceiling(_lg)
    c.true("a LEAGUE export (no E[WAR]) refuses to fake a FLOOR rank",
           all(p['rank_floor'] is None for p in _lg), _lg[0]['profile'])
    c.true("... but PUBLISHES the ceiling rank, which p_both makes computable",
           sorted(p['rank_ceiling'] for p in _lg) == [1, 2, 3],
           str([p['rank_ceiling'] for p in _lg]))
    c.true("... and the profile names WHICH rank and out of how many",
           all(p['profile'].startswith('ceiling ') and ' of ' in p['profile'] for p in _lg),
           _lg[0]['profile'])
    _zero = [{'side':'BAT','ewar':None,'ewar_adj':None,'p_both':Pct(0.0),'p_no2':Pct(0.0)}
             for _ in range(5)]
    rank_floor_and_ceiling(_zero)
    c.true("a group that NEVER clears the bar gets no ceiling rank at all",
           all(p['rank_ceiling'] is None for p in _zero))
    c.true("... and every one is labelled NO CEILING, not ranked 1..5 by input order",
           all('NO CEILING' in p['profile'] for p in _zero), _zero[0]['profile'])

    print("\n=== 15. G10 -- forcing a kind does not manufacture a league ===")
    _one = [{'ORG':'Philadelphia','Name':'A','POS':'SS'},
            {'ORG':'Philadelphia','Name':'B','POS':'C'}]
    _two = [{'ORG':'Philadelphia','Name':'A','POS':'SS'},
            {'ORG':'Toronto','Name':'B','POS':'C'}]
    c.true("a one-club file forced to LEAGUE is flagged single_org",
           Frame(_one, 'x.csv', kind='LEAGUE').single_org is True)
    c.true("a genuine two-club league is NOT flagged",
           Frame(_two, 'x.csv').single_org is False)
    c.true("a draft pool is never flagged single_org (the flag is LEAGUE-only)",
           Frame([{'ORG':'-','HSC':'HS','Name':'A'}], 'x.csv').single_org is False)

    print("\n=== 31. THE SUITE ITSELF ===")
    # ⛔ MUST BE LAST.  Section 30 is GENERATED and contributes ~72 of these checks. A
    # bug in the generator -- an allow-list that swallows everything, a loop that skips
    # two sheets, an export kind that never runs -- DELETES assertions, and the suite
    # then prints a SMALLER number and the word PASSED. Nothing compared that number to
    # anything. A shrinking suite is the quietest failure in this file: it looks exactly
    # like success. Raising MIN_CHECKS when checks are added is part of adding them.
    c.true(f"the suite has not SHRUNK -- {MIN_CHECKS} is the floor, and lowering it is a "
           f"decision, not an edit", c.n >= MIN_CHECKS, f"ran {c.n}, floor {MIN_CHECKS}")

    print(f"\n{'='*78}")
    if c.fail:
        print(f"  {c.fail} of {c.n} CHECKS FAILED -- nothing will be written.")
    else:
        print(f"  ALL {c.n} CHECKS PASSED.")
    print('='*78)
    return c.fail

# =============================================================================
# CLI
# =============================================================================

def main():
    ap = argparse.ArgumentParser(description="OOTP 27 player analysis (registry v16).")
    ap.add_argument('cmd', choices=['verify','analyze','columns'])
    ap.add_argument('export', nargs='?', help='.csv or .xlsx OOTP export')
    ap.add_argument('-o','--out', default=None, help='output .xlsx (default: alongside the input)')
    ap.add_argument('--sheet', default=None, help='sheet name, for multi-sheet .xlsx')
    ap.add_argument('--kind', default=None, choices=['POOL','LEAGUE'],
                    help='override the POOL/LEAGUE detection (G9). Use only when you are '
                         'certain; a single-team roster is NEITHER.')
    a = ap.parse_args()

    if a.cmd == 'verify':
        sys.exit(1 if verify() else 0)

    if not a.export: sys.exit("ERROR: this command needs an export file.")
    fr = Frame(load(a.export, a.sheet), a.export, a.sheet, kind=a.kind)
    print(f"\n  DETECTED: {fr.kind} export"
          + ("   (career-WAR projection WILL run -- A104 draft-day model)" if fr.kind=='POOL'
             else "   (career-WAR projection will NOT run on established players)"))

    if a.cmd == 'columns':
        print(f"\n{fr.stamp()}\n")
        check_columns(fr, verbose=True)
        print(f"\n  all columns ({len(fr.cols)}):")
        for i, col in enumerate(sorted(fr.cols)):
            print(f"   {col:<22}", end='\n' if i % 4 == 3 else '')
        print(); return

    print(f"\n{fr.stamp()}\n")
    check_columns(fr, verbose=True)
    print("\nrunning the self-test suite before touching your data (rule 22)...")
    if verify():
        sys.exit("\nREFUSING TO WRITE: the self-test suite failed. Nothing has been produced.")
    print("\nbuilding...")
    players = build(fr)
    notes = []
    if fr.kind == 'POOL':
        score(players)
    else:
        for p in players:
            p['ewar'] = None; p['ewar_adj'] = None
        notes.append('LEAGUE export: E[career WAR] is a DRAFT-DAY model (A104) and is not '
                     'computed for established players. Use FIP-/wRC+/WAR and the gates.')
    conflicts = [p['name'] for p in players if p.get('eff_conflict')]
    if conflicts:
        notes.append(f"A115 OPEN CONFLICT -- {len(conflicts)} arm(s) counted differently by A41 "
                     f"(changeup floor 45) and A103 (flat 40): {', '.join(conflicts[:12])}"
                     + (' ...' if len(conflicts) > 12 else ''))
    flips = [p['name'] for p in players if p.get('role_flips')]
    if flips:
        notes.append("*** A115 CHANGES THE ROLE VERDICT for "
                     f"{len(flips)} arm(s): {', '.join(flips)}. Under A41 they are RELIEVERS; "
                     "under A103 they are STARTERS. The board cannot decide this for you, and "
                     "E[career WAR] below uses the A41 count.")
    notes.append("A115 NOTE: _arm_raw() scores b_eff on the A41 count (changeup floor 45). "
                 "A104's b_eff may have been fitted on A103's flat-40 rule -- the sources "
                 "disagree. Each disputed pitch is worth 1.967 career WAR.")
    out = a.out or os.path.splitext(a.export)[0] + '_ANALYSIS.xlsx'
    write_workbook(fr, players, out, notes)
    print(f"\n  wrote {out}")
    print(f"  {sum(1 for p in players if p['side']=='BAT')} bats, "
          f"{sum(1 for p in players if p['side']=='ARM')} arms")
    for n in notes: print(f"  NOTE: {n}")

if __name__ == '__main__':
    main()
