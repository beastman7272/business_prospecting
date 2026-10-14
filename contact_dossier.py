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

import os
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from contact_discovery import (
    CompanyInput,
    ContactCandidate,
    SearchProvider,
    SearchResult,
    resolve_segment,
    normalize_domain,
    _get_domain,
    _own_domain_seed_urls,
    PEOPLE_PAGE_WORDS,
    score_people_link,
)
from fetch_and_extract import PageFetcher, is_placeholder_email
import finance_signals
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
    # own_domain_page | external_page | search_snippet | social_snippet |
    # linkedin_snippet
    source_type: str
    purpose: str = ""         # which research query surfaced it (identity, career, ...)


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
    confidence: str           # high | medium | low  (is the claim itself right?)
    # Is this really the same person? confirmed = the source ties the name to
    # this company; probable = same name + matching profession/area, no company
    # link; possible = same name, weak match. Only confirmed/probable facts may
    # feed outreach openers; possible ones surface as open questions.
    identity: str = "confirmed"
    identity_note: str = ""


@dataclass
class EngagementItem:
    url: str
    kind: str                 # post | article | talk | podcast | group | review | other
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
class RapportHook:
    """
    A personal detail the person CHOSE to publish themselves (their own
    business site, their own posts) that makes a warm, non-creepy opener --
    e.g. an office dog, a hobby named in their bio, why they started the firm.
    Boundary (§5.5): self-published only; never family members, home address,
    health, politics/religion, or anything from people-search/aggregator sites.
    """
    detail: str
    kind: str                 # pet | hobby | interest | origin_story | community | other
    source_url: str
    suggested_use: str = ""


@dataclass
class OutreachAngle:
    angle: str                # short label, e.g. "New-firm credibility"
    opener: str               # 1-2 sentences the rep can adapt
    rationale: str            # why this fits the seller's offer
    evidence: list[str] = field(default_factory=list)   # source URLs it rests on


@dataclass
class OutreachBrief:
    """The 'so what': how to open a cold conversation with this person, for
    THIS seller. Synthesized from the dossier's own findings only."""
    angles: list[OutreachAngle] = field(default_factory=list)
    likely_needs: list[str] = field(default_factory=list)   # hypotheses, tied to the offer
    why_now: str | None = None
    avoid: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list) # identity doubts / contradictions
    channel: str = ""          # recommended first channel + why
    tone: str = ""


@dataclass
class SellerContext:
    """Who is doing the outreach and what they sell (from the active searcher
    profile), so the LLM judges 'relevant' as relevant to THIS seller rather
    than to a generic B2B rep."""
    searcher_id: str
    display_name: str
    description: str
    sales_rationale: str = ""
    segment_id: str = ""
    target_roles: list[str] = field(default_factory=list)
    site_signals: list[str] = field(default_factory=list)   # e.g. ["team_photos"]


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
    rapport: list[RapportHook] = field(default_factory=list)
    outreach: OutreachBrief | None = None
    # What was searched/crawled and why a section may be empty (queries run,
    # own-site pages visited, engagement status). Lets "nothing found" be
    # told apart from "couldn't look".
    research_log: dict[str, Any] = field(default_factory=dict)
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
    single mock can stand in for all of Stage 3's model calls in tests.

    ``seller`` (a SellerContext, may be None) tells the model who the outreach
    is for, so relevance is judged against the seller's actual offer."""

    @abstractmethod
    def detect_person_signals(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc]
    ) -> PersonSignals: ...

    @abstractmethod
    def extract_background_facts(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc],
        seller: SellerContext | None = None,
    ) -> list[BackgroundFact]: ...

    @abstractmethod
    def associate_reach(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc]
    ) -> list[ReachValue]: ...

    @abstractmethod
    def summarize_engagement(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc],
        seller: SellerContext | None = None,
    ) -> list[EngagementItem]: ...

    @abstractmethod
    def infer_reporting(
        self, contact: ContactCandidate, company: CompanyInput, evidence: list[Doc]
    ) -> list[OrgInference]: ...

    @abstractmethod
    def extract_rapport_hooks(
        self, contact: ContactCandidate, company: CompanyInput, documents: list[Doc],
        seller: SellerContext | None = None,
    ) -> list[RapportHook]: ...

    @abstractmethod
    def synthesize_outreach(
        self, contact: ContactCandidate, company: CompanyInput, findings: dict,
        seller: SellerContext | None = None,
    ) -> OutreachBrief: ...


class MockDossierLLM(DossierLLM):
    """Canned responses for offline development/testing. Records the documents
    each method was handed (``self.seen``) so tests can assert on what evidence
    actually reached the model."""

    def __init__(
        self,
        signals: PersonSignals | None = None,
        background: list[BackgroundFact] | None = None,
        reach: list[ReachValue] | None = None,
        engagement: list[EngagementItem] | None = None,
        org: list[OrgInference] | None = None,
        rapport: list[RapportHook] | None = None,
        outreach: OutreachBrief | None = None,
    ):
        self._signals = signals or PersonSignals()
        self._background = background or []
        self._reach = reach or []
        self._engagement = engagement or []
        self._org = org or []
        self._rapport = rapport or []
        self._outreach = outreach
        self.seen: dict[str, Any] = {}

    def detect_person_signals(self, contact, company, documents):
        self.seen["signals"] = documents
        return self._signals

    def extract_background_facts(self, contact, company, documents, seller=None):
        self.seen["background"] = documents
        self.seen["seller"] = seller
        return list(self._background)

    def associate_reach(self, contact, company, documents):
        self.seen["reach"] = documents
        return list(self._reach)

    def summarize_engagement(self, contact, company, documents, seller=None):
        self.seen["engagement"] = documents
        return list(self._engagement)

    def infer_reporting(self, contact, company, evidence):
        self.seen["org"] = evidence
        return list(self._org)

    def extract_rapport_hooks(self, contact, company, documents, seller=None):
        self.seen["rapport"] = documents
        return list(self._rapport)

    def synthesize_outreach(self, contact, company, findings, seller=None):
        self.seen["outreach_findings"] = findings
        return self._outreach or OutreachBrief()


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
        self.last_stats: dict = {}
        self.last_docs: list[Doc] = []

    def research(self, contact, company, anchors):
        results = anchors.get("search_results") or []
        self.last_stats = {"candidates": len(results), "pages_fetched": 0}
        return list(self._items)


class SpineEngagementResearcher(EngagementResearcher):
    """
    Default (controlled) engagement track: search -> fetch -> LLM
    confirm-identity + summarize. The identity/summarize step routes through
    the DossierLLM seam, so it stays backend-agnostic. A
    HostedSearchEngagementResearcher can later implement the same interface and
    be swapped in if the eval shows this one under-recalls.

    When the orchestrator passes ``anchors["search_results"]`` (the pooled,
    multi-query results from collect_evidence), those are used instead of
    running a separate query -- the old single query just repeated the gate's.
    Results on the company's own domain are skipped (the own-site crawl already
    read them). Social/LinkedIn results are never fetched (the fetcher's
    denylist) and contribute their search snippet only.

    After ``research`` runs, ``last_docs`` holds the external evidence it
    gathered (reused by the background/rapport tracks) and ``last_stats`` says
    how much there was, so an empty result can be explained.
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
        self.last_stats: dict = {}
        self.last_docs: list[Doc] = []

    def research(self, contact, company, anchors):
        self.last_stats, self.last_docs = {}, []
        results = anchors.get("search_results")
        purposes = anchors.get("purposes") or {}
        get_page = anchors.get("get_page") or self.fetcher.fetch
        if results is None:   # legacy/standalone path: one scoped query
            title = contact.title or ""
            query = f'"{contact.name}" "{company.canonical_name}" {title}'.strip()
            try:
                results = self.search.search(query, max_results=self.max_pages)
            except Exception:
                results = []

        dom = normalize_domain(company.domain)
        external = [r for r in results if not (dom and _get_domain(r.url) == dom)]
        first, last = parse_name(contact.name)

        def promise(r) -> tuple:
            blob = f"{r.title} {r.snippet} {r.url}".lower()
            return (bool(last) and last in blob, bool(first) and first in blob)

        docs: list[Doc] = []
        fetched = 0
        for r in sorted(external, key=promise, reverse=True):
            src = snippet_source_type(r.url)
            purpose = purposes.get(r.url, "")
            # Only fetch pages that plausibly mention the person; the rest
            # (and all social/LinkedIn results) contribute their snippet.
            if src == "search_snippet" and fetched < self.max_pages and promise(r)[0]:
                fr = get_page(r.url)
                if fr.ok and fr.text:
                    fetched += 1
                    docs.append(Doc(fr.final_url or r.url,
                                    focus_text(fr.text, contact.name, self.per_page_chars),
                                    fr.fetched_at, "external_page", purpose))
                    continue
            docs.append(Doc(r.url, f"{r.title}\n{r.snippet}".strip(), None, src, purpose))

        self.last_docs = docs
        self.last_stats = {"candidates": len(external), "pages_fetched": fetched}
        if not docs:
            return []
        # Identity confirmation + summarization + relevance filtering all happen
        # inside the LLM step (mandatory disambiguation guard, §5.3).
        return self.llm.summarize_engagement(contact, company, docs,
                                             seller=anchors.get("seller"))


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
    return [e for e in EMAIL_RE.findall(text or "") if not is_placeholder_email(e)]


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
# Research collection  (§4.2 / §5 -- own-site crawl + multi-query search)
# =============================================================================

_SOCIAL_HOSTS = ("facebook.com", "instagram.com", "twitter.com", "x.com",
                 "tiktok.com", "youtube.com", "nextdoor.com")

# Title words too generic to make a useful profession search term.
_GENERIC_TITLE_WORDS = {
    "owner", "founder", "cofounder", "co-founder", "president", "ceo", "coo",
    "cfo", "director", "manager", "partner", "principal", "lead", "senior",
    "chief", "officer", "of", "and", "the", "&", "/", "-", "vp", "head",
    "managing", "executive", "general", "associate",
}


def snippet_source_type(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.endswith("linkedin.com"):
        return "linkedin_snippet"
    if any(host == h or host.endswith("." + h) for h in _SOCIAL_HOSTS):
        return "social_snippet"
    return "search_snippet"


def focus_text(text: str, name: str, budget: int) -> str:
    """
    Fit page text into ``budget`` chars WITHOUT losing the parts about the
    person. Plain head-truncation dropped Steven Tison's bio, which sits ~60%
    of the way down his firm's one-page site. Keeps the page head (context),
    then windows around each mention of the person's surname/first name
    (bios run forward from the name heading, so windows lean forward), joined
    with an elision marker.
    """
    text = text or ""
    if len(text) <= budget:
        return text
    first, last = parse_name(name)
    low = text.lower()
    hits: list[int] = []
    for term in (last, first):
        if not term or len(term) < 3:
            continue
        start = 0
        while True:
            i = low.find(term, start)
            if i < 0:
                break
            hits.append(i)
            start = i + len(term)
    if not hits:
        return text[:budget]

    before, after = 300, 1500
    windows: list[tuple[int, int]] = []
    for i in sorted(hits):
        a, b = max(0, i - before), min(len(text), i + after)
        if windows and a <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], b))
        else:
            windows.append((a, b))
    window_chars = sum(b - a for a, b in windows)
    # Spend whatever the name windows don't need on the page head (context).
    head = max(budget // 5, budget - window_chars - 50)
    spans = [(0, head)] + windows
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    sep = "\n[...]\n"
    out: list[str] = []
    used = 0
    for a, b in merged:
        room = budget - used - (len(sep) if out else 0)
        if room <= 0:
            break
        piece = text[a:min(b, a + room)]
        out.append(piece)
        used += len(piece) + (len(sep) if len(out) > 1 else 0)
    return sep.join(out)


def _profession_terms(contact: ContactCandidate, company: CompanyInput) -> str:
    """A couple of words describing the person's line of work, for a career
    search ('accounting', 'chiropractor'). Empty if nothing useful."""
    words: list[str] = []
    for w in (company.places_type or "").replace("_", " ").split():
        if w and w not in words:
            words.append(w)
    for w in re.split(r"[\s/,&()-]+", (contact.title or "").lower()):
        if w and w not in _GENERIC_TITLE_WORDS and w not in words and len(w) > 2:
            words.append(w)
    return " ".join(words[:3])


def build_research_queries(
    contact: ContactCandidate, company: CompanyInput, max_queries: int = 5,
) -> list[tuple[str, str]]:
    """
    Several differently-anchored searches instead of one narrow one. The old
    single query ("name" "company" title) can't match a Facebook group post
    that never names the company, or a past employer's staff page. Returns
    [(purpose, query)], most important first, capped at ``max_queries``.
    Identity is NOT assumed for any result -- the LLM steps disambiguate.
    """
    first, last = parse_name(contact.name)
    # Curly apostrophes (Places data: "L’Amour") don't match pages that use
    # a plain one inside a quoted phrase.
    co = company.canonical_name.replace("\u2019", "'").replace("\u2018", "'")
    city, state = (company.city or "").strip(), (company.state or "").strip()
    profession = _profession_terms(contact, company)

    if first and not last:
        # Only a first name is known (e.g. a salon team page listing "Hannah,
        # Founder"). Searching "Hannah" alone returns namesakes, so anchor
        # every query on the business and use the first name as a hint;
        # the web-search pass is asked to find the full name.
        fn = first.title()
        role = (contact.title or "owner").strip()
        queries = [
            ("identity", f'"{co}" {fn} {role}'),
            ("career", f'"{co}" {city} owner OR founder'.strip()),
            ("local", f'"{co}" "{city}" {state} {fn}'.strip()),
            ("social", f'"{co}" site:facebook.com'),
            ("linkedin", f'"{co}" {fn} site:linkedin.com'),
            ("content", f'"{co}" {fn} interview OR feature OR article'),
        ]
        return queries[:max(1, max_queries)]

    person = (f'"{first.title()} {last.title()}"' if first and last
              else f'"{contact.name}"')

    queries: list[tuple[str, str]] = [("identity", f'{person} "{co}"')]
    if profession:
        queries.append(("career", f"{person} {profession}"))
    if city:
        queries.append(("local", f'{person} "{city}" {state}'.strip()))
    queries.append(("social", f"{person} {city or co} site:facebook.com".replace("  ", " ")))
    queries.append(("linkedin", f"{person} site:linkedin.com"))
    queries.append(("content", f'{person} "{co}" podcast OR interview OR blog OR article'))
    return queries[:max(1, max_queries)]


class ThrottledSearchProvider(SearchProvider):
    """
    Paces calls to a search API and retries once on a rate-limit response.
    Brave's free tier allows 1 query/second, and a dossier now runs several
    queries back to back.
    """

    def __init__(self, inner: SearchProvider, min_interval: float = 1.1,
                 retry_wait: float = 2.0):
        self.inner = inner
        self.min_interval = min_interval
        self.retry_wait = retry_wait
        self._last = 0.0
        self.calls = 0

    def _pace(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        self._pace()
        self.calls += 1
        try:
            return self.inner.search(query, max_results=max_results)
        except Exception as ex:
            if "429" not in str(ex):
                raise
            time.sleep(self.retry_wait)
            self._pace()
            self.calls += 1
            return self.inner.search(query, max_results=max_results)


# Query purposes that are purely about the person: results that don't even
# contain the surname are dropped as namesakes/noise.
_NAME_REQUIRED_PURPOSES = {"linkedin", "social", "local"}
_GENERIC_CO_WORDS = {"company", "group", "services", "service", "solutions",
                     "associates", "partners", "studio", "boutique", "the",
                     "and", "inc", "llc", "corp", "center", "centre"}


# People-page words + link scoring are shared with Stage 2 discovery
# (contact_discovery.PEOPLE_PAGE_WORDS / score_people_link).
_PERSON_PAGE_WORDS = PEOPLE_PAGE_WORDS


def _norm_url(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/").lower()


def _own_link_score(link: dict, first: str, last: str) -> int:
    return score_people_link(link, first, last)


# Words in a page's address or title that mark it as a people page. Medical,
# dental and legal sites name these pages after the profession
# ("gwinnett-pediatricians.php", "Our Physicians") rather than "team".
_PEOPLE_PAGE_TITLE_WORDS = (
    "team", "staff", "people", "meet", "leadership", "about", "our-firm",
    "provider", "physician", "pediatrician", "doctor", "dentist", "orthodont",
    "clinician", "therapist", "practitioner", "attorney", "lawyer", "agents",
    "advisor", "partners", "bios", "directory", "management",
)


def team_photo_check(fr, url: str, via_people_link: bool = False) -> dict | None:
    """
    Site signal "team_photos": on a team/staff/providers page, how many photo
    slots hold a real photo vs a placeholder vs nothing -- plus, when image
    file names carry years (dr-smith-2021.jpg), how many come from each year.
    A page counts as a people page if the crawl reached it through a people
    link ("Meet Our Staff", "Providers"), if its address/title says so, or if
    it shows several placeholder/missing photo slots.
    None when it isn't a people page or shows too few images to say.
    """
    audit = getattr(fr, "image_audit", None) or {}
    total = audit.get("total", 0)
    real = audit.get("real", 0)
    stand_ins = audit.get("placeholder", 0) + audit.get("no_source", 0)
    looks_people = via_people_link or any(
        w in f"{url} {fr.title or ''}".lower() for w in _PEOPLE_PAGE_TITLE_WORDS)
    if total < 3 or not (looks_people or stand_ins >= 3):
        return None
    years = audit.get("photo_years") or {}
    dated = {y: n for y, n in years.items() if y != "undated"}
    year_note = ""
    if dated:
        parts = [f"{y}: {n}" for y, n in sorted(dated.items())]
        if years.get("undated"):
            parts.append(f"no year: {years['undated']}")
        year_note = (" Years in the photo file names (" + ", ".join(parts) +
                     ") suggest the photos were taken at different times.")
    if stand_ins == 0:
        status = (f"all {real} have real photos -- so the angle is consistency or a "
                  "refresh, not missing photos.")
    else:
        status = (f"{real} real photos, {audit.get('placeholder', 0)} placeholder/"
                  f"silhouette images, {audit.get('no_source', 0)} with no image source "
                  "(usually a photo never added; occasionally script-loaded, so verify "
                  "by viewing the page).")
    summary = f"[Team-page photo check: {total} photo slots on this page; {status}{year_note}]"
    return {"url": fr.final_url or url, "real": real,
            "placeholder": audit.get("placeholder", 0),
            "no_source": audit.get("no_source", 0), "total": total,
            "photo_years": dated, "undated": years.get("undated", 0) if dated else None,
            "summary": summary}


def crawl_own_site(
    contact: ContactCandidate,
    company: CompanyInput,
    get_page,
    *,
    max_pages: int = 6,
    per_page_chars: int = 6000,
    signals: list[str] | None = None,
) -> tuple[list[Doc], list[dict]]:
    """
    Read the company's own site the way a person would: Stage 2's own-domain
    evidence pages and the homepage first, then the site's own links that look
    like people pages (scored by the person's name and about/team/meet words),
    then -- only if the site exposed no such links -- blind guesses at common
    paths. Each page is focus_text()-ed around the person's name.
    Returns (docs, crawl_log).
    """
    dom = normalize_domain(company.domain)
    if not dom:
        return [], []
    first, last = parse_name(contact.name)
    seeds = _own_domain_seed_urls(company)           # homepage first

    docs: list[Doc] = []
    log: list[dict] = []
    seen: set[str] = set()
    seen_final: set[str] = set()
    links: list[dict] = []

    def visit(url: str, via_people_link: bool = False) -> None:
        key = _norm_url(url)
        if not key or key in seen:
            return
        seen.add(key)
        fr = get_page(url.split("#", 1)[0])
        entry = {"url": url, "ok": bool(fr.ok and fr.text),
                 "reason": fr.skipped_reason or fr.error or ""}
        log.append(entry)
        if not (fr.ok and fr.text):
            return
        final = _norm_url(fr.final_url or url)
        links.extend(getattr(fr, "links", None) or [])
        if final in seen_final:                      # e.g. /about-us -> /about
            entry["reason"] = "duplicate_of_visited_page"
            return
        seen_final.add(final)
        seen.add(final)
        text = focus_text(fr.text, contact.name, per_page_chars)
        # Footer/contact-link details the main-text extractor strips.
        found = getattr(fr, "contacts", None) or {}
        extra = [x for x in (found.get("emails") or []) + (found.get("phones") or [])
                 if x.lower() not in text.lower()]
        if extra:
            text += "\n[Contact details elsewhere on this page (header/footer/links): " + \
                    "; ".join(extra) + "]"
        if "team_photos" in (signals or []):
            photo = team_photo_check(fr, url, via_people_link=via_people_link)
            if photo:
                entry["team_photos"] = photo
                text += "\n" + photo["summary"]
        if finance_signals.SIGNAL in (signals or []):
            fin = finance_signals.finance_signal_check(fr, url)
            if fin:
                entry[finance_signals.SIGNAL] = fin
                text += "\n" + fin["summary"]
        docs.append(Doc(fr.final_url or url, text,
                        fr.fetched_at, "own_domain_page", "own_site"))

    first_wave = [e.get("url", "") for e in contact.evidence
                  if e.get("url") and _get_domain(e.get("url", "")) == dom]
    first_wave += seeds[:1]
    for u in first_wave:
        if len(docs) >= max_pages:
            break
        visit(u)

    candidates: dict[str, tuple[int, str]] = {}
    for link in links:
        href = link.get("href") or ""
        if _get_domain(href) != dom or _norm_url(href) in seen:
            continue
        score = _own_link_score(link, first, last)
        if score > 0:
            k = _norm_url(href)
            if k not in candidates or candidates[k][0] < score:
                candidates[k] = (score, href)
    for score, href in sorted(candidates.values(), key=lambda t: -t[0]):
        if len(docs) >= max_pages:
            break
        # score >= 2 means the link itself named a people page ("Providers",
        # "Meet Our Staff"); "Contact" alone (1) doesn't count.
        visit(href, via_people_link=score >= 2)

    if not candidates:
        for u in seeds[1:]:
            if len(docs) >= max_pages:
                break
            visit(u)

    if finance_signals.SIGNAL in (signals or []):
        _visit_careers_pages(links, dom, get_page, seen, log)
    return docs, log


def _visit_careers_pages(links: list[dict], dom: str, get_page, seen: set[str],
                         log: list[dict], max_pages: int = 2) -> None:
    """Accountant signal: follow up to two links that look like the business's
    job postings (own site or an applicant-tracking host) and check them for
    finance roles. Logged only -- a careers page says nothing about the person,
    so it is not added to the dossier's evidence documents."""
    picks: dict[str, tuple[int, str]] = {}
    for link in links:
        href = link.get("href") or ""
        k = _norm_url(href)
        if not k or k in seen:
            continue
        s = finance_signals.score_careers_link(link, dom)
        if s > 0 and (k not in picks or picks[k][0] < s):
            picks[k] = (s, href)
    for _, href in sorted(picks.values(), key=lambda t: -t[0])[:max_pages]:
        seen.add(_norm_url(href))
        fr = get_page(href.split("#", 1)[0])
        entry = {"url": href, "ok": bool(fr.ok and fr.text), "careers_page": True,
                 "reason": fr.skipped_reason or fr.error or ""}
        log.append(entry)
        if fr.ok and fr.text:
            fin = finance_signals.finance_signal_check(fr, href, careers_page=True)
            if fin:
                entry[finance_signals.SIGNAL] = fin


class PersonSearch(ABC):
    """
    A broader, engine-driven search for one person (e.g. an LLM with a hosted
    web-search tool), run ALONGSIDE the query-by-query SearchProvider. Brave's
    index proved thin for small local firms and community Facebook groups
    (Steven Tison: 0 results for his own name + company), so this widens
    recall. It returns ordinary SearchResults -- only URLs the engine actually
    cited -- which then go through the same identity/relevance checks as
    everything else. Nothing it returns is trusted on its own.
    """
    engine: str = "person_search"

    @abstractmethod
    def find(self, contact: ContactCandidate, company: CompanyInput,
             seller: SellerContext | None = None) -> list[SearchResult]: ...


class MockPersonSearch(PersonSearch):
    engine = "mock_web"

    def __init__(self, results: list[SearchResult] | None = None):
        self._results = results or []

    def find(self, contact, company, seller=None):
        return list(self._results)


@dataclass
class Evidence:
    """Everything the research phase gathered, shared by every track."""
    own_docs: list[Doc]
    snippet_docs: list[Doc]
    results: list[SearchResult]           # deduped across queries and engines
    purposes: dict[str, str]              # result url -> query purpose
    linkedin_ref: dict | None
    query_log: list[dict]
    crawl_log: list[dict]
    warnings: list[str]
    engines: dict[str, list[str]] = field(default_factory=dict)  # norm url -> engines that found it
    # Profile site-signal hits from searches (e.g. job listings naming the
    # business and a finance role). Kept OUT of `results`: they are about the
    # company, not the person.
    signal_hits: dict[str, list[dict]] = field(default_factory=dict)


def collect_evidence(
    contact: ContactCandidate,
    company: CompanyInput,
    *,
    search: SearchProvider,
    get_page,
    max_queries: int = 5,
    results_per_query: int = 8,
    max_own_pages: int = 6,
    per_page_chars: int = 6000,
    person_search: PersonSearch | None = None,
    seller: SellerContext | None = None,
    search_engine_name: str = "brave",
) -> Evidence:
    warnings: list[str] = []
    # The person search is slow (an LLM browsing); start it first and let it
    # run while the crawl and the paced keyword searches happen.
    ps_pool = ThreadPoolExecutor(max_workers=1) if person_search else None
    ps_future = (ps_pool.submit(person_search.find, contact, company, seller)
                 if ps_pool else None)
    own_docs, crawl_log = crawl_own_site(
        contact, company, get_page,
        max_pages=max_own_pages, per_page_chars=per_page_chars,
        signals=(seller.site_signals if seller else None),
    )

    results: list[SearchResult] = []
    purposes: dict[str, str] = {}
    engines: dict[str, list[str]] = {}
    query_log: list[dict] = []

    def absorb(batch, purpose, engine) -> int:
        new = 0
        for r in batch:
            key = _norm_url(r.url)
            if not key:
                continue
            if key in engines:
                if engine not in engines[key]:
                    engines[key].append(engine)
                continue
            engines[key] = [engine]
            results.append(r)
            purposes[r.url] = purpose
            new += 1
        return new

    surname = parse_name(contact.name)[1]
    # Without a surname, "is this about our person?" falls back to "does it
    # mention the business?" -- its most distinctive word.
    co_words = sorted((w for w in re.findall(r"[a-z0-9']+", company.canonical_name.lower())
                       if len(w) > 3 and w not in _GENERIC_CO_WORDS), key=len, reverse=True)
    must_contain = surname or (co_words[0] if co_words else "")
    if search is not None and max_queries > 0:
        for purpose, q in build_research_queries(contact, company, max_queries):
            err = None
            try:
                batch = search.search(q, max_results=results_per_query)
            except Exception as ex:
                batch, err = [], str(ex)
                warnings.append(f"search failed ({purpose}): {ex}")
            raw = len(batch)
            if purpose in _NAME_REQUIRED_PURPOSES and must_contain:
                # These queries are only about the person; an engine that
                # ignores the quotes (Brave returned eight "Steven Wilson"
                # LinkedIn profiles for "Steven Tison") just adds noise.
                batch = [r for r in batch
                         if must_contain in f"{r.title} {r.url} {r.snippet}".lower()]
            new = absorb(batch, purpose, search_engine_name)
            query_log.append({"engine": search_engine_name, "purpose": purpose,
                              "query": q, "results": raw, "new": new,
                              "dropped_namesakes": raw - len(batch), "error": err})

    if ps_future is not None:
        err = None
        try:
            batch = ps_future.result()
        except Exception as ex:
            batch, err = [], str(ex)
            warnings.append(f"web search failed ({person_search.engine}): {ex}")
        new = absorb(batch, "web_search", person_search.engine)
        query_log.append({"engine": person_search.engine, "purpose": "web_search",
                          "query": f"(open web search for {contact.name})",
                          "results": len(batch), "new": new, "error": err})
        ps_pool.shutdown(wait=False)

    signal_hits: dict[str, list[dict]] = {}
    if (search is not None and seller is not None
            and finance_signals.SIGNAL in (seller.site_signals or [])):
        co = company.canonical_name.replace("\u2019", "'").replace("\u2018", "'")
        q = f'"{co}" {company.city or ""} jobs OR hiring OR careers'.replace("  ", " ")
        err = None
        try:
            batch = search.search(q, max_results=results_per_query)
        except Exception as ex:
            batch, err = [], str(ex)
            warnings.append(f"search failed (hiring_signal): {ex}")
        co_word = co_words[0] if co_words else ""
        hits = finance_signals.search_hiring_hits(batch, co_word)
        # Open the business's own job board if the search found it and the
        # crawl didn't already read it (listings are rarely in the snippet).
        checked = {_norm_url(p["url"]) for p in crawl_log}
        for jurl in finance_signals.employer_job_pages(
                batch, co_word, normalize_domain(company.domain) or "", limit=2):
            if _norm_url(jurl) in checked:
                continue
            fr = get_page(jurl)
            entry = {"url": jurl, "ok": bool(fr.ok and fr.text), "careers_page": True,
                     "via": "job_search", "reason": fr.skipped_reason or fr.error or ""}
            crawl_log.append(entry)
            if fr.ok and fr.text:
                fin = finance_signals.finance_signal_check(fr, jurl, careers_page=True)
                if fin:
                    entry[finance_signals.SIGNAL] = fin
            break
        if hits:
            signal_hits["hiring"] = hits
        query_log.append({"engine": search_engine_name, "purpose": "hiring_signal",
                          "query": q, "results": len(batch), "new": 0,
                          "signal_hits": len(hits), "error": err,
                          # what the job search returned, to audit misses
                          "seen": [{"title": r.title, "url": r.url} for r in batch[:8]]})

    first, last = parse_name(contact.name)
    snippet_docs: list[Doc] = []
    linkedin_ref: dict | None = None
    for r in results:
        src = snippet_source_type(r.url)
        snippet_docs.append(Doc(r.url, f"{r.title}\n{r.snippet}".strip(), None,
                                src, purposes.get(r.url, "")))
        blob = f"{r.title} {r.url}".lower()
        if (src == "linkedin_snippet" and linkedin_ref is None
                and last and last in blob and "/in/" in r.url.lower()):
            linkedin_ref = {"url": r.url, "snippet": r.snippet}

    return Evidence(own_docs, snippet_docs, results, purposes, linkedin_ref,
                    query_log, crawl_log, warnings, engines, signal_hits)


def seller_context_for(company: CompanyInput) -> SellerContext | None:
    """Build the SellerContext from the active searcher profile and the
    company's segment. None if no profile resolves (never fatal)."""
    try:
        profile = get_active_profile()
        segment, _ = resolve_segment(company)
        play = effective_play(profile, segment.segment_id)
        return SellerContext(
            searcher_id=profile.searcher_id,
            display_name=profile.display_name,
            description=profile.description,
            sales_rationale=play.sales_rationale if play else "",
            segment_id=segment.segment_id,
            target_roles=[rr.role.key for rr in play.roles] if play else [],
            site_signals=list(getattr(profile, "site_signals", []) or []),
        )
    except Exception:
        return None


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
    evidence: Evidence,
    llm: DossierLLM,
    min_seniority: int = 1,
) -> tuple[GateVerdict, list[str]]:
    """
    Multi-source gate (§4.2) over the shared research evidence:
      1. the company's own pages (own-site crawl),
      2. the multi-query search results (the only source that can surface a
         *departure* signal),
      3. LinkedIn read-only via snippet (never fetched -- denylist enforces it).
    Returns (verdict, warnings).
    """
    warnings: list[str] = []
    segment, _ = resolve_segment(company)
    # Seniority reference roles come from the active searcher's ranked play
    # for this segment.
    _play = effective_play(get_active_profile(), segment.segment_id)
    _role_titles = ([t for rr in _play.roles for t in search_terms(rr.role.key)] if _play
                    else [t for k in segment.role_inventory for t in search_terms(k)])
    seniority = _seniority_score(contact.title or "", _role_titles)

    docs = evidence.own_docs + evidence.snippet_docs

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
    return verdict, warnings


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


def run_background(contact, company, docs, llm, seller=None) -> list[BackgroundFact]:
    """LLM extracts facts about the PERSON (career, credentials, how they
    started); each carries an identity level. Sorted confirmed -> possible."""
    facts = llm.extract_background_facts(contact, company, docs, seller=seller)
    order = {"confirmed": 0, "probable": 1, "possible": 2}
    return sorted(facts, key=lambda f: order.get(f.identity, 3))


def run_rapport(contact, company, docs, llm, seller=None) -> list[RapportHook]:
    """Self-published personal details (§5.5). Uncited hooks are dropped."""
    hooks = llm.extract_rapport_hooks(contact, company, docs, seller=seller)
    return [h for h in hooks if h.source_url and h.detail]


def run_org_inference(contact, company, evidence, llm) -> list[OrgInference]:
    """Low-confidence reporting inference with the citation guard (§5.4): any
    inference lacking a concrete evidence basis is dropped."""
    raw = llm.infer_reporting(contact, company, evidence)
    return [o for o in raw if o.basis]


def run_outreach(contact, company, llm, findings, seller=None) -> OutreachBrief:
    """The 'so what' (§5.6): angles, likely needs, why-now, things to avoid and
    open questions, synthesized from the dossier's findings for this seller.
    Angles without any cited evidence are dropped."""
    brief = llm.synthesize_outreach(contact, company, findings, seller=seller)
    brief.angles = [a for a in brief.angles if a.evidence]
    return brief


def attribute_findings(evidence: Evidence, company: CompanyInput, background,
                       engagement, rapport, outreach) -> dict:
    """
    Which source produced each item that SURVIVED into the dossier: the
    company's own site, or which search engine(s). Summed per source plus a
    per-item list, so after a handful of dossiers it is clear whether an
    engine is pulling its weight (e.g. whether Brave still finds anything the
    web search misses).
    """
    dom = normalize_domain(company.domain)
    kept: list[tuple[str, str]] = (
        [("background", f.source_url) for f in background]
        + [("engagement", e.url) for e in engagement]
        + [("rapport", h.source_url) for h in rapport]
        + [("outreach", u) for a in (outreach.angles if outreach else []) for u in a.evidence]
    )
    items, counts = [], {}
    for section, url in kept:
        if not url:
            continue
        if dom and _get_domain(url) == dom:
            source = "own_site"
        else:
            engines = evidence.engines.get(_norm_url(url), [])
            source = "+".join(sorted(engines)) if engines else "unknown"
        counts[source] = counts.get(source, 0) + 1
        items.append({"section": section, "url": url, "source": source})
    return {"counts": counts, "items": items}


class _SkipOutreach(Exception):
    """Internal: outreach brief switched off."""


def _engagement_status(items, stats: dict, failed: bool) -> str:
    if failed:
        return "failed"
    if items:
        return "found"
    if stats.get("candidates") == 0:
        return "no_results"
    if stats.get("candidates"):
        return "filtered"
    return "unknown"


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
    max_pages: int = 6,             # cap on own-site pages read
    per_page_chars: int = 6000,
    max_queries: int = 5,           # search budget per dossier (Brave free tier: 1 qps)
    results_per_query: int = 8,
    seller: SellerContext | None = None,
    person_search: PersonSearch | None = None,
    search_engine_name: str = "brave",
    outreach_brief: bool | None = None,
) -> ContactDossier:
    """
    Run the Stage 3 pipeline: research once (own-site crawl + multi-query
    search), gate, then the tracks over that shared evidence, then the
    outreach synthesis. Shared page cache; per-track graceful failure;
    short-circuit on a non-worth gate verdict.
    """
    page_cache: dict[str, Any] = {}

    def get_page(url: str):
        if url not in page_cache:
            page_cache[url] = fetcher.fetch(url)
        return page_cache[url]

    def _pages_dict() -> list[dict]:
        out = []
        for fr in page_cache.values():
            if hasattr(fr, "to_dict"):
                d = fr.to_dict()
                d.pop("links", None)          # navigation only; keep raw_json lean
                d.pop("chrome_text", None)    # header/footer text; signals only
                out.append(d)
        return out

    warnings: list[str] = []
    if seller is None:
        seller = seller_context_for(company)

    evidence = collect_evidence(
        contact, company, search=search, get_page=get_page,
        max_queries=max_queries, results_per_query=results_per_query,
        max_own_pages=max_pages, per_page_chars=per_page_chars,
        person_search=person_search, seller=seller,
        search_engine_name=search_engine_name,
    )
    warnings.extend(evidence.warnings)
    research_log: dict[str, Any] = {
        "seller": seller.searcher_id if seller else None,
        "queries": evidence.query_log,
        "own_site_pages": evidence.crawl_log,
        "search_results": len(evidence.results),
        # Every search result (capped), with which engine(s) returned it, so a
        # dossier can be audited and the engines compared over time.
        "results": [
            {"url": r.url, "title": r.title, "purpose": evidence.purposes.get(r.url, ""),
             "engines": evidence.engines.get(_norm_url(r.url), [])}
            for r in evidence.results[:80]
        ],
    }
    photos = [p["team_photos"] for p in evidence.crawl_log if p.get("team_photos")]
    if photos:
        research_log["site_signals"] = {"team_photos": [
            {k: v for k, v in ph.items() if k != "summary"} for ph in photos]}
    fin_signals = None
    if seller is not None and finance_signals.SIGNAL in (seller.site_signals or []):
        fin_signals = finance_signals.merge_signals(
            [p[finance_signals.SIGNAL] for p in evidence.crawl_log
             if p.get(finance_signals.SIGNAL)],
            evidence.signal_hits.get("hiring"))
        # Recorded even when empty, so "looked, found nothing" can be told
        # apart from "couldn't look" (site unreadable, job search failed).
        job_q = [q for q in evidence.query_log if q.get("purpose") == "hiring_signal"]
        research_log.setdefault("site_signals", {})[finance_signals.SIGNAL] = (
            fin_signals or {
                "none_found": True,
                "pages_checked": sum(1 for p in evidence.crawl_log if p.get("ok")),
                "careers_pages_checked": sum(1 for p in evidence.crawl_log
                                             if p.get("careers_page") and p.get("ok")),
                "job_search_ok": bool(job_q) and not job_q[0].get("error"),
            })
    if not evidence.own_docs:
        warnings.append("could not read any page on the company's own website")

    gate, gate_warnings = run_gate(
        contact, company, evidence=evidence, llm=llm, min_seniority=min_seniority,
    )
    warnings.extend(gate_warnings)

    if not gate.worth_deepdive:
        warnings.append(f"short-circuited: {gate.rationale}")
        return ContactDossier(
            contact=contact, company=company, gate=gate,
            research_log=research_log, warnings=warnings,
            fetched_pages=_pages_dict(),
        )

    reach: list[ReachValue] = []
    try:
        reach = run_reach(contact, company, evidence.own_docs, evidence.linkedin_ref,
                          llm, verify_email=verify_email)
    except Exception as ex:
        warnings.append(f"reach track failed: {ex}")

    # Independent LLM calls run concurrently to keep the request well under
    # the server timeout: org starts now; background + rapport start as soon
    # as engagement has gathered the external evidence they also read.
    pool = ThreadPoolExecutor(max_workers=3)
    org_future = pool.submit(run_org_inference, contact, company,
                             evidence.own_docs + evidence.snippet_docs, llm)

    engagement: list[EngagementItem] = []
    eng_failed = False
    try:
        anchors = {
            "company": company.canonical_name,
            "title": contact.title,
            "city": company.city,
            "state": company.state,
            "known_urls": [e.get("url", "") for e in contact.evidence],
            "search_results": evidence.results,
            "purposes": evidence.purposes,
            "get_page": get_page,
            "seller": seller,
        }
        engagement = engagement_researcher.research(contact, company, anchors)
    except Exception as ex:
        eng_failed = True
        warnings.append(f"engagement track failed: {ex}")
    stats = dict(getattr(engagement_researcher, "last_stats", {}) or {})
    research_log["engagement"] = {
        "status": _engagement_status(engagement, stats, eng_failed), **stats,
    }

    # External evidence: the engagement researcher's fetched pages + snippets
    # when available (one fetch, many uses), else the raw search snippets.
    external_docs = getattr(engagement_researcher, "last_docs", None) or evidence.snippet_docs
    person_docs = evidence.own_docs + external_docs

    bg_future = pool.submit(run_background, contact, company, person_docs, llm,
                            seller=seller)
    rapport_future = pool.submit(run_rapport, contact, company, person_docs, llm,
                                 seller=seller)

    def _collect(future, label):
        try:
            return future.result()
        except Exception as ex:
            warnings.append(f"{label} track failed: {ex}")
            return []

    background: list[BackgroundFact] = _collect(bg_future, "background")
    rapport: list[RapportHook] = _collect(rapport_future, "rapport")
    org: list[OrgInference] = _collect(org_future, "org-inference")
    pool.shutdown(wait=False)

    # The outreach brief is OFF by default: users bring their own sales
    # approach and scrolled past it (Oct 2026). DOSSIER_OUTREACH_BRIEF=on (or
    # outreach_brief=True) brings it back; the dashboard would also need its
    # section restored.
    if outreach_brief is None:
        outreach_brief = os.environ.get("DOSSIER_OUTREACH_BRIEF", "off").strip().lower() in (
            "1", "on", "true", "yes")
    outreach: OutreachBrief | None = None
    try:
        if not outreach_brief:
            raise _SkipOutreach
        findings = {
            "company": {"name": company.canonical_name, "type": company.places_type,
                        "city": company.city, "state": company.state,
                        "website": company.website},
            "contact": {"name": contact.name, "title": contact.title},
            "currency": gate.currency,
            "background": [asdict(f) for f in background],
            "rapport": [asdict(h) for h in rapport],
            "engagement": [asdict(e) for e in engagement],
            "org": [asdict(o) for o in org],
            "reach_channels": sorted({r.kind for r in reach}),
            "engagement_status": research_log["engagement"]["status"],
        }
        if photos:
            findings["team_photos"] = [
                {k: v for k, v in ph.items() if k != "summary"} for ph in photos]
        if fin_signals:
            findings["finance_signals"] = fin_signals
        outreach = run_outreach(contact, company, llm, findings, seller=seller)
    except _SkipOutreach:
        pass
    except Exception as ex:
        warnings.append(f"outreach synthesis failed: {ex}")

    research_log["attribution"] = attribute_findings(
        evidence, company, background, engagement, rapport, outreach)

    return ContactDossier(
        contact=contact, company=company, gate=gate,
        reach=reach, background=background, engagement=engagement,
        org_inferences=org, rapport=rapport, outreach=outreach,
        research_log=research_log, warnings=warnings,
        fetched_pages=_pages_dict(),
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
    from fetch_and_extract import FetchResult

    contact = ContactCandidate(
        name="Jane Doe",
        title="Director of Operations",
        company="Acme Widgets",
        evidence=[{"url": "https://acmewidgets.com/",
                   "snippet": "Acme Widgets", "query": "..."}],
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
        rapport=[RapportHook("Runs the office 5K every spring", "community",
                             "https://acmewidgets.com/team",
                             "Ask how this year's race went")],
        outreach=OutreachBrief(
            angles=[OutreachAngle("Office refresh", "Saw the team page...",
                                  "Ties to facilities work",
                                  ["https://acmewidgets.com/team"])],
            likely_needs=["Facilities refresh after growth (hypothesis)"],
        ),
    )
    engagement = MockEngagementResearcher(items=[
        EngagementItem("https://example.com/post", "post",
                       "On modernizing facilities", "2026-05",
                       "Wrote about an office renovation.", "high",
                       "Directly relevant to a GC pitch."),
    ])

    search = MockSearchProvider(fixtures={"": [
        {"title": "Jane Doe - Acme Widgets", "url": "https://example.com/post",
         "snippet": "Jane Doe on modernizing facilities"},
    ]})

    class _StubFetcher:
        """Offline stand-in for PageFetcher (build_dossier calls .fetch(url))."""
        def fetch(self, url):
            pages = {
                "https://acmewidgets.com/": ("Home", "Welcome to Acme Widgets.",
                    [{"href": "https://acmewidgets.com/team", "text": "Meet the team"}]),
                "https://acmewidgets.com/team": ("Team",
                    "Jane Doe, Director of Operations. john.smith@acmewidgets.com", []),
            }
            if url not in pages:
                return FetchResult(url=url, ok=False, error="http_404")
            title, text, links = pages[url]
            return FetchResult(url=url, ok=True, final_url=url, status_code=200,
                               title=title, text=text, links=links)

    dossier = build_dossier(
        contact, company,
        search=search, fetcher=_StubFetcher(), llm=llm,
        engagement_researcher=engagement,
        seller=SellerContext("demo", "Demo Seller", "Sells widgets."),
    )
    print(json.dumps(dossier_to_dict(dossier), indent=2))
