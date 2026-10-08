"""
Stage 2: Contact Discovery -- rewired onto the (segment x searcher) lookup.

Given a company and its Google Places type, plus an ACTIVE SEARCHER PROFILE,
find candidate contacts whose roles match what that searcher should target.

Pipeline:
  1. Resolve segment(s) from Places type          (places_mapping)
  2. (Optional) disambiguate chain vs. independent
  3. Resolve (segment x profile) -> ResolvedPlay   (searcher_profiles.base)
     -- ranked role keys + rationale + tactics. If the profile does not cover
        the segment (a legitimate "I don't sell to these" skip), return an
        empty run with a warning instead of guessing.
  4. Generate search queries from the play's tactics + ranked roles (role keys
     expanded to display + aliases via the role catalog)
  5. Execute searches
  6. Extract person candidates via LLM (prompted with the searcher's angle)
  7. Consolidate and rank (priority from the play's role order)

Difference from the original: nothing about "who to contact" is hardcoded to a
general contractor anymore. Swap the profile and the same pipeline prospects for
an accountant, attorney, handyman, etc.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any

from target_segments import TargetSegment, SEGMENTS
from places_mapping import get_segment_for_places_type
from searcher_profiles.base import SearcherProfile, ResolvedPlay, effective_play
from roles import search_terms


# -----------------------------------------------------------------------------
# Data structures
# -----------------------------------------------------------------------------

@dataclass
class CompanyInput:
    canonical_name: str
    input_name: str
    city: str
    state: str
    places_type: str
    website: str | None = None
    domain: str | None = None
    phone: str | None = None
    address: str | None = None


@dataclass
class SearchQuery:
    query: str
    target_role: str           # role key this query hunts for ("(company-wide)" for tactics)
    tactic_template: str
    source_segment: str
    source_searcher: str


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    query: str


@dataclass
class ContactCandidate:
    name: str
    title: str | None
    company: str
    evidence: list[dict[str, str]] = field(default_factory=list)
    confidence: str = "low"
    why_relevant: str = ""


@dataclass
class DiscoveryRun:
    company: CompanyInput
    searcher_used: str
    segments_used: list[str]
    queries: list[SearchQuery]
    raw_results: list[SearchResult]
    candidates: list[ContactCandidate]
    warnings: list[str] = field(default_factory=list)
    fetched_pages: list[dict] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Step 1-2: Resolve and disambiguate segment (searcher-agnostic)
# -----------------------------------------------------------------------------

def resolve_segment(
    company: CompanyInput,
    chain_check_fn=None,
) -> tuple[TargetSegment | None, list[str]]:
    warnings: list[str] = []
    candidates = get_segment_for_places_type(company.places_type)

    if not candidates:
        warnings.append(
            f"No segment mapping for Places type '{company.places_type}'. "
            f"Falling back to professional_services_office."
        )
        return SEGMENTS["professional_services_office"], warnings

    if len(candidates) == 1:
        return candidates[0], warnings

    if chain_check_fn is not None:
        is_chain = chain_check_fn(company)
        # Convention: first candidate in the mapping is the chain segment.
        return (candidates[0] if is_chain else candidates[1]), warnings

    warnings.append(
        f"Places type '{company.places_type}' is ambiguous (chain vs "
        f"independent); no chain_check_fn provided. Defaulting to "
        f"{candidates[0].segment_id}."
    )
    return candidates[0], warnings


# -----------------------------------------------------------------------------
# Step 3: Resolve (segment x profile) -> ResolvedPlay
# -----------------------------------------------------------------------------

def resolve_play(
    profile: SearcherProfile,
    segment: TargetSegment,
) -> tuple[ResolvedPlay | None, list[str]]:
    """
    Look up how THIS searcher plays THIS segment. None (with a warning) means
    the searcher deliberately doesn't target this kind of business -- callers
    should short-circuit to an empty run rather than invent contacts.
    """
    play = effective_play(profile, segment.segment_id)
    if play is None:
        return None, [
            f"Searcher '{profile.searcher_id}' does not target segment "
            f"'{segment.segment_id}' -- skipping (no contacts sought)."
        ]
    return play, []


# -----------------------------------------------------------------------------
# Step 4: Query generation (from the play, not the segment)
# -----------------------------------------------------------------------------

def _role_or_group(role_key: str, max_terms: int = 4) -> str:
    """Build an OR group of a role's display + aliases for one quoted query.

    Coarse role keys collapsed many title variants onto one key; ORing the
    variants back together covers them all in a SINGLE query instead of one
    query per hand-written variant (what the old per-string list did).
    """
    terms = search_terms(role_key)[:max_terms]
    return " OR ".join(f'"{t}"' for t in terms)


def generate_queries(
    company: CompanyInput,
    play: ResolvedPlay,
) -> list[SearchQuery]:
    queries: list[SearchQuery] = []

    company_subs = {
        "{company}": company.canonical_name,
        "{domain}": company.domain or "",
        "{city}": company.city,
        "{state}": company.state,
        "{address}": company.address or "",
    }

    # A) Company-wide queries from the searcher's tactics for this segment.
    for tactic in play.search_tactics:
        if "{domain}" in tactic and not company.domain:
            continue
        if "{role}" in tactic:
            continue
        q = tactic
        for placeholder, value in company_subs.items():
            q = q.replace(placeholder, value)
        queries.append(SearchQuery(
            query=q,
            target_role="(company-wide)",
            tactic_template=tactic,
            source_segment=play.segment_id,
            source_searcher=play.searcher_id,
        ))

    # B) Per-role, location-anchored queries -- ranked roles first, probes last
    #    (effective_play already orders them that way).
    for rr in play.roles:
        role_group = _role_or_group(rr.role.key)
        per_role_q = f'"{company.canonical_name}" ({role_group}) "{company.city}"'
        queries.append(SearchQuery(
            query=per_role_q,
            target_role=rr.role.key,
            tactic_template='"{company}" ({role display OR aliases}) "{city}"',
            source_segment=play.segment_id,
            source_searcher=play.searcher_id,
        ))

    # Deduplicate, preserving order.
    seen: set[str] = set()
    unique: list[SearchQuery] = []
    for q in queries:
        if q.query not in seen:
            seen.add(q.query)
            unique.append(q)
    return unique


# -----------------------------------------------------------------------------
# Step 4b: Search execution (unchanged, provider-agnostic)
# -----------------------------------------------------------------------------

class SearchProvider:
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError


class BraveSearchProvider(SearchProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError("BRAVE_SEARCH_API_KEY not set")

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        import requests
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json",
                     "X-Subscription-Token": self.api_key},
            params={"q": query, "count": max_results},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            SearchResult(title=r.get("title", ""), url=r.get("url", ""),
                         snippet=r.get("description", ""), query=query)
            for r in (data.get("web", {}).get("results") or [])[:max_results]
        ]


class MockSearchProvider(SearchProvider):
    def __init__(self, fixtures: dict[str, list[dict[str, str]]] | None = None):
        self.fixtures = fixtures or {}

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raw = self.fixtures.get(query, [])
        if not raw:
            for k, v in self.fixtures.items():
                if k in query or query in k:
                    raw = v
                    break
        return [
            SearchResult(title=r.get("title", ""), url=r.get("url", ""),
                         snippet=r.get("snippet", ""), query=query)
            for r in raw[:max_results]
        ]


def execute_searches(
    queries: list[SearchQuery],
    provider: SearchProvider,
    max_results_per_query: int = 5,
) -> list[SearchResult]:
    all_results: list[SearchResult] = []
    for q in queries:
        try:
            all_results.extend(provider.search(q.query, max_results=max_results_per_query))
        except Exception as e:
            print(f"[warn] search failed for {q.query!r}: {e}")
    return all_results


# -----------------------------------------------------------------------------
# Step 5: Candidate extraction (LLM) -- now prompted with the searcher's angle
# -----------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are helping a {searcher} identify the right person to contact at a target business.

The target company is: {company_name}
Located in: {city}, {state}
Type of business: {places_description}

This searcher's angle on this kind of business: {sales_rationale}

The searcher wants the decision-maker or influencer for that angle. The most likely relevant roles, in priority order, are:

{ranked_roles}

Below are search result snippets. Extract every person mentioned by name who appears to be associated with {company_name}. For each person, return:
- name: the person's name
- title: their role/title if stated or strongly implied (null if not)
- evidence_idx: list of indices of the result snippets that mention them
- confidence: "high" if the snippet directly states their role at this company; "medium" if clearly implied; "low" if inferred
- why_relevant: one short sentence on why this searcher would want to contact them, given the roles above. If not relevant, say so.

Return ONLY a JSON array, no other text. If no people are mentioned, return [].

Search results:
{results_block}
"""


class LLMExtractor:
    def extract(self, company: CompanyInput, segment: TargetSegment,
                play: ResolvedPlay, results: list[SearchResult]) -> list[ContactCandidate]:
        raise NotImplementedError


class GeminiExtractor(LLMExtractor):
    def __init__(self, api_key: str | None = None, model: str = "gemini-3.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set")
        self.model = model

    def extract(self, company, segment, play, results):
        import requests
        if not results:
            return []

        results_block = "\n".join(
            f"[{i}] {r.title}\n    {r.snippet}\n    ({r.url})"
            for i, r in enumerate(results)
        )
        ranked_roles = "\n".join(
            f"- {rr.role.display}" + (" (speculative probe)" if rr.is_probe else "")
            for rr in play.roles
        )
        prompt = EXTRACTION_PROMPT.format(
            searcher=play.searcher_display,
            company_name=company.canonical_name,
            city=company.city, state=company.state,
            places_description=segment.description,
            sales_rationale=play.sales_rationale or "(general prospecting)",
            ranked_roles=ranked_roles,
            results_block=results_block,
        )
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.api_key}")
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.1,
                                       "responseMimeType": "application/json"}},
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            print(f"[warn] LLM returned non-JSON: {text[:200]}")
            return []
        return _parse_llm_candidates(parsed, company.canonical_name, results)


class MockExtractor(LLMExtractor):
    def __init__(self, canned: list[ContactCandidate]):
        self.canned = canned

    def extract(self, company, segment, play, results):
        return self.canned


def _parse_llm_candidates(parsed, company_name, results):
    candidates: list[ContactCandidate] = []
    for entry in parsed:
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        evidence = []
        for idx in entry.get("evidence_idx") or []:
            if isinstance(idx, int) and 0 <= idx < len(results):
                r = results[idx]
                evidence.append({"url": r.url, "snippet": r.snippet, "query": r.query})
        candidates.append(ContactCandidate(
            name=entry["name"], title=entry.get("title"), company=company_name,
            evidence=evidence, confidence=entry.get("confidence", "low"),
            why_relevant=entry.get("why_relevant", ""),
        ))
    return candidates


# -----------------------------------------------------------------------------
# Step 6: Consolidation (unchanged)
# -----------------------------------------------------------------------------

def consolidate(candidates: list[ContactCandidate]) -> list[ContactCandidate]:
    clusters: dict[str, list[ContactCandidate]] = {}
    for c in candidates:
        clusters.setdefault(c.name.lower().strip(), []).append(c)

    merged: list[ContactCandidate] = []
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    for cluster in clusters.values():
        if len(cluster) == 1:
            merged.append(cluster[0])
            continue
        base = max(cluster, key=lambda c: (confidence_rank.get(c.confidence, 0),
                                           len(c.evidence)))
        by_url: dict[str, dict[str, str]] = {}

        def _consider(entry):
            u = entry.get("url", "")
            existing = by_url.get(u)
            if existing is None or len(entry.get("snippet", "")) > len(existing.get("snippet", "")):
                by_url[u] = entry

        for e in base.evidence:
            _consider(e)
        for other in cluster:
            if other is base:
                continue
            for e in other.evidence:
                _consider(e)
            if not base.title and other.title:
                base.title = other.title
        base.evidence = list(by_url.values())
        merged.append(base)
    return merged


# -----------------------------------------------------------------------------
# Step 7: Ranking (priority from the play's role order + keyword overlap)
# -----------------------------------------------------------------------------

def _get_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def normalize_domain(domain: str | None) -> str:
    if not domain:
        return ""
    from urllib.parse import urlparse
    d = domain.strip().lower()
    if "://" in d:
        parsed = urlparse(d)
        d = parsed.netloc or parsed.path
    d = d.split("/", 1)[0].split(":", 1)[0]
    return d[4:] if d.startswith("www.") else d


def _own_domain_score(candidate: ContactCandidate, company_domain: str | None) -> int:
    if not company_domain:
        return 0
    nd = normalize_domain(company_domain)
    return sum(1 for e in candidate.evidence if _get_domain(e.get("url", "")) == nd)


def rank(
    candidates: list[ContactCandidate],
    play: ResolvedPlay,
    company_domain: str | None = None,
) -> list[ContactCandidate]:
    """
    Confidence first, then own-domain evidence, then role relevance (priority
    from the play's ranked-role ORDER, with keyword overlap against each role's
    display + aliases), then evidence count. Probe roles sit last in play.roles,
    so they naturally carry the lowest role weight.
    """
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    n = len(play.roles)

    def role_keyword_score(title: str) -> int:
        title_words = set(title.lower().replace("/", " ").split())
        best = 0
        for i, rr in enumerate(play.roles):
            role_words: set[str] = set()
            for term in search_terms(rr.role.key):
                role_words |= set(term.lower().replace("/", " ").split())
            overlap = len(title_words & role_words)
            if overlap > 0:
                best = max(best, overlap * (n - i))
        return best

    def score(c: ContactCandidate):
        return (confidence_rank.get(c.confidence, 0),
                _own_domain_score(c, company_domain),
                role_keyword_score(c.title or ""),
                len(c.evidence))

    return sorted(candidates, key=score, reverse=True)


# -----------------------------------------------------------------------------
# Optional own-domain page fetch (lazy import so fetch_and_extract isn't required)
# -----------------------------------------------------------------------------

# Pages on a small business's own site that usually name its people. Fetched
# directly from the known website, so discovery still reads the site when no
# own-domain page ranks in the search results (common for small firms).
OWN_DOMAIN_SEED_PATHS = ("", "about", "about-us", "team", "our-team", "contact")


def _own_domain_seed_urls(company) -> list[str]:
    from urllib.parse import urljoin, urlparse
    base = (company.website or "").strip()
    if not base:
        dom = normalize_domain(company.domain)
        if not dom:
            return []
        base = f"https://{dom}"
    if "://" not in base:
        base = "https://" + base
    parsed = urlparse(base)
    root = f"{parsed.scheme}://{parsed.netloc}/"
    return [urljoin(root, p) for p in OWN_DOMAIN_SEED_PATHS]


def fetch_own_domain_pages(company, raw_results, fetcher, max_pages=8, per_page_chars=6000):
    dom = normalize_domain(company.domain)
    if not dom:
        return [], []
    urls, seen = [], set()
    # Own-domain pages surfaced by search first (they matched a role query),
    # then the seed pages on the known website.
    candidates = [r.url for r in raw_results if _get_domain(r.url) == dom]
    candidates += _own_domain_seed_urls(company)
    for url in candidates:
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append(url)
        if len(urls) >= max_pages:
            break
    if not urls:
        return [], []
    fetched = fetcher.fetch_many(urls)
    page_results, seen_final = [], set()
    for fr in fetched:
        if not (fr.ok and fr.text):
            continue
        final = (fr.final_url or fr.url).rstrip("/").lower()
        if final in seen_final:      # e.g. /about-us redirecting to /about
            continue
        seen_final.add(final)
        page_results.append(SearchResult(
            title=fr.title or "", url=fr.final_url or fr.url,
            snippet=fr.text[:per_page_chars], query="(own-domain page fetch)"))
    return page_results, fetched


# -----------------------------------------------------------------------------
# Top-level pipeline
# -----------------------------------------------------------------------------

def discover_contacts(
    company: CompanyInput,
    profile: SearcherProfile,
    search_provider: SearchProvider,
    extractor: LLMExtractor,
    chain_check_fn=None,
    max_results_per_query: int = 5,
    fetch_own_domain: bool = False,
    page_fetcher=None,
    max_own_domain_pages: int = 8,
    per_page_chars: int = 6000,
) -> DiscoveryRun:
    segment, warnings = resolve_segment(company, chain_check_fn=chain_check_fn)

    play, play_warnings = resolve_play(profile, segment)
    warnings += play_warnings
    if play is None:
        # Searcher doesn't target this segment -- return an empty, honest run.
        return DiscoveryRun(
            company=company, searcher_used=profile.searcher_id,
            segments_used=[segment.segment_id], queries=[], raw_results=[],
            candidates=[], warnings=warnings,
        )

    queries = generate_queries(company, play)
    raw_results = execute_searches(queries, search_provider,
                                   max_results_per_query=max_results_per_query)
    raw_candidates = extractor.extract(company, segment, play, raw_results)

    fetched_pages: list[dict] = []
    if fetch_own_domain and company.domain:
        if page_fetcher is None:
            from fetch_and_extract import PageFetcher  # lazy: optional dependency
            page_fetcher = PageFetcher()
        page_results, fetched = fetch_own_domain_pages(
            company, raw_results, page_fetcher,
            max_pages=max_own_domain_pages, per_page_chars=per_page_chars,
        )
        fetched_pages = [fr.to_dict() for fr in fetched]
        if page_results:
            raw_candidates += extractor.extract(company, segment, play, page_results)
        else:
            warnings.append("Couldn't read any pages on the company's own website.")

    consolidated = consolidate(raw_candidates)
    ranked = rank(consolidated, play, company_domain=company.domain)
    return DiscoveryRun(
        company=company, searcher_used=profile.searcher_id,
        segments_used=[segment.segment_id], queries=queries,
        raw_results=raw_results, candidates=ranked, warnings=warnings,
        fetched_pages=fetched_pages,
    )


def run_to_dict(run: DiscoveryRun) -> dict[str, Any]:
    return {
        "company": asdict(run.company),
        "searcher_used": run.searcher_used,
        "segments_used": run.segments_used,
        "queries": [asdict(q) for q in run.queries],
        "raw_results_count": len(run.raw_results),
        "raw_results": [asdict(r) for r in run.raw_results],
        "candidates": [asdict(c) for c in run.candidates],
        "warnings": run.warnings,
        "fetched_pages": run.fetched_pages,
    }
