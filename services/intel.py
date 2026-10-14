import json
import os
from urllib.parse import urlparse

from flask import current_app
from openai import OpenAI

MAX_CHARS = 14000

HIGH_VALUE_SLUGS = [
    "about", "services", "products", "contact", "team",
    "careers", "jobs", "capabilities", "industries", "solutions"
]

EXTRACTION_SCHEMA = {
    "schema": {
        "type": "object",
        "properties": {
            "company_summary":       {"type": "string", "description": "1-2 sentence summary of what the company does"},
            "products_services":     {"type": "string", "description": "Key products or services offered"},
            "estimated_size":        {"type": "string", "description": "Estimated company size (employees/revenue) if mentioned"},
            "target_customers":      {"type": "string", "description": "Who they sell to (B2B, B2C, industries served)"},
            "key_contacts":          {"type": "string", "description": "Any names/titles found (owner, manager, etc.)"},
            "technologies_used":     {"type": "string", "description": "Technologies, equipment, or software mentioned"},
            "recent_news":           {"type": "string", "description": "Any recent expansions, awards, or notable mentions"},
            "potential_pain_points": {"type": "string", "description": "Inferred challenges or needs based on their business type"},
            "outreach_angle":        {"type": "string", "description": "Suggested talking point for a sales rep reaching out"},
        },
        "required": [
            "company_summary", "products_services", "estimated_size",
            "target_customers", "key_contacts", "technologies_used",
            "recent_news", "potential_pain_points", "outreach_angle",
        ],
        "additionalProperties": False,
    }
}


# ── SCRAPING ──────────────────────────────────────────────────────────────────
#
# Uses the shared PageFetcher (robots, politeness delay, denylist) and the
# links it records BEFORE nav/header/footer are stripped. The old scraper
# removed the nav first and then looked for links, so menu-only pages like a
# salon's "Team" or a dealership's "Meet Our Staff" were never read and
# key_contacts came back "Unknown".

HOME_CHARS = 3500        # cap for the homepage, so it can't crowd out the rest
PAGE_CHARS = 2500        # cap for each other page
MAX_PAGES = 6            # pages read after the homepage


def _link_priority(link: dict) -> int:
    """People pages first (they feed key_contacts), then other useful pages."""
    from contact_discovery import score_people_link
    people = score_people_link(link)
    if people >= 2:
        return 10 + people
    blob = f"{link.get('text') or ''} {urlparse(link.get('href') or '').path}".lower()
    return 1 if any(slug in blob for slug in HIGH_VALUE_SLUGS) else 0


# Plain-English reasons a site couldn't be read (shown in the Summary).
_READ_FAILURES = {
    "ssl_error": "its security certificate doesn't match the address",
    "connection_error": "the site didn't respond",
    "timeout": "the site took too long to respond",
    "robots_disallowed": "the site asks automated tools not to read it (robots.txt)",
    "too_many_redirects": "the address redirects in a loop",
}


def _read_failure(fr) -> str:
    code = fr.error or fr.skipped_reason or "no readable text"
    if code.startswith("http_"):
        return f"the site returned an error ({code[5:]})"
    if code.startswith("non_text_content"):
        return "the address isn't a web page"
    return _READ_FAILURES.get(code, code)


def scrape_website(url: str, failure: list | None = None) -> str:
    """Text of the homepage and its most useful pages. On failure returns ""
    and, if ``failure`` is given, appends a plain-English reason to it."""
    if not url:
        if failure is not None:
            failure.append("no website on file")
        return ""
    from fetch_and_extract import PageFetcher
    fetcher = PageFetcher()

    home = fetcher.fetch(url)
    if not (home.ok and home.text):
        current_app.logger.warning(
            f"Scrape failed for {url}: {home.error or home.skipped_reason}")
        if failure is not None:
            failure.append(_read_failure(home))
        return ""
    host = urlparse(home.final_url or url).netloc.lower().removeprefix("www.")

    sections = [f"[Page: {home.final_url or url}]\n{home.text[:HOME_CHARS]}"]
    seen = {(home.final_url or url).split("#")[0].split("?")[0].rstrip("/").lower(),
            url.split("#")[0].split("?")[0].rstrip("/").lower()}
    candidates: dict[str, tuple[int, str]] = {}
    for link in home.links:
        href = link.get("href") or ""
        if urlparse(href).netloc.lower().removeprefix("www.") != host:
            continue
        key = href.split("#")[0].split("?")[0].rstrip("/").lower()
        if key in seen:
            continue
        prio = _link_priority(link)
        if prio > 0 and (key not in candidates or candidates[key][0] < prio):
            candidates[key] = (prio, href.split("#")[0])

    for _, href in sorted(candidates.values(), key=lambda t: -t[0])[:MAX_PAGES]:
        fr = fetcher.fetch(href)
        if fr.ok and fr.text:
            sections.append(f"[Page: {fr.final_url or href}]\n{fr.text[:PAGE_CHARS]}")
    return "\n\n".join(sections)[:MAX_CHARS]


# ── EXTRACTION ────────────────────────────────────────────────────────────────

def _seller_note() -> str:
    """Who the research is for (active searcher profile), so pain points and
    the outreach angle are about what THIS seller sells, not generic B2B."""
    try:
        from active_profile import get_active_profile
        prof = get_active_profile()
        return (f"The research is for this seller: {prof.display_name} -- "
                f"{prof.description}\n"
                "Write potential_pain_points and outreach_angle about what THIS "
                "seller offers; do not suggest products the seller doesn't sell.\n")
    except Exception:
        return ""


def extract_intel(name: str, address: str, raw_text: str, read_failure: str = "") -> dict:
    client = OpenAI(api_key=current_app.config["OPENAI_API_KEY"])
    if raw_text:
        content = raw_text
    else:
        # Without the site, the model used to guess ("If this is an owner-run
        # dental practice...") for a 7-practice dental group. Say plainly that
        # the site wasn't read, and don't guess the seller-facing fields.
        content = (
            "[The website could not be read"
            + (f": {read_failure}" if read_failure else "") + ".]\n"
            "Start company_summary with \"Website not read ("
            + (read_failure or "no content") + ").\" and then say only what the "
            "name and address support. Set potential_pain_points and "
            "outreach_angle to \"Unknown -- the website couldn't be read; "
            "re-run Enrich once it can be.\" Set key_contacts to \"Unknown\". "
            "Do not guess the business's size, structure or needs."
        )

    prompt = f"""
You are a B2B sales researcher. Given the following scraped website content for a business,
extract structured intelligence useful for a sales rep.
{_seller_note()}
Business Name: {name}
Address: {address}
Website Content (several pages, each starting with [Page: url]):
{content}

For key_contacts, list the people the pages name with their titles, most senior or
most relevant to the seller first (up to 10), e.g. "Jane Doe (General Manager);
John Roe (Marketing Director)". If the pages give only first names, list those.

Return ONLY the structured fields. If a field cannot be determined, return "Unknown".
"""

    resp = client.responses.create(
        # Sol on low reasoning: near-flagship quality for the summary and the
        # seller-aware angle without paying for deliberation the reading
        # doesn't need. Overridable via ENRICH_MODEL / ENRICH_REASONING_EFFORT.
        model=os.environ.get("ENRICH_MODEL") or "gpt-6.1-sol",
        reasoning={"effort": os.environ.get("ENRICH_REASONING_EFFORT") or "low"},
        input=[{"role": "user", "content": prompt}],
        text={
            "format": {
                "type": "json_schema",
                "name": "business_intel",
                "schema": EXTRACTION_SCHEMA["schema"],
                "strict": True,
            }
        },
        max_output_tokens=2048,
    )

    try:
        msg = next(o for o in resp.output if getattr(o, "type", None) == "message")
        content_item = msg.content[0]
        if hasattr(content_item, "text") and content_item.text:
            return json.loads(content_item.text)
    except Exception as e:
        current_app.logger.error(f"Failed to parse OpenAI response: {e}")

    return {}


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def enrich_business(business) -> dict:
    """
    Top-level function called by the API route.
    Accepts a Business model instance, returns intel dict.
    """
    failure: list[str] = []
    raw_text = scrape_website(business.website, failure)
    intel = extract_intel(business.name, business.formatted_address, raw_text,
                          read_failure=failure[0] if failure else "")

    if not isinstance(intel, dict):
        current_app.logger.warning(f"extract_intel returned non-dict for {business.name}")
        intel = {}

    return intel
