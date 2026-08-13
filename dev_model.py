"""
dev_model.py -- projection + valuation engine.

Pipeline:
  display rating --(midpoints)--> internal --(+ age budget)--> projected
  internal --(lower bounds)--> projected display --(cap at potential)--> final
  final ratings --(tool weights)--> score --(minus positional bar)--> value

Every constant lives in dev_constants.py. Nothing is hard-coded here.
"""
import numpy as np
import pandas as pd

from dev_constants import (
    DISPLAY_TO_INTERNAL_MID, INTERNAL_LOWER_BOUNDS,
    BATTER_AGE_BUDGET, PITCHER_AGE_BUDGET,
    BATTER_WEIGHTS, PITCHER_WEIGHTS_ACTIVE, PITCHER_DEVELOPING_TOOLS,
    COMMAND_GATE, COMMAND_GATE_SAFE, PITCH_FLOOR, PITCH_FLOOR_CHANGEUP,
    PITCH_COLUMNS, PITCH_EROSION, DEFENSIVE_FLOORS,
    PARK_OVERLAY, APPLY_PARK_OVERLAY,
    WORK_ETHIC_MULT, APPLY_WORK_ETHIC, REGISTRY_VERSION,
)

# Column aliases: the exports don't agree on names.
BAT_TOOLS = {
    "POW":   ("POW", "POW P"),
    "EYE":   ("EYE", "EYE P"),
    "BABIP": ("BABIP", "HT P"),
    "GAP":   ("GAP", "GAP P"),
    "AVK":   ("K's", "K P"),
}
PIT_TOOLS = {
    "MOV": ("MOV", "MOV P"),
    "CON": ("CON_1", "CON P_1"),
    "STU": ("STU", "STU P"),   # read/displayed only -- NOT scored (see score_pitcher)
}


# ---------------------------------------------------------------- conversions
def to_internal(display):
    """Display grade -> internal midpoint. Rounds to nearest 5-bucket."""
    try:
        d = int(round(float(display) / 5) * 5)
    except (TypeError, ValueError):
        return np.nan
    return DISPLAY_TO_INTERNAL_MID.get(max(20, min(80, d)), np.nan)


def to_display(internal):
    """Internal value -> display grade, using TRUE bucket LOWER BOUNDS."""
    if internal is None or (isinstance(internal, float) and np.isnan(internal)):
        return np.nan
    out = 20
    for grade, lo in INTERNAL_LOWER_BOUNDS:
        if internal >= lo:
            out = grade
    return out


def budget(age, pitcher=False):
    table = PITCHER_AGE_BUDGET if pitcher else BATTER_AGE_BUDGET
    try:
        a = int(age)
    except (TypeError, ValueError):
        return 0
    if a < min(table):
        return table[min(table)]
    return table.get(a, 0)


def project_tool(current, potential, age, pitcher=False, we=None):
    """
    Returns (projected_display, capped_by_potential, unreachable_grades).
    'unreachable' = grades of shown potential the age budget cannot reach.
    """
    ci = to_internal(current)
    if np.isnan(ci):
        return np.nan, False, 0
    b = budget(age, pitcher)
    if APPLY_WORK_ETHIC and we in WORK_ETHIC_MULT:
        b *= WORK_ETHIC_MULT[we]
    raw = ci + b
    uncapped = to_display(raw)
    if potential is None or (isinstance(potential, float) and np.isnan(potential)):
        return uncapped, False, 0
    p = int(round(float(potential) / 5) * 5)
    if uncapped >= p:
        return p, True, 0                       # ceiling binds -- good sign
    return uncapped, False, int((p - uncapped) / 5)   # budget binds


# ------------------------------------------------------------------- batters
def project_batter(row):
    age = pd.to_numeric(row.get("Age"), errors="coerce")
    we = row.get("WE")
    out, unreachable, capped_any = {}, 0, False
    unreachable_tools, binding_tools = [], []
    for tool, (cc, pc) in BAT_TOOLS.items():
        cur = pd.to_numeric(row.get(cc), errors="coerce")
        pot = pd.to_numeric(row.get(pc), errors="coerce")
        proj, capped, unr = project_tool(cur, pot, age, False, we)
        out[tool] = proj
        unreachable += unr
        capped_any = capped_any or capped
        if unr >= 2:
            unreachable_tools.append(f"{tool}+{unr}")
        if capped:
            binding_tools.append(tool)
    out["_unreachable_grades"] = unreachable
    out["_ceiling_binds"] = capped_any
    out["_unreachable_tools"] = unreachable_tools
    out["_binding_tools"] = binding_tools
    return out


def score_batter(proj):
    s = 0.0
    for tool, w in BATTER_WEIGHTS.items():
        v = proj.get(tool)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        if APPLY_PARK_OVERLAY and tool in PARK_OVERLAY:
            w = w * PARK_OVERLAY[tool]
        s += w * v
    return round(s, 1)


def decompose(proj):
    """Share of score from each tool -- exposes cheap-tool inflation."""
    parts, tot = {}, 0.0
    for tool, w in BATTER_WEIGHTS.items():
        v = proj.get(tool)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        parts[tool] = w * v
        tot += parts[tool]
    if tot == 0:
        return {}
    return {k: round(100 * v / tot) for k, v in parts.items()}


# ------------------------------------------------------------------ pitchers
def project_pitcher(row):
    age = pd.to_numeric(row.get("Age"), errors="coerce")
    out = {}
    for tool, (cc, pc) in PIT_TOOLS.items():
        cur = pd.to_numeric(row.get(cc), errors="coerce")
        if tool in PITCHER_DEVELOPING_TOOLS:
            pot = pd.to_numeric(row.get(pc), errors="coerce")
            proj, _, _ = project_tool(cur, pot, age, True)
            out[tool] = proj
        else:
            out[tool] = cur      # STU is DERIVED -- read only, never project
    return out


def score_pitcher(proj):
    """
    RESOLVED 2026-08-13 (Open Items #28): scores MOV/CON only
    (PITCHER_WEIGHTS_ACTIVE), matching the acquisitions.py sp_f1/rp_f1 fix.
    STU stays in project_pitcher()'s output for display (dev_board.py's
    report() still shows the STU column) but is NOT scored -- A27 excludes
    it as a derived roll-up, and A48/A32/A34 confirm it's engine-derived
    from velocity + pitch grades + arsenal depth, not an independent
    primitive; scoring it alongside MOV/CON risked double-counting the same
    arsenal signal. See dev_constants.py's PITCHER_WEIGHTS_ACTIVE comment.
    """
    s = 0.0
    for tool, w in PITCHER_WEIGHTS_ACTIVE.items():
        v = proj.get(tool)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        s += w * v
    return round(s, 1)


def real_pitches(row):
    """Count pitches clearing the A41 crossover floor. Current grades only."""
    n, names = 0, []
    for c in PITCH_COLUMNS:
        v = pd.to_numeric(row.get(c), errors="coerce")
        if pd.isna(v):
            continue
        floor = PITCH_FLOOR_CHANGEUP if c == "CH" else PITCH_FLOOR
        if v >= floor:
            n += 1
            names.append(c)
    return n, names


def out_pitch(row):
    """Highest-graded non-fastball -- the pitch the command gate acts on."""
    best, grade = None, -1
    for c in PITCH_COLUMNS:
        if c == "FB":
            continue
        v = pd.to_numeric(row.get(c), errors="coerce")
        if pd.isna(v):
            continue
        if v > grade:
            best, grade = c, v
    return best, grade


# --------------------------------------------------------------------- flags
def positional_floor_flag(row, pos):
    spec = DEFENSIVE_FLOORS.get(str(pos).upper().split("/")[0])
    if not spec:
        return None
    col, floor = spec
    v = pd.to_numeric(row.get(col), errors="coerce")
    if pd.isna(v):
        return None
    if v < floor:
        return f"MISSES {pos} FLOOR ({col} {int(v)} < {floor}) -- gloves are FIXED"
    return None


def flag_batter(row, proj, score, bar, pct):
    f = []
    age = pd.to_numeric(row.get("Age"), errors="coerce")
    ff = positional_floor_flag(row, row.get("POS"))
    if ff:
        f.append(ff)
    ut = proj.get("_unreachable_tools") or []
    if ut:
        f.append(f"UNREACHABLE potential in {', '.join(ut)} "
                 f"(grades the age budget cannot reach -- do not pay for them)")
    bt = proj.get("_binding_tools") or []
    if bt:
        f.append(f"REACHES ceiling in {', '.join(bt)} (budget >= gap -- good)")
    d = decompose(proj)
    cheap = d.get("GAP", 0) + d.get("AVK", 0)
    if cheap >= 25:
        f.append(f"CHEAP-TOOL INFLATION: {cheap}% of score from GAP+AvoidK "
                 f"(the two lowest-value tools)")
    if bar is not None and score < bar:
        f.append(f"BELOW THE POSITIONAL BAR ({score:.0f} vs {bar:.0f})")
    if not pd.isna(age):
        if age >= 24:
            f.append("DEVELOPMENT DONE (24+) -- current value only")
        elif age <= 19:
            f.append(f"FULL BUDGET AHEAD ({budget(age)} internal pts)")
    pw = pd.to_numeric(row.get("POW"), errors="coerce")
    if not pd.isna(pw) and pw >= 60:
        f.append("SCARCE: POW 60+ -- only ~34 such bats league-wide")
    return f


def flag_pitcher(row, proj):
    f = []
    con = pd.to_numeric(row.get("CON_1"), errors="coerce")
    op, og = out_pitch(row)
    if not pd.isna(con):
        if con <= COMMAND_GATE - 5:
            note = ""
            if op and PITCH_EROSION.get(op) == "erodes":
                note = f" -- his {op} ({int(og)}) BLEEDS 6-13 pts/yr under a starter load"
            elif op and PITCH_EROSION.get(op) == "grows":
                note = f" -- but his {op} grows with reps anyway (changeup exception)"
            f.append(f"BELOW COMMAND GATE (CON {int(con)} < {COMMAND_GATE}){note}")
        elif con >= COMMAND_GATE_SAFE:
            f.append(f"CLEARS COMMAND GATE (CON {int(con)}) -- work him freely")
        else:
            f.append(f"AT THE COMMAND GATE (CON {int(con)}) -- neutral")
    n, names = real_pitches(row)
    if n <= 1:
        f.append(f"MIRAGE ARSENAL: only {n} pitch clears the A41 floor "
                 f"-- ignore projected grades")
    else:
        f.append(f"{n} real pitches ({'/'.join(names)})")
    age = pd.to_numeric(row.get("Age"), errors="coerce")
    if not pd.isna(age) and age >= 25:
        f.append("ARM DEVELOPMENT DONE (25+)")
    return f


# ------------------------------------------------------------ positional bars
def positional_bars(league_df):
    """League mean score by position, computed on the SAME weights."""
    b = league_df[league_df["RL"] == "-"].copy()
    if "ORG" in b.columns:
        b = b[b["ORG"].astype(str) != "-"]
    rows = []
    for _, r in b.iterrows():
        s = 0.0
        for tool, w in BATTER_WEIGHTS.items():
            cc = BAT_TOOLS[tool][0]
            v = pd.to_numeric(r.get(cc), errors="coerce")
            if not pd.isna(v):
                s += w * v
        rows.append({"P0": str(r.get("POS")).split("/")[0].upper(), "score": s})
    d = pd.DataFrame(rows)
    d = d[d.P0.isin(["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"])]
    return d.groupby("P0").score.mean().round(0).to_dict(), d.score.values
