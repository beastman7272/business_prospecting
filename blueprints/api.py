from flask import Blueprint, request, jsonify
from models import db, Business, Note, Contact
from services.place_types import (
    PLACE_TYPE_OPTIONS,
    normalize_primary_types,
    suggest_place_types,
)
from services.places import search_places
from services.intel import enrich_business
from services.db_ops import get_or_create_business, save_intel
from services.contacts import (
    discover_and_save_contacts,
    build_and_save_dossier,
    contact_summary,
    dossier_dict,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/place-types")
def api_place_types():
    return jsonify({"place_types": list(PLACE_TYPE_OPTIONS)})


@api_bp.post("/search")
def api_search():
    data = request.get_json() or {}
    requested_primary_types = data.get("primary_types", data.get("text_query", ""))
    normalized_primary_types, invalid_primary_types = normalize_primary_types(requested_primary_types)

    if invalid_primary_types:
        suggestions = suggest_place_types(invalid_primary_types)
        parts = []
        for value in invalid_primary_types:
            suggestion_text = ""
            if suggestions.get(value):
                suggestion_text = f" Try {', '.join(suggestions[value])}."
            parts.append(f'Unknown place type "{value}".{suggestion_text}')
        return jsonify({
            "error": " ".join(parts),
            "invalid_primary_types": invalid_primary_types,
            "suggestions": suggestions,
        }), 400

    if not normalized_primary_types:
        return jsonify({"error": "At least one primary type is required."}), 400

    places = search_places(
        primary_types=normalized_primary_types,
        center_lat=float(data["center_lat"]),
        center_lng=float(data["center_lng"]),
        radius_m=float(data.get("radius_m", 5000)),
        max_results=int(data.get("max_results", 20)),
    )
    place_ids = []
    for p in places:
        biz = get_or_create_business(p)
        if biz.place_id:
            place_ids.append(biz.place_id)
    db.session.commit()

    businesses = Business.query.filter(Business.place_id.in_(place_ids)).all()
    result = [_biz_summary(b) for b in businesses]
    return jsonify({"businesses": result, "total": len(result), "count": len(result)})


@api_bp.post("/enrich/<int:business_id>")
def api_enrich(business_id):
    biz = Business.query.get_or_404(business_id)
    intel_data = enrich_business(biz)
    intel = save_intel(biz, intel_data)
    db.session.commit()
    return jsonify({"ok": True, "business_id": biz.id, "intel": intel_data})


@api_bp.get("/businesses")
def api_businesses():
    status = request.args.get("status")
    enriched = request.args.get("enriched")
    q = Business.query.order_by(Business.created_at.desc())
    if status:
        q = q.filter_by(status=status)
    if enriched in ("true", "false"):
        q = q.filter_by(enriched=(enriched.lower() == "true"))
    businesses = [_biz_summary(b) for b in q.limit(200).all()]
    return jsonify({"businesses": businesses, "total": len(businesses)})


@api_bp.get("/businesses/<int:business_id>")
def api_business_detail(business_id):
    biz = Business.query.get_or_404(business_id)
    data = _biz_summary(biz)
    data["intel"] = _intel_dict(biz.intel) if biz.intel else None
    data["notes"] = [
        {"id": n.id, "body": n.body, "type": n.type, "created_at": str(n.created_at)}
        for n in biz.notes
    ]
    return jsonify(data)


@api_bp.post("/businesses/<int:business_id>/status")
def api_update_status(business_id):
    biz = Business.query.get_or_404(business_id)
    body = request.get_json() or {}
    valid = {"New", "Qualified", "Contacted", "Not a fit"}
    status = body.get("status")
    if status not in valid:
        return jsonify({"error": f"Invalid status. Must be one of: {valid}"}), 400
    biz.status = status
    db.session.commit()
    return jsonify({"ok": True, "status": biz.status})


@api_bp.post("/businesses/<int:business_id>/notes")
def api_add_note(business_id):
    biz = Business.query.get_or_404(business_id)
    body = request.get_json() or {}
    note = Note(
        business_id=biz.id,
        body=body.get("body", ""),
        type=body.get("type", "note"),
    )
    db.session.add(note)
    db.session.commit()
    return jsonify({"ok": True, "note_id": note.id})


# ── Stage 2: contact discovery ────────────────────────────────────────────────

@api_bp.get("/businesses/<int:business_id>/contacts")
def api_list_contacts(business_id):
    """Persisted contacts for a business, ranked as the discovery run returned them."""
    biz = Business.query.get_or_404(business_id)
    contacts = (
        Contact.query.filter_by(business_id=biz.id)
        .order_by(Contact.rank.asc(), Contact.id.asc())
        .all()
    )
    return jsonify({
        "business_id": biz.id,
        "contacts": [contact_summary(c) for c in contacts],
        "total": len(contacts),
    })


@api_bp.post("/businesses/<int:business_id>/discover-contacts")
def api_discover_contacts(business_id):
    """
    Run Stage 2 discovery (Brave + Gemini, own-domain fetch on) and persist the
    ranked candidates. Synchronous — the run is slow; the UI shows a loading
    state. A single failing provider surfaces as a 502 with the error message.
    """
    biz = Business.query.get_or_404(business_id)
    try:
        result = discover_and_save_contacts(biz)
    except Exception as ex:
        db.session.rollback()
        return jsonify({"error": f"Contact discovery failed: {ex}"}), 502
    db.session.commit()
    contacts = result["contacts"]
    return jsonify({
        "ok": True,
        "business_id": biz.id,
        "segments_used": result["segments_used"],
        "warnings": result["warnings"],
        "contacts": [contact_summary(c) for c in contacts],
        "count": len(contacts),
    })


# ── Stage 3: contact deep-dive dossier ────────────────────────────────────────

@api_bp.get("/contacts/<int:contact_id>/dossier")
def api_get_dossier(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    return jsonify({
        "contact_id": contact.id,
        "dossier": dossier_dict(contact.dossier) if contact.dossier else None,
    })


@api_bp.post("/contacts/<int:contact_id>/dossier")
def api_build_dossier(contact_id):
    """
    Build (or rebuild) the Stage 3 dossier for one contact. Synchronous; touches
    Brave + OpenAI + page fetches. Returns the flattened dossier with the gate
    verdict, provenance-carrying tracks, and any per-track warnings.
    """
    contact = Contact.query.get_or_404(contact_id)
    try:
        record = build_and_save_dossier(contact)
    except Exception as ex:
        db.session.rollback()
        return jsonify({"error": f"Dossier build failed: {ex}"}), 502
    db.session.commit()
    return jsonify({
        "ok": True,
        "contact_id": contact.id,
        "dossier": dossier_dict(record),
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _biz_summary(b: Business) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "lat": b.lat,
        "lng": b.lng,
        "formatted_address": b.formatted_address,
        "website": b.website,
        "phone": b.phone,
        "status": b.status,
        "enriched": b.enriched,
        "created_at": str(b.created_at),
    }

def _intel_dict(i) -> dict:
    return {
        "company_summary":       i.company_summary,
        "products_services":     i.products_services,
        "estimated_size":        i.estimated_size,
        "target_customers":      i.target_customers,
        "key_contacts":          i.key_contacts,
        "technologies_used":     i.technologies_used,
        "recent_news":           i.recent_news,
        "potential_pain_points": i.potential_pain_points,
        "outreach_angle":        i.outreach_angle,
    }


# ── Searcher picker (gated by SHOW_SEARCHER_PICKER) ───────────────────────────

@api_bp.get("/searchers")
def api_searchers():
    from flask import current_app
    from searcher_profiles import SEARCHER_PROFILES
    from active_profile import get_active_profile
    show = bool(current_app.config.get("SHOW_SEARCHER_PICKER"))
    try:
        active = get_active_profile().searcher_id
    except Exception:
        active = None
    searchers = sorted(
        ({"id": p.searcher_id, "name": p.display_name} for p in SEARCHER_PROFILES.values()),
        key=lambda s: s["name"],
    )
    return jsonify({"show_picker": show, "active": active, "searchers": searchers})


@api_bp.post("/searchers/active")
def api_set_searcher():
    from flask import current_app, session
    from searcher_profiles import SEARCHER_PROFILES
    if not current_app.config.get("SHOW_SEARCHER_PICKER"):
        return jsonify({"error": "Searcher picker is disabled."}), 403
    data = request.get_json(silent=True) or {}
    sid = data.get("searcher")
    if sid not in SEARCHER_PROFILES:
        return jsonify({"error": f"Unknown searcher {sid!r}."}), 400
    session["searcher"] = sid
    return jsonify({"ok": True, "active": sid})
