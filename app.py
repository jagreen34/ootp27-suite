"""OOTP 27 Suite - placeholder, tools coming soon."""
import streamlit as st

st.set_page_config(page_title="OOTP 27 Suite", page_icon="⚾", layout="wide")
st.title("⚾ OOTP 27 Suite")
st.caption("v14.2 registry locked | GB WAR retrained for OOTP 27 schema")
st.info("Under active development. Tools being ported from the v26 suite to OOTP 27's data schema.")

st.markdown("## Status")
st.markdown("""
**Validated and locked:**
- v14.2 formula registry (amateur stats collinearity finding)
- F1 OFF model (variant A: CON retained, BAT_AVK dropped)
- GB WAR models retrained (gb_bat_season_v27, gb_sp_season_v27)

**Coming soon:**
- Lineup construction
- Pitching staff optimizer
- Draft board v1 (OOTP 27 schema)
- Roster builder
- Trade tools
""")

st.markdown("---")
st.markdown("Return to [home](/)")
