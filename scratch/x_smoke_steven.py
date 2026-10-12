"""
x_smoke_steven.py -- LIVE before/after check on the Steven Tison dossier.

RUN THIS LOCALLY (it makes real Brave + OpenAI calls using your .env keys):

    venv\\Scripts\\python scratch\\x_smoke_steven.py

Builds Steven's dossier with the photographer profile (the one used for the
original, thin dossier), prints a readable summary, scores it against what the
ChatGPT deep-dive found, and saves the full JSON to
scratch/out/steven_dossier.json so it can be reviewed afterwards.

Expect roughly 1-2 minutes: 5 Brave searches paced at ~1/second for the free
tier, one OpenAI web search (runs alongside), a few polite page fetches, and
7 more OpenAI calls (some run in parallel). Add --brave-only to skip the web
search and compare.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
os.environ["SEARCHER"] = "photographer"

from contact_discovery import BraveSearchProvider, CompanyInput, ContactCandidate
from contact_dossier import (
    SpineEngagementResearcher, ThrottledSearchProvider, build_dossier, dossier_to_dict,
)
from dossier_llm_openai import OpenAIDossierLLM, OpenAIWebPersonSearch
from fetch_and_extract import PageFetcher

HOME = "https://accountingconsultantexperts.com/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "steven_dossier.json")


def subject():
    company = CompanyInput(
        canonical_name="Accounting Consultant Experts",
        input_name="Accounting Consultant Experts",
        city="Duluth", state="GA", places_type="accounting",
        website=HOME, domain="accountingconsultantexperts.com",
    )
    contact = ContactCandidate(
        name="Steven Tison", title="Owner",
        company="Accounting Consultant Experts",
        evidence=[{"url": HOME, "snippet": "Meet Steven & ACE", "query": "(seed)"}],
        confidence="high", why_relevant="Founder/owner.",
    )
    return contact, company


def show(d):
    print("\n=== OUTREACH BRIEF ===")
    o = d.outreach
    if o:
        for a in o.angles:
            print(f"* {a.angle}: \"{a.opener}\"\n    why: {a.rationale}\n    from: {', '.join(a.evidence)}")
        for label, items in (("Likely needs", o.likely_needs), ("Avoid", o.avoid),
                             ("Check first", o.open_questions)):
            if items:
                print(f"{label}:")
                for x in items:
                    print(f"  - {x}")
        print(f"Why now: {o.why_now}\nChannel: {o.channel}\nTone: {o.tone}")
    print("\n=== BACKGROUND ===")
    for f in d.background:
        print(f"- [{f.identity}] {f.claim}  ({f.source_url})" + (f"  -- {f.identity_note}" if f.identity_note else ""))
    print("\n=== RAPPORT ===")
    for h in d.rapport:
        print(f"- {h.detail}  ({h.source_url})")
    print("\n=== ENGAGEMENT ===", d.research_log.get("engagement"))
    for e in d.engagement:
        print(f"- [{e.identity_confidence}] {e.title}: {e.summary}  ({e.url})")
    print("\n=== REACH ===")
    for r in d.reach:
        print(f"- {r.kind}: {r.value} [{r.confidence}, {r.how_obtained}]")
    print("\n=== ORG ===")
    for o_ in d.org_inferences:
        print(f"- {o_.claim}")
    print("\n=== RESEARCH LOG ===")
    for q in d.research_log.get("queries", []):
        print(f"- {q.get('engine', 'brave'):10} {q['purpose']:10} {q['results']:2} results ({q['new']} new)  {q['query']}" + (f"  ERROR {q['error']}" if q["error"] else ""))
    print("\nSearch results (engine -> url):")
    for r in d.research_log.get("results", []):
        print(f"  {'+'.join(r['engines']):18} {r['url']}")
    att = d.research_log.get("attribution", {})
    print("\nWhere kept findings came from:", att.get("counts"))
    for p in d.research_log.get("own_site_pages", []):
        print(f"- own site: {'read' if p['ok'] else 'skip'}  {p['url']}  {p['reason']}")
    if d.warnings:
        print("\nWARNINGS:")
        for w in d.warnings:
            print("  -", w)


def score(d):
    print("\n=== VS. THE CHATGPT DEEP-DIVE ===")
    for label, ok in (
        ("Facebook group activity surfaced", "facebook.com" in json.dumps([e.url for e in d.engagement]).lower()),
        ("CBT CPA history found (flagged as probable/possible)",
         any(w in (f.source_url + f.claim).lower()
             for f in d.background for w in ("cbtcpa", "carmichael", "brasher", "tuvell"))),
        ("Cooper / music / travel captured as rapport",
         any(w in json.dumps([h.detail for h in d.rapport]).lower() for w in ("cooper", "music", "travel"))),
        ("Outreach brief has 2+ cited angles", d.outreach is not None and len(d.outreach.angles) >= 2),
        ("Background is about Steven, not the service list",
         not any("pricing" in f.claim.lower() or "tiers" in f.claim.lower() for f in d.background)),
    ):
        print(f"  [{'YES' if ok else 'no '}] {label}")


def main():
    for key in ("OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY"):
        if not os.environ.get(key):
            print(f"ERROR: {key} not set (check your .env).")
            return 1
    contact, company = subject()
    search = ThrottledSearchProvider(BraveSearchProvider(), min_interval=1.1)
    fetcher = PageFetcher()
    llm = OpenAIDossierLLM()
    t0 = time.time()
    web = None if "--brave-only" in sys.argv else OpenAIWebPersonSearch()
    d = build_dossier(contact, company, search=search, fetcher=fetcher, llm=llm,
                      engagement_researcher=SpineEngagementResearcher(search, fetcher, llm),
                      person_search=web, min_seniority=0)
    print(f"Built in {time.time() - t0:.0f}s with {search.calls} Brave calls"
          f"{' and 2 OpenAI web searches (general + social)' if web else ' (Brave only)'}.")
    show(d)
    score(d)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dossier_to_dict(d), f, indent=2)
    print(f"\nFull JSON saved to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
