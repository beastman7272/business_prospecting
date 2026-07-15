"""Active searcher selection.

Order: the SEARCHER env var (from .env) wins. If SEARCHER is unset and exactly
one profile is present in this checkout, that one is used automatically -- so a
recipient who has only their own profile file need not set anything. With
several profiles present and no SEARCHER, prefer "gc", else the first available.
"""

import os
from dotenv import load_dotenv

from searcher_profiles import get_profile, available_searchers

load_dotenv()


def get_active_profile():
    searcher = os.environ.get("SEARCHER")
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
