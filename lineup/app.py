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
from dev_model import (
    project_batter, score_batter, def_runs, def_runs_breakdown, score_total,
    is_batter, is_pitcher, effective_position, budget,
)

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
    """Bat runs [A57] + glove runs at THIS position [A58]. The whole objective."""
    return score_batter(proj) + def_runs(row, pos)


# ── OPTIMIZER ────────────────────────────────────────────────────────────────
def optimize(bats, floors, secondary, locks):
    """
    Maximise total runs across the eight no-DH field slots.

    locks: {pos: Name} — forced assignments. A lock OVERRIDES eligibility by
    design: your call beats the model's.
    """
    recs = bats.to_dict("records")
    projs = {i: project_batter(r) for i, r in enumerate(recs)}
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


# ── UI ───────────────────────────────────────────────────────────────────────
def load(f):
    if f is None:
        return None
    if f.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(f)
    return pd.read_csv(f)


st.sidebar.header("📁 Roster")
roster_file = st.sidebar.file_uploader("Roster export", type=["csv", "xlsx"], key="rst")
team_filter = st.sidebar.text_input("Filter to ORG (blank = whole file)", "")
st.sidebar.markdown("---")
project_on = st.sidebar.checkbox(
    "Project to end of development", value=False,
    help="OFF is right for setting TODAY's lineup — you field the player you "
         "have. ON answers 'who should this be in 1980'.")
st.sidebar.markdown("---")
st.sidebar.caption(f"registry {K.REGISTRY_VERSION}")
st.sidebar.caption("Return to [home](/)")

st.title("⚾ Lineup Optimizer")
st.caption(f"Hungarian assignment maximising **bat runs [A57] + glove runs [A58]** "
           f"across the eight no-DH slots · registry {K.REGISTRY_VERSION}")

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

res = optimize(bats, floors, secondary, st.session_state["locks"])

if res["unfilled"]:
    st.error("⛔ Some slots could not be filled.")
    for p in res["unfilled"]:
        st.warning(diagnose(p, bats, floors, secondary, st.session_state["locks"]))

m1, m2, m3 = st.columns(3)
m1.metric("Total runs (8 slots)", f"{res['total']:.1f}")
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
    p9 = pits.iloc[(pd.to_numeric(pits.get("MOV"), errors="coerce").fillna(0) +
                    pd.to_numeric(pits.get("HRA"), errors="coerce").fillna(0)).argmax()]
    order.append({"#": 9, "Player": f"{p9.get('Name', 'Pitcher')} (P)", "POS": "P"})
else:
    order.append({"#": 9, "Player": "(pitcher)", "POS": "P"})
st.dataframe(pd.DataFrame(order), hide_index=True, use_container_width=True)
st.caption("Three best bats at 1/2/4, 4th–5th at 3/5, then descending; pitcher "
           "9th (no-DH). Ranked on **bat only** — a batting order cannot express "
           "defensive value. Worth ~1 win a season; freely editable, and it does "
           "not change the alignment above.")

if res["bench"]:
    st.markdown("---")
    st.markdown("#### Bench")
    st.dataframe(pd.DataFrame(res["bench"]), hide_index=True, use_container_width=True)

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
