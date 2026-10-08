"""Active searcher selection.

Order: a per-request override (set by the web layer from the picker) wins; then
the SEARCHER env var (from .env); then, if exactly one profile is present, that
one; else "gc" or the first available.

The override is a ContextVar so the web layer can bind the picked searcher for
the whole request -- discovery and dossier both read get_active_profile(), so
both honor the choice without threading it through every call.
"""

import os
from contextvars import ContextVar

from dotenv import load_dotenv

from searcher_profiles import get_profile, available_searchers

load_dotenv()

_override: ContextVar = ContextVar("active_searcher_override", default=None)


def set_active_searcher(searcher_id):
    """Bind the active searcher for the current request/context (None clears it)."""
    _override.set(searcher_id or None)


def get_active_profile():
    searcher = _override.get() or os.environ.get("SEARCHER")
    if not searcher:
        present = available_searchers()
        if len(present) == 1:
            searcher = present[0]
        elif "gc" in present:
            searcher = "gc"
        elif present:
            searcher = present[0]
        else:
            searcher = "gc"  # nothing present -> get_profile raises a clear error
    return get_profile(searcher)
