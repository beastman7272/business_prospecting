"""
Canonical role catalog -- SEARCHER-AGNOSTIC.

The single source of truth for "what roles exist at all." Both target-segment
role inventories and searcher profiles reference roles by their stable ``key``;
they never repeat the display string. This is what makes subset-only selection
enforceable and kills the query/ranking drift that free-text role strings cause
(e.g. "Facilities Director" vs "Director of Facilities" producing two different
quoted search queries and two different keyword-overlap scores).

Design rules:
  * ``key`` is the coarse, stable identity. Keep it coarse on purpose so trivial
    title variants collapse onto ONE key instead of spawning new ones. Several
    facilities/real-estate/finance titles that appeared as separate strings in
    the old per-segment lists collapse here (see facilities_leadership).
  * ``display`` is the primary human/search label.
  * ``search_aliases`` are the other title strings worth searching/matching for
    the same underlying role. Query generation can OR these together instead of
    firing one query per hand-written variant.

This catalog is the full migration of every role string that appeared across the
22 segments in gc_target_segments.py, de-duplicated onto coarse keys, plus a few
back-office roles (controller, bookkeeper, HR, IT, counsel) added so that
inventories are genuinely COMPLETE -- i.e. list who exists at a business, not
just who a general contractor happens to target.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    key: str                         # canonical, stable identity
    display: str                     # primary label used for search + prompts
    search_aliases: tuple[str, ...] = ()   # additional title strings, same role


def _r(key: str, display: str, *aliases: str) -> Role:
    return Role(key=key, display=display, search_aliases=tuple(aliases))


ROLES: dict[str, Role] = {r.key: r for r in [

    # --- Ownership / executive ---
    _r("owner", "Owner", "Proprietor", "Owner / Principal", "Principal", "Operator", "Founder", "Co-Founder",
       "Broker", "Managing Broker", "Principal Broker", "Broker/Owner",
       "Funeral Director", "Mortician", "Innkeeper"),
    _r("founder", "Founder", "Co-Founder"),
    _r("president", "President", "Chancellor"),
    _r("ceo", "Chief Executive Officer", "CEO"),
    _r("coo", "Chief Operating Officer", "COO", "Chief Operations Officer"),
    _r("cfo", "Chief Financial Officer", "CFO",
       "VP of Finance and Administration", "VP of Finance"),
    _r("general_manager", "General Manager", "GM"),
    _r("managing_partner", "Managing Partner"),
    _r("managing_director", "Managing Director"),
    _r("executive_director", "Executive Director", "Curator"),
    _r("operating_partner", "Operating Partner"),
    _r("chief_administrative_officer", "Chief Administrative Officer", "CAO"),
    _r("administrator", "Administrator", "Business Administrator"),
    _r("regional_manager", "Regional Manager"),
    _r("dealer_principal", "Dealer Principal"),
    _r("franchisee", "Franchisee"),

    # --- Office / operations / venue ---
    _r("office_manager", "Office Manager"),
    _r("operations_director",
       "Director of Operations", "Operations Director", "VP of Operations"),
    _r("studio_manager", "Studio Manager"),
    _r("venue_manager", "Venue Manager"),
    _r("center_director", "Director", "Center Director", "Camp Director"),

    # --- Facilities / engineering / construction / real estate ---
    # Coarse key: absorbs facilities-leadership titles across sectors
    # (buildings & grounds in K-12, general services in government, workplace
    #  experience in corporate, regional facilities in retail).
    _r("facilities_leadership",
       "Director of Facilities",
       "VP of Facilities", "Facilities Director", "Facilities Manager",
       "Chief Facilities Officer", "Director of Facilities Management",
       "Director of Buildings and Grounds", "Director of General Services",
       "Director of Workplace Experience", "Regional Facilities Manager"),
    _r("plant_operations_director",
       "Director of Plant Operations", "Plant Operations Director"),
    _r("plant_manager", "Plant Manager"),
    _r("engineering_director", "Director of Engineering", "Chief Engineer"),
    _r("ehs_manager", "EHS Manager",
       "Environmental Health and Safety Manager"),
    _r("construction_director",
       "Director of Construction", "Director of Design and Construction",
       "Construction Manager", "Director of Planning, Design and Construction"),
    _r("development_director",
       "Director of Development", "Director of Store Development",
       "VP of Development"),
    _r("capital_projects_director",
       "Director of Capital Projects", "Capital Projects Director"),
    _r("real_estate_director",
       "VP of Real Estate", "Director of Corporate Real Estate",
       "Director of Real Estate", "VP of Real Estate and Construction"),
    _r("university_architect", "University Architect"),
    _r("public_works_director", "Director of Public Works"),
    _r("vp_manufacturing", "VP of Manufacturing"),

    # --- Property management ---
    _r("property_manager", "Property Manager"),
    _r("asset_manager", "Asset Manager", "VP of Asset Management"),
    _r("property_management_director", "Director of Property Management"),
    _r("leasing_director", "Leasing Director"),

    # --- Finance / back-office (completeness: exist widely; GC ignores) ---
    _r("controller", "Controller", "Comptroller"),
    _r("bookkeeper", "Bookkeeper"),
    _r("billing_manager", "Billing Manager", "Director of Billing"),
    _r("hr_director", "Director of Human Resources", "HR Director", "VP of People"),
    _r("it_director", "Director of IT", "IT Director", "CIO"),
    _r("general_counsel", "General Counsel", "In-House Counsel"),

    # --- Healthcare ---
    _r("practice_manager", "Practice Manager", "Practice Administrator"),
    _r("managing_physician", "Managing Physician", "Managing Doctor",
       "Physician", "Doctor", "Dentist", "DDS", "DMD", "Chiropractor",
       "Veterinarian", "DVM", "Optometrist", "Podiatrist", "Physical Therapist",
       "MD", "DO", "DC", "OD", "DPT", "Orthodontist", "Dermatologist", "Pediatrician"),

    # --- Public sector / education / religious ---
    _r("superintendent", "Superintendent",
       "Principal", "Assistant Principal", "Head of School", "Headmaster"),
    _r("city_manager", "City Manager", "Mayor"),
    _r("county_manager", "County Manager"),
    _r("procurement_officer", "Procurement Officer", "Director of Procurement",
       "Purchasing Manager", "Director of Purchasing", "VP of Procurement",
       "Chief Procurement Officer", "Strategic Sourcing Manager", "Category Manager"),
    _r("executive_pastor", "Executive Pastor",
       "Senior Pastor", "Lead Pastor", "Pastor", "Rabbi", "Imam",
       "Minister", "Priest", "Rector", "Reverend", "Clergy"),
    _r("building_committee_chair", "Building Committee Chair"),

    # --- Trade / construction firms (specialty & general contractors) ---
    _r("project_manager", "Project Manager"),
    _r("estimator", "Estimator"),

    # --- Front-of-house / specialist functions (added as the searcher base
    #     widened beyond facilities/finance/legal to marketing, sales, HR,
    #     tech, customer success, and exec support) ---
    _r("marketing_director", "Director of Marketing",
       "VP of Marketing", "Marketing Director", "Chief Marketing Officer", "CMO",
       "Marketing Manager", "Head of Marketing", "Brand Manager"),
    _r("communications_director", "Director of Communications",
       "Communications Manager", "PR Manager", "Public Relations Manager",
       "Head of Communications", "Director of Public Relations"),
    _r("sales_director", "VP of Sales",
       "Director of Sales", "Sales Director", "Chief Revenue Officer", "CRO",
       "Head of Sales", "Business Development Director", "Sales Manager"),
    _r("talent_acquisition", "Director of Talent Acquisition",
       "Recruiter", "Head of Recruiting", "Talent Acquisition Manager",
       "HR Manager", "Recruiting Manager"),
    _r("cto", "Chief Technology Officer", "CTO",
       "VP of Engineering", "Head of Engineering", "VP of Technology"),
    _r("customer_success_director", "VP of Customer Success",
       "Director of Customer Success", "Head of Support",
       "Customer Success Manager", "Director of Customer Experience",
       "Service Manager"),
    _r("executive_assistant", "Executive Assistant",
       "Chief of Staff", "EA to the CEO", "Executive Administrative Assistant"),
]}


def role(key: str) -> Role:
    """Resolve a role key to its Role, or raise KeyError with a clear message."""
    try:
        return ROLES[key]
    except KeyError:
        raise KeyError(
            f"Unknown role key {key!r}. Add it to roles.ROLES before "
            f"referencing it from a segment inventory or searcher profile."
        )


def known_key(key: str) -> bool:
    return key in ROLES


def search_terms(key: str) -> list[str]:
    """Display + aliases, for query generation / LLM prompt hints."""
    r = role(key)
    return [r.display, *r.search_aliases]
