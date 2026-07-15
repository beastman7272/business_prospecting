import json
from models import db, Business, Intel

def get_or_create_business(data: dict) -> Business:
    biz = Business.query.filter_by(place_id=data["place_id"]).one_or_none()
    if not biz:
        biz = Business(place_id=data["place_id"])
        db.session.add(biz)

    biz.name = data.get("name")
    biz.formatted_address = data.get("formatted_address")
    biz.primary_type = data.get("primary_type")
    biz.types = json.dumps(data.get("types") or [])
    biz.website = data.get("website")
    biz.phone = data.get("phone")
    biz.lat = data.get("lat")
    biz.lng = data.get("lng")

    return biz

def save_intel(business: Business, intel_data: dict) -> Intel:
    intel = Intel.query.filter_by(business_id=business.id).one_or_none()
    if not intel:
        intel = Intel(business_id=business.id)
        db.session.add(intel)

    for field in [
        "company_summary",
        "products_services",
        "estimated_size",
        "target_customers",
        "key_contacts",
        "technologies_used",
        "recent_news",
        "potential_pain_points",
        "outreach_angle",
    ]:
        setattr(intel, field, intel_data.get(field))

    intel.raw_json = json.dumps(intel_data)
    business.enriched = True
    return intel
