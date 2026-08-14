def playable_positions(row):
    """
    Positions his TOOLS allow, not the ones he has experience at.
    Eligibility in OOTP is experience; the tools are the real gate
    (a clone went 0->55 at 1B in one period).
    """
    out = []
    for pos, spec in TOOL_POSITION_GATES.items():
        if spec is None:
            out.append(pos)
            continue
        col, floor = spec
        v = pd.to_numeric(row.get(col), errors="coerce")
        if not pd.isna(v) and v >= floor:
            out.append(pos)
    return out


def listed_positions(row):
    """Every position on the POS string, e.g. 'SS/3b' -> ['SS','3B']."""
    return [p.strip().upper() for p in str(row.get("POS", "")).split("/")
            if p.strip()]


def park_delta(proj):
    """
    Score under the FITTED park overlay minus neutral [A57d]. Positive = the
    park helps him. Power +18.3%, Gap -6.5%, Eye exactly 0 (walks are
    park-proof), BABIP/AvK ~ -0.7%.
    """
    neutral = adj = 0.0
    for tool, w in BATTER_WEIGHTS.items():
        v = proj.get(tool)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        neutral += w * (float(v) - 25.0)
        adj += w * PARK_OVERLAY.get(tool, 1.0) * (float(v) - 25.0)
    pr = power_runs(proj.get("POW"))
    neutral += pr
    adj += pr * PARK_OVERLAY.get("POW", 1.0)
    return round(adj - neutral, 1)


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
    BATTER_WEIGHTS, PITCHER_WEIGHTS, PITCHER_DEVELOPING_TOOLS,
    COMMAND_GATE, COMMAND_GATE_SAFE, PITCH_FLOOR, PITCH_FLOOR_CHANGEUP,
    PITCH_COLUMNS, PITCH_EROSION, DEFENSIVE_FLOORS,
    PARK_OVERLAY, APPLY_PARK_OVERLAY,
    WORK_ETHIC_MULT, APPLY_WORK_ETHIC, REGISTRY_VERSION,
    RP_STUFF_DEFLATOR, ROLE_POSITIONS, ROLE_INNINGS, APPLY_ROLE_VOLUME,
    POSITION_FALLBACK, MIN_REAL_PITCHES, MIRAGE_PENALTY,
    EROSION_PENALTY_GRADES, TOOL_POSITION_GATES,
    DEFENSIVE_SECONDARY, STARTER_FLOORS, POWER_CURVE,
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
    "STU": ("STU", "STU P"),
}



# ---------------------------------------------------------------- channel split
PITCHER_POS = {"SP", "RP", "CL", "P", "SP/RP", "RP/SP"}


def is_pitcher(row):
    """
    Channel split keyed on POS (SP/RP/CL), which every export carries.
    RL is used only as a fallback -- some exports (draft pools) omit it
    entirely, and defaulting on a missing column silently returned zero rows.
    """
    pos = str(row.get("POS", "")).upper().split("/")[0].strip()
    if pos in PITCHER_POS:
        return True
    if pos:                      # a real fielding position -> batter
        return False
    rl = row.get("RL")
    return rl is not None and str(rl) != "-"


def is_batter(row):
    return not is_pitcher(row)


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


def power_runs(display):
    """
    POWER via the engine-exact lookup [A57a]. Power is the ONLY genuine engine
    nonlinearity -- convex through display 85 with no roll-over, an 8x spread
    bottom to top. Linear interpolation between measured points.
    """
    if display is None or (isinstance(display, float) and np.isnan(display)):
        return 0.0
    g = sorted(POWER_CURVE)
    d = float(display)
    if d <= g[0]:
        return POWER_CURVE[g[0]]
    if d >= g[-1]:
        return POWER_CURVE[g[-1]]
    for a, b in zip(g, g[1:]):
        if a <= d <= b:
            f = (d - a) / (b - a)
            return POWER_CURVE[a] + f * (POWER_CURVE[b] - POWER_CURVE[a])
    return 0.0


def score_batter(proj):
    """
    Engine-exact runs above a display-25 baseline, 600-PA season [A57].
    POWER uses the lookup curve; the other four are linear in DISPLAY grade.
    """
    s = 0.0
    for tool, w in BATTER_WEIGHTS.items():
        v = proj.get(tool)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        ww = w * PARK_OVERLAY.get(tool, 1.0) if APPLY_PARK_OVERLAY else w
        s += ww * (float(v) - 25.0)
    pr = power_runs(proj.get("POW"))
    if APPLY_PARK_OVERLAY:
        pr *= PARK_OVERLAY.get("POW", 1.0)
    return round(s + pr, 1)


def decompose(proj):
    """Share of score from each tool -- exposes cheap-tool inflation."""
    parts, tot = {}, 0.0
    for tool, w in BATTER_WEIGHTS.items():
        v = proj.get(tool)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        parts[tool] = w * (float(v) - 25.0)
        tot += parts[tool]
    pr = power_runs(proj.get("POW"))
    parts["POW"] = pr
    tot += pr
    if tot <= 0:
        return {}
    return {k: round(100 * v / tot) for k, v in parts.items() if v > 0}


# ------------------------------------------------------------------ pitchers
def project_pitcher(row, apply_gate=True):
    """
    MOV/CON take the age budget; pitch grades barely develop [A48] so STU is
    read, never projected. If he is below the command gate his out-pitch
    ERODES rather than holds [A54] -- that is a development claim, so it is
    applied here (projection) and not to the current-state score.
    """
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
    if apply_gate and below_command_gate(row):
        op, og = out_pitch(row)
        if op and PITCH_EROSION.get(op) in ("erodes", "mild"):
            stu = out.get("STU")
            if stu is not None and not pd.isna(stu):
                out["STU"] = max(20, stu - 5 * EROSION_PENALTY_GRADES)
                out["_eroded"] = op
    return out


def score_pitcher(proj, row=None):
    """
    Role-adjusted. Two gates act on the SCORE because both are current-state
    facts, not projections:
      - RP/CL Stuff is deflated (registry: SP->RP conversion inflates ~+5)
      - a mirage arsenal (<2 pitches clearing the A41 floor) is penalised,
        because the derived Stuff rests on grades that will not play
    """
    s = 0.0
    role = role_of(row) if row is not None else None
    for tool, w in PITCHER_WEIGHTS.items():
        v = proj.get(tool)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        if tool == "STU" and role in ("RP", "CL"):
            v = max(0.0, v - RP_STUFF_DEFLATOR)
        s += w * v
    if row is not None:
        ok, _, _ = arsenal_ok(row)
        if not ok:
            s *= MIRAGE_PENALTY
        if APPLY_ROLE_VOLUME and role:
            s *= ROLE_INNINGS.get(role, 200) / 200.0
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



# ------------------------------------------------------------------- GATES
def role_of(row):
    """SP / RP / CL from POS."""
    pos = str(row.get("POS", "")).upper().split("/")[0].strip()
    return ROLE_POSITIONS.get(pos)


def effective_position(row):
    """
    The position he can ACTUALLY hold, on the HARD floor (league p10).
    Both the primary and secondary tool must clear -- arm alone is not a
    third baseman. Gloves are fixed [A50], so a miss is permanent.
    Returns (position, was_reassigned, reason_or_None).
    """
    listed = str(row.get("POS", "")).upper().split("/")[0].strip()
    checks = []
    if listed in DEFENSIVE_FLOORS:
        checks.append(DEFENSIVE_FLOORS[listed])
    if listed in DEFENSIVE_SECONDARY:
        checks.append(DEFENSIVE_SECONDARY[listed])
    if not checks:
        return listed, False, None
    for col, floor in checks:
        v = pd.to_numeric(row.get(col), errors="coerce")
        if pd.isna(v) or v >= floor:
            continue
        fb = POSITION_FALLBACK.get(listed, listed)
        return fb, True, (f"CANNOT HOLD {listed} ({col} {int(v)} < {floor}, "
                          f"league p10; gloves are FIXED) -- re-barred at {fb}")
    return listed, False, None


def below_starter_floor(row):
    """
    FLAG only: clears the hard floor but sits under the league MEDIAN at his
    position -- a real but below-average defender there. Never re-bars.
    """
    listed = str(row.get("POS", "")).upper().split("/")[0].strip()
    spec = STARTER_FLOORS.get(listed)
    if not spec:
        return None
    col, med = spec
    v = pd.to_numeric(row.get(col), errors="coerce")
    if pd.isna(v) or v >= med:
        return None
    return (f"BELOW-AVERAGE GLOVE at {listed} ({col} {int(v)} < league median "
            f"{med}) -- playable, but a bat-first fit there")


def arsenal_ok(row):
    """A41: does he have a usable arsenal, or is his Stuff built on mirages?"""
    n, names = real_pitches(row)
    return n >= MIN_REAL_PITCHES, n, names


def below_command_gate(row):
    con = pd.to_numeric(row.get("CON_1"), errors="coerce")
    return (not pd.isna(con)) and con < COMMAND_GATE


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
    _, moved, why = effective_position(row)
    if moved:
        f.append(why)
    else:
        sf = below_starter_floor(row)
        if sf:
            f.append(sf)
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
    """
    League mean score by EFFECTIVE position, computed with score_batter so the
    bars are on the SAME scale as the players being ranked.

    ⚠ Never recompute a score inline here -- always call the scorer. This
    previously used an inline weighted sum which, after A57, no longer matched
    score_batter (no -25 offset, no POWER curve): bars came out ~70 while
    scores came out 13-84, making vsBar meaningless.

    ⚠ The ORG != '-' filter drops free agents from a LEAGUE sweep, but a DRAFT
    POOL has ORG '-' for every player (amateurs have no org). Applying it there
    empties the frame. Only apply the filter if it leaves rows behind.
    """
    b = league_df[league_df.apply(is_batter, axis=1)].copy()
    if "ORG" in b.columns:
        keep = b[b["ORG"].astype(str).str.strip() != "-"]
        if len(keep):                      # a draft pool is ALL '-' -- keep it
            b = keep
    rows = []
    for _, r in b.iterrows():
        s = score_batter(project_batter(r))
        p0, _, _ = effective_position(r)
        rows.append({"P0": p0, "score": s})
    if not rows:
        raise ValueError(
            "No batters found in the population file. The channel split reads "
            "the POS column (pitchers are SP/RP/CL). Check that the file has a "
            "POS column with fielding positions in it."
        )
    d = pd.DataFrame(rows)
    d = d[d["P0"].isin(["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"])]
    if not len(d):
        raise ValueError(
            "No recognised fielding positions in the population file. Expected "
            "POS values like C / 1B / 2B / 3B / SS / LF / CF / RF."
        )
    return d.groupby("P0").score.mean().round(1).to_dict(), d.score.values
