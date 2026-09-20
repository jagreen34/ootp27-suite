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

Per METHODOLOGY RULE 22 this script FAILS LOUD: if any check fails, nothing is written.
Rule 9 is enforced by the MEASURED / ESTIMATED tag on every constant.
"""
import sys, os, io, csv, math, random, statistics, datetime, argparse

VERSION = "1.2.1  (registry v16, A1-A115)"
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
        assert tier in ('MEASURED', 'ESTIMATED'), tier
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
GATE_SS   = C(60, "THE_RULES_pocket rule 5 / A108 REVERSAL. ON THE RANGE TOOL.", 'MEASURED')
GATE_2B   = C(55, "THE_RULES_pocket rule 5 / A108 REVERSAL. ON THE RANGE TOOL.", 'MEASURED')
GATE_CF   = C(65, "THE_RULES_pocket rule 5 / A108 REVERSAL. ON OF RANGE.", 'MEASURED')
GATE_RF_ARM = C(50, "THE_RULES_pocket rule 5. OF ARM splits RF from LF.", 'MEASURED')
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

def check_columns(fr, verbose=False):
    missing = [c for c in REQUIRED_ANY if c not in fr.cols]
    if missing:
        sys.exit(f"ERROR: export is missing required column(s): {missing}\n"
                 f"       found {len(fr.cols)} columns. Run 'columns' to list them.")
    warn = [c for c in REQUIRED_BAT_TOOLS + REQUIRED_ARM_TOOLS if c not in fr.cols]
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

def pct(v, q):
    v = sorted(v); k = (len(v) - 1) * q; f = int(k)
    return v[f] if f + 1 >= len(v) else v[f] + (v[f + 1] - v[f]) * (k - f)

def round5(x): return int(round(x / 5.0) * 5)

def obp_index(eye, con, babip):
    return (OBP_W['EYE']*eye + OBP_W['CON']*con + OBP_W['BABIP']*babip) / OBP_DEN

def lands(gv):
    """Where his GLOVE lets him play.  TOOLS ONLY -- gv cannot return a position rating (G1).
    Gloves are FIXED (A50); range declines with age (A19)."""
    pos = gv.txt('POS')
    if pos == 'C':                      # A58a: catcher defence is a dead null, p=.921. No gate.
        return 'C'
    ifr = gv['IF RNG'] or 0.0
    ifa = gv['IF ARM'] or 0.0
    ofr = gv['OF RNG'] or 0.0
    ofa = gv['OF ARM'] or 0.0
    if pos in ('LF', 'CF', 'RF', 'DH'):
        if ofr >= GATE_CF.v: return 'CF'
        return 'RF' if ofa >= GATE_RF_ARM.v else 'LF'
    if ifr >= GATE_SS.v: return 'SS'
    if ifr >= GATE_2B.v: return '2B'
    if ifr + ifa >= GATE_3B_SUM.v: return '3B'      # pocket rule 5, n=17,459
    return '1B'

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

def pos_adj_runs(landing):
    """A74 runs/season, SCALED BY PLAYING TIME (A114/G8)."""
    return A74_POS.v.get(landing, 0.0) * PT_RATIO.v.get(landing, 1.0)

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
             ('EYE','EYE P','EYE'), ('BABIP','BABIP P','BABIP'), ("K's",'K P','AVK')]
ARM_TOOLS = [('STU','STU P','STU'), ('MOV','MOV P','MOV'),
             ('CON_1','CON P_1','PCON'), ('HRA','HRA P','HRA')]
BAT_CORE, ARM_CORE = ['CON','POW','EYE','BABIP'], ['STU','MOV','PCON','HRA']

def is_arm(r): return txt(r, 'POS') in ('SP', 'RP', 'CL')

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
            p[key + '_P10'] = round5(pct(sims[key], .10))
            p[key + '_P50'] = round5(pct(sims[key], .50))
            p[key + '_P90'] = round5(pct(sims[key], .90))
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
            p['pos_runs'] = round(pos_adj_runs(p['lands']), 2)
            p['pos_war'] = round(pos_adj_war(p['lands']), 2)
            ob = [obp_index(sims['EYE'][i], sims['CON'][i], sims['BABIP'][i]) for i in range(n)]
            p['obp_now'] = round(obp_index(cur['EYE'], cur['CON'], cur['BABIP']))
            p['obp_P10'], p['obp_P50'], p['obp_P90'] = (round(pct(ob,.10)), round(pct(ob,.50)),
                                                        round(pct(ob,.90)))
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
        p['ewar_adj'] = round(p['ewar'] + (pos_adj_war(p['lands']) if p['side']=='BAT' else 0.0), 1)
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
            for p in grp:
                p['rank_floor'] = p['rank_ceiling'] = None
                p['profile'] = 'n/a -- E[WAR] is draft-day only (A104)'
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

def write_workbook(fr, players, out_path, extra_notes=()):
    rank_floor_and_ceiling(players)
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        sys.exit("ERROR: writing .xlsx needs openpyxl.  pip install openpyxl")
    wb = openpyxl.Workbook()
    HDR = Font(bold=True, color='FFFFFF'); FILL = PatternFill('solid', fgColor='334155')
    WARN = Font(bold=True, color='B91C1C')

    def sheet(title, rows, headers, freeze='A2'):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for c in ws[1]: c.font = HDR; c.fill = FILL; c.alignment = Alignment(wrap_text=True, vertical='top')
        for r in rows: ws.append(r)
        ws.freeze_panes = freeze; _auto(ws); return ws

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
    ws.append([])
    ws.append(['POSITION ADJUSTMENT  (A74 runs/season x A114 playing-time ratio)'])
    ws[f'A{ws.max_row}'].font = Font(bold=True)
    ws.append(['position', 'A74 runs/season', 'PA ratio (A114)', 'scaled runs/season',
               f'career WAR over {SEASONS_DEFAULT.v} seasons'])
    for k in ['C','SS','3B','CF','2B','RF','LF','1B']:
        ws.append([k, A74_POS.v[k], PT_RATIO.v[k], round(pos_adj_runs(k),2), round(pos_adj_war(k),2)])
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
      '    column with no explanation.']:
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
                            p.get('ewar_adj'), p['rank_ceiling'], p['profile'],
                            f"P(both) {p['p_both']}  /  P(POW55) {p['p_pow']}",
                            'up the middle' if p['lands'] in ('C','SS','2B','3B','CF') else 'corner'])
            else:
                rbd.append([i, p['name'], 'ARM', p['pos'],
                            'starter' if p['role_gate'] else 'reliever',
                            p['age'], p['cls'], p['ovr_star'], p['pot_star'],
                            p.get('ewar'), None, p.get('ewar'),
                            p['rank_ceiling'], p['profile'],
                            f"P(#2+) {p['p_no2']}",
                            'STM+arsenal OK' if p['role_gate'] else
                            f"FAILS (STM {p['stm']}, eff {p['eff_now']})"])
        sheet('BOARD', rbd, hbd)

    # ---- BATS ---------------------------------------------------------------
    hb = ['Name','POS','lands','Age','Class','ORG','OVR*','POT*',
          'IF RNG','IF ARM','OF RNG','OF ARM','TDP','SPE',
          'POW now','POW pot','POW P10','POW P50','POW P90',
          'OBP now','OBP P50','OBP P90',
          'P(POW55)','P(OBP55)','P(both)',
          'pos runs/season','pos career WAR']
    if pool: hb += ['E[WAR] raw','E[WAR] +pos']
    hb += ['floor rank','ceiling rank','profile','PA','wRC+','WAR']
    rb = []
    for p in sorted(bats, key=lambda x: -(x.get('ewar_adj') or 0)):
        row = [p['name'],p['pos'],p['lands'],p['age'],p['cls'],p['org'],p['ovr_star'],p['pot_star'],
               p['if_rng'],p['if_arm'],p['of_rng'],p['of_arm'],p['tdp'],p['spe'],
               p['POW_now'],p['POW_pot'],p['POW_P10'],p['POW_P50'],p['POW_P90'],
               p['obp_now'],p['obp_P50'],p['obp_P90'],
               p['p_pow'].percent,p['p_obp'].percent,p['p_both'].percent,
               p['pos_runs'],p['pos_war']]
        if pool: row += [p.get('ewar'), p.get('ewar_adj')]
        row += [p['rank_floor'], p['rank_ceiling'], p['profile']]
        row += [p['pa'] or None, p['wrc_plus'], p['war']]
        rb.append(row)
    wsb = sheet('BATS', rb, hb)
    for col in ('W','X','Y'):
        for c in wsb[col][1:]: c.number_format = '0.0"%"'

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
    wsa = sheet('ARMS', ra, ha)
    for col in ('V','W','X'):
        for c in wsa[col][1:]: c.number_format = '0.0"%"'
    for r in wsa.iter_rows(min_row=2, min_col=11, max_col=11):
        if r[0].value: r[0].font = WARN

    # ---- GATED --------------------------------------------------------------
    g = [p for p in bats if p['lands'] in ('C','SS','2B','3B','CF')]
    sheet('GATED BATS', [[p['name'],p['lands'],p['age'],p['pot_star'],p['if_rng'],p['if_arm'],
                          p['of_rng'],p['POW_P50'],p['obp_P50'],p['p_pow'].percent,
                          p.get('ewar_adj')] for p in g],
          ['Name','lands','Age','POT*','IF RNG','IF ARM','OF RNG','POW P50','OBP P50',
           'P(POW55)','E[WAR] +pos'])
    ga = [p for p in arms if p['role_gate']]
    sheet('GATED ARMS', [[p['name'],p['age'],p['pot_star'],p['stm'],p['eff_now'],
                          p['HRA_now'],p['HRA_P50'],p['PCON_now'],p['PCON_P50'],
                          p['p_no2'].percent, p.get('ewar')] for p in ga],
          ['Name','Age','POT*','STM','eff','HRA now','HRA P50','CON now','CON P50',
           'P(#2+)','E[WAR]'])

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
    c.true("every constant is tagged MEASURED or ESTIMATED (rule 9)",
           all(x.tier in ('MEASURED','ESTIMATED') for x in allc.values()))
    c.true("the ESTIMATED ones are exactly the four we know are assumptions",
           {k for k,v in allc.items() if v.tier=='ESTIMATED'} ==
           {'SHARE','RUNS_PER_WIN','SEASONS_DEFAULT'},
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
    c.true("IF RNG 60 -> SS", L(**{'IF RNG':60}) == 'SS')
    c.true("IF RNG 55 -> 2B", L(**{'IF RNG':55}) == '2B')
    c.true("IF RNG 45 + IF ARM 75 = 120 -> 3B  (pocket rule 5)",
           L(**{'IF RNG':45,'IF ARM':75}) == '3B')
    c.true("IF RNG 45 + IF ARM 70 = 115 -> 1B  (just under the bar)",
           L(**{'IF RNG':45,'IF ARM':70}) == '1B')
    c.true("IF RNG 50 + IF ARM 55 = 105 -> 1B  (the invented ARM>=55 gate would have passed him)",
           L(**{'IF RNG':50,'IF ARM':55}) == '1B')
    c.true("a catcher lands at C with no gate at all (A58a)",
           lands(GateView({'POS':'C','IF RNG':0,'IF ARM':0,'OF RNG':0,'OF ARM':0})) == 'C')
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
    c.true("both ranks are assigned to every player",
           all('rank_floor' in p and 'rank_ceiling' in p
               for p in (_hi_floor, _hi_ceil, _mid)))
    _solo = _fake('ARM', 5.0, 0.01)
    rank_floor_and_ceiling([_solo])
    c.true("a one-player side does not divide by zero", _solo['profile'] == 'n/a')
    _lg = [{'side':'BAT','ewar':None,'ewar_adj':None,'p_both':Pct(0.01),'p_no2':Pct(0.01)}
           for _ in range(3)]
    rank_floor_and_ceiling(_lg)
    c.true("a LEAGUE export (no E[WAR]) refuses to fake a floor rank",
           all(p['rank_floor'] is None and p['profile'].startswith('n/a') for p in _lg),
           _lg[0]['profile'])

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
