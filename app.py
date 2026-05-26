"""
OOTP 27 Evaluation Suite — v1.0
Flat navigation | v14.2 registry locked | SQLite persistence | Docker-ready
"""
import streamlit as st
import pandas as pd
import db
import acquisitions as acq

st.set_page_config(
    page_title="OOTP 27 Suite",
    page_icon="⚾",
    layout="wide"
)

SECTIONS = [
    "📊 My Team",
    "⚾ Lineups",
    "🥎 Pitching",
    "🔄 Acquisitions",
    "📝 Draft",
    "🌱 Development",
    "🧑 Player Lookup",
    "⚙️ Settings",
]

def get_league():
    return st.session_state.get('active_league', None)

st.title("⚾ OOTP 27 Suite")
st.caption("v1.0 | v14.2 registry locked | F1.1 SP/RP | Full batter F1 reconstruction")

st.sidebar.header("🏟️ League")

existing_leagues = db.list_leagues()
CREATE_OPTION    = "➕ Create new league…"
league_choices   = existing_leagues + [CREATE_OPTION]

selected_league_name = st.sidebar.selectbox(
    "Select league", league_choices,
    index=0 if existing_leagues else len(league_choices) - 1,
    key='league_select'
)

if selected_league_name == CREATE_OPTION:
    new_name = st.sidebar.text_input("New league name", key='new_league_name',
                                      placeholder="e.g. American Circuit")
    if st.sidebar.button("Create", key='create_league_btn'):
        if new_name.strip():
            db.create_league(new_name.strip())
            st.rerun()
        else:
            st.sidebar.error("Enter a league name.")
    st.stop()

if st.session_state.get('_loaded_league') != selected_league_name:
    st.session_state['active_league']  = db.get_league(selected_league_name)
    st.session_state['_loaded_league'] = selected_league_name
    st.rerun()

league = get_league()
tc     = league.team_config
complete, missing = league.team_config_complete()
my_team = tc.get('my_team', '')
mode    = tc.get('mode', 'Competing')

if my_team:
    st.sidebar.success(f"🏟️ {my_team} | {mode}")
else:
    st.sidebar.warning("⚠️ Team not configured — go to Acquisitions → Settings")

pre_dl = league.is_pre_deadline()
if pre_dl is True:
    st.sidebar.info("📅 Pre-deadline window")
elif pre_dl is False:
    st.sidebar.info("📅 Offseason / post-deadline")

st.sidebar.markdown("---")
section = st.sidebar.radio("🛠️ Section", SECTIONS, key='section')
st.sidebar.markdown("---")
st.sidebar.caption("Return to [home](/)")

if section == "🔄 Acquisitions":
    acq.render_acquisitions(league)

elif section == "📊 My Team":
    st.header("📊 My Team")
    st.info("Coming soon — roster overview, F1 by position, WAR pace, service time dashboard.")

elif section == "⚾ Lineups":
    st.header("⚾ Lineups")
    st.info("Coming soon — lineup construction with Hungarian algorithm optimization and ZR defense.")

elif section == "🥎 Pitching":
    st.header("🥎 Pitching")
    st.info("Coming soon — 6-man rotation builder, bullpen role assignment, fatigue tracking.")

elif section == "📝 Draft":
    st.header("📝 Draft Board")
    st.info("Coming soon — OOTP 27 draft board with v14.2 F2 live-draft formula, pitch grade display, arsenal flags.")

elif section == "🌱 Development":
    st.header("🌱 Development")
    st.info("Coming soon — prospect tracking, delivery rate projections, reserve slot management, service time planning.")

elif section == "🧑 Player Lookup":
    st.header("🧑 Player Lookup")
    st.info("Coming soon — search any player in an uploaded CSV, full ratings card, F1/F2 scores, trade value.")

elif section == "⚙️ Settings":
    st.header("⚙️ Settings")
    acq.render_team_config(league)

    st.markdown("---")
    st.subheader("League Management")

    with st.expander("🗒️ League Notes"):
        cfg   = league.get_config()
        notes = st.text_area("Notes", value=cfg.get('notes', ''), height=120, key='lg_notes')
        if st.button("Save Notes", key='lg_notes_save'):
            league.save_config({'notes': notes})
            st.success("Saved.")

    with st.expander("📁 Season Archives"):
        archives = league.list_season_archives()
        with st.form("archive_form"):
            c1, c2, c3 = st.columns(3)
            with c1: arch_year   = st.number_input("Year", value=1976, min_value=1871, max_value=2100)
            with c2: arch_record = st.text_input("Record", placeholder="72-90")
            with c3: arch_finish = st.text_input("Finish", placeholder="3rd place")
            arch_notes = st.text_area("Notes", height=60)
            if st.form_submit_button("Archive Season"):
                league.save_season_archive(arch_year, arch_record, arch_finish, arch_notes)
                st.success(f"Season {arch_year} archived.")
                st.rerun()
        if archives:
            for arch in archives:
                c1, c2, c3, c4 = st.columns([1, 2, 3, 1])
                c1.metric(str(arch['year']), arch.get('record', '—'))
                c2.caption(arch.get('finish', ''))
                c3.caption(arch.get('notes', ''))
                if c4.button("🗑️", key=f"del_arch_{arch['year']}"):
                    league.delete_season_archive(arch['year'])
                    st.rerun()

    with st.expander("⚙️ Formula Reference"):
        st.subheader("Batter F1 (R²=0.738)")
        st.code("WAR = OFF_WAR + DEF_WAR + POS_ADJ\n"
                "OFF: CON, GAP, POW, EYE, SPE, AGE, POS, GBT, FBT, PA\n"
                "DEF: per-position exposure-weighted fielding model\n"
                "POS_ADJ: (PA/650) × positional_constant")
        st.subheader("SP F1.1 (R²=0.779)")
        st.code("v-splits: STU_vL, STU_vR, MOV_vL, MOV_vR, PIT_CON_vL, PIT_CON_vR\n"
                "+ STM, velo_mid, IP, PBABIP, HRA\n"
                "+ I_power and I_fb_k archetype interaction terms")
        st.subheader("RP F1.1 (R²=0.571)")
        st.code("Same v-split structure; separate archetype thresholds (STU≥65 for I_power)")
        st.subheader("Trade Value")
        st.code("TV = (F1 - 0.2) × control_window × POS_MULT\n"
                "control_window = min(YEARS_LEFT, years_until_FA)\n"
                "years_until_FA = max(0, 6 - (ML_YRS + ML_DAYS/76))")
        st.subheader("Positional Multipliers")
        st.dataframe(pd.DataFrame(list(acq.POS_MULT.items()), columns=['POS', 'Mult']),
                     hide_index=True, use_container_width=False)
        st.subheader("Delivery Rates (OOTP 27 A-T locked)")
        st.code("Batter CON 0.48 | GAP 0.48 | POW 0.45 | EYE 0.28\n"
                "Pitcher STU 0.53 | MOV 0.40 | CON 0.43\n"
                "Expected mature = current + (potential - current) × delivery_rate")
        st.subheader("Hard Rules")
        st.markdown(
            "- 6-man rotation, 37-GS hard cap (+3.2 WAR)\n"
            "- Never carry 7+ RP\n"
            "- Never draft RP before Round 4\n"
            "- Unmotivated / Disruptive = auto-skip, never override\n"
            "- Fragile = −40% to projected value\n"
            "- PIT_CON < 40 = LOW-CON flag\n"
            "- EYE never declines (increases through age 37)\n"
            "- SP: MOV/STU decline at 28, CON holds to 32\n"
            "- Batter peak age 25, hold to 28, decline 29+\n"
            "- Service time: 76 days = 1 year | 3 yrs = arb | 6 yrs = FA"
        )
