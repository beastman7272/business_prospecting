"""
Target business segments -- SEARCHER-AGNOSTIC.

A segment classifies the business you are prospecting *to*. After the split, a
segment carries only:

  * ``description``   -- a NEUTRAL description of what this kind of business is.
                         No sales pitch. (The old ``sales_rationale`` was the
                         GC's pitch and now lives on the searcher profile.)
  * ``role_inventory``-- the COMPLETE cast of roles that plausibly exist at this
                         kind of business, as role keys from roles.py. Ordering
                         here is NOT priority -- priority is imposed per searcher
                         by the profile. Completeness is the goal: if a role
                         exists at the business, list it, even if a general
                         contractor never cares about it. That is what lets a
                         different searcher (accountant, attorney) select
                         finance/legal roles the GC ignores, without inventing
                         new role strings.

Removed from the old TargetSegment: ``sales_rationale``, ``search_tactics``, and
``target_roles`` -- all three were searcher-specific and now live on the
SearcherProfile (see searcher_profiles/gc.py for the GC's migrated content).

Google Places type classification (PLACES_TYPE_TO_SEGMENT, the Food/Shopping
rules, EXCLUDED_TYPES, ALL_PLACES_TYPES, the completeness check) is also
searcher-agnostic but is a separate concern -- it lives in places_mapping.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TargetSegment:
    segment_id: str
    description: str                          # neutral: what this business IS
    role_inventory: list[str] = field(default_factory=list)   # role keys
    notes: str = ""


SEGMENTS: dict[str, TargetSegment] = {

    "professional_services_office": TargetSegment(
        segment_id="professional_services_office",
        description=(
            "Office-based professional services and membership organizations "
            "(law, accounting, insurance, real estate brokerage, consulting, "
            "financial, travel agencies, nonprofits/associations, employment "
            "agencies, telecom service providers)."
        ),
        role_inventory=[
            "owner", "president", "managing_partner", "managing_director",
            "coo", "operations_director", "office_manager",
            "executive_director", "administrator",
            "cfo", "controller", "bookkeeper", "billing_manager",
            "general_counsel", "hr_director", "it_director",
            "facilities_leadership",
        ],
        notes=(
            "Small firms collapse many of these onto the owner/managing "
            "partner; larger regional firms staff them separately."
        ),
    ),

    "corporate_office": TargetSegment(
        segment_id="corporate_office",
        description=(
            "Corporate headquarters or regional offices (Places type: "
            "corporate_office). Larger, often multi-department operations, "
            "distinct from small professional-services offices."
        ),
        role_inventory=[
            "real_estate_director", "facilities_leadership",
            "capital_projects_director", "construction_director",
            "chief_administrative_officer", "coo", "cfo",
            "operations_director", "office_manager",
            "hr_director", "it_director", "general_counsel",
        ],
        notes=(
            "A small business mis-tagged corporate_office by Places may really "
            "be a small office; treat the larger-company roles accordingly."
        ),
    ),

    "manufacturing_industrial": TargetSegment(
        segment_id="manufacturing_industrial",
        description=(
            "Manufacturers, industrial suppliers, and companies operating "
            "warehouse/distribution facilities (Places types: manufacturer, "
            "supplier, moving_company)."
        ),
        role_inventory=[
            "owner", "general_manager", "coo",
            "plant_manager", "operations_director", "vp_manufacturing",
            "facilities_leadership", "ehs_manager", "capital_projects_director",
            "cfo", "controller", "hr_director", "it_director", "general_counsel",
        ],
        notes="Plant managers are often quoted in local press for expansions.",
    ),

    "trade_services_small_business": TargetSegment(
        segment_id="trade_services_small_business",
        description=(
            "Small owner-operated service businesses with a physical location: "
            "funeral homes, laundries, tailors, catering, cemeteries, pet "
            "boarding/care, shipping-service storefronts, and similar."
        ),
        role_inventory=[
            "owner", "founder", "general_manager", "office_manager", "bookkeeper",
        ],
        notes="Catch-all for small owner-operated businesses; roles are simple.",
    ),

    "wellness_studio": TargetSegment(
        segment_id="wellness_studio",
        description=(
            "Spas, salons, barbershops, wellness centers, yoga studios, "
            "massage, skin care, and personal-care businesses."
        ),
        role_inventory=[
            "owner", "franchisee", "studio_manager", "general_manager",
            "operations_director", "development_director",
            "facilities_leadership", "bookkeeper",
        ],
        notes="Check for a franchise/parent brand before assuming independent.",
    ),

    "retail_chain_location": TargetSegment(
        segment_id="retail_chain_location",
        description=(
            "Individual locations of multi-location retail, restaurant, or "
            "grocery chains. Most decisions are made at corporate, not the "
            "individual location."
        ),
        role_inventory=[
            "construction_director", "development_director",
            "real_estate_director", "facilities_leadership",
            "capital_projects_director", "operations_director", "coo",
        ],
        notes="Identify the corporate parent first; the local store manager "
              "rarely decides.",
    ),

    "independent_small_business": TargetSegment(
        segment_id="independent_small_business",
        description=(
            "Single-location or small-chain retail and restaurants with no "
            "identifiable corporate parent."
        ),
        role_inventory=[
            "owner", "founder", "president", "general_manager",
            "operating_partner", "office_manager", "bookkeeper",
        ],
        notes="State business filings and local press profiles are reliable "
              "ownership sources.",
    ),

    "healthcare_hospital": TargetSegment(
        segment_id="healthcare_hospital",
        description=(
            "Hospitals and medical centers (Places types: hospital, "
            "general_hospital, medical_center). Large, multi-department "
            "institutions with long capital-project cycles."
        ),
        role_inventory=[
            "ceo", "coo", "cfo",
            "plant_operations_director", "facilities_leadership",
            "construction_director", "capital_projects_director",
            "real_estate_director",
            "hr_director", "it_director", "general_counsel",
        ],
        notes="Hospital systems publish leadership directories; ASHE lists help.",
    ),

    "healthcare_practice": TargetSegment(
        segment_id="healthcare_practice",
        description=(
            "Physician practices, chiropractors, dentists, dental/medical "
            "clinics, physiotherapists, medical labs, veterinary practices."
        ),
        role_inventory=[
            "owner", "managing_physician", "ceo",
            "practice_manager", "office_manager", "operations_director",
            "facilities_leadership", "bookkeeper",
        ],
        notes="Owner is usually a clinician; daily operations (incl. "
              "facilities) are delegated to a practice manager.",
    ),

    "education_k12": TargetSegment(
        segment_id="education_k12",
        description=(
            "K-12 schools (Places types: school, primary_school, "
            "secondary_school). Public districts usually follow public "
            "bidding."
        ),
        role_inventory=[
            "superintendent", "coo", "cfo",
            "facilities_leadership", "operations_director",
            "capital_projects_director", "construction_director",
            "administrator", "procurement_officer",
        ],
        notes="Public districts publish staff directories and board minutes; "
              "SPLOST/bond programs drive most funding in Georgia.",
    ),

    "education_higher": TargetSegment(
        segment_id="education_higher",
        description=(
            "Universities and higher-ed/research institutions (Places types: "
            "university, academic_department, educational_institution, "
            "research_institute)."
        ),
        role_inventory=[
            "cfo", "facilities_leadership", "operations_director",
            "capital_projects_director", "construction_director",
            "university_architect", "real_estate_director",
            "procurement_officer",
        ],
        notes="Facilities departments have public staff pages; the university "
              "architect is a useful gateway contact.",
    ),

    "childcare_camp": TargetSegment(
        segment_id="childcare_camp",
        description=(
            "Daycare/childcare centers and camps (Places types: preschool, "
            "child_care_agency, summer_camp_organizer, childrens_camp)."
        ),
        role_inventory=[
            "owner", "franchisee", "center_director", "operations_director",
            "development_director", "facilities_leadership", "bookkeeper",
        ],
        notes="Many childcare chains are franchised or corporate-run; check "
              "for a parent before assuming independent ownership.",
    ),

    "hospitality_hotel": TargetSegment(
        segment_id="hospitality_hotel",
        description=(
            "Hotels, motels, resorts, inns, bed & breakfasts, extended-stay "
            "properties."
        ),
        role_inventory=[
            "owner", "franchisee", "general_manager", "engineering_director",
            "asset_manager", "operations_director", "capital_projects_director",
            "property_manager", "real_estate_director", "controller",
        ],
        notes="Branded hotels are usually franchised; the franchisee owner "
              "makes capital decisions, not the brand.",
    ),

    "campground_rv": TargetSegment(
        segment_id="campground_rv",
        description=(
            "Campgrounds, RV parks, mobile home parks (Places types: "
            "campground, rv_park, mobile_home_park, camping_cabin)."
        ),
        role_inventory=[
            "owner", "general_manager", "property_manager",
            "operations_director", "development_director",
        ],
        notes="Many are independently owned; chains (KOA, etc.) have "
              "centralized development teams.",
    ),

    "commercial_property": TargetSegment(
        segment_id="commercial_property",
        description=(
            "Multi-tenant office buildings, shopping centers, multifamily "
            "housing, coworking/business centers, and marinas. The decision "
            "sits with the property owner or manager, NOT the listed tenant."
        ),
        role_inventory=[
            "owner", "property_manager", "asset_manager",
            "property_management_director", "construction_director",
            "capital_projects_director", "leasing_director",
            "operations_director",
        ],
        notes="Identify the owner via county tax records, then the (often "
              "separate) property management company, then the contact.",
    ),

    "government_municipal": TargetSegment(
        segment_id="government_municipal",
        description=(
            "Government offices, public safety, and public facilities (Places "
            "types: city_hall, courthouse, embassy, fire_station, "
            "government_office, local_government_office, police, post_office, "
            "library, tourist_information_center). Public procurement applies."
        ),
        role_inventory=[
            "city_manager", "county_manager", "public_works_director",
            "facilities_leadership", "capital_projects_director",
            "construction_director", "procurement_officer",
            "operations_director",
        ],
        notes="Org structures are public; procurement contacts are legally "
              "required to be available; CIPs identify upcoming projects.",
    ),

    "religious_nonprofit": TargetSegment(
        segment_id="religious_nonprofit",
        description=(
            "Churches, mosques, synagogues, temples, shrines, and other "
            "places of worship."
        ),
        role_inventory=[
            "executive_pastor", "executive_director", "administrator",
            "operations_director", "facilities_leadership",
            "building_committee_chair", "bookkeeper",
        ],
        notes="Staff pages are usually published; building committees are "
              "common for capital projects and the chair is often a lay leader.",
    ),

    "auto_dealership": TargetSegment(
        segment_id="auto_dealership",
        description=(
            "Car and truck dealerships (Places types: car_dealer, "
            "truck_dealer). Often part of dealer groups."
        ),
        role_inventory=[
            "owner", "dealer_principal", "general_manager",
            "real_estate_director", "facilities_leadership",
            "construction_director", "cfo",
        ],
        notes="OEM 'facility image programs' force dealership renovations on "
              "schedules -- useful timing intelligence.",
    ),

    "auto_service": TargetSegment(
        segment_id="auto_service",
        description=(
            "Car repair, car wash, gas stations, EV/e-bike charging, car "
            "rental, tire shops, rest stops. Often franchised or part of a "
            "regional chain."
        ),
        role_inventory=[
            "owner", "franchisee", "general_manager", "regional_manager",
            "development_director", "facilities_leadership",
        ],
        notes="Gas stations and car washes are frequently owned by multi-unit "
              "franchisees or fuel distributors, not the visible brand.",
    ),

    "fitness_recreation": TargetSegment(
        segment_id="fitness_recreation",
        description=(
            "Gyms, fitness centers, sports clubs/complexes, pools, golf "
            "courses, ice rinks, arenas, stadiums, ski resorts, race courses, "
            "tennis courts, sports schools and coaching facilities."
        ),
        role_inventory=[
            "owner", "franchisee", "general_manager", "construction_director",
            "development_director", "capital_projects_director",
            "operations_director", "facilities_leadership",
        ],
        notes="Many are franchised; large venues skew toward capital-projects "
              "/ operations leadership rather than an owner-operator.",
    ),

    "entertainment_venue": TargetSegment(
        segment_id="entertainment_venue",
        description=(
            "Movie theaters, museums/galleries, event/wedding venues, "
            "convention/community centers, performing-arts venues, "
            "amusement/water parks, aquariums, zoos, bowling alleys, casinos, "
            "nightlife, arcades, vineyards, and television studios."
        ),
        role_inventory=[
            "owner", "executive_director", "general_manager", "venue_manager",
            "operations_director", "facilities_leadership",
            "construction_director", "capital_projects_director",
        ],
        notes="Nonprofit-affiliated venues publish board/staff pages; capital "
              "campaigns are usually publicized with named leadership.",
    ),

    "self_storage": TargetSegment(
        segment_id="self_storage",
        description="Self-storage facilities (Places type: storage).",
        role_inventory=[
            "owner", "construction_director", "development_director",
            "real_estate_director", "regional_manager",
            "facilities_leadership", "operations_director",
        ],
        notes="Consolidating industry; many local facilities are owned by "
              "regional/national operators with centralized development teams.",
    ),

    "trade_contractor": TargetSegment(
        segment_id="trade_contractor",
        description=(
            "Specialty trade and construction contractors -- electricians, "
            "plumbers, painters, roofers, locksmiths -- and general "
            "contractors. Owner-operated to mid-size field-service businesses. "
            "(A general contractor treats these as peers/subs, not buyers, and "
            "its profile skips this segment; other searchers -- accounting, "
            "insurance, software, marketing -- actively target them.)"
        ),
        role_inventory=[
            "owner", "president", "general_manager", "operations_director",
            "project_manager", "estimator", "office_manager",
            "bookkeeper", "controller",
        ],
        notes="Reclassified out of the GC-era EXCLUDED_TYPES: these are real "
              "businesses with contacts, excluded only because the first "
              "profile (GC) didn't sell to them.",
    ),
}


# -----------------------------------------------------------------------------
# Front-of-house / specialist function roles, added as the searcher base widened
# beyond the original facilities/finance/legal profiles. Placed into segments
# where each function plausibly exists (not tiny owner-operated shops). Kept as a
# declarative augmentation so the additions are visible as one group.
# -----------------------------------------------------------------------------
_FUNCTION_ADDITIONS: dict[str, list[str]] = {
    "professional_services_office": ["marketing_director", "communications_director", "sales_director", "talent_acquisition", "customer_success_director", "executive_assistant"],
    "corporate_office": ["marketing_director", "communications_director", "sales_director", "talent_acquisition", "cto", "customer_success_director", "executive_assistant"],
    "manufacturing_industrial": ["marketing_director", "sales_director", "talent_acquisition", "cto", "executive_assistant"],
    "retail_chain_location": ["marketing_director", "sales_director", "talent_acquisition", "customer_success_director"],
    "healthcare_hospital": ["marketing_director", "communications_director", "talent_acquisition", "cto", "executive_assistant"],
    "education_higher": ["marketing_director", "communications_director", "talent_acquisition", "cto", "executive_assistant"],
    "hospitality_hotel": ["marketing_director", "sales_director", "talent_acquisition", "executive_assistant"],
    "entertainment_venue": ["marketing_director", "communications_director", "executive_assistant"],
    "fitness_recreation": ["marketing_director"],
    "auto_dealership": ["marketing_director", "sales_director"],
    "government_municipal": ["communications_director", "executive_assistant"],
    "religious_nonprofit": ["communications_director"],
}
for _sid, _new_roles in _FUNCTION_ADDITIONS.items():
    _inv = SEGMENTS[_sid].role_inventory
    for _rk in _new_roles:
        if _rk not in _inv:
            _inv.append(_rk)


_EXECUTIVE_ADDITIONS: dict[str, list[str]] = {
    # Basic executive/owner roles the GC-era inventories omitted -- a President
    # at a corporate office or manufacturer, a hospital Administrator, and a
    # university President were scoring 0 and short-circuiting.
    "corporate_office": ["ceo", "president", "owner"],
    "manufacturing_industrial": ["president", "ceo"],
    "healthcare_hospital": ["administrator"],
    "education_higher": ["president"],
}
for _sid, _new_roles in _EXECUTIVE_ADDITIONS.items():
    _inv = SEGMENTS[_sid].role_inventory
    for _rk in _new_roles:
        if _rk not in _inv:
            _inv.append(_rk)


_PROCUREMENT_ADDITIONS: dict[str, list[str]] = {
    # Corporate/enterprise purchasing gatekeeper -- the vendor-approval buyer
    # for print, fulfillment, IT, supplies, etc. (Government/education already
    # list procurement_officer natively.)
    "corporate_office": ["procurement_officer"],
    "manufacturing_industrial": ["procurement_officer"],
    "healthcare_hospital": ["procurement_officer"],
    "retail_chain_location": ["procurement_officer"],
}
for _sid, _new_roles in _PROCUREMENT_ADDITIONS.items():
    _inv = SEGMENTS[_sid].role_inventory
    for _rk in _new_roles:
        if _rk not in _inv:
            _inv.append(_rk)


def get_segment(segment_id: str) -> TargetSegment | None:
    return SEGMENTS.get(segment_id)
