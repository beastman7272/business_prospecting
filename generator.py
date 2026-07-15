"""
Searcher-profile GENERATOR.

Takes a plain-English description of a searcher's business ("I run a commercial
janitorial company in metro Atlanta") and drafts a SearcherProfile: for each
target segment the searcher plausibly sells to, a ranked subset of that
segment's role inventory, a sales rationale, and search tactics. Output is an
editable, staged ``searcher_profiles/_generated/<id>.py`` file for human review
before promotion.

Why this is the payoff of the segment/profile split: selection is BOUNDED to
the shared role catalog, so the generator can't invent drifting role strings.
Every key it proposes is checked against roles.py; picks inside the segment
inventory become ranked_roles, deliberate picks outside it become flagged
probe_roles, and anything unknown is dropped. The emitted profile therefore
ALWAYS passes validate_profile by construction.

LLM seam mirrors contact_discovery.py: an abstract ``ProfileLLM`` with a
``MockProfileLLM`` for offline development and a ``GeminiProfileLLM`` for real
runs (Gemini is what the extractor already uses).

STATUS: mock-first sketch. Runs fully offline via MockProfileLLM. Real
cross-segment generation is most useful AFTER the full inventory migration --
until then the two sample segments exercise the plumbing end to end.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from roles import ROLES, known_key
from searcher_profiles.base import (
    SearcherProfile, SegmentPlay, validate_profile, ValidationReport,
)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

GENERATION_PROMPT = """You are configuring a B2B sales-prospecting tool for one type of searcher.

THE SEARCHER (the business doing the prospecting):
{description}

Your job: for each TARGET SEGMENT below, decide who this searcher should contact
to make its sale, chosen ONLY from that segment's role inventory.

Rules:
- Choose role KEYS only from the "inventory" list given for each segment. Never
  invent a key or a job title. The display names are shown only to help you pick.
- Rank the keys you choose from most to least valuable for THIS searcher's sale.
- Omit a segment entirely (return it with empty "ranked_roles") if this searcher
  would never sell to that kind of business.
- Only if a genuinely essential contact is NOT in the inventory -- a role that
  usually does not even exist at that business type but this searcher would still
  probe for -- list its key under "probe_roles". Keys there must still be real
  catalog keys (the full catalog is listed at the end). Use this sparingly.
- Write a one-to-two sentence "rationale" (why this searcher sells to this
  segment) and 2-5 "tactics" (concrete web-search strategies to find the people).

TARGET SEGMENTS:
{segments_block}

FULL ROLE CATALOG (key -> display), for probe_roles only:
{catalog_block}

Return ONLY a JSON object of this shape, no other text:
{{
  "segments": {{
    "<segment_id>": {{
      "ranked_roles": ["<key>", ...],
      "probe_roles": ["<key>", ...],
      "rationale": "...",
      "tactics": ["...", "..."]
    }}
  }}
}}
"""


def build_segments_payload(segments: dict) -> dict[str, dict]:
    """seg_id -> {description, inventory: {key: display}} for the prompt/LLM."""
    payload: dict[str, dict] = {}
    for seg_id, seg in segments.items():
        payload[seg_id] = {
            "description": seg.description,
            "inventory": {k: ROLES[k].display for k in seg.role_inventory if known_key(k)},
        }
    return payload


def _render_segments_block(payload: dict[str, dict]) -> str:
    lines = []
    for seg_id, data in payload.items():
        lines.append(f"- segment_id: {seg_id}")
        lines.append(f"  what it is: {data['description']}")
        lines.append("  inventory:")
        for key, display in data["inventory"].items():
            lines.append(f"    {key} -> {display}")
    return "\n".join(lines)


def _render_catalog_block() -> str:
    return "\n".join(f"{k} -> {r.display}" for k, r in ROLES.items())


def build_prompt(description: str, segments: dict) -> str:
    payload = build_segments_payload(segments)
    return GENERATION_PROMPT.format(
        description=description.strip(),
        segments_block=_render_segments_block(payload),
        catalog_block=_render_catalog_block(),
    )


# ---------------------------------------------------------------------------
# LLM seam (abstract + mock + Gemini) -- same shape as contact_discovery.py
# ---------------------------------------------------------------------------

class ProfileLLM:
    """Abstract: description + segments -> raw selection dict (the JSON above)."""

    def propose(self, description: str, segments: dict) -> dict[str, Any]:
        raise NotImplementedError


class MockProfileLLM(ProfileLLM):
    """Returns a canned selection dict, for offline development/tests."""

    def __init__(self, canned: dict[str, Any]):
        self.canned = canned

    def propose(self, description: str, segments: dict) -> dict[str, Any]:
        return self.canned


class GeminiProfileLLM(ProfileLLM):
    """Calls Gemini. Requires GEMINI_API_KEY. Mirrors GeminiExtractor."""

    def __init__(self, api_key: str | None = None, model: str = "gemini-3.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set")
        self.model = model

    def propose(self, description: str, segments: dict) -> dict[str, Any]:
        import requests
        prompt = build_prompt(description, segments)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        resp = requests.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)


# ---------------------------------------------------------------------------
# Catalog constraint + repair: raw LLM selection -> valid SearcherProfile
# ---------------------------------------------------------------------------

@dataclass
class GenerationReport:
    """What the repair pass had to do -- surfaced for human review."""
    demoted_to_probe: list[tuple[str, str]] = field(default_factory=list)   # (seg, key) ranked pick was off-inventory
    promoted_to_ranked: list[tuple[str, str]] = field(default_factory=list) # (seg, key) probe was actually in inventory
    dropped_unknown: list[tuple[str, str]] = field(default_factory=list)    # (seg, key) not in catalog at all
    skipped_segments: list[str] = field(default_factory=list)               # empty selection -> no play
    validation: ValidationReport | None = None


def build_profile_from_raw(
    raw: dict[str, Any],
    searcher_id: str,
    display_name: str,
    description: str,
    segments: dict,
) -> tuple[SearcherProfile, GenerationReport]:
    """
    Turn the LLM's raw selection into a SearcherProfile that is valid BY
    CONSTRUCTION:
      * ranked pick in the segment inventory   -> kept as ranked_role
      * ranked pick in catalog but off-inventory-> demoted to probe_role (flagged)
      * probe pick that is actually in inventory-> promoted to ranked_role
      * any pick not in the catalog at all      -> dropped (recorded)
    Ordering of ranked_roles is preserved from the LLM.
    """
    report = GenerationReport()
    plays: dict[str, SegmentPlay] = {}

    for seg_id, sel in (raw.get("segments") or {}).items():
        seg = segments.get(seg_id)
        if seg is None:
            # LLM named a segment we don't have; nothing to anchor to.
            report.dropped_unknown.append((seg_id, "(whole segment)"))
            continue
        inventory = set(seg.role_inventory)

        ranked: list[str] = []
        probes: list[str] = []

        for key in (sel.get("ranked_roles") or []):
            if not known_key(key):
                report.dropped_unknown.append((seg_id, key))
            elif key in inventory:
                if key not in ranked:
                    ranked.append(key)
            else:
                if key not in probes:
                    probes.append(key)
                report.demoted_to_probe.append((seg_id, key))

        for key in (sel.get("probe_roles") or []):
            if not known_key(key):
                report.dropped_unknown.append((seg_id, key))
            elif key in inventory:
                if key not in ranked:
                    ranked.append(key)
                report.promoted_to_ranked.append((seg_id, key))
            else:
                if key not in probes:
                    probes.append(key)

        if not ranked and not probes:
            report.skipped_segments.append(seg_id)
            continue

        plays[seg_id] = SegmentPlay(
            segment_id=seg_id,
            ranked_roles=ranked,
            probe_roles=probes,
            sales_rationale=(sel.get("rationale") or "").strip(),
            search_tactics=[t for t in (sel.get("tactics") or []) if t],
        )

    profile = SearcherProfile(
        searcher_id=searcher_id,
        display_name=display_name,
        description=description.strip(),
        plays=plays,
    )
    report.validation = validate_profile(profile, segments)
    return profile, report


def generate_profile(
    description: str,
    searcher_id: str,
    display_name: str,
    llm: ProfileLLM,
    segments: dict,
) -> tuple[SearcherProfile, GenerationReport]:
    """End-to-end: ask the LLM, then constrain/repair into a valid profile."""
    raw = llm.propose(description, segments)
    return build_profile_from_raw(raw, searcher_id, display_name, description, segments)


# ---------------------------------------------------------------------------
# Emit an editable, staged profile file (same shape as the hand-written gc.py)
# ---------------------------------------------------------------------------

def _py_str_list(items: list[str], indent: int) -> str:
    pad = " " * indent
    if not items:
        return "[]"
    body = "".join(f"{pad}    {s!r},\n" for s in items)
    return "[\n" + body + f"{pad}]"


def render_profile_module(profile: SearcherProfile, description: str) -> str:
    """Render a reviewable .py module defining PROFILE = SearcherProfile(...)."""
    out: list[str] = []
    out.append('"""')
    out.append("AUTO-GENERATED searcher profile -- REVIEW BEFORE PROMOTING.")
    out.append("")
    out.append("Generated by generator.py from this description:")
    out.append(f"    {description.strip()}")
    out.append("")
    out.append("Once reviewed, move this file to searcher_profiles/"
               f"{profile.searcher_id}.py and register it in "
               "searcher_profiles/__init__.py.")
    out.append('"""')
    out.append("")
    out.append("from searcher_profiles.base import SearcherProfile, SegmentPlay")
    out.append("")
    out.append("PROFILE = SearcherProfile(")
    out.append(f"    searcher_id={profile.searcher_id!r},")
    out.append(f"    display_name={profile.display_name!r},")
    out.append(f"    description={profile.description!r},")
    out.append("    plays={")
    for seg_id, play in profile.plays.items():
        out.append(f"        {seg_id!r}: SegmentPlay(")
        out.append(f"            segment_id={seg_id!r},")
        out.append(f"            ranked_roles={_py_str_list(play.ranked_roles, 12)},")
        if play.probe_roles:
            out.append(f"            probe_roles={_py_str_list(play.probe_roles, 12)},")
        out.append(f"            sales_rationale={play.sales_rationale!r},")
        out.append(f"            search_tactics={_py_str_list(play.search_tactics, 12)},")
        out.append("        ),")
    out.append("    },")
    out.append(")")
    out.append("")
    return "\n".join(out)


def emit_profile_file(
    profile: SearcherProfile,
    description: str,
    staging_dir: str = "searcher_profiles/_generated",
) -> str:
    """Write the staged module and return its path."""
    os.makedirs(staging_dir, exist_ok=True)
    path = os.path.join(staging_dir, f"{profile.searcher_id}.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_profile_module(profile, description))
    return path
