from openai import OpenAI
from dotenv import load_dotenv
import json

load_dotenv()
client = OpenAI()

company_json = {
    "target_company": {
        "input_name": "Brown & Brown Insurance",
        "canonical_name": "Brown & Brown",
        "input_location": {
            "city": "Alpharetta",
            "state": "GA"
        }
    }
}


# Old prompt flagged by OpenAI for cybersecurity risk:  Search the web for this exact contact-discovery query:

def search_one_query(query: str) -> dict:
    prompt = f"""
Find publicly available business-profile pages matching this search phrase.
Only use public web results. Do not access private systems, bypass logins, scrape at scale, test security, or infer private data.

{query}

Return JSON only:
{{
  "query": "...",
  "results": [
    {{
      "name": "",
      "title": "",
      "company": "",
      "location": "",
      "source_url": "",
      "source_type": "",
      "why_relevant": "",
      "confidence": "low|medium|high"
    }}
  ]
}}

Rules:
- Prefer actual profile/source URLs over summaries.
- Include only people plausibly associated with the target company.
- If no useful results, return an empty results array.
"""

    response = client.responses.create(
        model="gpt-5.5",
        tools=[{"type": "web_search"}],
        tool_choice="required",
        include=["web_search_call.action.sources"],
        input=prompt,
    )

    return {
        "query": query,
        "raw_text": response.output_text,
        "response_id": response.id,
    }


def run_contact_searches(queries: list[str], max_queries: int = 4) -> list[dict]:
    all_results = []

    for query in queries[:max_queries]:
        result = search_one_query(query)
        all_results.append(result)

    return all_results

# Build queries

def quote(value: str) -> str:
    value = (value or "").strip()
    return f'"{value}"' if value else ""


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys([item for item in items if item.strip()]))


TARGET_ROLE_TERMS = [
    "office manager",
    "operations",
    "branch manager",
    "market leader",
    "regional leader",
    "managing director",
    "president",
    "vice president",
    "principal",
    "partner",
    "real estate",
    "facilities",
    "property",
    "procurement",
    "vendor",
    "business development"
]

IRRELEVANT_TITLE_TERMS = [
    "employee benefits",
    "benefits producer",
    "account manager",
    "assistant account manager",
    "aam",
    "ama",
    "claims",
    "underwriter",
    "csr",
    "customer service",
    "client service"
]


def build_contact_queries(company: dict, target_role_terms: list[str]) -> list[str]:
    input_name = company.get("input_name", "")
    canonical_name = company.get("canonical_name") or input_name

    location = company.get("input_location", {})
    city = location.get("city", "")
    state = location.get("state", "")

    names = unique([canonical_name, input_name])
    locations = unique([
        city,
        f"{city} {state}".strip(),
        state,
    ])


    source_terms = [
        "LinkedIn",
        "speaker",
        "webinar",
        "podcast",
        "press release",
        "conference",
        "interview",
    ]

    queries = []

    for name in names:
        for loc in locations:
            queries.append(f'{quote(name)} {quote(loc)} site:linkedin.com/in')
            queries.append(f'{quote(name)} {quote(loc)} "LinkedIn"')

    for name in names:
        for loc in locations:
            for role in TARGET_ROLE_TERMS:
                queries.append(f'{quote(name)} {quote(loc)} {quote(role)}')

    for name in names:
        for source in source_terms:
            queries.append(f'{quote(name)} {quote(source)}')

    return unique(queries)


import re
from collections import defaultdict

SENIOR_TERMS = [
    "president", "vice president", "vp", "svp", "senior vice president",
    "chief", "director", "leader", "principal", "partner", "executive",
    "manager", "market leader", "branch manager"
]

RELEVANT_TERMS = [
    "operations", "facilities", "real estate", "property", "procurement",
    "construction", "vendor", "business development", "commercial",
    "producer", "risk management"
]


def normalize_name(name: str) -> str:
    name = name or ""
    name = re.sub(r",.*$", "", name)  # remove credentials after comma
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def parse_raw_text(raw_text: str) -> dict:
    try:
        return json.loads(raw_text)
    except Exception:
        return {"results": []}


def score_contact(contact: dict, target_city: str, target_state: str) -> int:
    score = 0

    title = (contact.get("title") or "").lower()
    location = (contact.get("location") or "").lower()
    confidence = (contact.get("confidence") or "").lower()
    matched_queries = contact.get("matched_queries", 0)

    # Appears across multiple searches
    score += min(matched_queries, 3) * 1

    # Location relevance
    if target_city.lower() and target_city.lower() in location:
        score += 4
    elif target_state.lower() and target_state.lower() in location:
        score += 2
    elif "atlanta" in location:
        score += 2
    elif "georgia" in location:
        score += 2

    # Title quality
    if title:
        score += 2
    else:
        score -= 4

    # Strongly demote roles unlikely to matter to a general contractor
    if any(term in title for term in IRRELEVANT_TITLE_TERMS):
        score -= 10

    # Strongly boost roles that may control office/vendor/local decisions
    if any(term in title for term in TARGET_ROLE_TERMS):
        score += 10

    # Seniority / decision-maker terms
    if any(term in title for term in SENIOR_TERMS):
        score += 4

    # Role relevance
    if any(term in title for term in RELEVANT_TERMS):
        score += 3

    # Confidence from search result
    if confidence == "high":
        score += 2
    elif confidence == "medium":
        score += 1
    elif confidence == "low":
        score -= 2

    return score


def rank_contact_candidates(
    search_results: list[dict],
    target_city: str,
    target_state: str,
    cutoff: int = 5
) -> list[dict]:
    contacts = defaultdict(lambda: {
        "name": "",
        "title": "",
        "company": "",
        "location": "",
        "source_urls": set(),
        "matched_queries": set(),
        "confidences": [],
        "why_relevant": []
    })

    for search_item in search_results:
        query = search_item.get("query", "")
        parsed = parse_raw_text(search_item.get("raw_text", ""))

        for result in parsed.get("results", []):
            name = result.get("name", "").strip()
            source_url = result.get("source_url", "").strip()

            if not name:
                continue

            key = source_url or normalize_name(name)

            c = contacts[key]
            c["name"] = c["name"] or name

            # Prefer non-empty title/location/company
            if result.get("title"):
                c["title"] = result["title"]
            if result.get("company"):
                c["company"] = result["company"]
            if result.get("location"):
                c["location"] = result["location"]

            if source_url:
                c["source_urls"].add(source_url)

            c["matched_queries"].add(query)

            if result.get("confidence"):
                c["confidences"].append(result["confidence"])

            if result.get("why_relevant"):
                c["why_relevant"].append(result["why_relevant"])

    ranked = []

    for c in contacts.values():
        contact = {
            "name": c["name"],
            "title": c["title"],
            "company": c["company"],
            "location": c["location"],
            "source_urls": sorted(c["source_urls"]),
            "matched_queries": len(c["matched_queries"]),
            "confidences": list(dict.fromkeys(c["confidences"])),
            "why_relevant": list(dict.fromkeys(c["why_relevant"]))[:3],
        }

        contact["score"] = score_contact(contact, target_city, target_state)
        ranked.append(contact)

    ranked.sort(
        key=lambda x: (
            x["score"],
            x["matched_queries"],
            1 if x["title"] else 0
        ),
        reverse=True
    )

    return ranked[:cutoff]



if __name__ == "__main__":
    queries = build_contact_queries(company_json["target_company"], TARGET_ROLE_TERMS)

    print("\nGenerated queries:")
    for q in queries:
        print(q)

    results = run_contact_searches(queries, max_queries=5)

    with open("contact_search_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\nSaved results to contact_search_results.json")

    top_contacts = rank_contact_candidates(
    search_results=results,
    target_city=company_json["target_company"]["input_location"]["city"],
    target_state=company_json["target_company"]["input_location"]["state"],
    cutoff=5
)

with open("top_contacts.json", "w", encoding="utf-8") as f:
    json.dump(top_contacts, f, indent=2)

print("\nTop contacts:")
for contact in top_contacts:
    print(
        contact["score"],
        contact["name"],
        "|",
        contact["title"],
        "|",
        contact["location"]
    )
