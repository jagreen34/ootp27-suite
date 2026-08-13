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
from dev_model import (
    project_batter, score_batter, decompose, flag_batter,
    project_pitcher, score_pitcher, flag_pitcher, real_pitches,
    positional_bars, budget, is_batter, is_pitcher,
    effective_position, role_of, arsenal_ok,
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


# ── batters ───────────────────────────────────────────────────────────────────
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
            "Name": r.get("Name"), "POS": r.get("POS"),
            "Plays": p0 + ("*" if moved else ""),
            "Age": pd.to_numeric(r.get("Age"), errors="coerce"),
            "Score": sc,
            "Pct@POS": pct(pool, sc) if pool is not None else np.nan,
            "PctAll": pct(all_pool, sc),
            "vsBar": round(sc - bar) if bar else np.nan,
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
            "Name": r.get("Name"), "POS": r.get("POS"),
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
pos_filter = f3.multiselect("Positions", sorted(
    d["POS"].astype(str).str.split("/").str[0].str.upper().unique()))

v = d[d["Age"] <= age_cap] if d["Age"].notna().any() else d
if pos_filter:
    v = v[v["POS"].astype(str).str.split("/").str[0].str.upper().isin(pos_filter)]
v = v.head(top_n)

cols = (["Name", "POS", "Plays", "Age", "Score", "Pct@POS", "PctAll", "vsBar",
         "Budget", "POW", "EYE", "HT", "GAP", "AVK"]
        if mode == "Batters" else
        ["Name", "POS", "Role", "Age", "Score", "PctAll", "STU", "MOV", "CON",
         "RealPitches"])
st.dataframe(v[[c for c in cols if c in v.columns]],
             hide_index=True, use_container_width=True)
if mode == "Batters":
    st.caption("**Plays** = the position he can actually hold; `*` means he "
               "misses the defensive floor at his listed position and has been "
               "re-barred at the fallback. Gloves are FIXED [A50].")
else:
    st.caption("**Gates applied to the score:** RP/CL Stuff is deflated 5 pts "
               "(SP→RP conversion inflates Stuff ~+5); an arsenal with fewer "
               "than 2 pitches clearing the A41 floor is penalised. With "
               "projection ON, an arm below the CON 40 command gate has his "
               "out-pitch eroded [A54].")

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
