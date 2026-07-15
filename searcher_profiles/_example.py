"""
TEMPLATE -- copy this file to <your_searcher_id>.py and edit it.

A searcher profile tells the app who to contact at each kind of target business
for YOUR business. To make one:
  1. Copy this file to e.g. searcher_profiles/plumber.py
  2. Set searcher_id / display_name / description
  3. In `plays`, for each target segment you sell to, list ranked_roles (role
     keys from roles.py, most valuable first). Omit any segment you don't sell to.

Files whose names start with "_" are treated as templates and NOT loaded by the
registry. Real profile files are gitignored -- keep yours locally and either set
SEARCHER=<your_searcher_id> in .env, or (if it's the only profile present) it is
selected automatically.

Valid role keys:  python -c "import roles; print(sorted(roles.ROLES))"
Valid segments:   python -c "import target_segments as t; print(sorted(t.SEGMENTS))"
Shape reference:  searcher_profiles/base.py
"""

from searcher_profiles.base import SearcherProfile, SegmentPlay


def _p(seg_id, ranked, probe=None):
    return SegmentPlay(
        segment_id=seg_id, ranked_roles=ranked, probe_roles=probe or [],
        sales_rationale="Why this searcher sells to this kind of business.",
        search_tactics=[
            '"{company}" "{city}" owner OR manager',
            '"{company}" linkedin "{city}"',
        ],
    )


PROFILE = SearcherProfile(
    searcher_id="example",
    display_name="Example Searcher",
    description="What this business sells, and who its buyer is.",
    plays={
        "independent_small_business": _p("independent_small_business",
            ["owner", "founder", "general_manager"]),
        # add the segments you sell to, each with its ranked role keys...
    },
)
