import json
import time
from typing import Any
from openai import OpenAI

client = OpenAI()


DOSSIER_SCHEMA = {
    "type": "object",
    "properties": {
        "contact_name": {"type": "string"},
        "company": {"type": "string"},
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "source_type": {
                        "type": "string",
                        "description": (
                            "linkedin_profile, linkedin_post, linkedin_article, article, "
                            "podcast, webinar, conference_bio, company_page, press, "
                            "email_source, phone_source, other"
                        ),
                    },
                    "title_or_context": {"type": "string"},
                    "date": {"type": "string"},
                    "snippet": {"type": "string"},
                },
                "required": ["url", "source_type", "title_or_context", "date", "snippet"],
                "additionalProperties": False,
            },
        },
        "public_contact_info": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "value": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["type", "value", "source_url"],
                "additionalProperties": False,
            },
        },
        "reporting_or_org_clues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["claim", "source_url"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "contact_name",
        "company",
        "links",
        "public_contact_info",
        "reporting_or_org_clues",
    ],
    "additionalProperties": False,
}


def q(value: str) -> str:
    value = (value or "").strip()
    return f'"{value}"' if value else ""


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i and i.strip()))


def location_parts(location: Any) -> tuple[str, str]:
    """
    Handles either:
    - {"city": "Alpharetta", "state": "GA"}
    - "Alpharetta, Georgia, United States"
    """
    if isinstance(location, dict):
        return location.get("city", ""), location.get("state", "")

    if isinstance(location, str):
        parts = [p.strip() for p in location.split(",")]
        city = parts[0] if parts else ""

        state = ""
        for p in parts[1:]:
            if p.lower() in ["georgia", "ga"]:
                state = "GA"
                break

        return city, state

    return "", ""


def build_contact_dossier_queries(contact: dict[str, Any]) -> list[str]:
    name = contact.get("name", "")
    company = contact.get("company", "")
    title = contact.get("title", "")

    city, state = location_parts(contact.get("location", ""))

    base_terms = unique([
        f"{q(name)} {q(company)}",
        f"{q(name)} {q(company)} {q(title)}",
        f"{q(name)} {q(company)} {q(city)}",
        f"{q(name)} {q(company)} {q(state)}",
    ])

    evidence_terms = [
        "LinkedIn",
        "site:linkedin.com/in",
        "site:linkedin.com/posts",
        "site:linkedin.com/pulse",
        "podcast",
        "webinar",
        "interview",
        "speaker",
        "conference",
        "press release",
        "article",
        "bio",
        "email",
        "phone",
        "reports to",
        "org chart",
    ]

    queries = []

    # Use URLs from the ranked contact search as seed evidence.
    for url in contact.get("source_urls", []):
        queries.append(f"{q(name)} {q(company)} {url}")

    for base in base_terms:
        for term in evidence_terms:
            queries.append(f"{base} {term}")

    return unique(queries)


def run_dossier_query(contact: dict[str, Any], query: str) -> dict[str, Any]:
    prompt = f"""
You are collecting public-source evidence about one business contact.

Contact:
{json.dumps(contact, indent=2)}

Search query:
{query}

Return links first. Do not create outreach advice.

Find actual public source URLs connected to this person:
- LinkedIn profile URLs
- LinkedIn post URLs when available
- LinkedIn article URLs when available
- interviews, podcasts, webinars, speaker pages
- company bios, press mentions, articles
- public contact info only if clearly public
- reporting/org clues only if source-backed

Important:
- Prefer actual URLs over summaries.
- Do not invent URLs.
- Do not include unsupported claims.
- If nothing useful is found, return empty arrays.
"""

    resp = client.responses.create(
        model="gpt-5.5",
        tools=[{"type": "web_search"}],
        tool_choice="required",
        input=prompt,
        text={
            "format": {
                "type": "json_schema",
                "name": "contact_dossier",
                "schema": DOSSIER_SCHEMA,
                "strict": True,
            }
        },
        max_output_tokens=2500,
    )

    return json.loads(resp.output_text)


def merge_dossier_results(
    contact: dict[str, Any],
    partials: list[dict[str, Any]],
) -> dict[str, Any]:
    links_by_url = {}
    contact_info_by_key = {}
    org_clues_by_key = {}

    errors = []

    for part in partials:
        if "error" in part:
            errors.append(part)
            continue

        for item in part.get("links", []):
            url = item.get("url", "").strip()
            if url and url not in links_by_url:
                links_by_url[url] = item

        for item in part.get("public_contact_info", []):
            key = (
                item.get("type", ""),
                item.get("value", ""),
                item.get("source_url", ""),
            )
            contact_info_by_key[key] = item

        for item in part.get("reporting_or_org_clues", []):
            key = (
                item.get("claim", ""),
                item.get("source_url", ""),
            )
            org_clues_by_key[key] = item

    return {
        "contact_name": contact.get("name", ""),
        "company": contact.get("company", ""),
        "title": contact.get("title", ""),
        "location": contact.get("location", ""),
        "seed_source_urls": contact.get("source_urls", []),
        "links": list(links_by_url.values()),
        "public_contact_info": list(contact_info_by_key.values()),
        "reporting_or_org_clues": list(org_clues_by_key.values()),
        "errors": errors,
    }


def build_contact_dossier(
    contact: dict[str, Any],
    max_queries: int = 8,
    sleep_seconds: float = 0.5,
) -> dict[str, Any]:
    queries = build_contact_dossier_queries(contact)

    print("\nGenerated dossier queries:")
    for query in queries[:max_queries]:
        print("-", query)

    partials = []

    for query in queries[:max_queries]:
        print(f"\nSearching dossier query: {query}")

        try:
            partials.append(run_dossier_query(contact, query))
            time.sleep(sleep_seconds)
        except Exception as e:
            partials.append({
                "contact_name": contact.get("name", ""),
                "company": contact.get("company", ""),
                "links": [],
                "public_contact_info": [],
                "reporting_or_org_clues": [],
                "error": str(e),
                "query": query,
            })

    return merge_dossier_results(contact, partials)


def load_selected_contact(path: str = "top_contacts.json", index: int = 0) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        contacts = json.load(f)

    if not contacts:
        raise RuntimeError("top_contacts.json contains no contacts.")

    if index >= len(contacts):
        raise RuntimeError(f"Contact index {index} is out of range.")

    return contacts[index]


if __name__ == "__main__":
    # Change this to 1, 2, 3, etc. to test a different ranked contact.
    CONTACT_INDEX = 0

    selected_contact = load_selected_contact(
        path="top_contacts.json",
        index=CONTACT_INDEX,
    )

    print("\nSelected contact:")
    print(json.dumps(selected_contact, indent=2))

    dossier = build_contact_dossier(
        selected_contact,
        max_queries=8,
        sleep_seconds=0.5,
    )

    output_file = "contact_dossier.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(dossier, f, indent=2)

    print(f"\nSaved dossier to {output_file}")

    print("\nLinks found:")
    for link in dossier.get("links", []):
        print("-", link.get("source_type"), "|", link.get("url"))