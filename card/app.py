# ═══════════════════════════════════════════════════════════════════════════
# card/app.py — THE CARD (:8505). Drag a roster or a draft pool in, get the
# rules applied. Shares the ootp_uploads volume with /rank/ and /lineup/, so a
# file uploaded in any of them is offered in all of them.
#
# ⚠ THIS PAGE HOLDS NO COEFFICIENTS. Every constant comes from quakers.py
# (the card) or draft_board.py (the E[WAR] models), which are the same files
# run from the command line and verified by verify_draftday.py. If a number is
# wrong it is wrong in one place, and fixing it there fixes it here.
# ═══════════════════════════════════════════════════════════════════════════
"""
THE CARD — apply the locked rules to any OOTP export.

Two tabs, two jobs:
  ROSTER  — bars, glove gates, pitcher rules, and the counts that follow.
  DRAFT   — E[WAR] on the A104 draft-day models, with the verification banner.

Deliberately no valuation of its own. It answers "what do the rules say about
these players", not "what are they worth to me" — that is a different question
and it belongs to the GM.
"""
import csv, io, os, sys
import streamlit as st

sys.path.insert(0, "/app")
import data_store
import quakers as CARD

st.set_page_config(page_title="The Card", page_icon="⚾", layout="wide")

# ── auth, same pattern as the other services ────────────────────────────────
PW = os.environ.get("APP_PASSWORD")
if PW:
    if not st.session_state.get("ok"):
        with st.form("login"):
            if st.form_submit_button("Enter") and st.text_input("Password", type="password") == PW:
                st.session_state["ok"] = True
                st.rerun()
        st.stop()

st.title("The Card")
st.caption(
    "Locked 2026-08-26. Bars, gates and counts — no models, no fitting. "
    "Rules and citations live in `quakers.py`; the draft models in `draft_board.py`."
)

# ── upload cache (fail-loud, per rule 22) ───────────────────────────────────
usable, msg = data_store.status()
with st.sidebar:
    st.header("Files")
    (st.success if usable else st.error)(msg)
    data_store.manage(st)

def load_rows(kind: str, key: str, also=(), label="Drop a CSV export here",
              help_txt="Shared with Player Rank and Lineup — upload once, use anywhere."):
    """One widget, not two. data_store.picker() renders the uploader in the
    sidebar, saves a fresh upload automatically, and returns a FILE-LIKE object
    (a Streamlit UploadedFile, or a SavedFile that quacks like one) — never a
    path. Read the bytes off it; do not open() it."""
    f = data_store.picker(st, label, key, kind, also=also, help=help_txt)
    if f is None:
        return None
    raw = f.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows:
        st.error("%s parsed to zero rows — wrong file, or not a CSV?" % getattr(f, "name", "file"))
        return None
    return rows

def _to_csv(rows):
    if not rows:
        return ""
    buf = io.StringIO()
    keys = sorted({k for r in rows for k in r})
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()

roster_tab, draft_tab, rules_tab = st.tabs(["Roster", "Draft pool", "The rules"])

# ═══════════════════════════════ ROSTER ════════════════════════════════════
with roster_tab:
    rows = load_rows("roster", "roster", also=("league", "pool", "draftpool"),
                     label="1 · ROSTER or league export",
                     help_txt="A team roster or a full-league player export. Feeds the Roster tab.")
    if rows:
        orgs = sorted({str(r.get("ORG", "")) for r in rows} - {"", "-"})
        opts = ["(all)"] + orgs
        default = next((i for i, o in enumerate(opts) if "Philad" in o), 0)
        org = st.selectbox("Organisation", opts, index=default)
        sel = [r for r in rows if org == "(all)" or str(r.get("ORG", "")) == org]

        bats, arms, skipped = [], [], []
        for r in sel:
            name = r.get("Name", "?")
            try:
                g = (CARD.grade_arm(r, name) if r.get("POS") in CARD.ARM_POS
                     else CARD.grade_bat(r, name))
            except SystemExit as e:
                skipped.append("%s — %s" % (name, e))
                continue
            g.update({"Name": name, "POS": r.get("POS"), "Age": r.get("Age", ""),
                      "PA": r.get("PA", ""), "IP": r.get("IP", ""),
                      "wRC+": r.get("wRC+", ""), "FIP-": r.get("FIP-", "")})
            (arms if g["side"] == "ARM" else bats).append(g)

        if skipped:
            st.warning("%d row(s) could not be graded — a load-bearing column is "
                       "missing. They are NOT silently scored as zero:" % len(skipped))
            for s in skipped:
                st.text("   " + s)

        core = [b for b in bats if b["tools"] >= 2 and b["lead_tool"] == "yes"]
        ready = [a for a in arms if a["HRA"] >= CARD.HRA_OK and a["eff"] >= CARD.STARTER_EFF]
        aces = [a for a in arms if a["HRA"] >= CARD.ACE_HRA and (a["control"] or 0) >= CARD.ACE_CTL]
        c = st.columns(7)
        c[0].metric("Qualifying bats", len(core), help="2+ tools including power or eye. Target 3–4 (A94).")
        c[1].metric("Fail rule 2", sum(1 for b in bats if b["tools"] and b["lead_tool"] == "NO"),
                    help="Clears a bar, but none of it power or eye — below a no-tool bat.")
        c[2].metric("Fail glove gate", sum(1 for b in bats if b["glove"] == "FAIL"))
        # HRA FIRST — the primary run-prevention axis, 1.8x stuff and 2.1x control
        # on the within-player estimator (A88, n=18,319 transitions). NOT A75's
        # 2.5x/2.9x: that fitted on IP>=120, and A88 sec.0 showed conditioning on
        # innings is conditioning on a collider — it flips every pitcher sign.
        # The two metrics after it are a ROLE question and a FLOOR, not rankings.
        c[3].metric("Rotation-ready", len(ready),
                    help="HRA %d+ AND %d+ pitches — the arm analog of a qualifying bat. "
                         "Good enough to help, and enough arsenal to start."
                         % (CARD.HRA_OK, CARD.STARTER_EFF))
        c[4].metric("ACE gate", len(aces),
                    help="HRA %d+ AND control %d+. The arms clearing this are the best in "
                         "the league (A86)." % (CARD.ACE_HRA, CARD.ACE_CTL))
        c[5].metric("Arms HRA %d+" % CARD.HRA_OK,
                    "%d / %d" % (sum(1 for a in arms if a["HRA"] >= CARD.HRA_OK), len(arms)),
                    help="THE pitching number. Movement buys home runs, and home runs "
                         "are the run-prevention channel in this league (A88). Your "
                         "park rewards it more than anyone's.")
        c[6].metric("Control inert", sum(1 for a in arms if a["ctl_band"] == "INERT"),
                    help="A FLOOR, not a ranking axis — control owns walks and nothing else (A88). "
                         "Below %d a point is worth ~4%% of a point at 70 (A79)." % CARD.CTL_INERT)

        st.subheader("Bats")
        st.caption("Bars: " + " · ".join("%s ≥ %d" % (k, v) for k, v in CARD.BARS_AC.items())
                   + "  — AC percentiles. Do not use parquet bars on AC players.")
        st.dataframe(sorted(bats, key=lambda x: (-x["tools"], x["glove"] == "FAIL")),
                     use_container_width=True, hide_index=True,
                     column_order=["Name", "POS", "Age", "PA", "tools", "bars", "lead_tool",
                                   "glove", "glove_detail", "verdict", "wRC+"])

        st.subheader("Arms")
        st.caption("**Sorted by HRA — read that column first.** Movement buys home runs, "
                   "stuff buys strikeouts, control buys walks, and home runs are what "
                   "decides games here: HRA 1.8× stuff and 2.1× control (A88). "
                   "**STU is second, not control** — but it is pool-relative by role, so a "
                   "reliever's number flatters him as a starter (rule 11). "
                   "A pitch counts at %d, except the changeup at %d (A41). "
                   "Control buy zone %d+, inert below %d (A79). Stamina gate %d."
                   % (CARD.PITCH_FLOOR, CARD.PITCH_FLOOR_CH, CARD.CTL_BUY,
                      CARD.CTL_INERT, CARD.STM_GATE))
        st.dataframe(sorted(arms, key=lambda x: (-x["HRA"], -x["eff"], -(x["control"] or 0))),
                     use_container_width=True, hide_index=True,
                     column_order=["Name", "POS", "Age", "IP", "HRA", "STU", "eff",
                                   "control", "ctl_band", "STM", "verdict", "detail", "FIP-"])

# ═══════════════════════════════ DRAFT ═════════════════════════════════════
with draft_tab:
    try:
        import draft_board as DB
        ok = getattr(DB, "USE_DRAFTDAY", False)
        (st.success if ok else st.error)(
            ("Scoring on the A104 draft-day models — 5,978 players, each row from his own "
             "draft year. Run `verify_draftday.py` after any constant changes.")
            if ok else
            "USE_DRAFTDAY is FALSE — this board is running a superseded sample. Do not draft on it."
        )
    except Exception as e:
        st.error("draft_board.py did not import: %s" % e)
        DB = None

    rows = load_rows("draftpool", "draft", also=("pool", "roster"),
                         label="2 · DRAFT POOL export",
                         help_txt="The amateur draft class. Feeds the Draft pool tab only.")
    if rows and DB:
        scored, bad = [], []
        for r in rows:
            try:
                scored.append(DB.score(r))
            except SystemExit as e:
                bad.append("%s — %s" % (r.get("Name", "?"), e))
        if bad:
            st.warning("%d player(s) not scored (fail-loud, never a silent zero):" % len(bad))
            for s in bad[:20]:
                st.text("   " + s)
        scored.sort(key=lambda x: -x["E_WAR"])
        for i, s in enumerate(scored, 1):
            s["Rank"] = i
        st.info("The board is flat at the top — a 1–2 WAR difference across the first ten "
                "names is inside noise (rule 12). Use position and glove to separate them, "
                "not the ranking. And the bottom third is extrapolation: the pool sits below "
                "the fitted population's median. Do not read it.")
        st.dataframe(scored, use_container_width=True, hide_index=True)
        st.download_button("Download board", data=_to_csv(scored),
                           file_name="board.csv", mime="text/csv")

# ═══════════════════════════════ RULES ═════════════════════════════════════
with rules_tab:
    st.markdown("""
### Hitters
1. **Count tools, don't type them.** Each one is worth more than the last.
2. **Only power and eye stand alone.** A one-tool contact hitter grades *below* a bat with no strength at all — but contact is the best **third** tool on top of power+eye (+13.2). Never first, best third.
3. **Three quiet tools equal two loud ones.** BABIP+contact+gap = 112.8 wRC+; power+eye alone = 113.2.
4. **Buy eye, never project it.** It barely develops and flattens above 65.
5. **Glove floors on the tools, never the position rating.** SS 60 · 2B 55 · CF 65 on range; **3B is range + arm ≥ 120**. Nothing at C, 1B or the corners.
6. **Rank within class, not across it.** A HS bat at current 30 ≈ a college bat at 40.

### Pitchers
7. **HR-allowed is the best tool** — 2.1× control, 1.8× stuff. Read HRA, never Overall Movement. *The order is HRA → stuff → control → stamina: **stuff outranks control**, which overturned both "stuff is worthless" and A86's demotion of it. Each buys one thing — movement buys homers, stuff buys strikeouts, control buys walks — and homers decide games in this league.*
8. **Three effective pitches or he's a reliever.** A pitch counts at 40; a changeup at 45.
9. **Control is convex.** A point at 70 is worth 57× a point at 30.
10. **Stamina buys innings, not quality.** Buy 50 and stop.
11. **Only stuff carries a role penalty, and it scales.** Bullpen→rotation: 70 shows 60, but 40 shows 38.

### The rule about the rules
12. **Measure the edge.** Under 4 wRC+ ignore · 4–9 tiebreak only, never an argument about two named players · 10+ you can pay for. *One grade of any single rating is under 4. A whole tool is 9.5–15.8.*

**Tiebreakers, and they're bigger than the tie** — position (C vs 1B = 24.5) · elite legs (11.3) · a grade of glove at 2B/SS/CF (~10) · at the corners (~6) · at 1B (2.4) · a year past 30 (2.3).
**If those are close too, just pick one.** They're the same asset.
""")
    st.caption("Full evidence: SCOUTING_CARD_canonical.md · THE_RULES_pocket.md · A101–A105.")
