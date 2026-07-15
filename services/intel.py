import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import current_app
from openai import OpenAI

SCRAPE_DELAY = 0.5
MAX_CHARS = 10000

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

def _fetch_page(url: str, visited: set) -> tuple[str, object]:
    if url in visited:
        return "", None
    visited.add(url)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ProspectBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True))
        return text, soup
    except Exception as e:
        current_app.logger.warning(f"Scrape failed for {url}: {e}")
        return "", None


def scrape_website(url: str) -> str:
    if not url:
        return ""

    visited = set()
    collected = []

    base_domain = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    text, soup = _fetch_page(url, visited)
    if text:
        collected.append(text)

    if soup:
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].lower()
            full_url = urljoin(base_domain, a_tag["href"])
            if urlparse(full_url).netloc == urlparse(url).netloc:
                if any(slug in href for slug in HIGH_VALUE_SLUGS):
                    page_text, _ = _fetch_page(full_url, visited)
                    if page_text:
                        collected.append(page_text)
                        time.sleep(SCRAPE_DELAY)

    combined = " ".join(collected)
    return combined[:MAX_CHARS]


# ── EXTRACTION ────────────────────────────────────────────────────────────────

def extract_intel(name: str, address: str, raw_text: str) -> dict:
    client = OpenAI(api_key=current_app.config["OPENAI_API_KEY"])

    prompt = f"""
You are a B2B sales researcher. Given the following scraped website content for a business,
extract structured intelligence useful for a sales rep.

Business Name: {name}
Address: {address}
Website Content:
{raw_text if raw_text else "[No website content available — infer from business name/address only]"}

Return ONLY the structured fields. If a field cannot be determined, return "Unknown".
"""

    resp = client.responses.create(
        model="gpt-5.5",
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
    raw_text = scrape_website(business.website)
    intel = extract_intel(business.name, business.formatted_address, raw_text)

    if not isinstance(intel, dict):
        current_app.logger.warning(f"extract_intel returned non-dict for {business.name}")
        intel = {}

    return intel
