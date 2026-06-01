"""
DEPRECATED — compatibility shim.
================================
The Layer-3 reserve keep/cut logic moved to `roster_construction.py` when it was
promoted to the shared Roster Construction primitive (it is cross-cutting, not a
Development concern — see the "Roster Construction extraction" open item). Every
name that used to live here is re-exported below so nothing breaks during the
transition.

→ New code should import from `roster_construction` directly.
→ Safe to `git rm reserve_roster.py` once no module imports it (confirmed: the
  suite now imports `roster_construction`; this file has no remaining callers).
"""

from roster_construction import (  # noqa: F401  (re-export)
    PHASE_PRESETS, MODE_WEIGHTS, CLASS_DEFAULTS, RESERVE_DEFAULTS,
    PREMIUM_BACKUP_POS,
    player_value, classify, allocate_reserve,
)
