"""
data_store.py — shared upload cache for /rank/ and /lineup/.

Both containers mount the SAME named volume at OOTP_DATA_DIR, so a file
uploaded in one tool is immediately available in the other. Upload the roster
once; use it in both.

⚠ FAIL-LOUD [methodology rule 22]. If the directory is missing, unmounted or
read-only, the sidebar SAYS SO. It must never silently drop a save and then
render an empty list that reads like "you haven't uploaded anything yet" — that
is the silent-zero failure the rule exists to prevent. A save that did not
happen is reported as a save that did not happen.

⚠ NO SILENT TRUNCATION. Pruning to KEEP_PER_KIND is announced in the sidebar,
naming what was removed. A cap the user cannot see reads like "everything is
still here."

Layout:  {OOTP_DATA_DIR}/uploads/{kind}__{utc-stamp}__{original name}
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path

KEEP_PER_KIND = 8
_STAMP = "%Y%m%dT%H%M%SZ"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


# ── location ─────────────────────────────────────────────────────────────────
def root() -> Path:
    return Path(os.environ.get("OOTP_DATA_DIR", "/app/data")) / "uploads"


def status() -> tuple[bool, str]:
    """(usable, human message). Never raises — the caller renders the message."""
    d = root()
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, f"Saved uploads: {d}"
    except Exception as e:                                   # noqa: BLE001
        return False, (
            f"⚠ Upload caching is OFF — cannot write to {d} ({type(e).__name__}). "
            "The volume is probably not mounted. Files you upload will work for "
            "this session but will NOT be remembered."
        )


# ── records ──────────────────────────────────────────────────────────────────
class Entry:
    __slots__ = ("path", "kind", "stamp", "orig")

    def __init__(self, path: Path):
        self.path = path
        parts = path.name.split("__", 2)
        self.kind = parts[0] if len(parts) == 3 else "?"
        self.stamp = parts[1] if len(parts) == 3 else ""
        self.orig = parts[2] if len(parts) == 3 else path.name

    @property
    def when(self) -> str:
        try:
            t = datetime.strptime(self.stamp, _STAMP).replace(tzinfo=timezone.utc)
            return t.astimezone().strftime("%b %d %H:%M")
        except Exception:                                    # noqa: BLE001
            return "?"

    @property
    def kb(self) -> int:
        try:
            return max(1, self.path.stat().st_size // 1024)
        except Exception:                                    # noqa: BLE001
            return 0

    def label(self) -> str:
        return f"{self.orig}  ·  {self.when}  ·  {self.kb} KB"


def available(kind: str | None = None) -> list[Entry]:
    """Newest first. Empty list if the directory is unusable."""
    d = root()
    if not d.is_dir():
        return []
    try:
        items = [Entry(p) for p in d.iterdir() if p.is_file() and not p.name.startswith(".")]
    except Exception:                                        # noqa: BLE001
        return []
    if kind:
        items = [e for e in items if e.kind == kind]
    return sorted(items, key=lambda e: e.stamp, reverse=True)


# ── write / read ─────────────────────────────────────────────────────────────
def save(uploaded, kind: str) -> tuple[Path | None, list[str]]:
    """Persist a Streamlit UploadedFile. Returns (path_or_None, pruned_names)."""
    ok, _ = status()
    if not ok:
        return None, []
    name = _SAFE.sub("_", getattr(uploaded, "name", "upload.csv"))[:120]
    stamp = datetime.now(timezone.utc).strftime(_STAMP)
    dest = root() / f"{kind}__{stamp}__{name}"
    try:
        pos = uploaded.tell()
        uploaded.seek(0)
        dest.write_bytes(uploaded.read())
        uploaded.seek(pos)
    except Exception:                                        # noqa: BLE001
        return None, []
    pruned = []
    for old in available(kind)[KEEP_PER_KIND:]:
        try:
            old.path.unlink()
            pruned.append(old.orig)
        except Exception:                                    # noqa: BLE001
            pass
    return dest, pruned


class SavedFile(io.BytesIO):
    """Quacks like a Streamlit UploadedFile: has .name and reads as bytes."""

    def __init__(self, entry: Entry):
        super().__init__(entry.path.read_bytes())
        self.name = entry.orig
        self.entry = entry


def delete(entry: Entry) -> bool:
    try:
        entry.path.unlink()
        return True
    except Exception:                                        # noqa: BLE001
        return False


# ── sidebar widget ───────────────────────────────────────────────────────────
def picker(st, label: str, key: str, kind: str,
           types=("csv", "xlsx"), help: str | None = None,
           default_to_saved: bool = True):
    """Uploader + saved-file fallback. Returns a file-like object or None.

    A fresh upload always wins and is saved automatically. With no fresh
    upload, the most recent saved file of this kind is offered and — when
    default_to_saved is True — pre-selected, which is the whole point: the
    tool remembers what you gave it last time.
    """
    up = st.sidebar.file_uploader(label, type=list(types), key=key, help=help)

    if up is not None:
        path, pruned = save(up, kind)
        if path is None:
            ok, msg = status()
            if not ok:
                st.sidebar.warning(msg)
        else:
            st.sidebar.caption(f"💾 saved · {up.name}")
            if pruned:
                st.sidebar.caption(
                    f"🧹 pruned {len(pruned)} older {kind} file(s), keeping "
                    f"{KEEP_PER_KIND}: {', '.join(pruned)}")
        return up

    saved = available(kind)
    if not saved:
        ok, msg = status()
        if not ok:
            st.sidebar.warning(msg)
        return None

    opts = ["(none)"] + [e.label() for e in saved]
    idx = 1 if default_to_saved else 0
    pick = st.sidebar.selectbox(f"…or reuse a saved {kind}", opts, index=idx,
                                key=f"{key}__saved")
    if pick == "(none)":
        return None
    chosen = saved[opts.index(pick) - 1]
    st.sidebar.caption(f"📂 using saved · {chosen.orig} ({chosen.when})")
    return SavedFile(chosen)


def manage(st) -> None:
    """Expander listing every cached file with a delete control."""
    ok, msg = status()
    with st.sidebar.expander("🗂 Saved files"):
        if not ok:
            st.warning(msg)
            return
        items = available()
        if not items:
            st.caption("Nothing cached yet. Uploads are saved automatically.")
            st.caption(msg)
            return
        st.caption(msg)
        for e in items:
            c1, c2 = st.columns([5, 1])
            c1.write(f"**{e.kind}** — {e.orig}  \n<small>{e.when} · {e.kb} KB</small>",
                     unsafe_allow_html=True)
            if c2.button("🗑", key=f"del_{e.path.name}", help="Delete"):
                if delete(e):
                    st.rerun()
                else:
                    st.error(f"Could not delete {e.orig}")
