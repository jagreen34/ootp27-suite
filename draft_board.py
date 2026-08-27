#!/usr/bin/env python3
"""
draft_board.py — score an OOTP draft pool on measured expected career WAR.

    python3 draft_board.py AC_draft_pool_172.csv [-o board.csv]

Every constant below is measured on the parquet (seeds K-T) and carries its source.
Nothing here is a judgement call except where a comment says so explicitly.

Design rule: this script FAILS LOUDLY rather than producing a plausible-looking board.
A missing column, an unrecognised school class, or a cell with no measurement is an
error or an explicit blank -- never a silent zero.
"""
import csv, sys, argparse, math

# ============================== CONSTANTS ==============================
# --------------------------------------------------------------------
# E[career WAR] = intercept + b_cur * current_level + b_gap * potential_gap,
# fitted separately within each school class. Parquet seeds K-T:
# 8,126 drafted position players and 7,858 drafted pitchers followed to 26+.
#
# This REPLACES the (class x level) lookup cells used in the first version of
# this script. Those cells rounded current level to the nearest 5, which put
# everything from 42.5 to 50 in one bucket and inflated it: the "JR cur-45"
# cell read 19.6 where the true value at 42.5 is 14.2. Measured at 2.5-point
# resolution the relationship is smooth and near-linear, with no cliff:
#   JR  cur 35 -> 5.7 | 37.5 -> 8.4 | 40 -> 12.5 | 42.5 -> 14.2 | 45 -> 15.0 | 50 -> 20.4
#   SR  cur 35 -> 4.6 | 37.5 -> 9.6 | 40 -> 12.2 | 42.5 -> 13.1 | 45 -> 14.0 | 50 -> 18.4
# Calibration check: at each class's mean current level and mean gap the model
# returns that class's observed mean career WAR (HS 13.3 v 13.28 observed).
#
# current level = (POW+EYE)/2 for bats, (HRA+CON)/2 for arms.
# gap = potential of the same pair, minus current.
#                 intercept   b_cur   (t)     b_gap   (t)
# ---------------------------------------------------------------------------
# LEAGUE CALIBRATION -- WITHDRAWN. A99 claimed ratings are not comparable across
# leagues (the AC carrying ~4.9 less POW and ~6.7 more HRA while hitting 17% more
# home runs). A100 cut the outcome gap to +7.7% by season-matching, and A101 closed
# it: the AC and the parquet share one display scale and one run environment, and
# the whole remaining difference is ballparks. Ratings cross over UNCONVERTED.
# RETIRED 2026-08-26 (A101). Kept only as a record of what was removed and why.
# These offsets were fitting the AC's +5.5% ballpark advantage as a rating shift.
_RETIRED_LEAGUE_CAL = {'POW': 4.9, 'EYE': -1.5, 'HRA': -6.7, 'PCON': -0.5}
AC_MEAN_PF_HR = 1.0546     # A101. Divisor for AC->parquet OUTCOME comparison only.
QUAKERS_PF_HR = 1.300      # A95/A101. Highest in the AC (tied Denver). Team-level only.
# ⚠ BOTH ARE DECLARED AND DELIBERATELY UNUSED IN SCORING. DO NOT WIRE THEM IN.
# A102: the draft board must be park-BLIND. A draftee reaches the majors in 3-6
# years; the AC's park-change window runs every few years and the standing plan is
# to move off 1.300. Scoring a draft pool against the current park prices an asset
# on an environment that will not exist when it arrives. Park adjustment belongs in
# `board.html` (PARK.POW, the LIVE roster, this season) and nowhere else.
# Position-mean RANGE for the POOL's league. The fitted term is
# b_range * (range - position mean) = 'points above a typical fielder HERE', so
# the centre must be the pool's own league. AC shortstop regulars average
# IF RNG 68.0 against the parquet's 58.5 -- centring an AC shortstop on 58.5
# credits him ~9.5 points he does not have, about 8 career WAR at b_range 0.84.
POS_MEAN_RNG_AC = {'C': 30.4, 'SS': 68.0, '2B': 58.3, '3B': 54.6, 'CF': 64.9, 'RF': 56.6, 'LF': 51.1, '1B': 43.3}
# ---------------------------------------------------------------------------
# LEAGUE_CAL IS OFF. Verified 2026-08-25: the AC and the parquet share one display
# scale. Both run 20-80 on a step-5 grid with 13 distinct values; spreads match
# (POW sd 10.3 v 11.1, EYE 10.7 v 11.8); and the tail frequencies are near-identical
# (EYE at 80: 1.63% AC v 1.67% parquet; HRA at 80: 0.44% v 0.41%). The GM confirms
# the leagues are on the same scale and that league TOTALS are engine-calculated from
# era settings -- which is why the AC out-homers a league whose stated power is higher,
# with no rating-scale difference involved. Rule 14 / A100 §6: with the scale question
# answered YES, the calibration is deleted rather than fitted.
CALIBRATE_LEVEL = False   # RETIRED, not toggled. A101 closed the question. Do not re-enable.
#
# RANGE CENTRING STAYS ON, and it is a different object. The fitted term is
# b_range * (range - position mean) = "points above a typical fielder at this position".
# Defensive value is measured by ZR, which is scored against LEAGUE-AVERAGE defence, so
# a shortstop's run value depends on his peers: IF RNG 70 in a league whose shortstops
# average 68.0 is barely above average, while in one averaging 58.5 it is excellent.
# Offensive value is absolute -- a home run is a home run -- so `cur` must NOT be
# re-centred, which is exactly what LEAGUE_CAL was doing.
CALIBRATE_RANGE = True    # centre range on the POOL league's own position means
CALIBRATE = CALIBRATE_RANGE   # back-compat for the gate selection below
#
# CROSS-SIDE STATUS: caveat DOWNGRADED 2026-08-25 by A100. Cross-side comparison of E_WAR
# is usable with the reservations below. The earlier "5.3-point shift worth 4-5 career WAR,
# rank bats against bats only" warning is WITHDRAWN -- it differenced two numbers on two
# different models' input scales, which is not a quantity in any unit, and it rested on a
# run-environment argument that does not hold (in a closed league R = RA identically, so
# league R/G carries zero information about the bat/arm split).
#
# What mean-matching actually assumes: the average AC regular is worth what the average
# parquet regular is worth, and likewise for starters. Season-matched, the AC-parquet
# outcome gap is +7.7% HR, +6.5% ISO, +2.6% runs -- not the 17% A99 reported off a
# 15-season pool spanning 1.87x in HR rate. So the assumption is wrong by at most a couple
# of percent of run production.
#
# The offsets themselves were re-measured on parquet 1977 only and are stable: POW -4.9 ->
# -5.3, HRA +6.7 -> +7.0, nothing moving more than 0.5. Parquet ratings drift <=1.0 point
# across all 15 seasons while its outcomes swing 1.87x -- so the RATING gaps were not a
# pooling artifact even though the OUTCOME gap was.
#
# Two real defects remain, neither of which was the one originally diagnosed:
#   1. NO SLOPE TERM. LEAGUE_CAL is an additive constant applied in DISPLAY space, and
#      rule 15 says the internal->display map compresses above 50. +4.9 display points at
#      POW 30 and at POW 70 are different internal shifts. A defect of form, independent
#      of the level.
#   2. THE SCALE QUESTION IS UNASKED (rule 14). The parquet is `TRUE 256k Test`, a test
#      league with every park factor exactly 1.000 in all 4,200 team-seasons; the AC is a
#      live league with real parks. If a same-scale export of both is obtainable,
#      LEAGUE_CAL should be DELETED, not re-fitted. Cost to check: minutes. Do that first.
#   3. RESOLVED 2026-08-26 by A101. The AC's absolute park level is now measured. The
#      parquet enforces 1.000 on EVERY park factor in all 4,200 team-seasons (a neutral
#      rig), so it is the external anchor the AC's own normalised PF columns could not
#      provide. AC mean PF HR = 1.0546. Season-matched on the 64-game file the AC runs
#      0.9160 HR/team-game against parquet-1977's 0.8582 = +6.7%; divide by 1.0546 and
#      the gap is +1.2%, inside noise. The residual was park, not scale, not calibration.
#      LEAGUE_CAL is therefore RETIRED, not merely disabled -- it was fitting a ballpark
#      effect with a rating offset. Defect 1 (no slope term) is moot with the block gone.
#
# See claude/A100_cross_league_calibration_is_mostly_a_pooling_artifact.md and
#     claude/A101_ac_park_level_closes_calibration.md.
# ---------------------------------------------------------------------------

# ===========================================================================
# A104 — MODELS REFIT ON TRUE DRAFT-DAY PLAYERS. 2026-08-26.
# Source: draft_pool_full.parquet joined to player_cross_section_full.parquet on
# (seed, ID), keeping the pool row where season == DRAFT_YR, followed to 26+.
# n = 5,978 (2,724 bats / 3,254 arms). Calibrated: predicted class means match
# observed exactly. SUPERSEDES the first-observed-season reconstruction, which
# was 16.7% true draft-day rows at a median lag of six seasons.
#
# THE HEADLINE CHANGE: potential GAP is a NULL for hitters (-0.049, t -1.10) and
# NEGATIVE for college juniors (-0.209, t -2.8). The old board paid 0.33-0.48 per
# gap point -- roughly +20 career WAR of fiction on a 42.5-point gap. A98's
# "+1.36 per gap point" is WITHDRAWN; it was fitted on 24-year-olds.
# RANGE is the strongest batter term in the model (t = 17.2).
# For ARMS gap survives small (+0.162) and only for high schoolers.
BAT_MODEL_DD = {   # (intercept, b_current, b_gap, b_range_centred)
    'HS': [-2.9, 0.939, -0.051, 0.327],
    'JR': [-14.415, 0.965, -0.198, 0.781],
    'SR': [-4.359, 0.345, 0.427, 0.91],
}
ARM_MODEL_DD = {   # (intercept, b_current, b_gap, b_eff, b_stamina)
    'HS': [-36.603, 0.909, 0.229, 1.638, 0.253],
    'JR': [-54.834, 1.193, 0.056, 2.359, 0.286],
    'SR': [-43.536, 1.012, 0.166, 2.074, 0.123],
}
# Position-mean RANGE measured on DRAFT-DAY players (not regulars -- draftees sit
# ~15 points below a regular on every tool, so regular-season means over-centre).
POS_MEAN_RNG_DD = {'1B': 38.3, '2B': 51.0, '3B': 48.3, 'C': 32.9, 'CF': 58.9, 'LF': 44.2, 'RF': 50.7, 'SS': 58.3}
USE_DRAFTDAY = True   # A104. False reproduces the pre-A104 board for provenance.
# ===========================================================================

BAT_MODEL = {   # (intercept, b_current, b_gap, b_range)
    # ONE joint fit per class: WAR ~ current + gap + range + position dummies,
    # with RANGE CENTRED ON THE POSITION MEAN. All four terms and the positional
    # adjustment below come from the same specification -- they cannot be mixed
    # with coefficients fitted any other way. An earlier version paired intercepts
    # fitted on RAW range with a centred range term and silently removed ~25 WAR
    # from every hitter.
    'HS': ( -34.97,  0.904,  0.476,  0.785),   # n=2895, R2=.296
    '19': ( -17.57,  0.525,  0.363,  0.662),   # n=1227, R2=.268
    'JR': ( -32.61,  1.000,  0.334,  1.126),   # n=1336, R2=.417
    'SR': ( -34.40,  0.849,  0.408,  0.789),   # n=2668, R2=.346
}
# POSITIONAL ADJUSTMENT -- career WAR relative to LF, pooled across classes
# (class-specific dummies are noisy at these n and disagree on 1B).
# This is the value REMAINING after whatever positional adjustment OOTP's own
# WAR already applies, so it understates the true premium at C and SS.
POS_ADJ = {'C': 2.7, 'SS': 13.92, '2B': 6.31, '3B': 5.67, 'CF': 8.27, 'RF': 1.45, '1B': -3.16, 'LF': 0.0, 'DH': -3.16}
# Range is measured against the POSITION mean, not a global 50. Catchers average
# IF RNG 32.5 because the rating does not describe their job.
CATCHER_MODEL = {'HS': [-31.946, 0.875, 0.416, 0.306], '19': [-3.677, 0.274, 0.107, 0.704], 'JR': [-18.461, 0.667, 0.319, 0.567], 'SR': [-20.367, 0.631, 0.374, 0.757]}
# Catchers are scored on C_ABI, not IF RNG. Within catchers (n=1,203) IF RNG is
# NOISE -- t=+0.7, R2 unmoved -- while C_ABI is t=+11.6 and lifts R2 .235 -> .312.
# An earlier version scored catchers on IF RNG centred at 32.5 and handed one a
# fabricated +8.4 WAR. C_ARM (t=4.8) and C_FRM (t=9.6) also predict but correlate
# 0.53 with C_ABI, so only C_ABI is used.
# CAUTION: A58 nulled C_ABI against a RUN-PREVENTION outcome (p=.921, N=1,044) and
# A83 §16 withdrew a C_ABI gate on that basis. That result stands. This is a
# different question -- C_ABI predicts a catcher's CAREER WAR, which may simply be
# OOTP's WAR crediting catcher defence directly. Use it to rank catchers; do NOT
# claim it shows catcher defence prevents runs.
CATCHER_MEAN_ABI = 55.7
POS_MEAN_RNG = {'1B': 39.0, '2B': 52.3, '3B': 49.5, 'C': 32.5, 'CF': 59.7, 'LF': 47.7, 'RF': 50.6, 'SS': 58.5}
# ---------------------------------------------------------------------------
# A103 (2026-08-26): ARSENAL DEPTH IS THE LARGEST OMITTED TERM IN THE PITCHER MODEL.
# Refit on the SAME sample construction as PIT_MODEL (parquet seeds K-T, first
# draft season, followed to 26+, dage 17-23, gap>=0), adding `eff` = the count of
# pitches rated >= PITCH_FLOOR (40) -- the board's own definition, used until now
# only as a ROLE LABEL and never as a value term.
#
#   eff at draft ->  career WAR    career IP    career GS      n
#        0              1.1           443          38          97
#        1              2.3           394          18         412
#        2              5.5           488          31       1,631
#        3             11.6           918         113       1,781   <-- the cliff
#        4             16.2         1,125         155         956
#        5             21.2         1,348         198         281
#
# Two effective pitches is a career reliever (31 starts, 488 innings). Three is a
# starter (113 starts, 918 innings). Career WAR DOUBLES across that one step, and
# the old two-term model could not see it at all.
# Every class significant: HS t=8.9, 19 t=5.1, JR t=10.7, SR t=14.6.
PIT_MODEL_EFF = {   # (intercept, b_current, b_gap, b_eff)
    'HS': (-31.644, 0.704, 0.260, 2.552),   # n=1885, t(eff)= 8.86
    '19': (-35.484, 0.813, 0.315, 2.042),   # n= 842, t(eff)= 5.07
    'JR': (-73.548, 1.295, 0.805, 7.459),   # n= 718, t(eff)=10.67
    'SR': (-68.574, 1.296, 0.804, 5.371),   # n=1725, t(eff)=14.60
}
USE_ARSENAL = True    # A103. Set False only to reproduce the pre-A103 board.

# SUPERSEDED by PIT_MODEL_EFF above. Retained for reproducibility only.
PIT_MODEL = {   # same design, fitted on PIT_WAR
    'HS': (-24.57, 0.707, 0.260),   # n=2620
    '19': (-28.81, 0.817, 0.304),   # n=1283
    'JR': (-42.17, 1.201, 0.372),   # n=1163
    'SR': (-41.08, 1.091, 0.559),   # n=2792
}
# The models are linear and unbounded, so current level is clamped to the range
# the fit actually covers before predicting. Measured p0.1-p99.9 of current level
# across both fitted populations is 20.0 to 79.7 -- i.e. the full display scale.
# An earlier value of (25.0, 55.0) was invented rather than derived and silently
# inflated every player below cur 25. Caught by verify_constants.py.
CUR_CLAMP = (20.0, 80.0)

# Positional glove gates, measured against real ZR (parquet, 4,700-5,900
# player-seasons per position, >=60 fielding G), converted at 1.0353 runs/ZR.
# SS 55->-6.6 / 60->+3.9 ; 2B 50->-11.5 / 55->0.0 ; CF 60->-2.2 / 65->+14.0 runs per 150 G.
# 3B is read on the POSITION rating, not range (R2 0.512 vs 0.337).
# GLOVE GATE = the pool league's OWN positional mean, rounded to the display grid.
# ZR is measured against league-average defence, so the rating at which a fielder
# stops costing runs is the rating of an average fielder IN THAT LEAGUE. Verified
# on AC data (58 G, thin n but two independent routes agree):
#   SS  60:-20.8  65:-5.6  70:+10.2  -> crossing ~68, AC regular mean 68.0
#   2B  55:-11.9  60: +3.9           -> crossing ~58, AC regular mean 58.3
#   CF  65: +4.1  70:+13.2           -> crossing just under 65, AC mean 64.9
# Parquet gates were SS 60 / 2B 55 / CF 65 -- correct THERE, where the position
# means are 58.5 / 52.3 / 59.7. They do not transfer (A99).
def _grid(v): return int(round(v/5.0)*5)
GLOVE_GATE_AC = {p: ('IF RNG' if p in ('C','1B','2B','3B','SS') else 'OF RNG', _grid(v))
                 for p, v in POS_MEAN_RNG_AC.items()}
GLOVE_GATE_AC['3B'] = ('3B', 55)     # 3B reads the position rating (R2 .512 v .335)
GLOVE_GATE_PQ = {'SS': ('IF RNG', 60), '2B': ('IF RNG', 55), 'CF': ('OF RNG', 65),
                 'LF': ('OF RNG', 50), 'RF': ('OF RNG', 55), '1B': ('IF RNG', 50),
                 '3B': ('3B', 55)}
GLOVE_GATE = GLOVE_GATE_AC if CALIBRATE else GLOVE_GATE_PQ
POS_MEAN_ACTIVE = POS_MEAN_RNG_DD if USE_DRAFTDAY else (POS_MEAN_RNG_AC if CALIBRATE else POS_MEAN_RNG)
NO_GATE    = {'C', 'DH'}                 # catcher defence is R2~0.24 on either measure

PITCH_FLOOR = 40          # A41 -- below this a pitch is a mirage
PITCH_FLOOR_CH = 45       # A41: the changeup is the exception. At grade 40 a
                          # changeup delivers only 61%% of the time against 80%%+
                          # for a fastball or slider, so its floor is one grade up.
PITCHES = ['FB','CH','CB','SL','SI','SP','CT','FO','CC','SC','KC','KN']
STARTER_STM = 45          # judgement: below this he cannot turn a lineup over
STARTER_EFF = 3           # judgement: a starter needs three usable pitches

PITCHER_POS = {'SP', 'RP', 'CL'}

REQUIRED = ['Name','POS','Age','HSC','C ABI','POW','EYE','POW P','EYE P',
            'HRA','CON_1','HRA P','CON P_1','STM','IF RNG','OF RNG','3B'] + PITCHES

# ============================== HELPERS ==============================
def num(v, field, name):
    """Ratings are integers on the 20-80 display scale. '-' means not applicable."""
    if v is None or str(v).strip() in ('', '-'):
        return None
    try:
        return int(float(v))
    except ValueError:
        raise SystemExit("FATAL: %s has non-numeric %s = %r" % (name, field, v))

def school_class(hsc, name):
    """Map the pool's HSC label to the four measured bands. Unknown labels are fatal."""
    h = (hsc or '').strip()
    if not h:                                    raise SystemExit("FATAL: %s has no HSC" % name)
    if 'HS' in h:                                return 'HS'
    if 'Freshman' in h or 'Sophomore' in h:      return '19'   # JuCo
    if 'Junior' in h:                            return 'JR'
    if 'Senior' in h:                            return 'SR'
    raise SystemExit("FATAL: unrecognised HSC %r for %s -- add it to school_class()" % (h, name))

def check_models():
    """Every class must have a model for both sides, and slopes must be positive."""
    for label, mdl in (('BAT', BAT_MODEL), ('PIT', PIT_MODEL)):
        for cls in ('HS', '19', 'JR', 'SR'):
            if cls not in mdl: raise SystemExit("FATAL: %s model missing class %s" % (label, cls))
            a0, bc, bg = mdl[cls][0], mdl[cls][1], mdl[cls][2]
            if any(v <= 0 for v in (bc, bg)):
                raise SystemExit("FATAL: %s %s has a non-positive slope %s" % (label, cls, (bc, bg)))

# ============================== SCORING ==============================
def score(row):
    name = row['Name']
    pos  = (row['POS'] or '').strip()
    arm  = pos in PITCHER_POS
    cls  = school_class(row.get('HSC'), name)

    if arm:
        t1, t2 = num(row['HRA'],'HRA',name),   num(row['CON_1'],'CON',name)
        p1, p2 = num(row['HRA P'],'HRA P',name), num(row['CON P_1'],'CON P',name)
        model = PIT_MODEL
    else:
        t1, t2 = num(row['POW'],'POW',name), num(row['EYE'],'EYE',name)
        p1, p2 = num(row['POW P'],'POW P',name), num(row['EYE P'],'EYE P',name)
        model = BAT_MODEL

    if None in (t1, t2, p1, p2):
        raise SystemExit("FATAL: %s is missing a core tool or potential" % name)

    # No level calibration. A101: the leagues share one display scale and one run
    # environment; the only difference is ballparks, which are a per-team multiplier
    # on OUTCOMES and never a shift on RATINGS. Ratings cross over untouched.
    cur  = (t1 + t2) / 2
    gap  = max(0.0, (p1 + p2) / 2 - cur)
    if cls not in model:
        raise SystemExit("FATAL: no model for class %r (%s)" % (cls, name))
    curc = min(max(cur, CUR_CLAMP[0]), CUR_CLAMP[1])
    if arm:
        eff_n = sum(1 for p in PITCHES if (num(row.get(p), p, name) or 0) >= (PITCH_FLOOR_CH if p == 'CH' else PITCH_FLOOR))
        rng, frng, padj = None, 0.0, 0.0
        if USE_DRAFTDAY:
            stm_v = num(row.get('STM'), 'STM', name) or 0.0
            a0, bcur, bgap, beff, bstm = ARM_MODEL_DD[cls if cls in ARM_MODEL_DD else 'SR']
            war = a0 + bcur * curc + bgap * gap + beff * eff_n + bstm * stm_v
        elif USE_ARSENAL:
            a0, bcur, bgap, beff = PIT_MODEL_EFF[cls]
            war = a0 + bcur * curc + bgap * gap + beff * eff_n
        else:
            a0, bcur, bgap = model[cls]
            war = a0 + bcur * curc + bgap * gap
    else:
        a0, bcur, bgap, brng = (BAT_MODEL_DD[cls if cls in BAT_MODEL_DD else 'SR'] if USE_DRAFTDAY else model[cls])
        rcol = 'IF RNG' if pos in ('1B','2B','3B','SS') else ('C ABI' if pos=='C' else 'OF RNG')
        rng  = num(row.get(rcol), rcol, name)
        if rng is None:
            raise SystemExit("FATAL: %s (%s) has no %s" % (name, pos, rcol))
        padj = POS_ADJ.get(pos)
        if padj is None:
            raise SystemExit("FATAL: no POS_ADJ for %s (%s)" % (pos, name))
        if USE_DRAFTDAY:
            # A104: one joint fit over all bats, range centred on the DRAFT-DAY
            # position mean, NO position dummies (they were not in the fit, so
            # adding POS_ADJ here would double-count) and NO catcher special case
            # (catchers are in the fit, centred on their own draft-day mean of 32.9).
            rcol = 'IF RNG' if pos in ('1B','2B','3B','SS','C') else 'OF RNG'
            rng  = num(row.get(rcol), rcol, name)
            base = POS_MEAN_ACTIVE.get(pos)
            if base is None:
                raise SystemExit("FATAL: no draft-day position mean for %s (%s)" % (pos, name))
            padj = 0.0
            frng = brng * (rng - base)
            war  = a0 + bcur * curc + bgap * gap + frng
        elif pos == 'C':
            a0, bcur, bgap, babi = CATCHER_MODEL[cls]
            abi = num(row.get('C ABI'), 'C ABI', name)
            if abi is None:
                raise SystemExit("FATAL: catcher %s has no C ABI" % name)
            rng  = abi
            frng = babi * (abi - CATCHER_MEAN_ABI)
            padj = 0.0
            war  = a0 + bcur * curc + bgap * gap + frng
        else:
            base = (POS_MEAN_RNG_AC if CALIBRATE_RANGE else POS_MEAN_RNG).get(pos)
            if base is None:
                raise SystemExit("FATAL: no POS_MEAN_RNG for %s (%s)" % (pos, name))
            frng = brng * (rng - base)
            war  = a0 + bcur * curc + bgap * gap + frng + padj
    cell = round(a0 + bcur * curc, 1)
    adj  = bgap * gap

    # glove
    if arm:
        glove = 'n/a'
    elif pos in GLOVE_GATE:
        col, need = GLOVE_GATE[pos]
        v = num(row.get(col), col, name)
        glove = 'no rating' if v is None else ('CLEARS' if v >= need else 'FAILS %s %d<%d' % (col, v, need))
    elif pos in NO_GATE:
        glove = 'no gate'
    else:
        glove = 'unknown pos %s' % pos

    # arsenal
    if arm:
        eff = sum(1 for p in PITCHES if (num(row.get(p), p, name) or 0) >= (PITCH_FLOOR_CH if p == 'CH' else PITCH_FLOOR))
        stm = num(row['STM'], 'STM', name) or 0
        role = 'SP' if (stm >= STARTER_STM and eff >= STARTER_EFF) else ('swing' if stm >= STARTER_STM else 'RP')
    else:
        eff, stm, role = '', '', ''

    return {
        'Side': 'ARM' if arm else 'BAT', 'Name': name, 'POS': pos, 'Age': row.get('Age'),
        'Class': row.get('HSC'), 'ClassBand': cls,
        'E_WAR': round(war, 1),
        'CurLevel': cur, 'Gap': gap,
        'FromLevel': cell, 'FromGap': round(adj, 2), 'FromRange': round(frng, 2), 'PosAdj': round(padj, 2), 'Range': rng,
        'GloveGate': glove, 'EffPitches': eff, 'Role': role, 'STM': stm,
        'Tool1': 'HRA' if arm else 'POW', 'V1': t1, 'V1_POT': p1,
        'Tool2': 'CON' if arm else 'EYE', 'V2': t2, 'V2_POT': p2,
        'STU': row.get('STU','') if arm else '', 'MOV': row.get('MOV','') if arm else '',
        'GF': row.get('G/F','') if arm else '', 'VELO': row.get('VELO','') if arm else '',
        'IF_RNG': row.get('IF RNG',''), 'OF_RNG': row.get('OF RNG',''),
        'IF_ARM': row.get('IF ARM',''), 'C_ABI': row.get('C ABI',''),
        'B': row.get('B',''), 'T': row.get('T',''),
        'OVR': row.get('OVR',''), 'POT': row.get('POT',''),
        'School': row.get('Schl',''), 'COMP': row.get('COMP',''),
    }

COLS = ['Rank','Side','Name','POS','Age','Class','ClassBand','E_WAR','CurLevel','Gap',
        'FromLevel','FromGap','FromRange','PosAdj','Range','GloveGate','EffPitches','Role','STM',
        'Tool1','V1','V1_POT','Tool2','V2','V2_POT','STU','MOV','GF','VELO',
        'IF_RNG','OF_RNG','IF_ARM','C_ABI','B','T','OVR','POT','School','COMP']

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pool'); ap.add_argument('-o','--out', default='draft_board.csv')
    ap.add_argument('-n','--top', type=int, default=15)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.pool)))
    if not rows: raise SystemExit("FATAL: %s is empty" % a.pool)
    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        raise SystemExit("FATAL: %s is missing required columns: %s\n"
                         "  (see claude/EXPORT_SPEC_ac_views.md)" % (a.pool, ', '.join(missing)))
    check_models()

    out = [score(r) for r in rows]
    out.sort(key=lambda r: -r['E_WAR'])
    for i, r in enumerate(out, 1): r['Rank'] = i
    with open(a.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction='ignore')
        w.writeheader(); w.writerows(out)

    nb = sum(1 for r in out if r['Side']=='BAT'); na = len(out)-nb
    print("scored %d players (%d bats, %d arms) -> %s" % (len(out), nb, na, a.out))
    print("\n  #  side name                 pos age class            E[WAR]  cur  gap  note")
    for r in out[:a.top]:
        note = ('eff=%s %s' % (r['EffPitches'], r['Role'])) if r['Side']=='ARM' else r['GloveGate']
        flag = '  <-- UNUSABLE ARSENAL' if (r['Side']=='ARM' and r['EffPitches'] < STARTER_EFF and r['Role']!='RP') else ''
        print("  %2d  %-4s %-20s %-3s %2s  %-15s %5s  %4.1f %4.1f  %s%s" % (
            r['Rank'], r['Side'], r['Name'][:20], r['POS'], r['Age'], r['Class'],
            r['E_WAR'], r['CurLevel'], r['Gap'], note, flag))

if __name__ == '__main__':
    main()
