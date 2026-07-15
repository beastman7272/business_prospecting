"""
fetch_and_extract
=================

Shared page-fetching + content-extraction component for the prospecting app.

Both Stage 2 (contact discovery) and Stage 3 (contact deep-dive) need to read
the *body* of a web page, not just the search-result snippet: the fact that
matters (a name and title on a leadership page, a "started a new role" post
date, an email in a footer) usually lives in the page text, not the ~160
character description a search API returns.

This module is deliberately:

  * **Deterministic and backend-agnostic.** It is pure HTTP + HTML-to-text.
    It calls no LLM and needs no API key, so it works regardless of whether
    downstream extraction uses Gemini, OpenAI, or anything else. The LLM step
    that turns page text into structured people/facts stays with each stage
    (it consumes ``FetchResult.text``); this component stops at clean text.

  * **The single home for crawl policy.** The LinkedIn denylist, robots.txt
    respect, timeouts, response-size caps, and per-host rate limiting all live
    here, in one place, so the boundaries the project agreed to (e.g. "read
    LinkedIn content that a search engine indexed, but do not fetch LinkedIn
    directly") are enforced by construction rather than re-implemented per
    stage and allowed to drift.

  * **Failure-tolerant.** Expected problems (a denylisted host, a robots
    disallow, a timeout, a non-HTML response, a 404) never raise — they come
    back as a ``FetchResult`` with ``ok=False`` and a ``skipped_reason`` or
    ``error``, so one bad URL never kills a run. This mirrors the "log and
    keep going" philosophy already used in the Stage 2 search loop.

Every ``FetchResult`` carries a ``fetched_at`` UTC timestamp, so downstream
staleness logic has a real provenance date to work with.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Defaults / policy
# -----------------------------------------------------------------------------

# A descriptive User-Agent is good crawling etiquette and lets site owners
# identify the traffic. Replace the contact address with a real one.
DEFAULT_USER_AGENT = (
    "ProspectingResearchBot/1.0 "
    "(+contact: replace-me@example.com; purpose: B2B sales research)"
)

# Hosts we must never fetch directly, regardless of what links to them.
# LinkedIn is the load-bearing entry (project constraint: content indexed by a
# search engine is fine to read, but scraping LinkedIn directly is not). The
# others are ToS-protected social platforms in the same category; reading them
# via a search engine's index is fine, hitting them directly is not.
DEFAULT_DENYLIST: frozenset[str] = frozenset({
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
})

# Only these content types are parsed for text. Anything else (PDF, images,
# JSON, etc.) is skipped with a reason. PDF handling could be added later as a
# separate branch; it is intentionally out of scope here.
DEFAULT_TEXT_CONTENT_TYPES: frozenset[str] = frozenset({
    "text/html",
    "application/xhtml+xml",
    "text/plain",
})


@dataclass
class FetchPolicy:
    """All tunable crawl behaviour in one place."""
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 15.0                 # seconds per request
    max_bytes: int = 2_000_000            # cap on bytes read per page (~2 MB)
    min_interval_per_host: float = 1.0    # politeness delay between hits/host
    respect_robots: bool = True
    denylisted_domains: frozenset[str] = DEFAULT_DENYLIST
    allowed_content_types: frozenset[str] = DEFAULT_TEXT_CONTENT_TYPES
    # If robots.txt can't be fetched/parsed, allow the fetch (standard crawler
    # behaviour). Set False to fail closed instead.
    assume_allow_on_robots_error: bool = True


# -----------------------------------------------------------------------------
# Result type
# -----------------------------------------------------------------------------

@dataclass
class FetchResult:
    """
    Outcome of attempting to fetch one URL.

    On success: ok=True, text holds the cleaned main text, title holds the
    page <title>. On any expected failure: ok=False with either
    skipped_reason (we chose not to fetch) or error (the fetch was attempted
    and failed). Never both.
    """
    url: str                              # the URL we were asked to fetch
    ok: bool = False
    final_url: str | None = None          # after redirects
    status_code: int | None = None
    content_type: str | None = None
    title: str | None = None
    text: str = ""
    truncated: bool = False               # hit max_bytes before the page ended
    skipped_reason: str | None = None     # e.g. "denylisted:linkedin.com"
    error: str | None = None              # e.g. "timeout", "connection_error"
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


# -----------------------------------------------------------------------------
# HTML -> text extraction
# -----------------------------------------------------------------------------

# Elements whose contents are never useful body text.
_NON_CONTENT_TAGS = [
    "script", "style", "noscript", "template", "svg",
    "nav", "header", "footer", "aside", "form",
]


def _clean_with_bs4(html: str) -> tuple[str | None, str]:
    """Preferred path: BeautifulSoup (already a project dependency)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    for tag in soup(_NON_CONTENT_TAGS):
        tag.decompose()

    text = soup.get_text(separator="\n")
    return title, _collapse_whitespace(text)


def _clean_with_stdlib(html: str) -> tuple[str | None, str]:
    """
    Fallback path using only the standard library, so the component still
    works if BeautifulSoup is ever unavailable.
    """
    from html.parser import HTMLParser

    class _Extractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.title_parts: list[str] = []
            self._skip_depth = 0
            self._in_title = False

        def handle_starttag(self, tag, attrs):
            if tag in _NON_CONTENT_TAGS:
                self._skip_depth += 1
            elif tag == "title":
                self._in_title = True

        def handle_endtag(self, tag):
            if tag in _NON_CONTENT_TAGS and self._skip_depth > 0:
                self._skip_depth -= 1
            elif tag == "title":
                self._in_title = False

        def handle_data(self, data):
            if self._in_title:
                self.title_parts.append(data)
            elif self._skip_depth == 0:
                self.parts.append(data)

    parser = _Extractor()
    try:
        parser.feed(html)
    except Exception:  # malformed HTML shouldn't crash the run
        logger.debug("stdlib HTML parse hit an error; returning partial text")

    title = _collapse_whitespace("".join(parser.title_parts)) or None
    text = _collapse_whitespace("\n".join(parser.parts))
    return title, text


def _collapse_whitespace(text: str) -> str:
    """Collapse runs of blank lines and trailing spaces into tidy text."""
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")           # keep a single blank line as a separator
            blank = True
    return "\n".join(out).strip()


def extract_main_text(html: str) -> tuple[str | None, str]:
    """
    Turn raw HTML into (title, clean_text). Uses BeautifulSoup if available,
    otherwise a stdlib parser. Never raises on bad markup.
    """
    try:
        return _clean_with_bs4(html)
    except ImportError:
        return _clean_with_stdlib(html)
    except Exception:
        logger.debug("bs4 extraction failed; falling back to stdlib parser")
        return _clean_with_stdlib(html)


# -----------------------------------------------------------------------------
# Fetcher
# -----------------------------------------------------------------------------

def _normalize_url(url: str) -> str:
    """Lowercase scheme/host and drop the fragment, for dedupe and caching."""
    p = urlparse(url)
    return urlunparse((
        p.scheme.lower(),
        p.netloc.lower(),
        p.path or "/",
        p.params,
        p.query,
        "",  # strip fragment
    ))


class PageFetcher:
    """
    Fetches pages under a shared FetchPolicy: denylist, robots.txt, rate
    limiting, timeouts, size caps, and content-type filtering all applied
    centrally. Thread-safe rate limiting so it can be parallelised later.
    """

    def __init__(
        self,
        policy: FetchPolicy | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.policy = policy or FetchPolicy()
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": self.policy.user_agent})
        self._last_hit: dict[str, float] = {}
        self._robots_cache: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    # --- policy checks ------------------------------------------------------

    def denylisted_domain(self, url: str) -> str | None:
        """Return the matched denylisted domain, or None if allowed."""
        host = urlparse(url).netloc.lower()
        # strip a port if present
        host = host.split(":", 1)[0]
        for domain in self.policy.denylisted_domains:
            if host == domain or host.endswith("." + domain):
                return domain
        return None

    def _robots_allows(self, url: str) -> bool:
        if not self.policy.respect_robots:
            return True
        p = urlparse(url)
        host = p.netloc.lower()
        rp = self._get_robots(p.scheme, host)
        if rp is None:  # couldn't get/parse robots -> policy decides
            return self.policy.assume_allow_on_robots_error
        try:
            return rp.can_fetch(self.policy.user_agent, url)
        except Exception:
            return self.policy.assume_allow_on_robots_error

    def _get_robots(self, scheme: str, host: str) -> RobotFileParser | None:
        if host in self._robots_cache:
            return self._robots_cache[host]
        rp: RobotFileParser | None = RobotFileParser()
        robots_url = f"{scheme}://{host}/robots.txt"
        try:
            resp = self._session.get(robots_url, timeout=self.policy.timeout)
            if resp.status_code >= 400:
                # 404/410 etc. conventionally mean "no restrictions".
                rp = None
            else:
                rp.parse(resp.text.splitlines())
        except Exception:
            rp = None  # unreachable robots -> handled by assume_allow flag
        self._robots_cache[host] = rp
        return rp

    def _respect_rate_limit(self, host: str) -> None:
        with self._lock:
            last = self._last_hit.get(host)
            now = time.monotonic()
            if last is not None:
                wait = self.policy.min_interval_per_host - (now - last)
                if wait > 0:
                    time.sleep(wait)
            self._last_hit[host] = time.monotonic()

    # --- fetching -----------------------------------------------------------

    def fetch(self, url: str) -> FetchResult:
        """Fetch one URL, applying all policy. Never raises on expected errors."""
        result = FetchResult(url=url)

        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            result.skipped_reason = f"unsupported_scheme:{p.scheme or 'none'}"
            return result

        denied = self.denylisted_domain(url)
        if denied:
            result.skipped_reason = f"denylisted:{denied}"
            logger.info("skip (denylisted %s): %s", denied, url)
            return result

        if not self._robots_allows(url):
            result.skipped_reason = "robots_disallowed"
            logger.info("skip (robots): %s", url)
            return result

        host = p.netloc.lower()
        self._respect_rate_limit(host)

        try:
            resp = self._session.get(
                url,
                timeout=self.policy.timeout,
                stream=True,
                allow_redirects=True,
            )
        except requests.exceptions.Timeout:
            result.error = "timeout"
            return result
        except requests.exceptions.TooManyRedirects:
            result.error = "too_many_redirects"
            return result
        except requests.exceptions.ConnectionError:
            result.error = "connection_error"
            return result
        except requests.exceptions.RequestException as e:
            result.error = f"request_error:{type(e).__name__}"
            return result

        with resp:
            result.final_url = resp.url
            result.status_code = resp.status_code
            content_type = (resp.headers.get("Content-Type") or "").lower()
            result.content_type = content_type or None

            if resp.status_code >= 400:
                result.error = f"http_{resp.status_code}"
                return result

            base_type = content_type.split(";", 1)[0].strip()
            if base_type and base_type not in self.policy.allowed_content_types:
                result.skipped_reason = f"non_text_content:{base_type}"
                return result

            raw, truncated = self._read_capped(resp)
            result.truncated = truncated

            encoding = resp.encoding or resp.apparent_encoding or "utf-8"
            try:
                html = raw.decode(encoding, errors="replace")
            except (LookupError, TypeError):
                html = raw.decode("utf-8", errors="replace")

        title, text = extract_main_text(html)
        result.title = title
        result.text = text
        result.ok = True
        return result

    def _read_capped(self, resp: requests.Response) -> tuple[bytes, bool]:
        """Read up to max_bytes; return (data, truncated)."""
        chunks: list[bytes] = []
        total = 0
        truncated = False
        for chunk in resp.iter_content(chunk_size=16_384):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= self.policy.max_bytes:
                truncated = True
                break
        return b"".join(chunks), truncated

    def fetch_many(
        self,
        urls: list[str],
        dedupe: bool = True,
    ) -> list[FetchResult]:
        """
        Fetch several URLs sequentially (honouring the per-host rate limit).
        With dedupe=True, normalized-duplicate URLs are fetched only once.
        """
        results: list[FetchResult] = []
        seen: set[str] = set()
        for url in urls:
            key = _normalize_url(url) if dedupe else url
            if dedupe and key in seen:
                continue
            seen.add(key)
            results.append(self.fetch(url))
        return results


def make_default_fetcher() -> PageFetcher:
    """Convenience constructor with default policy."""
    return PageFetcher()


# -----------------------------------------------------------------------------
# Demo. Policy decisions (denylist, scheme) need no network; the live fetch at
# the end is guarded so it degrades gracefully offline.
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    fetcher = make_default_fetcher()

    print("=== Policy decisions (no network needed) ===")
    for url in [
        "https://www.linkedin.com/in/some-person",   # denylisted
        "ftp://example.com/file",                     # bad scheme
        "https://example.com/team",                   # allowed (would fetch)
    ]:
        denied = fetcher.denylisted_domain(url)
        scheme = urlparse(url).scheme
        verdict = (
            f"DENYLISTED ({denied})" if denied
            else "BAD SCHEME" if scheme not in ("http", "https")
            else "allowed"
        )
        print(f"  {verdict:<22} {url}")

    print("\n=== HTML -> text on a sample string (no network) ===")
    sample = (
        "<html><head><title>  Our Team </title></head>"
        "<body><nav>Home About</nav>"
        "<h1>Leadership</h1>"
        "<p>Jane Doe, Director of Operations.</p>"
        "<script>var x=1;</script>"
        "<footer>Copyright 2026</footer></body></html>"
    )
    title, text = extract_main_text(sample)
    print(f"  title: {title!r}")
    print(f"  text:  {text!r}")

    print("\n=== Live fetch (needs network; fails gracefully) ===")
    live = fetcher.fetch("https://example.com/")
    print(f"  ok={live.ok} status={live.status_code} "
          f"truncated={live.truncated} error={live.error} "
          f"skipped={live.skipped_reason}")
    print(f"  title: {live.title!r}")
    print(f"  fetched_at: {live.fetched_at}")
    if live.text:
        print(f"  text[:200]: {live.text[:200]!r}")
