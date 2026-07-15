"""
SearcherProfile -- the searcher axis of the (segment x searcher) lookup.

A segment says who EXISTS at a target business (searcher-agnostic). A profile
says, for a given searcher (GC, accountant, attorney, handyman...), which of
those roles to contact, in what PRIORITY ORDER, and WHY -- plus the search
tactics that searcher uses. One profile per searcher type; each profile covers
the target segments that searcher actually sells to and may omit the rest.

Effective lookup:  (segment x profile) -> ranked roles + rationale + tactics
                   layered on the one shared role inventory.

Selection rule (resolved earlier in design):
  * DEFAULT: ``ranked_roles`` is a subset of the segment's ``role_inventory``.
    Reordering/selecting the complete inventory covers almost every real case
    once inventories are built for completeness.
  * ESCAPE HATCH: ``probe_roles`` are role keys deliberately OUTSIDE the segment
    inventory -- a searcher speculatively probing for a role that usually does
    NOT exist at that business type (e.g. an attorney probing a small business
    for in-house counsel). They are kept SEPARATE and FLAGGED so ranking and
    telemetry can distinguish "expected" from "speculative," and so a probe
    that recurs across profiles can be promoted into the inventory. Both
    ranked_roles and probe_roles must still be real keys in roles.py -- never
    free-text -- so no query/ranking drift is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from roles import Role, role, known_key


@dataclass
class SegmentPlay:
    """One searcher's approach to ONE target segment."""
    segment_id: str
    ranked_roles: list[str]                       # role keys, priority order
    sales_rationale: str = ""                     # why THIS searcher sells here
    search_tactics: list[str] = field(default_factory=list)
    probe_roles: list[str] = field(default_factory=list)   # flagged, off-inventory
    notes: str = ""


@dataclass
class SearcherProfile:
    searcher_id: str                              # "gc", "accountant", ...
    display_name: str
    description: str                              # plain-English; also the
                                                  # seed the generator writes from
    plays: dict[str, SegmentPlay] = field(default_factory=dict)  # by segment_id


# ---------------------------------------------------------------------------
# Effective-play resolution
# ---------------------------------------------------------------------------

@dataclass
class RankedRole:
    role: Role
    is_probe: bool          # True = off-inventory speculative probe


@dataclass
class ResolvedPlay:
    """What discovery actually consumes for a (segment, profile) pair."""
    segment_id: str
    searcher_id: str
    roles: list[RankedRole]          # ranked_roles first, then probe_roles
    sales_rationale: str
    search_tactics: list[str]
    searcher_display: str = ""


def effective_play(profile: SearcherProfile, segment_id: str) -> ResolvedPlay | None:
    """
    Resolve (segment x profile) into the ranked, role-object play that
    contact_discovery would use. Returns None if this searcher does not cover
    the segment (a legitimate 'I never sell to these' case).
    """
    play = profile.plays.get(segment_id)
    if play is None:
        return None
    ranked = [RankedRole(role(k), is_probe=False) for k in play.ranked_roles]
    probes = [RankedRole(role(k), is_probe=True) for k in play.probe_roles]
    return ResolvedPlay(
        segment_id=segment_id,
        searcher_id=profile.searcher_id,
        roles=ranked + probes,
        sales_rationale=play.sales_rationale,
        search_tactics=list(play.search_tactics),
        searcher_display=profile.display_name,
    )


# ---------------------------------------------------------------------------
# Validation -- enforces subset-only + surfaces probes
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    profile_id: str
    unknown_keys: list[tuple[str, str]] = field(default_factory=list)   # (segment, key)
    subset_violations: list[tuple[str, str]] = field(default_factory=list)  # ranked role not in inventory
    unknown_segments: list[str] = field(default_factory=list)
    probes: list[tuple[str, str]] = field(default_factory=list)          # (segment, key) -- ok but flagged

    @property
    def ok(self) -> bool:
        return not (self.unknown_keys or self.subset_violations or self.unknown_segments)


def validate_profile(profile: SearcherProfile, segments: dict) -> ValidationReport:
    """
    Check a profile against the role catalog and segment inventories.

    Errors (report.ok == False):
      * a role key that doesn't exist in roles.py
      * a play for a segment_id that doesn't exist
      * a ranked_role that is NOT in the segment's inventory  <-- the
        subset-only rule; use probe_roles for deliberate off-inventory picks.
    Warnings (allowed, but surfaced):
      * probe_roles -- deliberate off-inventory speculation.
    """
    report = ValidationReport(profile_id=profile.searcher_id)
    for seg_id, play in profile.plays.items():
        seg = segments.get(seg_id)
        if seg is None:
            report.unknown_segments.append(seg_id)
            continue
        inventory = set(seg.role_inventory)
        for k in play.ranked_roles:
            if not known_key(k):
                report.unknown_keys.append((seg_id, k))
            elif k not in inventory:
                report.subset_violations.append((seg_id, k))
        for k in play.probe_roles:
            if not known_key(k):
                report.unknown_keys.append((seg_id, k))
            else:
                # A probe that is actually in the inventory isn't a probe --
                # flag it so the author moves it to ranked_roles.
                report.probes.append((seg_id, k))
                if k in inventory:
                    report.subset_violations.append((seg_id, f"{k} (probe already in inventory)"))
    return report
