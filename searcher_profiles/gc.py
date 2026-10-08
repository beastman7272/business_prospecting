"""
General Contractor searcher profile -- the hand-tuned EXEMPLAR.

The reference profile: kept polished by hand, and the few-shot example the
generator learns from when it drafts accountant.py, handyman.py, etc. All the
GC-specific material that used to live inside gc_target_segments.py -- the
per-segment sales_rationale, search_tactics, and role ORDERING -- now lives
here, where it belongs. Each play's ranked_roles is a subset of that segment's
inventory in target_segments.py, expressed as role keys from roles.py.

Full migration: all 22 segments covered.
"""

from __future__ import annotations

from searcher_profiles.base import SearcherProfile, SegmentPlay


GC_PROFILE = SearcherProfile(
    searcher_id="gc",
    display_name="Commercial General Contractor",
    description=(
        "A commercial general contractor selling tenant improvements, "
        "buildouts, expansions, and renovations. Targets whoever owns the "
        "facilities/construction decision at a prospect business."
    ),
    plays={

        "professional_services_office": SegmentPlay(
            segment_id="professional_services_office",
            ranked_roles=[
                "office_manager", "operations_director", "coo",
                "managing_partner", "managing_director", "owner",
                "executive_director", "administrator",
            ],
            sales_rationale=(
                "Tenant improvement, office buildout, expansion, or refresh of "
                "leased office space. Decisions usually sit with whoever runs "
                "the office, not a dedicated facilities team."
            ),
            search_tactics=[
                'site:{domain} "{city}" leadership OR team OR office',
                'site:{domain} "team" OR "leadership" OR "about"',
                '"{company}" "{city}" "office manager" OR "director of operations"',
                '"{company}" linkedin "{city}"',
                'Georgia Secretary of State business registration "{company}"',
            ],
            notes="Small firms: owner/partner decides. Larger regional firms: "
                  "office manager or COO handles facilities.",
        ),

        "corporate_office": SegmentPlay(
            segment_id="corporate_office",
            ranked_roles=[
                "real_estate_director", "facilities_leadership",
                "chief_administrative_officer", "office_manager",
            ],
            sales_rationale=(
                "Office buildouts, campus expansion, workplace renovation. "
                "Decisions usually route through a dedicated corporate real "
                "estate or workplace function rather than a single office "
                "manager."
            ),
            search_tactics=[
                'site:{domain} "corporate real estate" OR "workplace" OR "facilities"',
                '"{company}" "director of facilities" OR "corporate real estate"',
                '"{company}" "{city}" office OR campus expansion',
                '"{company}" linkedin "facilities" OR "workplace"',
            ],
            notes="For a small business mis-tagged corporate_office, fall back "
                  "to professional_services_office roles.",
        ),

        "manufacturing_industrial": SegmentPlay(
            segment_id="manufacturing_industrial",
            ranked_roles=[
                "plant_manager", "operations_director", "vp_manufacturing",
                "facilities_leadership", "ehs_manager", "general_manager",
            ],
            sales_rationale=(
                "Plant expansion, production line additions, warehouse "
                "buildouts, dock work, office additions on industrial property."
            ),
            search_tactics=[
                '"{company}" "plant manager" OR "general manager"',
                '"{company}" "operations" linkedin',
                'site:{domain} "leadership" OR "team"',
                '"{company}" expansion OR "new facility" OR "groundbreaking"',
            ],
            notes="Plant managers are often quoted in local press for "
                  "expansions -- high-value search target.",
        ),

        "trade_services_small_business": SegmentPlay(
            segment_id="trade_services_small_business",
            ranked_roles=["owner", "founder", "general_manager"],
            sales_rationale=(
                "Buildout, remodel, or expansion of a small leased or owned "
                "commercial space. Decision-maker is almost always the owner."
            ),
            search_tactics=[
                '"{company}" owner OR founder "{city}"',
                '"{company}" linkedin "{city}"',
                'Georgia Secretary of State business registration "{company}"',
            ],
            notes="Roles are simple; keep search effort light.",
        ),

        "wellness_studio": SegmentPlay(
            segment_id="wellness_studio",
            ranked_roles=[
                "owner", "franchisee", "studio_manager", "general_manager",
                "operations_director",
            ],
            sales_rationale=(
                "Buildout or remodel for a new or existing location. Often "
                "owner-operated; larger chains may be franchised."
            ),
            search_tactics=[
                '"{company}" owner OR franchisee "{city}"',
                'parent brand of "{company}"',
                '"{company}" linkedin "{city}"',
            ],
            notes="Check for a franchise/parent brand before assuming "
                  "independent.",
        ),

        "retail_chain_location": SegmentPlay(
            segment_id="retail_chain_location",
            ranked_roles=[
                "construction_director", "development_director",
                "real_estate_director", "facilities_leadership",
            ],
            sales_rationale=(
                "New store buildouts, remodels, rollout programs. Decisions "
                "almost always made at corporate, not the individual location."
            ),
            search_tactics=[
                'corporate parent of "{company}"',
                '"{parent_company}" "director of construction" OR "store development"',
                '"{parent_company}" linkedin "real estate" OR "development"',
                '"{parent_company}" ICSC OR retail construction',
            ],
            notes="Identify the corporate parent first; ICSC speaker/panel "
                  "lists are a good source.",
        ),

        "independent_small_business": SegmentPlay(
            segment_id="independent_small_business",
            ranked_roles=[
                "owner", "founder", "president", "general_manager",
                "operating_partner",
            ],
            sales_rationale=(
                "Buildout, remodel, or expansion. Decision-maker is usually "
                "the owner."
            ),
            search_tactics=[
                '"{company}" owner OR founder',
                '"{company}" interview "{city}"',
                'Georgia Secretary of State business registration "{company}"',
                '"{company}" linkedin',
            ],
            notes="State filings and local business press are reliable "
                  "ownership sources.",
        ),

        "healthcare_hospital": SegmentPlay(
            segment_id="healthcare_hospital",
            ranked_roles=[
                "plant_operations_director", "facilities_leadership",
                "construction_director", "real_estate_director", "coo",
                "capital_projects_director",
            ],
            sales_rationale=(
                "Renovations, expansions, new wings, medical office buildings. "
                "Long sales cycles, large project values."
            ),
            search_tactics=[
                'site:{domain} "facilities" OR "plant operations" "director"',
                'site:{domain} leadership OR administration',
                '"{company}" "VP of facilities" OR "chief facilities"',
                '"{company}" capital project OR expansion announcement',
                '"{company}" ASHE OR healthcare construction',
            ],
            notes="Hospital systems publish leadership directories; ASHE lists "
                  "are useful.",
        ),

        "healthcare_practice": SegmentPlay(
            segment_id="healthcare_practice",
            ranked_roles=[
                "practice_manager", "office_manager", "owner",
                "managing_physician", "ceo",
            ],
            sales_rationale=(
                "Office buildout, expansion to new location, remodel. Often "
                "owner-operator for smaller practices; practice manager "
                "handles facilities for larger groups."
            ),
            search_tactics=[
                'site:{domain} "practice manager" OR "administrator"',
                'site:{domain} "Dr." OR "meet" OR "about" OR bio',
                '"{company}" owner OR founder "{city}"',
                '"{company}" "Dr." "{city}"',
                '"{company}" linkedin "practice"',
                'Georgia Secretary of State "{company}"',
            ],
            notes="Owner is usually a clinician; facilities delegated to a "
                  "practice manager.",
        ),

        "education_k12": SegmentPlay(
            segment_id="education_k12",
            ranked_roles=[
                "facilities_leadership", "operations_director", "coo", "cfo",
                "superintendent", "capital_projects_director", "administrator",
            ],
            sales_rationale=(
                "New construction, renovations, additions, capital improvement "
                "programs. Public bidding usually applies for public districts."
            ),
            search_tactics=[
                'site:{district_domain} "facilities" OR "operations" director',
                'site:{district_domain} staff directory',
                'site:{district_domain} board meeting minutes facilities',
                '"{district}" SPLOST OR bond program',
                'Georgia Department of Education "{district}"',
            ],
            notes="Districts publish staff directories and board minutes; "
                  "SPLOST/bond programs drive K-12 funding.",
        ),

        "education_higher": SegmentPlay(
            segment_id="education_higher",
            ranked_roles=[
                "facilities_leadership", "operations_director",
                "capital_projects_director", "construction_director",
                "university_architect", "cfo",
            ],
            sales_rationale=(
                "Capital projects, renovations, residence halls, academic "
                "buildings, research facilities. Long cycles, often involves "
                "public bidding."
            ),
            search_tactics=[
                'site:{domain} "facilities" OR "capital projects" director',
                'site:{domain} planning design construction',
                '"{institution}" master plan',
                '"{institution}" capital project announcement',
            ],
            notes="Facilities departments have public staff pages; the "
                  "university architect is a useful gateway contact.",
        ),

        "childcare_camp": SegmentPlay(
            segment_id="childcare_camp",
            ranked_roles=[
                "owner", "center_director", "operations_director",
                "facilities_leadership",
            ],
            sales_rationale=(
                "Buildout or expansion of a childcare facility -- often has "
                "specific code/safety requirements, a recurring niche for a GC "
                "that specializes in it."
            ),
            search_tactics=[
                '"{company}" owner OR director "{city}"',
                'parent brand of "{company}"',
                '"{company}" linkedin "{city}"',
            ],
            notes="Check for a franchise/corporate parent before assuming "
                  "independent ownership.",
        ),

        "hospitality_hotel": SegmentPlay(
            segment_id="hospitality_hotel",
            ranked_roles=[
                "owner", "general_manager", "engineering_director",
                "asset_manager", "operations_director",
                "capital_projects_director",
            ],
            sales_rationale=(
                "Renovations (property improvement plans), expansions, "
                "restaurant additions. Decision authority depends on ownership "
                "structure."
            ),
            search_tactics=[
                '"{hotel}" "general manager" OR "director of engineering"',
                'owner of "{hotel}"',
                'county tax records "{hotel address}"',
                '"{brand}" property improvement plan',
            ],
            notes="Branded hotels are usually franchised; county tax/property "
                  "records identify the actual ownership entity.",
        ),

        "campground_rv": SegmentPlay(
            segment_id="campground_rv",
            ranked_roles=["owner", "property_manager", "operations_director"],
            sales_rationale=(
                "Site development, cabin/structure construction, amenity "
                "building construction."
            ),
            search_tactics=[
                '"{company}" owner "{city}"',
                'parent brand of "{company}"',
            ],
            notes="Lower priority; many independently owned, chains have "
                  "centralized development teams.",
        ),

        "commercial_property": SegmentPlay(
            segment_id="commercial_property",
            ranked_roles=[
                "property_manager", "asset_manager",
                "property_management_director", "construction_director",
                "leasing_director", "owner",
            ],
            sales_rationale=(
                "Tenant improvements, common area renovations, capital "
                "improvements. Decision-maker is the property owner or property "
                "manager, NOT the listed tenant."
            ),
            search_tactics=[
                'county tax records "{address}" owner',
                'commercial property "{address}" management company',
                '"{property name}" property manager',
                '"{owner LLC}" principal OR manager',
            ],
            notes="Identify owner via county tax records, then the (often "
                  "separate) management company, then the contact.",
        ),

        "government_municipal": SegmentPlay(
            segment_id="government_municipal",
            ranked_roles=[
                "public_works_director", "facilities_leadership",
                "capital_projects_director", "city_manager", "county_manager",
                "procurement_officer",
            ],
            sales_rationale=(
                "Public buildings, infrastructure-adjacent buildings, "
                "renovations. Public procurement rules apply."
            ),
            search_tactics=[
                'site:{gov_domain} "public works" director',
                'site:{gov_domain} "facilities" OR "general services"',
                'site:{gov_domain} procurement',
                '"{municipality}" capital improvement plan',
                '"{municipality}" SPLOST projects',
            ],
            notes="Org structures are public; CIPs identify upcoming projects "
                  "with responsible departments.",
        ),

        "religious_nonprofit": SegmentPlay(
            segment_id="religious_nonprofit",
            ranked_roles=[
                "executive_pastor", "administrator", "operations_director",
                "executive_director", "facilities_leadership",
                "building_committee_chair",
            ],
            sales_rationale=(
                "Expansion, renovation, new sanctuary or facility "
                "construction. Often capital campaign driven."
            ),
            search_tactics=[
                'site:{domain} staff OR leadership',
                '"{organization}" "executive pastor" OR "business administrator"',
                '"{organization}" capital campaign OR building campaign',
                '"{organization}" expansion announcement',
            ],
            notes="Staff pages usually published; building committee chair is "
                  "often a lay leader with decision experience.",
        ),

        "auto_dealership": SegmentPlay(
            segment_id="auto_dealership",
            ranked_roles=[
                "dealer_principal", "general_manager", "owner",
                "real_estate_director",
            ],
            sales_rationale=(
                "OEM-driven facility upgrades, expansions, new dealership "
                "construction. Often part of dealer groups."
            ),
            search_tactics=[
                '"{dealership}" "dealer principal" OR owner',
                'parent dealer group of "{dealership}"',
                '"{dealer group}" "director of real estate" OR "facilities"',
                '"{OEM}" facility image program',
            ],
            notes="OEM 'facility image programs' force renovations on "
                  "schedules -- useful timing intelligence.",
        ),

        "auto_service": SegmentPlay(
            segment_id="auto_service",
            ranked_roles=[
                "owner", "franchisee", "regional_manager",
                "facilities_leadership",
            ],
            sales_rationale=(
                "Small-format buildouts and remodels. Often franchised or part "
                "of a regional chain."
            ),
            search_tactics=[
                '"{company}" owner OR franchisee "{city}"',
                'parent brand of "{company}"',
            ],
            notes="Frequently owned by multi-unit franchisees or fuel "
                  "distributors, not the visible brand.",
        ),

        "fitness_recreation": SegmentPlay(
            segment_id="fitness_recreation",
            ranked_roles=[
                "owner", "franchisee", "construction_director",
                "development_director", "general_manager",
            ],
            sales_rationale=(
                "Buildouts for new locations, expansion, remodel, new athletic "
                "facilities."
            ),
            search_tactics=[
                '"{company}" franchisee OR owner',
                'parent brand of "{company}"',
                '"{parent brand}" "director of construction" OR development',
            ],
            notes="Many franchised; large venues skew toward capital-projects "
                  "/ operations leadership.",
        ),

        "entertainment_venue": SegmentPlay(
            segment_id="entertainment_venue",
            ranked_roles=[
                "facilities_leadership", "operations_director",
                "general_manager", "executive_director",
                "capital_projects_director", "venue_manager",
            ],
            sales_rationale=(
                "New construction, renovation, expansion of entertainment and "
                "cultural facilities. Often involves specialized buildout and "
                "may be nonprofit or municipally affiliated."
            ),
            search_tactics=[
                'site:{domain} staff OR leadership OR "about"',
                '"{company}" "director of facilities" OR "director of operations"',
                '"{company}" expansion OR renovation announcement',
                '"{company}" capital campaign',
            ],
            notes="Nonprofit-affiliated venues publish board/staff pages; "
                  "capital campaigns name leadership.",
        ),

        "self_storage": SegmentPlay(
            segment_id="self_storage",
            ranked_roles=[
                "owner", "construction_director", "development_director",
                "real_estate_director", "regional_manager",
            ],
            sales_rationale=(
                "New facility construction, expansion, climate-control "
                "additions."
            ),
            search_tactics=[
                'corporate parent of "{company}"',
                '"{company}" "director of development" OR "construction"',
                'county tax records "{address}" owner',
            ],
            notes="Consolidating industry; many local facilities owned by "
                  "regional/national operators with centralized development.",
        ),
    },
)

# The GC intentionally does NOT cover trade_contractor: specialty and general
# contractors are peers and non-buyers for a GC's services. The segment still
# exists (other searchers -- e.g. an accountant -- target it); this profile
# simply omits it, which validate_profile treats as a legitimate skip rather
# than an error.
SKIPPED_SEGMENTS = ["trade_contractor"]


if __name__ == "__main__":
    # Runnable demo:  python -m searcher_profiles.gc   (from searcher_refactor/)
    from target_segments import SEGMENTS
    from searcher_profiles.base import effective_play, validate_profile

    report = validate_profile(GC_PROFILE, SEGMENTS)
    print(f"GC profile covers {len(GC_PROFILE.plays)} segments; valid: {report.ok}")
    if not report.ok:
        print("  subset_violations:", report.subset_violations)
        print("  unknown_keys:", report.unknown_keys)
        print("  unknown_segments:", report.unknown_segments)

    play = effective_play(GC_PROFILE, "government_municipal")
    print("\nEffective play: gc x government_municipal")
    for i, rr in enumerate(play.roles, 1):
        print(f"  {i}. {rr.role.display}  (key={rr.role.key})")
