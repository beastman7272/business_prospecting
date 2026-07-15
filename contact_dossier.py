"""
Stage 3: Contact Deep-Dive Research (spine, backend-agnostic scaffold)

Given ONE chosen ContactCandidate (from Stage 2) plus its CompanyInput,
produce a dossier for approaching that specific person: a gate verdict, reach
info, background, engagement material, and low-confidence reporting inferences.

See docs/stage3_contact_dossier.md for the full design and rationale. This
module builds the parts that do NOT depend on the Gemini-vs-OpenAI backend
decision:

  * the data model (provenance on every leaf),
  * the multi-source gate and its short-circuit rule,
  * the deterministic reach logic (email/phone extraction + pattern inference),
  * the orchestrator (shared page cache, per-track budgets, graceful failure),
  * the org-inference citation guard.

The backend-specific work sits behind two mockable seams:

  * ``DossierLLM``          — the LLM reasoning steps (currency signals,
                              background facts, reach association, engagement
                              summaries, reporting inference).
  * ``EngagementResearcher`` — the one pluggable track (spine vs hosted-search).

Both have Mock implementations here so the whole pipeline runs and is testable
offline. Concrete Gemini/OpenAI implementations are deferred until the backend
decision is made.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from contact_discovery import (
    CompanyInput,
    ContactCandidate,
    SearchProvider,
    SearchResult,
    resolve_segment,
    normalize_domain,
    _get_domain,
)
from fetch_and_extract import PageFetcher
from active_profile import get_active_profile
from searcher_profiles.base import effective_play
from roles import search_terms


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Data model  (§7 of the design note — provenance on every leaf)
# =============================================================================

@dataclass
class Doc:
    """A unit of evidence text handed to the LLM seam."""
    url: str
    text: str
    fetched_at: str | None
    source_type: str  # own_domain_page | search_snippet | linkedin_snippet


@dataclass
class ReachValue:
    value: str
    kind: str                 # email | phone | linkedin | other
    how_obtained: str         # listed | pattern_inferred | snippet
    source_url: str
    confidence: str           # high | medium | low
    fetched_at: str
    note: str = ""


@dataclass
class BackgroundFact:
    claim: str
    source_url: str
    date: str | None
    confidence: str           # high | medium | low


@dataclass
class EngagementItem:
    url: str
    kind: str                 # post | article | talk | podcast | other
    title: str
    date: str | None
    summary: str
    identity_confidence: str  # high | medium | low  (is this really the person?)
    relevance: str            # professional relevance note


@dataclass
class OrgInference:
    claim: str
    basis: list[str]          # evidence refs (urls); MUST be non-empty to survive
    confidence: str = "low"


@dataclass
class GateVerdict:
    currency: str             # current | uncertain | likely_departed
    currency_evidence: dict[str, Any]
    seniority_score: int
    worth_deepdive: bool
    rationale: str


@dataclass
class ContactDossier:
    contact: ContactCandidate
    company: CompanyInput
    gate: GateVerdict
    reach: list[ReachValue] = field(default_factory=list)
    background: list[BackgroundFact] = field(default_factory=list)
    engagement: list[EngagementItem] = field(default_factory=list)
    org_inferences: list[OrgInference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fetched_pages: list[dict] = field(default_factory=list)
    generated_at: str = field(default_factory=_now)


# =============================================================================
# LLM reasoning seam  (backend-agnostic; concrete impls deferred)
# =============================================================================

@dataclass
class PersonSignals:
    """Structured signals the gate reasons over. The LLM's job is to fill this
    from evidence text; the gate combines it deterministically."""
    present_urls: list[str] = field(default_factory=list)
    departure_signals: list[dict] = field(default_factory=list)   # [{url, note}]
    current_title_notes: list[dict] = field(default_factory=list)  # [{url, note}]


class DossierLLM(ABC):
    """The LLM-dependent reasoning steps. One interface, many methods, so a
    single mock can stand in for all of Stage 3's model calls in tests."""

    @abstractmethod
    def detect_person_signals(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc]
    ) -> PersonSignals: ...

    @abstractmethod
    def extract_background_facts(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc]
    ) -> list[BackgroundFact]: ...

    @abstractmethod
    def associate_reach(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc]
    ) -> list[ReachValue]: ...

    @abstractmethod
    def summarize_engagement(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc]
    ) -> list[EngagementItem]: ...

    @abstractmethod
    def infer_reporting(
        self, contact: ContactCandidate, company: CompanyInput, evidence: list[Doc]
    ) -> list[OrgInference]: ...


class MockDossierLLM(DossierLLM):
    """Canned responses for offline development/testing."""

    def __init__(
        self,
        signals: PersonSignals | None = None,
        background: list[BackgroundFact] | None = None,
        reach: list[ReachValue] | None = None,
        engagement: list[EngagementItem] | None = None,
        org: list[OrgInference] | None = None,
    ):
        self._signals = signals or PersonSignals()
        self._background = background or []
        self._reach = reach or []
        self._engagement = engagement or []
        self._org = org or []

    def detect_person_signals(self, contact, company, documents):
        return self._signals

    def extract_background_facts(self, contact, company, documents):
        return list(self._background)

    def associate_reach(self, contact, company, documents):
        return list(self._reach)

    def summarize_engagement(self, contact, company, documents):
        return list(self._engagement)

    def infer_reporting(self, contact, company, evidence):
        return list(self._org)


# =============================================================================
# Engagement seam  (§5.3 — the one pluggable track)
# =============================================================================

class EngagementResearcher(ABC):
    @abstractmethod
    def research(
        self, contact: ContactCandidate, company: CompanyInput, anchors: dict
    ) -> list[EngagementItem]: ...


class MockEngagementResearcher(EngagementResearcher):
    def __init__(self, items: list[EngagementItem] | None = None):
        self._items = items or []

    def research(self, contact, company, anchors):
        return list(self._items)


class SpineEngagementResearcher(EngagementResearcher):
    """
    Default (controlled) engagement track: scoped search -> fetch -> LLM
    confirm-identity + summarize. Structure only; the identity/summarize step
    routes through the DossierLLM seam, so it stays backend-agnostic. A
    HostedSearchEngagementResearcher can later implement the same interface and
    be swapped in if the eval shows this one under-recalls.
    """

    def __init__(
        self,
        search: SearchProvider,
        fetcher: PageFetcher,
        llm: DossierLLM,
        max_pages: int = 5,
        per_page_chars: int = 6000,
    ):
        self.search = search
        self.fetcher = fetcher
        self.llm = llm
        self.max_pages = max_pages
        self.per_page_chars = per_page_chars

    def research(self, contact, company, anchors):
        title = contact.title or ""
        query = f'"{contact.name}" "{company.canonical_name}" {title}'.strip()
        try:
            results = self.search.search(query, max_results=self.max_pages)
        except Exception:
            results = []

        docs: list[Doc] = []
        for r in results[: self.max_pages]:
            # The fetcher's denylist guarantees LinkedIn etc. are never fetched;
            # such results contribute their snippet only.
            fr = self.fetcher.fetch(r.url)
            if fr.ok and fr.text:
                docs.append(Doc(fr.final_url or fr.url,
                                fr.text[: self.per_page_chars],
                                fr.fetched_at, "search_snippet"))
            else:
                docs.append(Doc(r.url, r.snippet, None, "search_snippet"))

        # Identity confirmation + summarization + relevance filtering all happen
        # inside the LLM step (mandatory disambiguation guard, §5.3).
        return self.llm.summarize_engagement(contact, company, docs)


# =============================================================================
# Deterministic helpers  (fully backend-agnostic; real logic, tested)
# =============================================================================

_SUFFIXES = {
    "jr", "sr", "ii", "iii", "iv", "esq", "pc", "phd", "md", "cpa",
    "dc", "dds", "dvm",              # common practitioner credentials
}
# Leading honorifics to strip (e.g. "Dr. Marta Trujillo" -> first="marta").
_HONORIFICS = {
    "dr", "dra", "mr", "mrs", "ms", "miss", "mx",
    "prof", "professor", "rev", "sir", "dame", "fr",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}"
)


def parse_name(name: str) -> tuple[str, str]:
    """
    Return (first, last) as lowercased alpha tokens. Strips leading honorifics
    (Dr., Mr., ...) and trailing suffixes/credentials (Jr., PhD, DC, ...), so
    e.g. "Dr. Marta M. Trujillo" -> ("marta", "trujillo").
    """
    cleaned = name.replace(",", " ")
    tokens = [re.sub(r"[^a-z]", "", t.lower()) for t in re.split(r"\s+", cleaned)]
    tokens = [t for t in tokens if t and t not in _SUFFIXES]
    while tokens and tokens[0] in _HONORIFICS:   # handles stacked prefixes too
        tokens.pop(0)
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], tokens[-1]


def find_emails(text: str) -> list[str]:
    return EMAIL_RE.findall(text or "")


def find_phones(text: str) -> list[str]:
    return [m.strip() for m in PHONE_RE.findall(text or "")]


def _email_local(email: str) -> str:
    return email.split("@", 1)[0].lower()


def _email_domain(email: str) -> str:
    return email.split("@", 1)[1].lower() if "@" in email else ""


def local_matches_person(email: str, first: str, last: str) -> bool:
    """True if an email's local part plausibly belongs to this person."""
    if not first or not last:
        return False
    norm = re.sub(r"[^a-z]", "", _email_local(email))
    candidates = {
        first + last, last + first,
        first[0] + last, first + last[0],
        first + "." + last,  # already stripped of '.', kept for clarity
    }
    candidates = {re.sub(r"[^a-z]", "", c) for c in candidates}
    return norm in candidates or (first in norm and last in norm)


def infer_pattern_from_email(local: str) -> str | None:
    """
    Infer an email template from an existing address's *structure*. Only
    separator-bearing locals are inferred (higher precision); ambiguous
    no-separator forms return None rather than guessing.
    """
    local = local.lower()
    for sep, tmpl_full, tmpl_initial in (
        (".", "{first}.{last}", "{f}.{last}"),
        ("_", "{first}_{last}", "{f}_{last}"),
    ):
        if sep in local:
            a, _, b = local.partition(sep)
            if a and b:
                return tmpl_initial if len(a) == 1 else tmpl_full
    return None


def apply_email_pattern(tmpl: str, first: str, last: str, domain: str) -> str | None:
    if not first or not last or not domain:
        return None
    local = (tmpl.replace("{first}", first)
                 .replace("{last}", last)
                 .replace("{f}", first[0]))
    return f"{local}@{domain}"


def _seniority_score(title: str, target_roles: list[str]) -> int:
    """
    Coarse keyword-overlap score of a title against a segment's ordered target
    roles (mirrors Stage 2's ranker). Higher = more clearly a decision/
    influence role. NOTE: this is a heuristic; an unusual-but-senior title can
    score 0, so the seniority short-circuit is tunable via min_seniority.
    """
    title_words = set((title or "").lower().replace("/", " ").split())
    best = 0
    for i, role in enumerate(target_roles):
        role_words = set(role.lower().replace("/", " ").split())
        overlap = len(title_words & role_words)
        if overlap > 0:
            best = max(best, overlap * (len(target_roles) - i))
    return best


# =============================================================================
# The gate  (§4 — multi-source, with the short-circuit rule)
# =============================================================================

def combine_currency_verdict(
    signals: PersonSignals,
    seniority_score: int,
    min_seniority: int,
) -> tuple[str, bool, str]:
    """
    Apply the §4.3 rule.

      - likely_departed requires a POSITIVE departure signal, and never follows
        from mere absence of confirmation.
      - conflicting signals (present AND departure) -> uncertain, not departed.
      - uncertain PROCEEDS (does not short-circuit).
      - short-circuit only on likely_departed, or seniority below the bar.
    """
    present = bool(signals.present_urls or signals.current_title_notes)
    departed = bool(signals.departure_signals)

    if departed and not present:
        currency = "likely_departed"
    elif departed and present:
        currency = "uncertain"          # conflicting -> don't reject
    elif present:
        currency = "current"
    else:
        currency = "uncertain"          # absence != departure

    low_value = seniority_score < min_seniority
    worth = (currency != "likely_departed") and (not low_value)

    bits = [f"currency={currency}", f"seniority={seniority_score}"]
    if currency == "likely_departed":
        bits.append("positive departure signal present")
    if low_value:
        bits.append(f"below seniority bar (min={min_seniority})")
    if currency == "uncertain":
        bits.append("proceeding despite uncertainty (flagged)")
    rationale = "; ".join(bits)
    return currency, worth, rationale


def run_gate(
    contact: ContactCandidate,
    company: CompanyInput,
    *,
    search: SearchProvider,
    get_page,                       # callable(url) -> FetchResult (cached)
    llm: DossierLLM,
    min_seniority: int = 1,
    max_pages: int = 5,
    per_page_chars: int = 6000,
) -> tuple[GateVerdict, list[Doc], dict | None, list[str]]:
    """
    Multi-source gate. Sources (§4.2):
      1. own-domain pages already in the contact's Stage 2 evidence,
      2. a targeted freshness search (the only source that can surface a
         *departure* signal),
      3. LinkedIn read-only via snippet (never fetched — denylist enforces it).
    Returns (verdict, gate_docs, linkedin_ref, warnings). gate_docs are reused
    downstream so reach/background don't re-fetch.
    """
    warnings: list[str] = []
    segment, _ = resolve_segment(company)
    # Seniority reference roles now come from the active searcher's ranked play
    # for this segment (was segment.target_roles, which moved onto the profile).
    _play = effective_play(get_active_profile(), segment.segment_id)
    _role_titles = ([t for rr in _play.roles for t in search_terms(rr.role.key)] if _play
                    else [t for k in segment.role_inventory for t in search_terms(k)])
    seniority = _seniority_score(contact.title or "", _role_titles)

    docs: list[Doc] = []

    # Source 1: own-domain pages from inherited Stage 2 evidence.
    dom = normalize_domain(company.domain)
    own_urls: list[str] = []
    seen: set[str] = set()
    for e in contact.evidence:
        u = e.get("url", "")
        if u and _get_domain(u) == dom and u not in seen:
            seen.add(u)
            own_urls.append(u)
    for u in own_urls[:max_pages]:
        fr = get_page(u)
        if fr.ok and fr.text:
            docs.append(Doc(fr.final_url or u, fr.text[:per_page_chars],
                            fr.fetched_at, "own_domain_page"))

    # Source 2 + 3: targeted freshness search (+ read-only LinkedIn snippet).
    title = contact.title or ""
    query = f'"{contact.name}" "{company.canonical_name}" {title}'.strip()
    linkedin_ref: dict | None = None
    try:
        results = search.search(query, max_results=max_pages)
    except Exception as ex:
        results = []
        warnings.append(f"gate freshness search failed: {ex}")
    for r in results:
        src = "linkedin_snippet" if "linkedin.com" in r.url.lower() else "search_snippet"
        docs.append(Doc(r.url, r.snippet, None, src))
        if src == "linkedin_snippet" and linkedin_ref is None:
            linkedin_ref = {"url": r.url, "snippet": r.snippet}

    # A failure here (e.g. a transient API error) must not crash the dossier.
    # Degrade to empty signals -> "uncertain", which PROCEEDS per §4.3, and flag
    # it. Seniority is computed deterministically above, so it is unaffected.
    try:
        signals = llm.detect_person_signals(contact, company, docs)
    except Exception as ex:
        signals = PersonSignals()
        warnings.append(
            f"gate currency assessment failed ({ex}); proceeding as uncertain"
        )
    currency, worth, rationale = combine_currency_verdict(signals, seniority, min_seniority)

    verdict = GateVerdict(
        currency=currency,
        currency_evidence={
            "present_urls": signals.present_urls,
            "departure_signals": signals.departure_signals,
            "current_title_notes": signals.current_title_notes,
        },
        seniority_score=seniority,
        worth_deepdive=worth,
        rationale=rationale,
    )
    return verdict, docs, linkedin_ref, warnings


# =============================================================================
# Tracks
# =============================================================================

def run_reach(
    contact: ContactCandidate,
    company: CompanyInput,
    docs: list[Doc],
    linkedin_ref: dict | None,
    llm: DossierLLM,
    *,
    verify_email: bool = False,       # off-by-default seam; not implemented in v1
) -> list[ReachValue]:
    """
    Deterministic reach: extract listed emails/phones from own-domain page text,
    match to the person, and infer an email from a detected company pattern only
    when no listed address is found. Then merge any LLM-associated values.
    """
    first, last = parse_name(contact.name)
    company_domain = normalize_domain(company.domain)
    now = _now()
    out: list[ReachValue] = []

    page_docs = [d for d in docs if d.source_type == "own_domain_page"]

    listed_emails: list[tuple[str, str]] = []   # (email, source_url)
    listed_phones: list[tuple[str, str]] = []
    for d in page_docs:
        for em in find_emails(d.text):
            listed_emails.append((em, d.url))
        for ph in find_phones(d.text):
            listed_phones.append((ph, d.url))

    # 1) Listed email that matches the person -> high confidence.
    person_has_listed = False
    for em, url in listed_emails:
        if local_matches_person(em, first, last):
            out.append(ReachValue(em, "email", "listed", url, "high", now))
            person_has_listed = True

    # 2) Pattern inference — only if no listed email for the person, and only
    #    anchored on a confirmed company-domain address.
    if not person_has_listed and company_domain:
        for em, url in listed_emails:
            if _email_domain(em) != company_domain:
                continue
            tmpl = infer_pattern_from_email(_email_local(em))
            if tmpl:
                inferred = apply_email_pattern(tmpl, first, last, company_domain)
                if inferred:
                    out.append(ReachValue(
                        inferred, "email", "pattern_inferred", url, "low", now,
                        note=f"pattern {tmpl} inferred from {em}",
                    ))
                    break

    # 3) Phones (listed only, never inferred).
    seen_phone = set()
    for ph, url in listed_phones:
        key = re.sub(r"\D", "", ph)
        if key and key not in seen_phone:
            seen_phone.add(key)
            out.append(ReachValue(ph, "phone", "listed", url, "medium", now))

    # 4) LinkedIn read-only reference (from the gate's snippet).
    if linkedin_ref:
        out.append(ReachValue(linkedin_ref["url"], "linkedin", "snippet",
                              linkedin_ref["url"], "medium", now,
                              note="read-only reference; not fetched"))

    # 5) Merge LLM-associated reach (mock returns []); dedupe by (kind, value).
    seen_vals = {(r.kind, r.value) for r in out}
    for rv in llm.associate_reach(contact, company, page_docs):
        if (rv.kind, rv.value) not in seen_vals:
            out.append(rv)
            seen_vals.add((rv.kind, rv.value))

    return out


def run_background(contact, company, docs, llm) -> list[BackgroundFact]:
    """LLM extracts career/tenure/education facts; professional-relevance
    filtering lives in the prompt (§5.2). Deterministic pass-through here."""
    return llm.extract_background_facts(contact, company, docs)


def run_org_inference(contact, company, evidence, llm) -> list[OrgInference]:
    """Low-confidence reporting inference with the citation guard (§5.4): any
    inference lacking a concrete evidence basis is dropped."""
    raw = llm.infer_reporting(contact, company, evidence)
    return [o for o in raw if o.basis]


# =============================================================================
# Orchestrator  (§8)
# =============================================================================

def build_dossier(
    contact: ContactCandidate,
    company: CompanyInput,
    *,
    search: SearchProvider,
    fetcher: PageFetcher,
    llm: DossierLLM,
    engagement_researcher: EngagementResearcher,
    min_seniority: int = 1,
    verify_email: bool = False,
    max_pages: int = 5,
    per_page_chars: int = 6000,
) -> ContactDossier:
    """
    Run the Stage 3 pipeline. Shared page cache across tracks; per-track
    graceful failure; short-circuit on a non-worth gate verdict.
    """
    page_cache: dict[str, Any] = {}

    def get_page(url: str):
        if url not in page_cache:
            page_cache[url] = fetcher.fetch(url)
        return page_cache[url]

    warnings: list[str] = []

    gate, gate_docs, linkedin_ref, gate_warnings = run_gate(
        contact, company, search=search, get_page=get_page, llm=llm,
        min_seniority=min_seniority, max_pages=max_pages,
        per_page_chars=per_page_chars,
    )
    warnings.extend(gate_warnings)

    def _pages_dict() -> list[dict]:
        return [fr.to_dict() for fr in page_cache.values()
                if hasattr(fr, "to_dict")]

    if not gate.worth_deepdive:
        warnings.append(f"short-circuited: {gate.rationale}")
        return ContactDossier(
            contact=contact, company=company, gate=gate,
            warnings=warnings, fetched_pages=_pages_dict(),
        )

    reach: list[ReachValue] = []
    try:
        reach = run_reach(contact, company, gate_docs, linkedin_ref, llm,
                          verify_email=verify_email)
    except Exception as ex:
        warnings.append(f"reach track failed: {ex}")

    background: list[BackgroundFact] = []
    try:
        background = run_background(contact, company, gate_docs, llm)
    except Exception as ex:
        warnings.append(f"background track failed: {ex}")

    engagement: list[EngagementItem] = []
    try:
        anchors = {
            "company": company.canonical_name,
            "title": contact.title,
            "city": company.city,
            "state": company.state,
            "known_urls": [e.get("url", "") for e in contact.evidence],
        }
        engagement = engagement_researcher.research(contact, company, anchors)
    except Exception as ex:
        warnings.append(f"engagement track failed: {ex}")

    org: list[OrgInference] = []
    try:
        org = run_org_inference(contact, company, gate_docs, llm)
    except Exception as ex:
        warnings.append(f"org-inference track failed: {ex}")

    return ContactDossier(
        contact=contact, company=company, gate=gate,
        reach=reach, background=background, engagement=engagement,
        org_inferences=org, warnings=warnings, fetched_pages=_pages_dict(),
    )


def dossier_to_dict(dossier: ContactDossier) -> dict[str, Any]:
    """JSON-serializable dict of a dossier, for inspection or output."""
    return asdict(dossier)


# =============================================================================
# Demo with mocked seams (no network, no API keys)
# =============================================================================

if __name__ == "__main__":
    import json
    from contact_discovery import MockSearchProvider

    contact = ContactCandidate(
        name="Jane Doe",
        title="Director of Operations",
        company="Acme Widgets",
        evidence=[{"url": "https://acmewidgets.com/team",
                   "snippet": "Meet our team", "query": "..."}],
        confidence="high",
        why_relevant="Runs operations; owns facilities decisions.",
    )
    company = CompanyInput(
        canonical_name="Acme Widgets", input_name="Acme Widgets",
        city="Duluth", state="GA", places_type="lawyer",
        website="https://acmewidgets.com/", domain="acmewidgets.com",
    )

    # Mock seams: person is currently present; a coworker email reveals the
    # company email pattern for inference.
    llm = MockDossierLLM(
        signals=PersonSignals(
            present_urls=["https://acmewidgets.com/team"],
            current_title_notes=[{"url": "https://acmewidgets.com/team",
                                  "note": "Listed as Director of Operations"}],
        ),
        background=[BackgroundFact("10+ years in operations",
                                   "https://acmewidgets.com/team", None, "medium")],
        org=[OrgInference("Likely reports to the Managing Partner",
                          ["https://acmewidgets.com/team"], "low")],
    )
    engagement = MockEngagementResearcher(items=[
        EngagementItem("https://example.com/post", "post",
                       "On modernizing facilities", "2026-05",
                       "Wrote about an office renovation.", "high",
                       "Directly relevant to a GC pitch."),
    ])

    search = MockSearchProvider(fixtures={"": [
        {"title": "Team", "url": "https://acmewidgets.com/team",
         "snippet": "Jane Doe, Director of Operations. john.smith@acmewidgets.com"},
    ]})

    class _StubFetcher:
        """Offline stand-in for PageFetcher (build_dossier calls .fetch(url))."""
        def fetch(self, url):
            from fetch_and_extract import FetchResult
            return FetchResult(
                url=url, ok=True, final_url=url, status_code=200,
                title="Team",
                text=("Jane Doe, Director of Operations. "
                      "john.smith@acmewidgets.com"),
            )

    dossier = build_dossier(
        contact, company,
        search=search, fetcher=_StubFetcher(), llm=llm,
        engagement_researcher=engagement,
    )
    print(json.dumps(dossier_to_dict(dossier), indent=2))
