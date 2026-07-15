"""
Google Places type -> target segment classification -- SEARCHER-AGNOSTIC.

Which segment a business belongs to depends only on WHAT the business is, never
on who is prospecting it, so this whole apparatus is shared across all searcher
profiles. Migrated unchanged from gc_target_segments.py except that it now
references segment ids in target_segments.SEGMENTS.

DESIGN PRINCIPLE: every type in ALL_PLACES_TYPES must end up either in
PLACES_TYPE_TO_SEGMENT (mapped to a segment) or in EXCLUDED_TYPES (with a
documented reason). Run this file directly to verify.
"""

from __future__ import annotations

from target_segments import TargetSegment, SEGMENTS


# -----------------------------------------------------------------------------
# Food and Drink -- rule-based mapping (defaults to chain-vs-independent pair)
# -----------------------------------------------------------------------------

FOOD_AND_DRINK_TYPES = [
    "acai_shop", "afghani_restaurant", "african_restaurant",
    "american_restaurant", "argentinian_restaurant", "asian_fusion_restaurant",
    "asian_restaurant", "australian_restaurant", "austrian_restaurant",
    "bagel_shop", "bakery", "bangladeshi_restaurant", "bar", "bar_and_grill",
    "barbecue_restaurant", "basque_restaurant", "bavarian_restaurant",
    "beer_garden", "belgian_restaurant", "bistro", "brazilian_restaurant",
    "breakfast_restaurant", "brewery", "brewpub", "british_restaurant",
    "brunch_restaurant", "buffet_restaurant", "burmese_restaurant",
    "burrito_restaurant", "cafe", "cafeteria", "cajun_restaurant",
    "cake_shop", "californian_restaurant", "cambodian_restaurant",
    "candy_store", "cantonese_restaurant", "caribbean_restaurant",
    "cat_cafe", "chicken_restaurant", "chicken_wings_restaurant",
    "chilean_restaurant", "chinese_noodle_restaurant", "chinese_restaurant",
    "chocolate_factory", "chocolate_shop", "cocktail_bar",
    "coffee_roastery", "coffee_shop", "coffee_stand", "colombian_restaurant",
    "confectionery", "croatian_restaurant", "cuban_restaurant",
    "czech_restaurant", "danish_restaurant", "deli", "dessert_restaurant",
    "dessert_shop", "dim_sum_restaurant", "diner", "dog_cafe",
    "donut_shop", "dumpling_restaurant", "dutch_restaurant",
    "eastern_european_restaurant", "ethiopian_restaurant",
    "european_restaurant", "falafel_restaurant", "family_restaurant",
    "fast_food_restaurant", "filipino_restaurant", "fine_dining_restaurant",
    "fish_and_chips_restaurant", "fondue_restaurant", "food_court",
    "french_restaurant", "fusion_restaurant", "gastropub",
    "german_restaurant", "greek_restaurant", "gyro_restaurant",
    "halal_restaurant", "hamburger_restaurant", "hawaiian_restaurant",
    "hookah_bar", "hot_dog_restaurant", "hot_dog_stand", "hot_pot_restaurant",
    "hungarian_restaurant", "ice_cream_shop", "indian_restaurant",
    "indonesian_restaurant", "irish_pub", "irish_restaurant",
    "israeli_restaurant", "italian_restaurant", "japanese_curry_restaurant",
    "japanese_izakaya_restaurant", "japanese_restaurant", "juice_shop",
    "kebab_shop", "korean_barbecue_restaurant", "korean_restaurant",
    "latin_american_restaurant", "lebanese_restaurant", "lounge_bar",
    "malaysian_restaurant", "meal_delivery", "meal_takeaway",
    "mediterranean_restaurant", "mexican_restaurant",
    "middle_eastern_restaurant", "mongolian_barbecue_restaurant",
    "moroccan_restaurant", "noodle_shop", "north_indian_restaurant",
    "oyster_bar_restaurant", "pakistani_restaurant", "pastry_shop",
    "persian_restaurant", "peruvian_restaurant", "pizza_delivery",
    "pizza_restaurant", "polish_restaurant", "portuguese_restaurant", "pub",
    "ramen_restaurant", "restaurant", "romanian_restaurant",
    "russian_restaurant", "salad_shop", "sandwich_shop",
    "scandinavian_restaurant", "seafood_restaurant", "shawarma_restaurant",
    "snack_bar", "soul_food_restaurant", "soup_restaurant",
    "south_american_restaurant", "south_indian_restaurant",
    "southwestern_us_restaurant", "spanish_restaurant", "sports_bar",
    "sri_lankan_restaurant", "steak_house", "sushi_restaurant",
    "swiss_restaurant", "taco_restaurant", "taiwanese_restaurant",
    "tapas_restaurant", "tea_house", "tex_mex_restaurant",
    "thai_restaurant", "tibetan_restaurant", "tonkatsu_restaurant",
    "turkish_restaurant", "ukrainian_restaurant", "vegan_restaurant",
    "vegetarian_restaurant", "vietnamese_restaurant", "western_restaurant",
    "wine_bar", "winery", "yakiniku_restaurant", "yakitori_restaurant",
    "drugstore", "pharmacy",
]

FOOD_AND_DRINK_OVERRIDES: dict[str, str] = {
    "fast_food_restaurant": "retail_chain_location",   # virtually always chain
    "chocolate_factory": "manufacturing_industrial",   # it's a factory
    "food_court": "commercial_property",               # shared facility
}

# -----------------------------------------------------------------------------
# Shopping -- rule-based mapping
# -----------------------------------------------------------------------------

SHOPPING_TYPES = [
    "asian_grocery_store", "auto_parts_store", "bicycle_store", "book_store",
    "building_materials_store", "butcher_shop", "cell_phone_store",
    "clothing_store", "convenience_store", "cosmetics_store",
    "department_store", "discount_store", "discount_supermarket",
    "electronics_store", "farmers_market", "flea_market", "food_store",
    "furniture_store", "garden_center", "general_store", "gift_shop",
    "grocery_store", "hardware_store", "health_food_store",
    "home_goods_store", "home_improvement_store", "hypermarket",
    "jewelry_store", "liquor_store", "market", "pet_store", "shoe_store",
    "shopping_mall", "sporting_goods_store", "sportswear_store", "store",
    "supermarket", "tea_store", "thrift_store", "toy_store",
    "warehouse_store", "wholesaler", "womens_clothing_store",
]

SHOPPING_OVERRIDES: dict[str, str] = {
    "shopping_mall": "commercial_property",          # the mall itself
    "farmers_market": "independent_small_business",  # organizer/manager
    "flea_market": "independent_small_business",     # organizer/manager
    "general_store": "independent_small_business",   # local by definition
}


# -----------------------------------------------------------------------------
# Explicit mapping -- all other categories
# -----------------------------------------------------------------------------

PLACES_TYPE_TO_SEGMENT: dict[str, str | list[str]] = {

    # --- Automotive ---
    "car_dealer": "auto_dealership",
    "truck_dealer": "auto_dealership",
    "car_rental": "auto_service",
    "car_repair": "auto_service",
    "car_wash": "auto_service",
    "gas_station": "auto_service",
    "electric_vehicle_charging_station": "auto_service",
    "ebike_charging_station": "auto_service",
    "tire_shop": "auto_service",
    "rest_stop": "auto_service",

    # --- Business ---
    "corporate_office": "corporate_office",
    "manufacturer": "manufacturing_industrial",
    "supplier": "manufacturing_industrial",
    "coworking_space": "commercial_property",
    "business_center": "commercial_property",
    "television_studio": "entertainment_venue",

    # --- Culture ---
    "art_gallery": "entertainment_venue",
    "art_museum": "entertainment_venue",
    "art_studio": "entertainment_venue",
    "auditorium": "entertainment_venue",
    "history_museum": "entertainment_venue",
    "museum": "entertainment_venue",
    "performing_arts_theater": "entertainment_venue",

    # --- Education ---
    "school": "education_k12",
    "primary_school": "education_k12",
    "secondary_school": "education_k12",
    "preschool": "childcare_camp",
    "university": "education_higher",
    "academic_department": "education_higher",
    "educational_institution": "education_higher",
    "research_institute": "education_higher",
    "library": "government_municipal",

    # --- Entertainment and Recreation ---
    "amusement_center": "entertainment_venue",
    "amusement_park": "entertainment_venue",
    "aquarium": "entertainment_venue",
    "banquet_hall": "entertainment_venue",
    "botanical_garden": "entertainment_venue",
    "bowling_alley": "entertainment_venue",
    "casino": "entertainment_venue",
    "childrens_camp": "childcare_camp",
    "comedy_club": "entertainment_venue",
    "community_center": "entertainment_venue",
    "concert_hall": "entertainment_venue",
    "convention_center": "entertainment_venue",
    "cultural_center": "entertainment_venue",
    "dance_hall": "entertainment_venue",
    "event_venue": "entertainment_venue",
    "karaoke": "entertainment_venue",
    "movie_theater": "entertainment_venue",
    "night_club": "entertainment_venue",
    "opera_house": "entertainment_venue",
    "paintball_center": "entertainment_venue",
    "philharmonic_hall": "entertainment_venue",
    "planetarium": "entertainment_venue",
    "video_arcade": "entertainment_venue",
    "water_park": "entertainment_venue",
    "wedding_venue": "entertainment_venue",
    "wildlife_park": "entertainment_venue",
    "zoo": "entertainment_venue",
    "go_karting_venue": "entertainment_venue",
    "miniature_golf_course": "entertainment_venue",
    "internet_cafe": "entertainment_venue",
    "live_music_venue": "entertainment_venue",
    "vineyard": "entertainment_venue",
    "movie_rental": "independent_small_business",
    "marina": "commercial_property",
    "adventure_sports_center": "fitness_recreation",
    "cycling_park": "fitness_recreation",

    # --- Finance ---
    "accounting": "professional_services_office",
    "bank": "professional_services_office",

    # --- Government ---
    "city_hall": "government_municipal",
    "courthouse": "government_municipal",
    "embassy": "government_municipal",
    "fire_station": "government_municipal",
    "government_office": "government_municipal",
    "local_government_office": "government_municipal",
    "police": "government_municipal",
    "post_office": "government_municipal",

    # --- Health and Wellness ---
    "chiropractor": "healthcare_practice",
    "dental_clinic": "healthcare_practice",
    "dentist": "healthcare_practice",
    "doctor": "healthcare_practice",
    "medical_clinic": "healthcare_practice",
    "medical_lab": "healthcare_practice",
    "physiotherapist": "healthcare_practice",
    "general_hospital": "healthcare_hospital",
    "hospital": "healthcare_hospital",
    "medical_center": "healthcare_hospital",
    "massage": "wellness_studio",
    "massage_spa": "wellness_studio",
    "sauna": "wellness_studio",
    "skin_care_clinic": "wellness_studio",
    "spa": "wellness_studio",
    "tanning_studio": "wellness_studio",
    "wellness_center": "wellness_studio",
    "yoga_studio": "wellness_studio",

    # --- Housing ---
    "apartment_building": "commercial_property",
    "apartment_complex": "commercial_property",
    "condominium_complex": "commercial_property",
    "housing_complex": "commercial_property",

    # --- Lodging ---
    "bed_and_breakfast": "hospitality_hotel",
    "budget_japanese_inn": "hospitality_hotel",
    "cottage": "hospitality_hotel",
    "extended_stay_hotel": "hospitality_hotel",
    "farmstay": "hospitality_hotel",
    "guest_house": "hospitality_hotel",
    "hostel": "hospitality_hotel",
    "hotel": "hospitality_hotel",
    "inn": "hospitality_hotel",
    "japanese_inn": "hospitality_hotel",
    "lodging": "hospitality_hotel",
    "motel": "hospitality_hotel",
    "private_guest_room": "hospitality_hotel",
    "resort_hotel": "hospitality_hotel",
    "campground": "campground_rv",
    "camping_cabin": "campground_rv",
    "rv_park": "campground_rv",
    "mobile_home_park": "campground_rv",

    # --- Places of Worship ---
    "buddhist_temple": "religious_nonprofit",
    "church": "religious_nonprofit",
    "hindu_temple": "religious_nonprofit",
    "mosque": "religious_nonprofit",
    "shinto_shrine": "religious_nonprofit",
    "synagogue": "religious_nonprofit",

    # --- Services ---
    "association_or_organization": "professional_services_office",
    "consultant": "professional_services_office",
    "courier_service": "professional_services_office",
    "employment_agency": "professional_services_office",
    "insurance_agency": "professional_services_office",
    "lawyer": "professional_services_office",
    "marketing_consultant": "professional_services_office",
    "non_profit_organization": "professional_services_office",
    "real_estate_agency": "professional_services_office",
    "telecommunications_service_provider": "professional_services_office",
    "tour_agency": "professional_services_office",
    "travel_agency": "professional_services_office",
    "barber_shop": "wellness_studio",
    "beautician": "wellness_studio",
    "beauty_salon": "wellness_studio",
    "body_art_service": "wellness_studio",
    "foot_care": "wellness_studio",
    "hair_care": "wellness_studio",
    "hair_salon": "wellness_studio",
    "makeup_artist": "wellness_studio",
    "nail_salon": "wellness_studio",
    "child_care_agency": "childcare_camp",
    "summer_camp_organizer": "childcare_camp",
    "storage": "self_storage",
    "moving_company": "manufacturing_industrial",
    "catering_service": "trade_services_small_business",
    "cemetery": "trade_services_small_business",
    "florist": "independent_small_business",
    "funeral_home": "trade_services_small_business",
    "laundry": "trade_services_small_business",
    "pet_boarding_service": "trade_services_small_business",
    "pet_care": "trade_services_small_business",
    "shipping_service": "trade_services_small_business",
    "tailor": "trade_services_small_business",
    "tourist_information_center": "government_municipal",
    "veterinary_care": "healthcare_practice",

    # --- Sports ---
    "arena": "fitness_recreation",
    "athletic_field": "fitness_recreation",
    "fitness_center": "fitness_recreation",
    "golf_course": "fitness_recreation",
    "gym": "fitness_recreation",
    "ice_skating_rink": "fitness_recreation",
    "indoor_golf_course": "fitness_recreation",
    "race_course": "fitness_recreation",
    "ski_resort": "fitness_recreation",
    "sports_activity_location": "fitness_recreation",
    "sports_club": "fitness_recreation",
    "sports_coaching": "fitness_recreation",
    "sports_complex": "fitness_recreation",
    "sports_school": "fitness_recreation",
    "stadium": "fitness_recreation",
    "swimming_pool": "fitness_recreation",
    "tennis_court": "fitness_recreation",
    "fishing_charter": "trade_services_small_business",

    # --- Trade / construction contractors ---
    # Real businesses with contacts. The GC profile skips this segment (peers
    # and non-buyers), but other searchers (accounting, insurance, software,
    # marketing) target them -- so classification is agnostic, targeting is
    # per-profile. Reclassified out of the old GC-era EXCLUDED_TYPES.
    "electrician": "trade_contractor",
    "plumber": "trade_contractor",
    "painter": "trade_contractor",
    "locksmith": "trade_contractor",
    "roofing_contractor": "trade_contractor",
    "general_contractor": "trade_contractor",
}

# Merge in the rule-based Food and Drink / Shopping mappings
for _type in FOOD_AND_DRINK_TYPES:
    PLACES_TYPE_TO_SEGMENT[_type] = FOOD_AND_DRINK_OVERRIDES.get(
        _type, ["retail_chain_location", "independent_small_business"]
    )
for _type in SHOPPING_TYPES:
    PLACES_TYPE_TO_SEGMENT[_type] = SHOPPING_OVERRIDES.get(
        _type, ["retail_chain_location", "independent_small_business"]
    )


# -----------------------------------------------------------------------------
# Explicitly excluded types, with reasons
# -----------------------------------------------------------------------------

EXCLUDED_TYPES: dict[str, str] = {
    # This dict mixes TWO kinds of exclusion. Most are UNIVERSAL non-targets:
    # not a business, or no contactable entity (parking, natural features,
    # geographic areas, transit infrastructure, landmarks, atm, public
    # bathrooms). A minority, tagged "GC deferral" below, are real businesses
    # excluded only because the first profile (GC) didn't sell to them -- the
    # same GC-era bias that kept subcontractor trades out until they were
    # reclassified into the trade_contractor segment. Reclassify a "GC deferral"
    # into a segment when a searcher profile actually needs it.
    "parking": "not a business with a contact to find",
    "parking_garage": "not a business with a contact to find",
    "parking_lot": "not a business with a contact to find",
    "farm": "GC deferral: agricultural business; revisit per profile",
    "ranch": "GC deferral: agricultural business; revisit per profile",
    "castle": "landmark, not an operating business",
    "cultural_landmark": "landmark, not an operating business",
    "fountain": "public infrastructure/landmark feature",
    "historical_place": "landmark, not an operating business",
    "monument": "landmark, not an operating business",
    "sculpture": "landmark/art object, not an operating business",
    "amphitheatre": "usually a park/venue feature rather than a standalone business",
    "barbecue_area": "public park feature",
    "city_park": "public park, not a business",
    "dog_park": "public park feature",
    "ferris_wheel": "ride component of an amusement park, not standalone",
    "garden": "public park/landmark feature",
    "hiking_area": "public land, not a business",
    "historical_landmark": "landmark, not an operating business",
    "indoor_playground": "usually part of another business; no standalone contact",
    "national_park": "public land, not a business",
    "observation_deck": "usually part of another building, not standalone",
    "off_roading_area": "public/private land feature, not a business with public contacts",
    "picnic_ground": "public park feature",
    "park": "public park, not a business",
    "plaza": "public space, not a business",
    "roller_coaster": "ride component of an amusement park, not standalone",
    "skateboard_park": "usually public/municipal recreation feature",
    "state_park": "public land, not a business",
    "tourist_attraction": "too generic/ambiguous a category to target reliably",
    "visitor_center": "usually government/tourism-run, low prospecting value",
    "wildlife_refuge": "usually nonprofit/government conservation land",
    "public_bath": "public infrastructure, not a realistic GC target",
    "public_bathroom": "public infrastructure, not a business",
    "stable": "GC deferral: agricultural/equestrian business; revisit per profile",
    "atm": "not a business location with staff to contact",
    "administrative_area_level_1": "geographic area, not a business",
    "administrative_area_level_2": "geographic area, not a business",
    "country": "geographic area, not a business",
    "locality": "geographic area, not a business",
    "postal_code": "geographic area, not a business",
    "school_district": "geographic area, not a business (individual schools are mapped)",
    "neighborhood_police_station": "Japan-only type, not relevant",
    "beach": "natural feature, not a business",
    "island": "natural feature, not a business",
    "lake": "natural feature, not a business",
    "mountain_peak": "natural feature, not a business",
    "nature_preserve": "natural feature/conservation land, not a business",
    "river": "natural feature, not a business",
    "scenic_spot": "natural feature/landmark, not a business",
    "woods": "natural feature, not a business",
    # subcontractor trades + general_contractor moved to the trade_contractor
    # segment (real businesses; GC skips, others target).
    "aircraft_rental_service": "GC deferral: niche; a real business -- revisit per profile",
    "astrologer": "GC deferral: solo/tiny, no buildout, but still a business",
    "chauffeur_service": "GC deferral: no fixed facility, but still a business",
    "food_delivery": "GC deferral: delivery-only/virtual, but still a business",
    "psychic": "GC deferral: solo/tiny, no buildout, but still a business",
    "service": "too generic/ambiguous to target reliably (universal)",
    "fishing_pier": "usually public/municipal infrastructure",
    "fishing_pond": "niche, usually not a standalone commercial business",
    "playground": "usually public/municipal or part of a park",
    "airport": "transportation infrastructure, excluded per user direction",
    "airstrip": "transportation infrastructure, excluded per user direction",
    "bike_sharing_station": "transportation infrastructure, excluded per user direction",
    "bridge": "transportation infrastructure, excluded per user direction",
    "bus_station": "transportation infrastructure, excluded per user direction",
    "bus_stop": "transportation infrastructure, excluded per user direction",
    "ferry_service": "transportation infrastructure, excluded per user direction",
    "ferry_terminal": "transportation infrastructure, excluded per user direction",
    "heliport": "transportation infrastructure, excluded per user direction",
    "international_airport": "transportation infrastructure, excluded per user direction",
    "light_rail_station": "transportation infrastructure, excluded per user direction",
    "park_and_ride": "transportation infrastructure, excluded per user direction",
    "subway_station": "transportation infrastructure, excluded per user direction",
    "taxi_service": "transportation infrastructure, excluded per user direction",
    "taxi_stand": "transportation infrastructure, excluded per user direction",
    "toll_station": "transportation infrastructure, excluded per user direction",
    "train_station": "transportation infrastructure, excluded per user direction",
    "train_ticket_office": "transportation infrastructure, excluded per user direction",
    "tram_stop": "transportation infrastructure, excluded per user direction",
    "transit_depot": "transportation infrastructure, excluded per user direction",
    "transit_station": "transportation infrastructure, excluded per user direction",
    "transit_stop": "transportation infrastructure, excluded per user direction",
    "transportation_service": "transportation infrastructure, excluded per user direction",
    "truck_stop": "transportation infrastructure, excluded per user direction",
}


# -----------------------------------------------------------------------------
# Canonical list of every type, for the completeness check
# -----------------------------------------------------------------------------

ALL_PLACES_TYPES = [
    "car_dealer", "car_rental", "car_repair", "car_wash",
    "ebike_charging_station", "electric_vehicle_charging_station",
    "gas_station", "parking", "parking_garage", "parking_lot", "rest_stop",
    "tire_shop", "truck_dealer",
    "business_center", "corporate_office", "coworking_space", "farm",
    "manufacturer", "ranch", "supplier", "television_studio",
    "art_gallery", "art_museum", "art_studio", "auditorium", "castle",
    "cultural_landmark", "fountain", "historical_place", "history_museum",
    "monument", "museum", "performing_arts_theater", "sculpture",
    "academic_department", "educational_institution", "library",
    "preschool", "primary_school", "research_institute", "school",
    "secondary_school", "university",
    "adventure_sports_center", "amphitheatre", "amusement_center",
    "amusement_park", "aquarium", "banquet_hall", "barbecue_area",
    "botanical_garden", "bowling_alley", "casino", "childrens_camp",
    "city_park", "comedy_club", "community_center", "concert_hall",
    "convention_center", "cultural_center", "cycling_park", "dance_hall",
    "dog_park", "event_venue", "ferris_wheel", "garden", "go_karting_venue",
    "hiking_area", "historical_landmark", "indoor_playground",
    "internet_cafe", "karaoke", "live_music_venue", "marina",
    "miniature_golf_course", "movie_rental", "movie_theater",
    "national_park", "night_club", "observation_deck", "off_roading_area",
    "opera_house", "paintball_center", "park", "philharmonic_hall",
    "picnic_ground", "planetarium", "plaza", "roller_coaster",
    "skateboard_park", "state_park", "tourist_attraction", "video_arcade",
    "vineyard", "visitor_center", "water_park", "wedding_venue",
    "wildlife_park", "wildlife_refuge", "zoo",
    "public_bath", "public_bathroom", "stable",
    "accounting", "atm", "bank",
    *FOOD_AND_DRINK_TYPES,
    "administrative_area_level_1", "administrative_area_level_2", "country",
    "locality", "postal_code", "school_district",
    "city_hall", "courthouse", "embassy", "fire_station",
    "government_office", "local_government_office",
    "neighborhood_police_station", "police", "post_office",
    "chiropractor", "dental_clinic", "dentist", "doctor",
    "general_hospital", "hospital", "massage", "massage_spa",
    "medical_center", "medical_clinic", "medical_lab", "physiotherapist",
    "sauna", "skin_care_clinic", "spa", "tanning_studio", "wellness_center",
    "yoga_studio",
    "apartment_building", "apartment_complex", "condominium_complex",
    "housing_complex",
    "bed_and_breakfast", "budget_japanese_inn", "campground",
    "camping_cabin", "cottage", "extended_stay_hotel", "farmstay",
    "guest_house", "hostel", "hotel", "inn", "japanese_inn", "lodging",
    "mobile_home_park", "motel", "private_guest_room", "resort_hotel",
    "rv_park",
    "beach", "island", "lake", "mountain_peak", "nature_preserve", "river",
    "scenic_spot", "woods",
    "buddhist_temple", "church", "hindu_temple", "mosque", "shinto_shrine",
    "synagogue",
    "aircraft_rental_service", "association_or_organization", "astrologer",
    "barber_shop", "beautician", "beauty_salon", "body_art_service",
    "catering_service", "cemetery", "chauffeur_service", "child_care_agency",
    "consultant", "courier_service", "electrician", "employment_agency",
    "florist", "food_delivery", "foot_care", "funeral_home", "hair_care",
    "hair_salon", "insurance_agency", "laundry", "lawyer", "locksmith",
    "makeup_artist", "marketing_consultant", "moving_company", "nail_salon",
    "non_profit_organization", "painter", "pet_boarding_service",
    "pet_care", "plumber", "psychic", "real_estate_agency",
    "roofing_contractor", "service", "shipping_service", "storage",
    "summer_camp_organizer", "tailor", "telecommunications_service_provider",
    "tour_agency", "tourist_information_center", "travel_agency",
    "veterinary_care",
    *SHOPPING_TYPES,
    "arena", "athletic_field", "fishing_charter", "fishing_pier",
    "fishing_pond", "fitness_center", "golf_course", "gym",
    "ice_skating_rink", "indoor_golf_course", "playground", "race_course",
    "ski_resort", "sports_activity_location", "sports_club",
    "sports_coaching", "sports_complex", "sports_school", "stadium",
    "swimming_pool", "tennis_court",
    "airport", "airstrip", "bike_sharing_station", "bridge", "bus_station",
    "bus_stop", "ferry_service", "ferry_terminal", "heliport",
    "international_airport", "light_rail_station", "park_and_ride",
    "subway_station", "taxi_service", "taxi_stand", "toll_station",
    "train_station", "train_ticket_office", "tram_stop", "transit_depot",
    "transit_station", "transit_stop", "transportation_service",
    "truck_stop", "general_contractor",
]

# de-duplicate while preserving order
_seen: set[str] = set()
ALL_PLACES_TYPES = [t for t in ALL_PLACES_TYPES if not (t in _seen or _seen.add(t))]


# -----------------------------------------------------------------------------
# Lookup helpers
# -----------------------------------------------------------------------------

def get_segment_for_places_type(places_type: str) -> list[TargetSegment]:
    """
    Resolve a Google Places type to one or more candidate target segments.
    Length 1 usually; length 2 for ambiguous (chain vs independent) cases.
    Empty list if the type has no mapping (including excluded types).
    """
    normalized = places_type.strip().lower().replace(" ", "_") if places_type else ""
    mapped = PLACES_TYPE_TO_SEGMENT.get(normalized)
    if mapped is None:
        return []
    if isinstance(mapped, str):
        return [SEGMENTS[mapped]]
    return [SEGMENTS[seg_id] for seg_id in mapped]


def check_completeness() -> list[str]:
    """Types in ALL_PLACES_TYPES that are neither mapped nor excluded."""
    return [
        t for t in ALL_PLACES_TYPES
        if t not in PLACES_TYPE_TO_SEGMENT and t not in EXCLUDED_TYPES
    ]


if __name__ == "__main__":
    unaccounted = check_completeness()
    print(f"Total known Places types: {len(ALL_PLACES_TYPES)}")
    print(f"Mapped to a segment: {len(PLACES_TYPE_TO_SEGMENT)}")
    print(f"Explicitly excluded: {len(EXCLUDED_TYPES)}")
    print("All accounted for." if not unaccounted
          else f"UNACCOUNTED ({len(unaccounted)}): {unaccounted}")
