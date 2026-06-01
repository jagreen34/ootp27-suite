"""
OOTP 27 Suite — Player Lookup
=============================
Type a name, see one player's full evaluation card; or paste/select 2–4 names for
a side-by-side compare. Searches ALL players in an uploaded full-league export
(falls back to the saved My Team roster if nothing is uploaded here).

Pure consumer of the existing scorers — no new formulas. Everything (F1, TV, Park
Fit Δ, BABIP luck, flex, defense, arsenal, gate, projected SP WAR) is imported from
`acquisitions` / `my_team` / `park_fit` so a coefficient change anywhere propagates
here automatically.

Role-aware: batters show OFF/DEF/POS_ADJ F1 + Park Fit Δ + luck + flex + defense;
pitchers show BOTH SP and RP F1 (role is an output of skills, A14) + arsenal + the
top-pitch gate + projected SP WAR. Pitchers carry no Park Fit Δ (A23 NULL).
"""

import pandas as pd
import streamlit as st

from db import League, compute_control_window, compute_arb_status
from acquisitions import (
    prep_data, _s,
    batter_f1, pitcher_f1, sp_f1, rp_f1, off_f1, def_war, pos_adj,
    trade_value, babip_luck_flag,
    defense_summary, defense_detail, arsenal_detail,
    top_pitch_grade, secondary_pitch_count, passes_pitch_gate, cnt_eff_pitches,
    sp_war_estimate,
    bats_hand, throws_hand, hand_str,
    BATTER_POSITIONS, PITCHER_POSITIONS,
)
from my_team import flex_summary
import park_fit as pf

_V27_SIG = {'CON_1', 'BABIP_1', 'WAR_1'}
_V26_SIG = {'CON.1', 'BABIP.1', 'WAR.1'}


# ══════════════════════════════════════════════════════════════════════════════
# POOL LOADING — own uploader (all players), saved-roster fallback
# ══════════════════════════════════════════════════════════════════════════════

def _load_pool(league: League):
    """Return (df, source_label). Prefers a Player-Lookup upload (held in session
    so searches don't re-upload); falls back to the saved My Team roster."""
    up = st.session_state.get('_lookup_pool')
    if up is not None and not up.empty:
        return up, st.session_state.get('_lookup_pool_src', 'uploaded league export')

    saved = league.get_last_roster()
    if saved is not None and not saved.empty:
        return saved.copy(), 'saved My Team roster (upload a full league export to search everyone)'
    return None, None


def _render_uploader(league: League):
    with st.expander("📤 Upload a player pool to search "
                     "(full league export = all players)", expanded=False):
        st.caption("A full combined league CSV lets you look up ANY player. "
                   "Without one, lookup falls back to your saved My Team roster. "
                   "This upload is held for this session only — it does NOT replace "
                   "your My Team roster.")
        up = st.file_uploader("Player pool CSV", type=['csv'], key='lookup_upload')
        if up is not None:
            uid = f"{up.name}:{up.size}"
            if uid != st.session_state.get('_lookup_upload_id'):
                try:
                    raw = pd.read_csv(up, encoding='utf-8-sig', low_memory=False)
                    cols = set(raw.columns)
                    if (_V26_SIG & cols) and not (_V27_SIG & cols):
                        st.error("⛔ Looks like an OOTP 26 export, not 27 — "
                                 "ratings columns differ. Re-export from OOTP 27.")
                        return
                    if not (_V27_SIG & cols):
                        st.warning("⚠️ Missing the OOTP 27 signature "
                                   "(CON_1/BABIP_1/WAR_1). Verify results.")
                    df = prep_data(raw)
                    st.session_state['_lookup_pool'] = df
                    st.session_state['_lookup_pool_src'] = f"{up.name} ({len(df)} players)"
                    st.session_state['_lookup_upload_id'] = uid
                    st.success(f"Loaded {len(df)} players. Search below.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to read CSV: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SEARCH
# ══════════════════════════════════════════════════════════════════════════════

def _name_col(df) -> str:
    for c in ('Name', 'NAME', 'Player', 'PLAYER'):
        if c in df.columns:
            return c
    return 'Name'


def _search(df, query: str) -> pd.DataFrame:
    """Case-insensitive substring match on the name column. Multiple comma- or
    newline-separated terms → union (so you can paste a list of 3–4 names)."""
    ncol = _name_col(df)
    if ncol not in df.columns:
        return df.iloc[0:0]
    terms = [t.strip().lower() for t in query.replace('\n', ',').split(',') if t.strip()]
    if not terms:
        return df.iloc[0:0]
    names = df[ncol].astype(str).str.lower()
    mask = pd.Series(False, index=df.index)
    for t in terms:
        mask |= names.str.contains(t, regex=False, na=False)
    return df[mask]


# ══════════════════════════════════════════════════════════════════════════════
# CARD — single player
# ══════════════════════════════════════════════════════════════════════════════

def _contract_line(row) -> str:
    yl   = _s(row.get('YEARS_LEFT', 0))
    mly  = _s(row.get('ML_YRS', 0))
    mld  = _s(row.get('ML_DAYS', 0))
    ctrl = compute_control_window(yl, mly, mld)
    arb  = compute_arb_status(mly, mld)
    svc  = round(mly + mld / 76.0, 2)
    sal  = int(_s(row.get('SALARY', 0)))
    bits = [f"Svc {svc} yr", arb, f"{round(ctrl, 1)} yr control"]
    if sal:
        bits.append(f"${sal:,}")
    if yl:
        bits.append(f"{int(yl)} yr left")
    return " · ".join(bits)


def _park_entry(league: League):
    prof = pf.profile_from_team_config(league.team_config or {})
    return pf.match_profile(prof), prof


def _render_card(row, league: League):
    pos = str(row.get('POS', '')).strip()
    name = str(row.get('Name', ''))
    age = int(_s(row.get('AGE', row.get('Age', 0))))
    team = str(row.get('TM', row.get('ORG', '')))
    is_pit = pos in PITCHER_POSITIONS

    st.markdown(f"### {name} — {pos}" + (f", {team}" if team and team != '-' else ""))
    st.caption(f"Age {age} · B/T {hand_str(row)} · {_contract_line(row)}")

    if is_pit:
        _render_pitcher_card(row, league)
    elif pos in BATTER_POSITIONS:
        _render_batter_card(row, league)
    else:
        st.info(f"Position `{pos}` isn't a scored batter or pitcher slot — "
                "showing identity only.")


def _render_batter_card(row, league: League):
    f1 = batter_f1(row)
    off = off_f1(row)
    dwar = def_war(row, str(row.get('POS', '')))
    padj = pos_adj(row, str(row.get('POS', '')))
    ctrl = compute_control_window(_s(row.get('YEARS_LEFT', 0)),
                                  _s(row.get('ML_YRS', 0)), _s(row.get('ML_DAYS', 0)))
    tv = trade_value(f1, ctrl, str(row.get('POS', '')))

    c1, c2, c3 = st.columns(3)
    c1.metric("F1 (total WAR)", f"{f1:.2f}")
    c2.metric("Trade Value", f"{tv:.1f}")
    luck = babip_luck_flag(row)
    c3.metric("BABIP luck", luck if luck not in ('', 'N/A') else "—")

    st.caption(f"F1 decomposition — OFF {off:.2f} · DEF {dwar:.2f} · POS_ADJ {padj:.2f} "
               "(total = OFF + DEF + POS_ADJ, A-rule decomposition)")

    # Ratings
    st.markdown("**Ratings**")
    st.dataframe(pd.DataFrame([{
        'CON': int(_s(row.get('CON', 0))), 'GAP': int(_s(row.get('GAP', 0))),
        'POW': int(_s(row.get('POW', 0))), 'EYE': int(_s(row.get('EYE', 0))),
        'SPE': int(_s(row.get('SPE', 0))),
        'BABIP(rtg)': int(_s(row.get('BAT_BABIP_RATING', 0))),
    }]), use_container_width=True, hide_index=True)

    # Park Fit Δ (per-650 fit rate; fail-loud)
    entry, prof = _park_entry(league)
    if entry is not None:
        res = pf.park_fit_rate(dict(row), entry['factors'])
        if res['ok']:
            conf = entry['confidence']
            st.markdown(f"**Park Fit Δ ({entry['name']}):** `{res['delta_war']:+.2f}` "
                        "WAR/650 — full-season fit rate, additive (never folds into F1). "
                        f"SPE {conf['SPE']}, POW {conf['POW']}.")
        else:
            st.caption(f"Park Fit Δ — n/a ({res['error']}).")
    else:
        st.caption(f"Park Fit Δ — park not calibrated (HR {prof.get('HR')}/AVG "
                   f"{prof.get('AVG')}/2B {prof.get('2B')}/3B {prof.get('3B')}); "
                   "A22 covers HR 1.30/0.98/0.95/0.90 only.")

    # Flex + defense
    flex = flex_summary(row)
    if flex:
        st.markdown(f"**Position flex:** {flex}")
    dsum = defense_summary(row)
    if dsum and dsum != '—':
        st.markdown(f"**Defense:** {dsum}")


def _render_pitcher_card(row, league: League):
    sp = sp_f1(row)
    rp = rp_f1(row)
    ctrl = compute_control_window(_s(row.get('YEARS_LEFT', 0)),
                                  _s(row.get('ML_YRS', 0)), _s(row.get('ML_DAYS', 0)))
    tv = trade_value(pitcher_f1(row), ctrl, str(row.get('POS', '')))
    proj = sp_war_estimate(row)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SP F1", f"{sp:.2f}")
    c2.metric("RP F1", f"{rp:.2f}")
    c3.metric("Proj WAR (SP)", f"{proj:.2f}")
    c4.metric("Trade Value", f"{tv:.1f}")
    st.caption("Role is an OUTPUT of skills (A14) — priced both ways, never "
               "collapsed. Proj WAR (SP) from the v27 GB model.")

    # Gate + flags
    gate_ok = passes_pitch_gate(row)
    tp = int(top_pitch_grade(row))
    sec = secondary_pitch_count(row)
    gate_txt = ("✅ clears rotation gate" if gate_ok
                else "⛔ fails rotation gate → bullpen")
    st.markdown(f"**Top-pitch gate:** {gate_txt} "
                f"(best pitch {tp}, secondaries ≥40: {sec}; need best ≥50 + ≥1 sec ≥40)")
    con = _s(row.get('PIT_CON', 0))
    if con and con < 40:
        st.warning(f"⚠️ LOW-CON (PIT_CON {int(con)} < 40)")

    # Ratings
    st.markdown("**Ratings**")
    st.dataframe(pd.DataFrame([{
        'STU': int(_s(row.get('STU', 0))), 'MOV': int(_s(row.get('MOV', 0))),
        'PIT_CON': int(_s(row.get('PIT_CON', 0))), 'STM': int(_s(row.get('STM', 0))),
        'velo': int(_s(row.get('velo_mid', 0))),
        'eff pitches': cnt_eff_pitches(row),
    }]), use_container_width=True, hide_index=True)

    ars = arsenal_detail(row)
    if ars:
        st.markdown("**Arsenal:** " + " · ".join(f"{n} {g}" for n, g in ars))
    st.caption("No Park Fit Δ for pitchers (A23 NULL — park compresses rather than "
               "rewards HR-avoidance; the SP F1 HRA term already carries it).")


# ══════════════════════════════════════════════════════════════════════════════
# COMPARE — 2–4 players side by side
# ══════════════════════════════════════════════════════════════════════════════

def _compare_row(row, league: League) -> dict:
    pos = str(row.get('POS', '')).strip()
    is_pit = pos in PITCHER_POSITIONS
    ctrl = compute_control_window(_s(row.get('YEARS_LEFT', 0)),
                                  _s(row.get('ML_YRS', 0)), _s(row.get('ML_DAYS', 0)))
    out = {
        'Name': str(row.get('Name', '')),
        'POS': pos,
        'Age': int(_s(row.get('AGE', row.get('Age', 0)))),
        'F1': round(pitcher_f1(row) if is_pit else batter_f1(row), 2),
        'TV': round(trade_value(pitcher_f1(row) if is_pit else batter_f1(row),
                                ctrl, pos), 1),
        'Control': round(ctrl, 1),
    }
    if is_pit:
        out.update({
            'SP F1': round(sp_f1(row), 2), 'RP F1': round(rp_f1(row), 2),
            'Proj WAR': round(sp_war_estimate(row), 2),
            'STU': int(_s(row.get('STU', 0))), 'MOV': int(_s(row.get('MOV', 0))),
            'PIT_CON': int(_s(row.get('PIT_CON', 0))), 'STM': int(_s(row.get('STM', 0))),
            'Gate': '✅' if passes_pitch_gate(row) else '⛔',
            'Park Fit Δ': None,            # A23 NULL
        })
    else:
        entry, _ = _park_entry(league)
        pfd = None
        if entry is not None:
            r = pf.park_fit_rate(dict(row), entry['factors'])
            pfd = r['delta_war'] if r['ok'] else None
        out.update({
            'CON': int(_s(row.get('CON', 0))), 'POW': int(_s(row.get('POW', 0))),
            'GAP': int(_s(row.get('GAP', 0))), 'EYE': int(_s(row.get('EYE', 0))),
            'SPE': int(_s(row.get('SPE', 0))),
            'Luck': babip_luck_flag(row),
            'Park Fit Δ': pfd,
        })
    return out


def _render_compare(matches, league: League, ncol: str):
    names = matches[ncol].astype(str).tolist()
    pick = st.multiselect("Pick 2–4 to compare", names,
                          default=names[:min(4, len(names))], key='lookup_cmp')
    if len(pick) < 2:
        st.info("Pick at least two players to compare.")
        return
    if len(pick) > 4:
        st.warning("Showing the first 4 — comparison is designed for up to 4.")
        pick = pick[:4]
    rows = [matches[matches[ncol].astype(str) == n].iloc[0].to_dict() for n in pick]
    recs = [_compare_row(r, league) for r in rows]
    # Transpose: metrics down the side, players across — easier to read 2–4 wide.
    cmp_df = pd.DataFrame(recs).set_index('Name').T
    st.dataframe(cmp_df, use_container_width=True)
    st.caption("Batters and pitchers don't share every row — blank cells are "
               "metrics that don't apply to that player's role. Park Fit Δ is the "
               "per-650 fit rate (hitters only; A23 NULL for pitchers).")


# ══════════════════════════════════════════════════════════════════════════════
# RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render_player_lookup(league: League):
    st.header("🧑 Player Lookup")
    st.caption("Look up any player by name for a full evaluation card, or compare "
               "a few side by side. Reuses every suite scorer — nothing re-derived.")

    _render_uploader(league)
    df, src = _load_pool(league)
    if df is None or df.empty:
        st.info("Upload a player pool above (a full league export searches everyone), "
                "or load a roster in 📊 My Team first.")
        return
    st.caption(f"Searching: **{src}**.")

    ncol = _name_col(df)
    query = st.text_input("Search by name (comma-separate a few to compare)",
                          key='lookup_query',
                          placeholder="e.g. Nino   ·   or:  Nino, Norberg, Reynolds")
    if not query.strip():
        return

    matches = _search(df, query)
    if matches.empty:
        st.warning(f"No players matching “{query}”.")
        return

    n = len(matches)
    if n == 1:
        _render_card(matches.iloc[0].to_dict(), league)
        return

    st.caption(f"{n} matches.")
    mode = st.radio("View", ['Compare side by side', 'One full card'],
                    horizontal=True, key='lookup_mode')
    if mode == 'Compare side by side':
        _render_compare(matches, league, ncol)
    else:
        names = matches[ncol].astype(str).tolist()
        pick = st.selectbox("Which player?", names, key='lookup_pick_one')
        sel = matches[matches[ncol].astype(str) == pick].iloc[0].to_dict()
        _render_card(sel, league)
