# ═══════════════════════════════════════════════════════════════════════════
# ⚠⚠  THIS FILE IS  lineup/app.py  —  IT IS **NOT** THE REPO-ROOT app.py.  ⚠⚠
# The repo now has three files named app.py (root = Suite, rank/ = Player Rank,
# lineup/ = this). Uploading it over the root app.py replaces the Suite.
# ═══════════════════════════════════════════════════════════════════════════
"""
OOTP Lineup Optimizer — Hungarian assignment on ENGINE-EXACT runs.

Deliberately small, and a peer of rank/ rather than a part of the Suite.

WHY THIS IS A REWRITE AND NOT A PORT
────────────────────────────────────
The previous `lineups.py` imported eleven names from `acquisitions.py` (3,799
lines, itself importing db / park_fit / rating_scale). Every one of them is now
either superseded or cancels out:

  off_f1            -> score_batter   [A57 engine-exact runs; off_f1 still runs
                                       the pre-A57 OLS weights]
  def_war           -> def_runs       [A58: range dominant, TDP real at SS/2B,
                                       errors ~1/10th, arm a GATE not a value
                                       term, catchers BAT-ONLY]
  ZR_MODELS         -> superseded     [A29's fit; A58 replaces it and the
                                       deployed one still drops TDP]
  ZR_WAR_FACTOR     -> unnecessary    [def_runs is already denominated in runs]
  pos_adj           -> CANCELS        [see below]
  POS_ADJ_CONSTANTS -> CANCELS
  prep_data         -> unnecessary    [raw exports read fine, as in rank/]
  BATTER/PITCHER_POSITIONS, _s -> dev_model.is_batter / is_pitcher / pandas

⚠ WHY POSITIONAL ADJUSTMENT CANCELS. In an assignment where every slot is
filled exactly once, adding a constant to every cell of a COLUMN shifts the
total by the same amount for EVERY possible assignment. It cannot change the
argmax. Positional scarcity is an ACQUISITION question ("what must a 1B hit to
be worth a roster spot"), not an ARRANGEMENT question. Carrying it here would
add noise and a stale constant while changing nothing.

⚠ WHAT DOES NOT CANCEL, and is the whole point: def_runs is position-specific.
A 70-range glove is worth +24.6 runs at SS (6.15 per +5) and +5.6 at 1B (1.40
per +5). That difference is exactly the signal the optimizer should be reading,
and the old objective could not see it — the deployed ZR models omit TDP and
over-weight arm.

⚠ CATCHER IS NO LONGER LOCKED BY DEFAULT. The old file locked it because "the C
DEF model is weak (R²=0.21)". A58 gives a better answer: C_ABI is a DEAD NULL
(p=.921, unchanged from N=349 to N=1,044), so a catcher's value is his BAT. The
optimizer can simply take the best bat who clears catcher eligibility. Lock him
anyway if you want — the lock still overrides everything.

Registry constants come from the parent dev_constants.py / dev_model.py. There
is exactly one copy, so this tool cannot drift from the registry.
"""
import os
import sys

import streamlit as st

st.set_page_config(page_title="OOTP Lineup Optimizer", page_icon="⚾", layout="wide")


# ── ACCESS GATE (identical to rank/ and the suite) ───────────────────────────
def _expected_password():
    try:
        if "app_password" in st.secrets:
            return st.secrets["app_password"]
    except Exception:
        pass
    return os.environ.get("APP_PASSWORD")


def check_password() -> bool:
    expected = _expected_password()
    if not expected:                       # fail loud, never open
        st.error("Access is not configured: set `app_password` in "
                 "`.streamlit/secrets.toml` or the `APP_PASSWORD` env var.")
        return False

    def entered():
        st.session_state["auth_ok"] = st.session_state.get("pw") == expected
        st.session_state.pop("pw", None)

    if st.session_state.get("auth_ok"):
        return True
    st.title("⚾ OOTP Lineup Optimizer")
    st.text_input("Password", type="password", key="pw", on_change=entered)
    if st.session_state.get("auth_ok") is False:
        st.error("Incorrect password")
    return False


if not check_password():
    st.stop()
# ── authenticated below ──────────────────────────────────────────────────────

sys.path.insert(0, "/app")               # parent modules live at the repo root

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

import dev_constants as K
import data_store as store
import nav
from dev_model import (
    project_batter, score_batter, def_runs,
    is_batter, is_pitcher,
    project_pitcher, real_pitches, arsenal_ok, arsenal_vs_age, role_of,
)
# ⚠ score_total is deliberately NOT imported here. This module's objective is
# bat + glove runs, which is NOT a player total -- no baserunning term exists
# [A62 pending]. Importing a name containing "total" into this file invites the
# exact conflation the captions were corrected to remove (methodology rule 20:
# threads grep for NAMES).

# No-DH: exactly eight field slots, every one filled by a position player.
FIELD_POSITIONS = ["C", "SS", "CF", "2B", "3B", "RF", "LF", "1B"]
CARD_ORDER = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
_NEG = -1.0e6


# ── ELIGIBILITY ──────────────────────────────────────────────────────────────
def can_play(row, pos, floors, secondary):
    """
    Hard defensive gate: BOTH the primary and (where one exists) the secondary
    tool must clear. Arm alone is not a third baseman.

    Gloves do not develop upward [A50], so a miss here is permanent, not a
    projection risk. ⚠ A19 does note range DECLINES with age (magnitude never
    measured) — so for a 30+ glove this is a present-tense read, not a floor.
    """
    checks = []
    if pos in floors:
        checks.append(floors[pos])
    if pos in secondary:
        checks.append(secondary[pos])
    for col, floor in checks:
        v = pd.to_numeric(row.get(col), errors="coerce")
        if pd.isna(v) or v < floor:
            return False
    return True


def eligible_positions(row, floors, secondary):
    return [p for p in FIELD_POSITIONS if can_play(row, p, floors, secondary)]


# ── OBJECTIVE ────────────────────────────────────────────────────────────────
def runs_at(row, proj, pos):
    """Bat runs [A57] + glove runs at THIS position [A58].

    ⚠ NOT total offensive value. A57 is BATTING ONLY -- no baserunning term
    exists anywhere in the model (no SPE/SR/STE/RUN/wSB/UBR). For contact-and-
    legs profiles this understates value by ~4-9 runs a season; R. Paige reads
    2nd-worst here while leading the roster in wSB. Coefficient study: A62,
    claude/HANDOFF_baserunning_coefficients.md. Treat as a LOWER BOUND when
    SR/STE/RUN clear ~60."""
    return score_batter(proj) + def_runs(row, pos)


# ── OPTIMIZER ────────────────────────────────────────────────────────────────
def current_tools(row):
    """Today's ratings, no age budget applied. The right input for TODAY's
    lineup: you field the player you have, not the one he becomes."""
    return {t: pd.to_numeric(row.get(c), errors="coerce") for t, c in
            [("POW", "POW"), ("EYE", "EYE"), ("BABIP", "BABIP"),
             ("GAP", "GAP"), ("AVK", "K's")]}


def tools_for(row, projected):
    return project_batter(row) if projected else current_tools(row)


def optimize(bats, floors, secondary, locks, projected=False):
    """
    Maximise bat + glove runs across the eight no-DH field slots.
    (Not total value -- no baserunning term exists yet [A62 pending].)

    locks: {pos: Name} — forced assignments. A lock OVERRIDES eligibility by
    design: your call beats the model's.

    ⚠ FIXED: `projected` was previously ignored — the optimizer always applied
    the age budget, so it silently returned the 1980 lineup no matter what the
    sidebar said. Default is now FALSE, which is the right answer for setting
    today's lineup.
    """
    recs = bats.to_dict("records")
    projs = {i: tools_for(r, projected) for i, r in enumerate(recs)}
    by_name = {str(r.get("Name", "")): i for i, r in enumerate(recs)}

    assignment = {p: None for p in FIELD_POSITIONS}
    used = set()

    def entry(i, pos, locked):
        r = recs[i]
        bat = score_batter(projs[i])
        dfn = def_runs(r, pos)
        return {"Name": str(r.get("Name", "")), "Bat": round(bat, 1),
                "Def": round(dfn, 1), "Runs": round(bat + dfn, 1),
                "locked": locked, "_i": i}

    for pos, name in (locks or {}).items():
        if pos in FIELD_POSITIONS and name in by_name:
            i = by_name[name]
            assignment[pos] = entry(i, pos, True)
            used.add(i)

    open_slots = [p for p in FIELD_POSITIONS if assignment[p] is None]
    cand = [i for i in range(len(recs)) if i not in used]

    if open_slots and cand:
        M = np.full((len(cand), len(open_slots)), _NEG)
        for a, i in enumerate(cand):
            for b, pos in enumerate(open_slots):
                if can_play(recs[i], pos, floors, secondary):
                    M[a, b] = runs_at(recs[i], projs[i], pos)
        ri, ci = linear_sum_assignment(-M)
        for a, b in zip(ri, ci):
            if M[a, b] <= -1.0e5:
                continue                      # infeasible — leave unfilled
            i, pos = cand[a], open_slots[b]
            assignment[pos] = entry(i, pos, False)
            used.add(i)

    unfilled = [p for p in FIELD_POSITIONS if assignment[p] is None]
    total = round(sum(a["Runs"] for a in assignment.values() if a), 1)

    bench = []
    for i in range(len(recs)):
        if i in used:
            continue
        best, bw = None, _NEG
        for pos in FIELD_POSITIONS:
            if can_play(recs[i], pos, floors, secondary):
                w = runs_at(recs[i], projs[i], pos)
                if w > bw:
                    bw, best = w, pos
        if best:
            bench.append({"Name": str(recs[i].get("Name", "")),
                          "Best pos": best, "Runs@best": round(bw, 1)})
    bench.sort(key=lambda x: x["Runs@best"], reverse=True)
    return {"assignment": assignment, "total": total,
            "unfilled": unfilled, "bench": bench, "recs": recs, "projs": projs}



def find_upgrades(cand_df, assignment, floors, secondary, projected, exclude=()):
    """
    For every outside bat, find the ONE slot where he helps most, and by how
    much against the man currently there.

    ⚠ Gain is in RUNS over the incumbent AT THAT SLOT, so it already nets out
    both the bat and the glove. A +12 here is roughly a win.
    ⚠ It does NOT price acquisition cost, contract, service time or age. It
    answers "would he improve the eight slots", nothing else.
    """
    rows = []
    for _, r in cand_df.iterrows():
        if not is_batter(r):
            continue
        nm = str(r.get("Name", ""))
        if nm in exclude:
            continue
        proj = tools_for(r, projected)
        bat = score_batter(proj)
        best = None
        for pos in FIELD_POSITIONS:
            if not can_play(r, pos, floors, secondary):
                continue
            runs = bat + def_runs(r, pos)
            inc = assignment.get(pos)
            gain = runs - (inc["Runs"] if inc else 0.0)
            if best is None or gain > best["Gain"]:
                best = {"Name": nm, "Org": str(r.get("ORG", r.get("TM", ""))),
                        "Age": pd.to_numeric(r.get("Age"), errors="coerce"),
                        "Slot": pos, "Bat": round(bat, 1),
                        "Def": round(def_runs(r, pos), 1), "Runs": round(runs, 1),
                        "Replaces": inc["Name"] if inc else "(unfilled)",
                        "Their runs": inc["Runs"] if inc else 0.0,
                        "Gain": round(gain, 1)}
        if best and best["Gain"] > 0:
            rows.append(best)
    rows.sort(key=lambda x: x["Gain"], reverse=True)
    return pd.DataFrame(rows)


def diagnose(pos, bats, floors, secondary, locks):
    recs = bats.to_dict("records")
    elig = [str(r.get("Name", "")) for r in recs if can_play(r, pos, floors, secondary)]
    locked_elsewhere = {n: p for p, n in (locks or {}).items() if p != pos}
    free = [n for n in elig if n not in locked_elsewhere]
    if not elig:
        gate = floors.get(pos)
        extra = secondary.get(pos)
        bits = [f"{c} ≥ {v}" for c, v in filter(None, [gate, extra])]
        return (f"**{pos}**: nobody clears the gate ({' and '.join(bits)}). "
                f"Lower it below, or lock a player in — a lock overrides the gate.")
    if not free:
        who = ", ".join(f"{n} → {locked_elsewhere[n]}" for n in elig if n in locked_elsewhere)
        return (f"**{pos}**: the only eligible bats are locked elsewhere ({who}). "
                f"Unlock one, or lock someone into {pos}.")
    return (f"**{pos}**: eligible bats exist ({', '.join(free[:3])}…) but the "
            f"optimizer placed them where they were worth more. Lock your "
            f"preferred {pos} to force it.")


# ── THE BOOK (Tango/Lichtman/Dolphin) ────────────────────────────────────────
def _obp_skill(r):
    g = lambda c: pd.to_numeric(r.get(c), errors="coerce")
    return np.nansum([g("EYE"), g("K's"), g("BABIP")])


def _slg_skill(r):
    g = lambda c: pd.to_numeric(r.get(c), errors="coerce")
    return np.nansum([g("POW"), g("GAP")])


def book_order(starters):
    """
    The Book: three best bats at 1/2/4 (higher-OBP up top, bigger-SLG at 4),
    4th-5th best at 3/5, then descending. Worth ~1 win a season.

    ⚠ Ranks on BAT ONLY — a batting order cannot capture defensive value, so
    using total runs here would put a glove-first shortstop above a masher.
    """
    rem, order = list(starters), {}

    def take(key):
        b = max(rem, key=key)
        rem.remove(b)
        return b

    if rem: order[2] = take(lambda s: s["Bat"])
    if rem: order[4] = take(lambda s: s["Bat"])
    if rem: order[1] = take(lambda s: _obp_skill(s["row"]))
    if rem: order[5] = take(lambda s: _slg_skill(s["row"]))
    if rem: order[3] = take(lambda s: _slg_skill(s["row"]))
    rem.sort(key=lambda s: s["Bat"], reverse=True)
    slot = 6
    for s in rem:
        order[slot] = s
        slot += 1
    return [{"#": k, "Player": order[k]["Name"], "POS": order[k]["pos"]}
            for k in sorted(order)]



# ═══════════════════════════════════════════════════════════════════════════
# PITCHING STAFF  [A6 structure · A27 hierarchy · A59 depth · A14 role-as-output]
# ═══════════════════════════════════════════════════════════════════════════
# A6 is a HARD gameplay rule, not a preference: 6-man rotation (37-GS cap),
# 6 SP + 5 RP on the active roster, NEVER 7+ relievers.
ROTATION_SLOTS = 6
BULLPEN_SLOTS = 5


def staff_score(row, proj, as_role):
    """
    Price an arm AS A GIVEN ROLE. A14: role is an OUTPUT of skills, never a
    label to collapse — so every arm gets priced BOTH ways and the gap is the
    signal. Mirrors dev_model.score_pitcher but with the role forced.

    ⚠ RP/CL Stuff is deflated because SP->RP conversion inflates displayed Stuff
    ~+5 [A32]. A reliever's STU 60 is not the same object as a starter's STU 60.
    """
    s = 0.0
    for tool, w in K.PITCHER_WEIGHTS.items():
        v = proj.get(tool)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if tool == "STU" and as_role in ("RP", "CL"):
            v = max(0.0, float(v) - K.RP_STUFF_DEFLATOR)
        s += w * float(v)
    if K.APPLY_ARSENAL_DEPTH:
        n, _ = real_pitches(row)
        s += (K.PITCHER_WEIGHTS["HRA"] * K.ARSENAL_DEPTH_RATING_EQUIV
              * (n - K.STARTER_ARSENAL_TARGET))
    ok, _, _ = arsenal_ok(row)
    if not ok:
        s *= K.MIRAGE_PENALTY
    return round(s, 1)


def sp_innings(row):
    """A14: STM is a VOLUME lever, not an eligibility gate — ~120 IP at STM 35,
    +1.25 IP per point. There is no stamina floor for starting."""
    stm = pd.to_numeric(row.get("STM"), errors="coerce")
    if pd.isna(stm):
        return None
    return int(round(120 + 1.25 * (float(stm) - 35)))


def build_staff(pits_df, projected):
    rows = []
    for _, r in pits_df.iterrows():
        proj = project_pitcher(r) if projected else {
            "STU": pd.to_numeric(r.get("STU"), errors="coerce"),
            "HRA": pd.to_numeric(r.get("HRA"), errors="coerce"),
            "CON": pd.to_numeric(r.get("CON_1"), errors="coerce")}
        n, norm, vs = arsenal_vs_age(r)
        as_sp, as_rp = staff_score(r, proj, "SP"), staff_score(r, proj, "RP")
        rows.append({
            "Name": str(r.get("Name", "")), "Age": pd.to_numeric(r.get("Age"), errors="coerce"),
            "Listed": r.get("POS"), "asSP": as_sp, "asRP": as_rp,
            # ⚠ ONE HRA column -- see the same note in rank_app. The duplicate
            # here was SILENT (the column list names HRA once), so it shipped
            # the projection where the raw rating was intended.
            "HRA": proj.get("HRA"), "CON": proj.get("CON"), "STU": proj.get("STU"),
            "STM": pd.to_numeric(r.get("STM"), errors="coerce"),
            "IP@STM": sp_innings(r),
            "Real": n, "vsAgeNorm": vs,
            "ERA+": pd.to_numeric(r.get("ERA+"), errors="coerce"),
            "FIP-": pd.to_numeric(r.get("FIP-"), errors="coerce"),
            "_row": r, "_proj": proj,
        })
    return pd.DataFrame(rows)


def find_staff_upgrades(cand_df, staff_df, projected, role, slots, exclude=()):
    """Outside arms who would displace the last man in the top `slots` at `role`.

    ⚠ GAIN HERE IS **NOT RUNS**. asSP / asRP are weighted rating-space scores
    [A27+A59], not run values — unlike the batter upgrade table, which IS in
    runs and where +12 is roughly a win. **A +12 on this table and a +12 on the
    batter table are different units and must never be compared.** Read this
    one as an ordering, not a magnitude.

    ⚠ No volume term (A14): `asSP` prices talent, not innings. Check `IP@STM`
    beside it — a 35-STM reliever can out-rank a 60-STM starter here and still
    throw 30 fewer innings.
    """
    col = "asSP" if role == "SP" else "asRP"
    have = staff_df.sort_values(col, ascending=False).head(slots)
    if have.empty:
        return pd.DataFrame(), None, 0.0
    floor_row = have.iloc[-1]
    floor = float(floor_row[col])

    outside = cand_df[cand_df.apply(is_pitcher, axis=1)]
    if outside.empty:
        return pd.DataFrame(), str(floor_row["Name"]), floor
    cs = build_staff(outside, projected)
    if cs.empty:
        return pd.DataFrame(), str(floor_row["Name"]), floor
    cs = cs[~cs["Name"].astype(str).isin(set(exclude) | set(staff_df["Name"].astype(str)))]
    if cs.empty:
        return pd.DataFrame(), str(floor_row["Name"]), floor
    cs["Gain"] = (cs[col] - floor).round(1)
    out = cs[cs["Gain"] > 0].sort_values("Gain", ascending=False)
    return out.reset_index(drop=True), str(floor_row["Name"]), floor


def _staff_cols(d, extra=()):
    base = ["Name", "Age", "Listed", "HRA", "CON", "STU", "Real",
            "vsAgeNorm", "STM", "IP@STM", "ERA+", "FIP-"]
    return [c for c in list(extra) + base if c in d.columns]


# ── UI ───────────────────────────────────────────────────────────────────────
def load(f):
    if f is None:
        return None
    if f.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(f)
    return pd.read_csv(f)


st.sidebar.header("📁 Roster")
roster_file = store.picker(
    st, "Roster export", key="rst", kind="roster", also=("league",),
    help="Uploaded files are saved to the shared volume and offered back next "
         "time — and they are visible to /rank/ too. Upload once.")
team_filter = st.sidebar.text_input("Filter to ORG (blank = whole file)", "")
st.sidebar.markdown("---")
project_on = st.sidebar.checkbox(
    "Project to end of development", value=False,
    help="OFF = TODAY's ratings. This is the right setting for setting today's "
         "lineup — you field the player you have. ON applies the A56 age budget "
         "and answers a different question: who should be playing where once "
         "development is done. A 20-year-old can look like a starter under ON "
         "and a bench bat under OFF, and BOTH are correct answers to their own "
         "question.")
store.manage(st)
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Upgrades")
cand_file = store.picker(
    st, "Candidate pool — FAs / other teams / league", key="cand", kind="pool",
    also=("league", "roster"),
    help="Anyone outside your roster. The tool finds the single slot where each "
         "would help most and ranks by runs gained over the man there now. "
         "Saved and reused automatically, and shared with /rank/.")
cand_scope = st.sidebar.radio(
    "Who to consider", ["Free agents only", "Everyone in the file"],
    index=0,
    help="FREE AGENTS ONLY keeps rows whose org reads '-' (blank/unsigned) — "
         "the players you can simply sign. EVERYONE also surfaces players on "
         "other rosters, which is a trade-target list, not a shopping list.")
st.sidebar.markdown("---")
st.sidebar.caption(f"registry {K.REGISTRY_VERSION}")
st.sidebar.caption("Return to [home](/)")

nav.render(st, "lineup", note=f"registry {K.REGISTRY_VERSION}")
st.title("⚾ Lineup Optimizer")
st.caption(f"Hungarian assignment maximising **bat runs [A57] + glove runs [A58]** "
           f"across the eight no-DH slots · registry {K.REGISTRY_VERSION}  \n"
           f"⚠ Bat is **batting only** — no baserunning term yet [A62 pending]. "
           f"Under-rates contact-and-legs profiles by roughly 4–9 runs/season.")

if roster_file is None:
    st.info("Upload a roster export to begin. Positional adjustment is "
            "deliberately absent — it is a constant per slot and cancels out of "
            "the assignment. See the notes at the foot of the page.")
    st.stop()

df = load(roster_file)
if team_filter.strip():
    col = next((c for c in ("ORG", "TM", "Team") if c in df.columns), None)
    if col:
        df = df[df[col].astype(str).str.strip() == team_filter.strip()]
    if df.empty:
        st.error(f"No players with {col} == '{team_filter}'.")
        st.stop()

bats = df[df.apply(is_batter, axis=1)].copy()
pits = df[df.apply(is_pitcher, axis=1)].copy()
if bats.empty:
    st.error("No position players found. The channel split reads POS "
             "(pitchers are SP/RP/CL).")
    st.stop()

# editable gates, seeded from the registry
if "floors" not in st.session_state:
    st.session_state["floors"] = dict(K.DEFENSIVE_FLOORS)
    st.session_state["secondary"] = dict(K.DEFENSIVE_SECONDARY)
if "locks" not in st.session_state:
    st.session_state["locks"] = {}

with st.expander("⚙️ Defensive gates (hard — a miss re-bars him)"):
    st.caption(
        "Seeded from the registry's league p10 by position. Both the primary "
        "and secondary tool must clear. Gloves do not develop upward [A50], so "
        "a miss is permanent — but range DECLINES with age [A19], so for a 30+ "
        "glove read this as present-tense."
    )
    cols = st.columns(4)
    nf = {}
    for i, pos in enumerate(FIELD_POSITIONS):
        spec = st.session_state["floors"].get(pos)
        if not spec:
            continue
        col, val = spec
        with cols[i % 4]:
            nf[pos] = (col, st.number_input(f"{pos} · {col}", value=float(val),
                                            step=5.0, key=f"fl_{pos}"))
    if st.button("↺ Reset gates"):
        st.session_state["floors"] = dict(K.DEFENSIVE_FLOORS)
        st.rerun()
    st.session_state["floors"].update(nf)

floors, secondary = st.session_state["floors"], st.session_state["secondary"]

names = sorted(bats["Name"].astype(str).tolist())
with st.expander("🔒 Position locks (a lock overrides the gate)"):
    lc = st.columns(4)
    nl = {}
    for i, pos in enumerate(CARD_ORDER):
        with lc[i % 4]:
            opts = ["(open)"] + names
            cur = st.session_state["locks"].get(pos, "(open)")
            ch = st.selectbox(pos, opts, index=opts.index(cur) if cur in opts else 0,
                              key=f"lk_{pos}")
            if ch != "(open)":
                nl[pos] = ch
    if st.button("🔓 Clear all locks"):
        st.session_state["locks"] = {}
        st.rerun()
    st.session_state["locks"] = nl

res = optimize(bats, floors, secondary, st.session_state["locks"], project_on)

def build_cand_pool(cand_file, cand_scope):
    """Load + scope the candidate pool ONCE, before the tabs.

    ⚠ It used to be loaded inside the Lineup tab, which meant the Rotation and
    Bullpen tabs referenced a name that did not exist yet -- a NameError at
    render, not at import, so it only appeared once a roster was loaded.
    Returns (df_or_None, notes) where notes are (kind, text) for the caller to
    render wherever it wants.
    """
    notes = []
    if cand_file is None:
        return None, notes
    pool = load(cand_file)
    n_all = len(pool)
    if cand_scope.startswith("Free"):
        ocol = next((c for c in ("ORG", "TM", "Team", "Org") if c in pool.columns), None)
        if ocol is None:
            notes.append(("warning",
                          "No ORG/TM/Team column in that file — cannot isolate free "
                          "agents, so everyone is being considered."))
        else:
            fa = pool[ocol].astype(str).str.strip().isin(["-", "", "nan", "NaN", "None"])
            pool = pool[fa]
            notes.append(("caption",
                          f"Free-agent filter: **{len(pool):,} of {n_all:,}** rows have "
                          f"an empty `{ocol}`."))
            if not len(pool):
                notes.append(("info",
                              "No free agents in that file. Either it is a roster export "
                              "rather than an FA list, or the org column uses a different "
                              "marker than '-'. Switch to *Everyone in the file* to see "
                              "the trade-target view instead."))
    return pool, notes


def _render_notes(notes):
    for kind, text in notes or []:
        getattr(st, kind)(text)


def _staff_upgrade_ui(pool, staff_all, projected, role, slots, key):
    """Render the 'who out there is better' block for a staff tab."""
    label = "rotation" if role == "SP" else "bullpen"
    st.markdown("---")
    st.markdown(f"#### 🔍 Who out there improves the {label}?")
    if pool is None or pool.empty:
        st.info("Upload a candidate pool in the sidebar (under 🔍 Upgrades) to "
                "search free agents and other teams for arms.")
        return
    ups, displaced, floor = find_staff_upgrades(
        pool, staff_all, projected, role, slots,
        exclude=set(staff_all["Name"].astype(str)))
    if displaced is None:
        return
    st.caption(
        f"Arms in the pool who out-score **{displaced}** — the last man in your "
        f"{label} ({role} score {floor:.1f}). "
        f"⚠ **Gain is in {role}-score units, NOT runs.** The batter upgrade "
        f"table is in runs where +12 ≈ a win; this one is an ordering only. "
        f"Do not compare the two numbers."
    )
    if ups.empty:
        st.success(f"Nobody in that pool improves your {label}.")
        return
    st.dataframe(ups.head(25)[_staff_cols(ups, ["Gain", "asSP" if role == "SP" else "asRP"])],
                 hide_index=True, use_container_width=True)
    st.caption(f"Showing the top {min(25, len(ups))} of {len(ups)}. "
               "⚠ No contract, age-curve or acquisition cost is priced here — "
               "it answers 'is he better', not 'should you get him'.")


cand, cand_notes = build_cand_pool(cand_file, cand_scope)

tab_lineup, tab_rot, tab_pen = st.tabs(["⚾ Lineup", "🔄 Rotation", "🔥 Bullpen"])

# ═══════════════════════════ ROTATION ════════════════════════════════════════
with tab_rot:
    st.subheader("🔄 Rotation")
    if pits.empty:
        st.info("No pitchers in this file.")
    else:
        staff = build_staff(pits, project_on)
        by_volume = st.checkbox(
            "Weight by innings (STM)", value=False, key="rotvol",
            help="OFF ranks on talent alone. ON multiplies by IP@STM/200, which "
                 "makes an arm that throws 150 innings beat an equal arm that "
                 "throws 120. ⚠ This is the A14 volume lever made explicit — "
                 "registry-supported in DIRECTION but the exact conversion is "
                 "ASSUMED, not fitted (methodology rule 9), which is why it is "
                 "off by default and shown as its own column.")
        staff["SPvol"] = (staff["asSP"] * staff["IP@STM"].fillna(160) / 200).round(1)
        rot = staff.sort_values("SPvol" if by_volume else "asSP",
                                ascending=False).reset_index(drop=True)
        st.caption(
            f"Ranked as STARTERS on **HRA → CON → best-two → arsenal depth → STM** "
            f"[A27 + A59]. A6 fixes the rotation at **{ROTATION_SLOTS}** with a "
            f"37-GS cap. **HRA is the movement rating that matters in this park** "
            f"(HR ×1.30) — A35 makes it a tie with overall movement for starters, "
            f"so do not break a close call on it. **Real** counts pitches clearing "
            f"the A41 floor (≥40, CH ≥45); **vsAgeNorm** is that count against the "
            f"mean for his age, because the screen is age-relative [A59c]."
        )
        st.markdown(f"**Rotation ({ROTATION_SLOTS})**")
        st.dataframe(rot.head(ROTATION_SLOTS)[_staff_cols(rot, ["asSP", "SPvol"])],
                     hide_index=True, use_container_width=True)
        if len(rot) > ROTATION_SLOTS:
            st.markdown("**Next in line**")
            st.dataframe(rot.iloc[ROTATION_SLOTS:][_staff_cols(rot, ["asSP", "SPvol"])],
                         hide_index=True, use_container_width=True)
        _staff_upgrade_ui(cand, staff, project_on, "SP", ROTATION_SLOTS, "rot")
        st.caption(
            "⚠ **`asSP` HAS NO VOLUME TERM — read it next to `IP@STM`.** A14 is "
            "explicit that stamina is a volume lever with **no eligibility "
            "floor**, so nothing here disqualifies a low-stamina arm — but that "
            "also means a 35-STM reliever and a 60-STM starter are scored as if "
            "they pitch the same number of innings, and they do not "
            "(~120 IP vs ~151). **A closer can top this list on talent alone.** "
            "`IP@STM` is the innings stamina buys (~120 at STM 35, +1.25/point); "
            "`SPvol` is `asSP × IP/200`. Tick the box above to rank on it.\n\n"
            "⚠ **No command gate is applied.** The erosion break-even is an "
            "INTERNAL value (~310–320 of 1–600) and the card equivalent is "
            "uncalibrated, so no usage call here rests on a card CON.\n\n"
            "⚠ The bullpen tab excludes whoever lands in the rotation above, so "
            "if a reliever is ranked into the rotation on talent he leaves the "
            "pen — check both tabs before acting."
        )

# ═══════════════════════════ BULLPEN ═════════════════════════════════════════
with tab_pen:
    st.subheader("🔥 Bullpen")
    if pits.empty:
        st.info("No pitchers in this file.")
    else:
        staff = build_staff(pits, project_on)
        rot_names = set(staff.sort_values("asSP", ascending=False)
                        .head(ROTATION_SLOTS)["Name"])
        pen = staff[~staff["Name"].isin(rot_names)].sort_values(
            "asRP", ascending=False).reset_index(drop=True)
        st.caption(
            f"Everyone not in the rotation, ranked as RELIEVERS. A6: **never "
            f"carry 7+**; {BULLPEN_SLOTS} is the target. Stuff is deflated "
            f"{K.RP_STUFF_DEFLATOR:g} points here — SP→RP conversion inflates "
            f"displayed Stuff ~+5 [A32], so a reliever's STU 60 is not a "
            f"starter's STU 60 and comparing them raw overrates every reliever."
        )
        if len(pen):
            closer = pen.iloc[pen["STU"].fillna(0).argmax()]
            st.markdown(f"**Closer — {closer['Name']}** "
                        f"(highest Stuff among the pen: {closer['STU']:g})")
            st.markdown(f"**Bullpen ({BULLPEN_SLOTS})**")
            st.dataframe(pen.head(BULLPEN_SLOTS)[_staff_cols(pen, ["asRP"])],
                         hide_index=True, use_container_width=True)
            if len(pen) > BULLPEN_SLOTS:
                st.markdown("**Surplus / reserve**")
                st.dataframe(pen.iloc[BULLPEN_SLOTS:][_staff_cols(pen, ["asRP"])],
                             hide_index=True, use_container_width=True)

        _staff_upgrade_ui(pen, staff, project_on, "RP", BULLPEN_SLOTS, "pen")

        # ── the interesting bit: who is miscast
        st.markdown("---")
        st.markdown("#### 🔀 Role check — is anyone in the wrong job?")
        mis = staff.copy()
        mis["listed_role"] = mis["_row"].apply(role_of)
        mis["gap"] = (mis["asSP"] - mis["asRP"]).round(1)
        flag = []
        for _, r in mis.iterrows():
            if r["listed_role"] in ("RP", "CL") and r["Real"] >= K.STARTER_ARSENAL_TARGET:
                flag.append({**{k: r[k] for k in ("Name", "Age", "Listed", "Real",
                                                  "vsAgeNorm", "STM", "IP@STM",
                                                  "HRA", "CON", "asSP", "asRP")},
                             "why": f"{int(r['Real'])} real pitches in the pen — "
                                    f"A59 makes depth a STARTER trait"})
            elif r["listed_role"] == "SP" and r["Real"] <= 2:
                flag.append({**{k: r[k] for k in ("Name", "Age", "Listed", "Real",
                                                  "vsAgeNorm", "STM", "IP@STM",
                                                  "HRA", "CON", "asSP", "asRP")},
                             "why": "2 or fewer real pitches — league-average as a "
                                    "starter, but the profile is a reliever"})
        if flag:
            st.dataframe(pd.DataFrame(flag), hide_index=True, use_container_width=True)
            st.caption(
                "A14: **role is an OUTPUT of skills, never a label.** Every arm is "
                "priced both ways above. ⚠ A 2-pitch starter is **exactly "
                "league-average** (ERA+ 99.8), not unusable — and at 17–18 two "
                "real pitches is ABOVE the age norm, so do not read a teenager's "
                "count as a verdict."
            )
        else:
            st.success("Nobody is obviously miscast on arsenal depth.")

# ═══════════════════════════ LINEUP ══════════════════════════════════════════
with tab_lineup:
    if res["unfilled"]:
        st.error("⛔ Some slots could not be filled.")
        for p in res["unfilled"]:
            st.warning(diagnose(p, bats, floors, secondary, st.session_state["locks"]))

    m1, m2, m3 = st.columns(3)
    m1.metric("Bat + glove runs (8 slots)", f"{res['total']:.1f}")
    m2.metric("of which glove",
              f"{sum(a['Def'] for a in res['assignment'].values() if a):+.1f}")
    m3.metric("Locked slots",
              sum(1 for a in res["assignment"].values() if a and a["locked"]))

    rows, starters = [], []
    for pos in CARD_ORDER:
        a = res["assignment"].get(pos)
        if a:
            rows.append({"POS": pos, "Player": a["Name"], "🔒": "🔒" if a["locked"] else "",
                         "Bat": a["Bat"], "Def": a["Def"], "Runs": a["Runs"]})
            starters.append({"Name": a["Name"], "row": res["recs"][a["_i"]],
                             "pos": pos, "Bat": a["Bat"]})
        else:
            rows.append({"POS": pos, "Player": "(unfilled)", "🔒": "",
                         "Bat": None, "Def": None, "Runs": None})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption(
        "**Bat** = runs above a display-25 baseline [A57, engine-exact]. **Def** = "
        "runs above an average glove AT THIS POSITION [A58] — the same 70 range is "
        "worth +24.6 at SS and +5.6 at 1B, and that difference is what the optimizer "
        "is actually solving. Catchers show Def 0.0: C_ABI is a dead null (p=.921 at "
        "N=1,044), so a catcher's value is his bat. Arm is a GATE above, never a "
        "value term here. ⚠ TDP and error runs pass through an assumed 0.5 runs each "
        "[A58 flags this as carried in by analogy, not derived]."
    )

    st.markdown("---")
    st.markdown("#### Batting order — The Book")
    order = book_order(starters)
    if not pits.empty:
        p9 = pits.iloc[(pd.to_numeric(pits.get("HRA"), errors="coerce").fillna(0) +
                        pd.to_numeric(pits.get("HRA"), errors="coerce").fillna(0)).argmax()]
        order.append({"#": 9, "Player": f"{p9.get('Name', 'Pitcher')} (P)", "POS": "P"})
    else:
        order.append({"#": 9, "Player": "(pitcher)", "POS": "P"})
    st.dataframe(pd.DataFrame(order), hide_index=True, use_container_width=True)
    st.caption("Three best bats at 1/2/4, 4th–5th at 3/5, then descending; pitcher "
               "9th (no-DH). Ranked on **bat only** — a batting order cannot express "
               "defensive value, and **bat runs exclude baserunning** [A62 pending] — "
               "a high-SR/STE/RUN player is ranked low here and may belong higher. "
               "Worth ~1 win a season; freely editable, and it does "
               "not change the alignment above.")

    if res["bench"]:
        st.markdown("---")
        st.markdown("#### Bench")
        st.dataframe(pd.DataFrame(res["bench"]), hide_index=True, use_container_width=True)

    # ── UPGRADES ─────────────────────────────────────────────────────────────────
    if cand is not None:
        st.markdown("---")
        st.markdown("#### 🔍 Who would improve this lineup")
        _render_notes(cand_notes)
        mine = {str(a["Name"]) for a in res["assignment"].values() if a}
        mine |= set(bats["Name"].astype(str))
        up = find_upgrades(cand, res["assignment"], floors, secondary, project_on,
                           exclude=mine)
        if not len(up):
            st.success("Nobody in that pool improves any of the eight slots.")
        else:
            st.caption(f"{len(up):,} of {len(cand):,} would improve at least one slot. "
                       f"**Gain** is runs over the incumbent at that slot — bat and "
                       f"glove together. Roughly 10 runs to a win.")
            st.dataframe(up.head(40), hide_index=True, use_container_width=True)
            st.download_button("⬇ Download upgrade list (CSV)",
                               up.to_csv(index=False), file_name="lineup_upgrades.csv",
                               mime="text/csv")
        st.caption(
            "⚠ This ranks IMPROVEMENT ONLY. It does not know what anyone costs, who "
            "is actually available, contract length, service time, or age. It also "
            "carries every limitation listed below — no baserunning, no platoon "
            "splits, no park, and it cannot see performance history, which beats "
            "ratings wherever a real record exists (R²≈0.43)."
        )

    st.markdown("---")
    with st.expander("Why there is no positional adjustment here"):
        st.markdown(
            "In an assignment where every slot is filled exactly once, adding a "
            "constant to every cell of a column shifts the total identically for "
            "**every** possible assignment — it cannot change which one wins. "
            "Positional scarcity is an **acquisition** question (what must a first "
            "baseman hit to deserve a roster spot), not an **arrangement** one. "
            "The old optimizer carried `pos_adj` + `POS_ADJ_CONSTANTS` through the "
            "objective, which changed nothing and imported a stale constant.\n\n"
            "What does *not* cancel is `def_runs`, because it is position-specific "
            "and that is the entire signal being optimised."
        )
    with st.expander("What this does NOT model"):
        st.markdown(
            "- **Baserunning.** There is no baserunning channel anywhere in the "
            "value model — steals, and the SPE demotion, are both open items.\n"
            "- **Tool interactions.** Additivity is FALSE for tools sharing the "
            "balls-in-play channel [A57c]: BABIP×AvK is super-additive (+1.24 runs), "
            "BABIP×POW sub-additive (−0.47). Deferred, ~2–7% at the corner.\n"
            "- **Platoon splits.** Real and permanent [A49], not in the objective.\n"
            "- **Park.** `APPLY_PARK_OVERLAY` is off by default; the park is shown "
            "as its own column on the rank page rather than baked into a score.\n"
            "- **Performance history.** Ratings explain under half of offensive "
            "outcome (R²≈0.43). Where a player has a real record, trust the record."
        )
