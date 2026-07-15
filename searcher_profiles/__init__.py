"""
Searcher profile registry -- AUTO-DISCOVERING.

Each searcher's profile is a single drop-in module in this folder (gc.py,
accountant.py, photographer.py, ...) exposing one SearcherProfile. This file
discovers whatever profile modules are physically present and registers them --
no hardcoded imports -- so the registry reflects exactly the profiles in THIS
checkout, and adding one never requires editing this file.

Distribution model: real profile modules are gitignored. The shared repo ships
only the engine (base.py) and a template (_example.py); each recipient is given
just their own profile file to drop in here. Modules named "base" or starting
with "_" (like _example.py) are skipped.
"""

from __future__ import annotations

import importlib
import pkgutil

from searcher_profiles.base import SearcherProfile


def _discover() -> dict[str, SearcherProfile]:
    found: dict[str, SearcherProfile] = {}
    for mod in pkgutil.iter_modules(__path__):
        name = mod.name
        if name == "base" or name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{name}")
        for value in vars(module).values():
            if isinstance(value, SearcherProfile):
                found[value.searcher_id] = value
    return found


SEARCHER_PROFILES: dict[str, SearcherProfile] = _discover()


def get_profile(searcher_id: str) -> SearcherProfile:
    try:
        return SEARCHER_PROFILES[searcher_id]
    except KeyError:
        present = ", ".join(sorted(SEARCHER_PROFILES)) or "(none)"
        raise KeyError(
            f"No searcher profile {searcher_id!r}. Present in this checkout: "
            f"{present}. Drop the profile module into searcher_profiles/."
        )


def available_searchers() -> list[str]:
    return sorted(SEARCHER_PROFILES)
