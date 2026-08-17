"""
nav.py — shared top navigation for the ootptools apps.

Every tool sits behind nginx on its own path, so the links are plain anchors
rather than Streamlit page links: /rank/ and /lineup/ and /27/ are separate
containers, not pages of one app.

Usage — first Streamlit call after set_page_config and the auth gate:

    import nav
    nav.render(st, "rank")

Keys: "home" · "rank" · "lineup" · "suite".

⚠ Paths are declared ONCE here. If nginx ever moves a tool, change it in this
file and every app follows. Do not hand-write these links in an app.
"""

from __future__ import annotations

LINKS: list[tuple[str, str, str, str]] = [
    # key,      icon, label,    href
    ("home",   "🏠", "Home",   "/"),
    ("rank",   "📊", "Rank",   "/rank/"),
    ("lineup", "⚾", "Lineup", "/lineup/"),
    ("suite",  "🧰", "Suite",  "/27/"),
]

_CSS = """
<style>
.ootpnav{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;
         margin:.1rem 0 .9rem 0;font-size:.86rem;line-height:1}
.ootpnav a,.ootpnav span.cur{
    display:inline-block;padding:.34rem .72rem;border-radius:999px;
    border:1px solid rgba(128,128,128,.35);text-decoration:none;
    color:inherit!important;white-space:nowrap}
.ootpnav a:hover{border-color:rgba(128,128,128,.75);
                 background:rgba(128,128,128,.12);text-decoration:none}
.ootpnav span.cur{background:rgba(128,128,128,.20);font-weight:600;
                  border-color:rgba(128,128,128,.55)}
.ootpnav .note{margin-left:auto;opacity:.55;border:0;padding-left:.2rem;
               font-size:.78rem}
</style>
"""


def render(st, current: str = "", note: str | None = None) -> None:
    """Draw the nav bar. `current` is rendered inert so you can see where you are."""
    parts = [_CSS, '<div class="ootpnav">']
    for key, icon, label, href in LINKS:
        if key == current:
            parts.append(f'<span class="cur">{icon} {label}</span>')
        else:
            parts.append(f'<a href="{href}" target="_self">{icon} {label}</a>')
    if note:
        parts.append(f'<span class="note">{note}</span>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
