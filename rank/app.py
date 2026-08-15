"""
OOTP Player Rank — percentile analysis against an uploaded population.

Deliberately small. It answers ONE question: how good is this player relative
to that population, at his position. No trade value, no contracts, no service
time, no F1/F2. If you want one of those, use the OOTP 27 Suite.

Registry constants are imported from the parent dev_constants.py / dev_model.py
so this tool CANNOT drift from the registry. There is only one copy.
"""
import os
import sys

import streamlit as st

st.set_page_config(page_title="OOTP Player Rank", page_icon="📊", layout="wide")


# ── ACCESS GATE (identical to the suite) ──────────────────────────────────────
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
    st.title("📊 OOTP Player Rank")
    st.text_input("Password", type="password", key="pw", on_change=entered)
    if st.session_state.get("auth_ok") is False:
        st.error("Incorrect password")
    return False


if not check_password():
    st.stop()
# ── authenticated below ───────────────────────────────────────────────────────

sys.path.insert(0, "/app")               # parent modules live at the repo root

import numpy as np
import pandas as pd

import dev_constants as K
from dev_constants import PITCH_COLUMNS as PITCH_COLS
from dev_model import (
    project_batter, score_batter, decompose, flag_batter,
    project_pitcher, score_pitcher, flag_pitcher, real_pitches,
    positional_bars, budget, is_batter, is_pitcher,
    effective_position, role_of, arsenal_ok,
    playable_positions, listed_positions, park_delta,
)

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]


def load(f):
    if f is None:
        return None
    if f.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(f)
    return pd.read_csv(f)


@st.cache_data(show_spinner=False)
def load_cached(b):
    """Re-read an uploaded file from its bytes. Cached so repeated calls in
    one session cost nothing."""
    import io
    try:
        return pd.read_csv(io.BytesIO(b))
    except Exception:
        return pd.read_excel(io.BytesIO(b))


@st.cache_data(show_spinner=False)
def bars_cached(b):
    return positional_bars(load_cached(b))


def pct(series, value):
    s = series.dropna()
    return round(100 * (s < value).mean()) if len(s) else np.nan


# ── sidebar: the population defines every bar ─────────────────────────────────
st.sidebar.header("📁 Files")
league_file = st.sidebar.file_uploader(
    "League population (sets the bars)", type=["csv", "xlsx"], key="lg")
target_file = st.sidebar.file_uploader(
    "Players to rank (roster / draft pool)", type=["csv", "xlsx"], key="tg")
st.sidebar.caption("Leave the second empty to rank the league against itself.")
st.sidebar.markdown("---")
mode = st.sidebar.radio("Channel", ["Batters", "Pitchers"])
show_projected = st.sidebar.checkbox(
    "Project to end of development", value=True,
    help="Applies the A56 age budget. Off = rank on current ratings only.")
st.sidebar.markdown("---")
st.sidebar.caption(f"registry {K.REGISTRY_VERSION}")
st.sidebar.caption("Return to [home](/)")

st.title("📊 OOTP Player Rank")
st.caption(f"Percentile analysis against an uploaded population · "
           f"registry {K.REGISTRY_VERSION} · bars recomputed from YOUR file every run")

if league_file is None:
    st.info("Upload a league-wide export to begin. **Every bar and percentile "
            "is computed from that file** — nothing is stored or assumed.")
    st.stop()

league_df = load(league_file)
bars, league_scores = bars_cached(league_file.getvalue())
target_df = load(target_file) if target_file is not None else league_df

c1, c2, c3 = st.columns(3)
c1.metric("Population", f"{len(league_df):,} players")
c2.metric("Ranking", f"{len(target_df):,} players")
c3.metric("Positions with a bar", len(bars))

with st.expander("Positional bars from this population"):
    bd = pd.DataFrame(sorted(bars.items(), key=lambda x: x[1]),
                      columns=["POS", "League mean score"])
    st.dataframe(bd, hide_index=True, use_container_width=False)
    st.caption("The bar is the mean rating-score of players listed at that "
               "position **in the file you uploaded**. A shortstop clearing a "
               "low bar can outrank a first baseman clearing a high one.")



# ── player card ───────────────────────────────────────────────────────────────
def render_card(row_src, proj, sc, bar, pool, mode_is_bat):
    """Full grade card for one player: current vs projected, flags, mix."""
    name = row_src.get("Name", "?")
    age = pd.to_numeric(row_src.get("Age"), errors="coerce")
    org = org_of(row_src)
    st.markdown(f"### {name}")
    head = f"{row_src.get('POS','?')} · age {int(age) if pd.notna(age) else '?'}"
    if org:
        head += f" · {org}"
    st.caption(head)

    if mode_is_bat:
        p0, moved, why = effective_position(row_src)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Runs (projected)", f"{sc:.1f}")
        if bar:
            c2.metric(f"vs {p0} bar", f"{sc - bar:+.1f}")
        if pool is not None:
            c3.metric("Pct at position", f"{pct(pool, sc)}")
        c4.metric("Budget left", f"{budget(age)}")

        rows = []
        for tool, (cc, pc) in [("POW", ("POW", "POW P")), ("EYE", ("EYE", "EYE P")),
                               ("BABIP", ("BABIP", "HT P")), ("GAP", ("GAP", "GAP P")),
                               ("AVK", ("K's", "K P"))]:
            cur = pd.to_numeric(row_src.get(cc), errors="coerce")
            pot = pd.to_numeric(row_src.get(pc), errors="coerce")
            pr = proj.get(tool)
            gap_left = (pot - pr) if (pd.notna(pot) and pr is not None) else np.nan
            rows.append({
                "Tool": tool, "Current": cur, "Projected": pr, "Potential": pot,
                "Unreachable": gap_left if pd.notna(gap_left) and gap_left > 0 else 0,
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("**Unreachable** = grades of shown potential the age budget "
                   "cannot reach. Gap beyond the budget must not be priced.")

        d1, d2 = st.columns(2)
        with d1:
            st.markdown("**Defense** *(fixed — current IS truth)*")
            dcols = [c for c in ["IF RNG", "IF ARM", "IF ERR", "TDP",
                                 "OF RNG", "OF ARM", "OF ERR", "C ABI", "C ARM", "SPE"]
                     if c in row_src and pd.notna(pd.to_numeric(row_src.get(c), errors="coerce"))]
            st.dataframe(pd.DataFrame([{c: row_src[c] for c in dcols}]).T
                         .rename(columns={0: "grade"}), use_container_width=True)
        with d2:
            st.markdown("**Fit**")
            st.write(f"Plays: **{p0}**" + (" ⚠ re-barred" if moved else ""))
            st.write("Tools allow: " + "/".join(playable_positions(row_src)))
            st.write(f"Park Δ: **{park_delta(proj):+.1f}** runs")
            for k in ("WE", "INT"):
                if k in row_src:
                    st.write(f"{k}: {row_src[k]}")
            mix = decompose(proj)
            if mix:
                st.caption("score mix: " + " / ".join(
                    f"{k} {v}%" for k, v in sorted(mix.items(), key=lambda x: -x[1])))
        for f in flag_batter(row_src, proj, sc, bar, None):
            st.write(f"• {f}")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Score", f"{sc:.1f}")
        n, names = real_pitches(row_src)
        c2.metric("Real pitches", n)
        c3.metric("Role", role_of(row_src) or "?")
        st.dataframe(pd.DataFrame([{
            "STU": proj.get("STU"), "MOV": proj.get("MOV"), "CON": proj.get("CON"),
            "HRA": row_src.get("HRA"), "STM": row_src.get("STM"),
        }]), hide_index=True, use_container_width=True)
        pit = {c: row_src.get(c) for c in PITCH_COLS
               if c in row_src and pd.notna(pd.to_numeric(row_src.get(c), errors="coerce"))}
        if pit:
            st.markdown("**Arsenal** *(A41: trust ≥40, changeup ≥45)*")
            st.dataframe(pd.DataFrame([pit]), hide_index=True, use_container_width=True)
        for f in flag_pitcher(row_src, proj):
            st.write(f"• {f}")


# ── batters ───────────────────────────────────────────────────────────────────
def org_of(r):
    """Team/org label. Exports disagree on the column name; try each."""
    for c in ("ORG", "TM", "Team", "Org", "Organization"):
        v = r.get(c)
        if v is not None and str(v) not in ("nan", "-", ""):
            return str(v)
    return ""


def _raw_batter_proj(r):
    if show_projected:
        return project_batter(r)
    return {t: pd.to_numeric(r.get(c), errors="coerce") for t, c in
            [("POW", "POW"), ("EYE", "EYE"), ("BABIP", "BABIP"),
             ("GAP", "GAP"), ("AVK", "K's")]}


@st.cache_data(show_spinner=False)
def league_batter_pools(_df_bytes, projected):
    """
    Score the league population ONCE and bucket by effective position.
    Cached on the uploaded file's bytes + the projection toggle, so changing
    a filter does not rescore anything.
    """
    df = load_cached(_df_bytes)
    all_scores, by_pos = [], {}
    for _, r in df.iterrows():
        if not is_batter(r):
            continue
        proj = project_batter(r) if projected else {
            t: pd.to_numeric(r.get(c), errors="coerce") for t, c in
            [("POW", "POW"), ("EYE", "EYE"), ("BABIP", "BABIP"),
             ("GAP", "GAP"), ("AVK", "K's")]}
        sc = score_batter(proj)
        if not sc:
            continue
        all_scores.append(sc)
        p0, _, _ = effective_position(r)
        by_pos.setdefault(p0, []).append(sc)
    return (pd.Series(all_scores),
            {k: pd.Series(v) for k, v in by_pos.items()})


def build_batters(df, all_pool, pos_pools):
    rows = []
    for _, r in df.iterrows():
        if not is_batter(r):
            continue
        proj = _raw_batter_proj(r)
        sc = score_batter(proj)
        if not sc:
            continue
        p0, moved, _ = effective_position(r)
        bar = bars.get(p0)
        pool = pos_pools.get(p0)
        rows.append({
            "Name": r.get("Name"), "Org": org_of(r), "POS": r.get("POS"),
            "Plays": p0 + ("*" if moved else ""),
            "Age": pd.to_numeric(r.get("Age"), errors="coerce"),
            "Score": sc,
            "Pct@POS": pct(pool, sc) if pool is not None else np.nan,
            "PctAll": pct(all_pool, sc),
            "vsBar": round(sc - bar) if bar else np.nan,
            "ParkD": park_delta(proj),
            "CanPlay": "/".join(playable_positions(r)),
            "Budget": budget(pd.to_numeric(r.get("Age"), errors="coerce")),
            "POW": proj.get("POW"), "EYE": proj.get("EYE"),
            "HT": proj.get("BABIP"), "GAP": proj.get("GAP"), "AVK": proj.get("AVK"),
            "_flags": flag_batter(r, proj, sc, bar, None) if show_projected else [],
            "_mix": decompose(proj),
        })
    return pd.DataFrame(rows)


def build_pitchers(df):
    rows = []
    for _, r in df.iterrows():
        if not is_pitcher(r):
            continue
        proj = project_pitcher(r) if show_projected else {
            "STU": pd.to_numeric(r.get("STU"), errors="coerce"),
            "MOV": pd.to_numeric(r.get("MOV"), errors="coerce"),
            "CON": pd.to_numeric(r.get("CON_1"), errors="coerce")}
        sc = score_pitcher(proj, r)
        n, _ = real_pitches(r)
        rows.append({
            "Name": r.get("Name"), "Org": org_of(r), "POS": r.get("POS"),
            "Role": role_of(r),
            "Age": pd.to_numeric(r.get("Age"), errors="coerce"),
            "Score": sc, "STU": proj.get("STU"), "MOV": proj.get("MOV"),
            "CON": proj.get("CON"), "RealPitches": n,
            "_flags": flag_pitcher(r, proj),
        })
    d = pd.DataFrame(rows)
    if len(d):
        pool = d["Score"] if target_file is None else league_pitcher_pool(
            league_file.getvalue(), show_projected)
        d["PctAll"] = d["Score"].apply(lambda s: pct(pool, s))
    return d


@st.cache_data(show_spinner=False)
def league_pitcher_pool(_df_bytes, projected):
    df = load_cached(_df_bytes)
    out = []
    for _, x in df.iterrows():
        if not is_pitcher(x):
            continue
        proj = project_pitcher(x) if projected else {
            "STU": pd.to_numeric(x.get("STU"), errors="coerce"),
            "MOV": pd.to_numeric(x.get("MOV"), errors="coerce"),
            "CON": pd.to_numeric(x.get("CON_1"), errors="coerce")}
        out.append(score_pitcher(proj, x))
    return pd.Series(out)


with st.spinner("Scoring…"):
    if mode == "Batters":
        all_pool, pos_pools = league_batter_pools(league_file.getvalue(), show_projected)
        d = build_batters(target_df, all_pool, pos_pools)
    else:
        d = build_pitchers(target_df)

if not len(d):
    other = "batters" if mode == "Pitchers" else "pitchers"
    st.warning(
        f"**No {mode.lower()} in the uploaded file.** The channel split reads the "
        f"`POS` column — pitchers are SP/RP/CL. This file appears to contain only "
        f"{other}; switch the Channel toggle, or upload a file that has them."
    )
    st.stop()

sort_col = "vsBar" if mode == "Batters" else "Score"
d = d.sort_values(sort_col, ascending=False, na_position="last")

f1, f2, f3 = st.columns(3)
max_age = int(d["Age"].max()) if d["Age"].notna().any() else 45
age_cap = f1.slider("Max age", 17, max_age, max_age)
top_n = f2.slider("Show top", 5, min(200, len(d)), min(30, len(d)))
all_pos = sorted({p for v in d["POS"].astype(str) for p in v.upper().split("/") if p.strip()})
pos_filter = f3.multiselect("Positions", all_pos)
match_tools = st.checkbox(
    "Position filter includes anyone whose TOOLS allow it",
    value=False,
    help="Eligibility in OOTP is experience, not ability — the tools are the "
         "real gate. On: a 2B with IF ARM 55+ shows under 3B even if he's "
         "never played there.")
orgs = sorted(o for o in d.get("Org", pd.Series(dtype=str)).unique() if str(o).strip())
org_filter = st.multiselect("Teams", orgs) if orgs else []

v = d[d["Age"] <= age_cap] if d["Age"].notna().any() else d
if pos_filter:
    want = set(pos_filter)
    def _hit(row):
        listed = {p.strip().upper() for p in str(row["POS"]).split("/") if p.strip()}
        if listed & want:
            return True
        if match_tools and row.get("CanPlay"):
            return bool({p for p in str(row["CanPlay"]).split("/")} & want)
        return False
    v = v[v.apply(_hit, axis=1)]
if org_filter:
    v = v[v["Org"].isin(org_filter)]
v = v.head(top_n)

cols = (["Name", "Org", "POS", "Plays", "CanPlay", "Age", "Score", "Pct@POS",
         "PctAll", "vsBar", "ParkD", "Budget", "POW", "EYE", "HT", "GAP", "AVK"]
        if mode == "Batters" else
        ["Name", "Org", "POS", "Role", "Age", "Score", "PctAll", "STU", "MOV",
         "CON", "RealPitches"])
# drop the Org column entirely when the file has no team info (draft pools)
if "Org" in d.columns and not d["Org"].astype(str).str.strip().any():
    cols = [c for c in cols if c != "Org"]
st.dataframe(v[[c for c in cols if c in v.columns]],
             hide_index=True, use_container_width=True)
if mode == "Batters":
    st.caption("**ParkD** = score under the Quakers park overlay minus neutral "
               "(positive = the park helps him). ⚠ The multiplier is DERIVED "
               "(HR ×1.30 at home ≈ +15% over a season), **not fitted** — the "
               "multiverse the weights came from is park-neutral. "
               "**CanPlay** = positions his TOOLS allow, not his experience. "
               "**Plays** = the position he can actually hold; `*` means he "
               "misses the defensive floor at his listed position and has been "
               "re-barred at the fallback. Gloves are FIXED [A50].")
else:
    st.caption("**Gates applied to the score:** RP/CL Stuff is deflated 5 pts "
               "(SP→RP conversion inflates Stuff ~+5); an arsenal with fewer "
               "than 2 pitches clearing the A41 floor is penalised. With "
               "projection ON, an arm below the CON 40 command gate has his "
               "out-pitch eroded [A54].")

st.markdown("---")
pick = st.selectbox("🔍 Player card", ["—"] + v["Name"].astype(str).tolist(),
                    help="Full grades, projection, defense, flags.")
if pick and pick != "—":
    src = target_df[target_df["Name"].astype(str) == pick]
    if len(src):
        r0 = src.iloc[0]
        if mode == "Batters":
            pj = _raw_batter_proj(r0)
            s0 = score_batter(pj)
            p0e, _, _ = effective_position(r0)
            render_card(r0, pj, s0, bars.get(p0e), pos_pools.get(p0e), True)
        else:
            pj = project_pitcher(r0) if show_projected else {
                "STU": pd.to_numeric(r0.get("STU"), errors="coerce"),
                "MOV": pd.to_numeric(r0.get("MOV"), errors="coerce"),
                "CON": pd.to_numeric(r0.get("CON_1"), errors="coerce")}
            render_card(r0, pj, score_pitcher(pj, r0), None, None, False)
st.markdown("---")

st.download_button("⬇ Download board (CSV)",
                   d.drop(columns=["_flags", "_mix"], errors="ignore").to_csv(index=False),
                   file_name="rank_board.csv", mime="text/csv")

st.markdown("---")
st.subheader("Flags")
for _, r in v.iterrows():
    if not r.get("_flags"):
        continue
    age = int(r["Age"]) if pd.notna(r["Age"]) else "?"
    with st.expander(f"{r['Name']} ({r['POS']}, {age})"):
        for f in r["_flags"]:
            st.write(f"• {f}")
        if r.get("_mix"):
            st.caption("score mix: " + " / ".join(
                f"{k} {vv}%" for k, vv in sorted(r["_mix"].items(), key=lambda x: -x[1])))

st.markdown("---")
st.caption(
    "**Percentile ≠ value across channels.** An 85th-percentile starter and an "
    "83rd-percentile centre fielder sit in different distributions with different "
    "spreads — the ranks are not comparable. "
    "**Projections are the centre of a wide distribution, not forecasts** — "
    "development is bimodal (~1/5 pop hard, ~1/5 barely move) [A56]. "
    "Age budgets are TCR=0-derived; the AC runs TCR=100 where delivery is higher "
    "with ~2× the pop rate [A51], so read projections as a **floor**. "
    "**Ratings explain under half of offensive outcome** (R²≈0.43) — where you "
    "have real performance history, trust the history."
)
