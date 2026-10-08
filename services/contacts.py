"""
Service layer wiring Stage 2 (contact discovery) and Stage 3 (contact
deep-dive) into the Flask app.

This is the thin adapter the handoff calls for: it turns a persisted
``Business`` into the ``CompanyInput`` the standalone pipelines expect,
constructs the real providers from app config (Brave search, Gemini
extraction, OpenAI DossierLLM, shared PageFetcher), runs the pipeline, and
persists the result into the ``Contact`` / ``Dossier`` models.

The pipelines themselves are untouched and provider-free; all provider binding
lives here, mirroring how ``services/intel.py`` binds OpenAI for Stage 1.

Design choices carried from the handoff:
  * Discovery runs with the optional own-domain page fetch ON — richer, higher
    confidence contacts, and the own-domain evidence the ranker rewards.
  * Calls run synchronously in the request handler (same as /api/enrich). A
    full run touches Brave + Gemini + OpenAI, so it is slow; the UI shows a
    loading state. Swapping to a background job later only touches this layer
    and the two endpoints.
  * Persistence is upsert-by-name so re-running discovery refreshes a contact
    without orphaning a dossier already built for it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict

from flask import current_app

from models import db, Business, Contact, Dossier

from contact_discovery import (
    CompanyInput,
    ContactCandidate,
    BraveSearchProvider,
    GeminiExtractor,
    discover_contacts,
    normalize_domain,
)
from active_profile import get_active_profile
from contact_dossier import (
    build_dossier,
    dossier_to_dict,
    SpineEngagementResearcher,
)
from dossier_llm_openai import OpenAIDossierLLM
from fetch_and_extract import PageFetcher


# -----------------------------------------------------------------------------
# Business -> CompanyInput
# -----------------------------------------------------------------------------

# Matches the "ST 30096" (state + ZIP) chunk of a US formatted address, from
# which we can recover the city as the comma-part immediately before it.
_STATE_ZIP_RE = re.compile(r"^([A-Z]{2})\s+\d{5}(?:-\d{4})?$")


def parse_city_state(formatted_address: str | None) -> tuple[str, str]:
    """
    Best-effort (city, state) from a Google `formattedAddress`, e.g.
    "1234 Peachtree St NE, Atlanta, GA 30309, USA" -> ("Atlanta", "GA").

    Location anchoring matters for discovery (city is what keeps multi-location
    companies from returning only corporate-parent results), but the pipeline
    tolerates blanks, so this degrades to ("", "") rather than raising.
    """
    if not formatted_address:
        return "", ""
    parts = [p.strip() for p in formatted_address.split(",") if p.strip()]
    for i, part in enumerate(parts):
        m = _STATE_ZIP_RE.match(part)
        if m:
            state = m.group(1)
            city = parts[i - 1] if i - 1 >= 0 else ""
            return city, state
        # Also handle a bare two-letter state part (no ZIP).
        if re.fullmatch(r"[A-Z]{2}", part) and i - 1 >= 0:
            return parts[i - 1], part
    # Fallback: assume [.., city, region, country] shape.
    if len(parts) >= 3:
        return parts[-3], parts[-2]
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", ""


def business_to_company_input(biz: Business) -> CompanyInput:
    city, state = parse_city_state(biz.formatted_address)
    domain = normalize_domain(biz.website) or None
    return CompanyInput(
        canonical_name=biz.name,
        input_name=biz.name,
        city=city,
        state=state,
        places_type=biz.primary_type or "",
        website=biz.website,
        domain=domain,
        phone=biz.phone,
        address=biz.formatted_address,
    )


# -----------------------------------------------------------------------------
# Provider construction (from app config, like services/intel.py)
# -----------------------------------------------------------------------------

def _search_provider() -> BraveSearchProvider:
    return BraveSearchProvider(current_app.config.get("BRAVE_SEARCH_API_KEY"))


def _extractor() -> GeminiExtractor:
    return GeminiExtractor(current_app.config.get("GEMINI_API_KEY"))


def _dossier_llm() -> OpenAIDossierLLM:
    # Build the OpenAI client with the configured key so the DossierLLM matches
    # how Stage 1 intel binds OpenAI, rather than relying on ambient env.
    from openai import OpenAI
    client = OpenAI(api_key=current_app.config.get("OPENAI_API_KEY"))
    return OpenAIDossierLLM(client=client)


# -----------------------------------------------------------------------------
# Stage 2: discover + persist contacts
# -----------------------------------------------------------------------------

def discover_and_save_contacts(biz: Business) -> dict:
    """
    Run Stage 2 discovery for a business and persist the ranked candidates.
    Returns a dict with the run-level metadata (segments, warnings) plus the
    saved Contact rows. Commit is left to the caller (the API route), matching
    the existing api.py convention.
    """
    company = business_to_company_input(biz)
    fetcher = PageFetcher()

    run = discover_contacts(
        company,
        get_active_profile(),           # active searcher (SEARCHER env, default gc)
        _search_provider(),
        _extractor(),
        fetch_own_domain=True,          # handoff decision: own-domain fetch ON
        page_fetcher=fetcher,
    )

    saved = _upsert_contacts(biz, run.candidates)
    pages_ok = sum(1 for p in run.fetched_pages if p.get("ok"))
    current_app.logger.warning(
        "discovery business=%s searcher=%s segment=%s queries=%d search_results=%d "
        "own_site_pages=%d/%d candidates=%d warnings=%s",
        biz.id, run.searcher_used, run.segments_used, len(run.queries),
        len(run.raw_results), pages_ok, len(run.fetched_pages),
        len(run.candidates), run.warnings,
    )
    return {
        "segments_used": run.segments_used,
        "warnings": run.warnings,
        "contacts": saved,
    }


def _upsert_contacts(biz: Business, candidates: list[ContactCandidate]) -> list[Contact]:
    """
    Upsert candidates by lowercased name. Existing rows are refreshed in place
    (preserving any built dossier); new candidates are added. `rank` records the
    order the discovery run returned them (0 = top).
    """
    existing = {(c.name or "").lower().strip(): c for c in biz.contacts}
    saved: list[Contact] = []
    for i, cand in enumerate(candidates):
        key = (cand.name or "").lower().strip()
        contact = existing.get(key)
        if contact is None:
            contact = Contact(business_id=biz.id, name=cand.name)
            db.session.add(contact)
        contact.title = cand.title
        contact.company = cand.company
        contact.confidence = cand.confidence
        contact.why_relevant = cand.why_relevant
        contact.evidence = json.dumps(cand.evidence or [])
        contact.rank = i
        saved.append(contact)
    return saved


# -----------------------------------------------------------------------------
# Stage 3: build + persist a dossier for one contact
# -----------------------------------------------------------------------------

def contact_to_candidate(contact: Contact) -> ContactCandidate:
    try:
        evidence = json.loads(contact.evidence) if contact.evidence else []
    except (ValueError, TypeError):
        evidence = []
    company_name = contact.company or (contact.business.name if contact.business else "")
    return ContactCandidate(
        name=contact.name,
        title=contact.title,
        company=company_name,
        evidence=evidence,
        confidence=contact.confidence or "low",
        why_relevant=contact.why_relevant or "",
    )


def build_and_save_dossier(contact: Contact) -> Dossier:
    """
    Run Stage 3 for a chosen contact and persist the dossier. Providers: Brave
    (freshness search + engagement), OpenAI DossierLLM, shared PageFetcher, and
    the default (controlled) SpineEngagementResearcher. Commit left to caller.
    """
    biz = contact.business
    company = business_to_company_input(biz)
    candidate = contact_to_candidate(contact)

    search = _search_provider()
    fetcher = PageFetcher()
    llm = _dossier_llm()
    engagement = SpineEngagementResearcher(search, fetcher, llm)

    dossier = build_dossier(
        candidate,
        company,
        search=search,
        fetcher=fetcher,
        llm=llm,
        engagement_researcher=engagement,
    )

    contact.selected = True
    return _save_dossier(contact, dossier)


def _save_dossier(contact: Contact, dossier) -> Dossier:
    """Flatten a ContactDossier into the Dossier row (upsert on the 1-1)."""
    full = dossier_to_dict(dossier)
    record = contact.dossier
    if record is None:
        record = Dossier(contact_id=contact.id)
        db.session.add(record)

    gate = full["gate"]
    record.currency = gate["currency"]
    record.seniority_score = gate["seniority_score"]
    record.worth_deepdive = gate["worth_deepdive"]
    record.rationale = gate["rationale"]
    record.currency_evidence = json.dumps(gate["currency_evidence"])

    record.reach = json.dumps(full["reach"])
    record.background = json.dumps(full["background"])
    record.engagement = json.dumps(full["engagement"])
    record.org_inferences = json.dumps(full["org_inferences"])
    record.warnings = json.dumps(full["warnings"])
    record.raw_json = json.dumps(full)
    record.generated_at = full.get("generated_at")
    return record


# -----------------------------------------------------------------------------
# Serialization for the API layer
# -----------------------------------------------------------------------------

def contact_summary(contact: Contact) -> dict:
    try:
        evidence = json.loads(contact.evidence) if contact.evidence else []
    except (ValueError, TypeError):
        evidence = []
    return {
        "id": contact.id,
        "business_id": contact.business_id,
        "name": contact.name,
        "title": contact.title,
        "company": contact.company,
        "confidence": contact.confidence,
        "why_relevant": contact.why_relevant,
        "evidence": evidence,
        "rank": contact.rank,
        "selected": contact.selected,
        "has_dossier": contact.dossier is not None,
    }


def _loads(value, default):
    try:
        return json.loads(value) if value else default
    except (ValueError, TypeError):
        return default


def dossier_dict(record: Dossier) -> dict:
    return {
        "id": record.id,
        "contact_id": record.contact_id,
        "gate": {
            "currency": record.currency,
            "seniority_score": record.seniority_score,
            "worth_deepdive": record.worth_deepdive,
            "rationale": record.rationale,
            "currency_evidence": _loads(record.currency_evidence, {}),
        },
        "reach": _loads(record.reach, []),
        "background": _loads(record.background, []),
        "engagement": _loads(record.engagement, []),
        "org_inferences": _loads(record.org_inferences, []),
        "warnings": _loads(record.warnings, []),
        "generated_at": record.generated_at,
    }
