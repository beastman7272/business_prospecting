"""
x_smoke_accountant.py -- LIVE dossiers with the ACCOUNTANT profile.

RUN THIS LOCALLY (real Brave + OpenAI calls with your .env keys):

    venv\\Scripts\\python scratch\\x_smoke_accountant.py           (prints + JSON only)
    venv\\Scripts\\python scratch\\x_smoke_accountant.py --save    (also saves to the app)

Builds dossiers for three saved contacts in segments the accountant covers:
  * Danielle Song, founder, JR Skin Studio (salon/studio; booking site)
  * Scarlett Hart, office manager, Duluth Chiropractic (medical practice)
  * Angela Jennings, controller, Gwinnett Place Nissan (dealership)
and prints the new "Accounting-need signals" (finance-role hiring, growth /
new location / new ownership, start year, payment and accounting tools)
alongside the usual sections. Full JSON goes to scratch/out/acct_<name>.json.

--save writes each dossier into the app's database, replacing that contact's
existing dossier (Danielle Song already has one, from the photographer
profile), so you can look at them on the dashboard.

Roughly 1-2 minutes per contact: 7 Brave searches paced ~1/second (the 5
research searches, the gate/engagement search and one job search), a few
polite page fetches including up to two careers pages, the OpenAI web search,
and the usual model calls.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
os.environ["SEARCHER"] = "accountant"

from app import create_app                      # noqa: E402
from active_profile import set_active_searcher  # noqa: E402
from models import db, Business, Contact        # noqa: E402
from services import contacts as svc            # noqa: E402
from contact_dossier import (                   # noqa: E402
    SpineEngagementResearcher, ThrottledSearchProvider, build_dossier, dossier_to_dict,
)
from fetch_and_extract import PageFetcher       # noqa: E402

SUBJECTS = [("JR Skin Studio", "Danielle Song"),
            ("Duluth Chiropractic and Wellness Center", "Scarlett Hart"),
            ("Gwinnett Place Nissan", "Angela Jennings")]
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
KIND = {"p2p": "person-to-person app", "manual": "cash/check",
        "pos": "point-of-sale/booking", "software": "accounting/invoicing software"}


def show_signals(d):
    fin = (d.research_log.get("site_signals") or {}).get("finance_signals")
    print("\n--- ACCOUNTING-NEED SIGNALS ---")
    if not fin:
        print("  (signal not run -- is the accountant profile active?)")
        return
    if fin.get("none_found"):
        print(f"  none found -- site pages read: {fin.get('pages_checked', 0)}, careers pages: "
              f"{fin.get('careers_pages_checked', 0)}, job search ok: {fin.get('job_search_ok')}")
        return
    for h in fin.get("hiring", []):
        print(f"  HIRING  {h['role']} [{h['source']}]  {h['url']}\n          {h['snippet'][:200]}")
    for e in fin.get("expansion", []):
        print(f"  GROWTH  {e['phrase']}  {e['url']}\n          {e['snippet'][:200]}")
    s = fin.get("start")
    if s:
        print(f"  START   {s.get('year') or '?'} (~{s['years_in_business']} yrs){' YOUNG' if s.get('young') else ''}"
              f"  {s['url']}\n          {s['snippet'][:160]}")
    for p in fin.get("payments", []):
        print(f"  MONEY   {p['tool']} ({KIND.get(p['kind'], p['kind'])})  {p['url']}\n          {p['where'][:160]}")


def show(d):
    show_signals(d)
    print("\n--- BACKGROUND ---")
    for f in d.background:
        print(f"  [{f.identity}] {f.claim}  ({f.source_url})")
    print("--- RAPPORT ---")
    for h in d.rapport:
        print(f"  {h.detail}  ({h.source_url})")
    print("--- ENGAGEMENT ---", (d.research_log.get("engagement") or {}).get("status"))
    for e in d.engagement:
        print(f"  [{e.identity_confidence}] {e.title}  ({e.url})")
    print("--- REACH ---")
    for r in d.reach:
        print(f"  {r.kind}: {r.value} [{r.confidence}]")
    print("--- SEARCHES ---")
    for q in d.research_log.get("queries", []):
        print(f"  {q.get('engine', 'brave'):10} {q['purpose']:14} {q['results']:2} results  {q['query']}"
              + (f"  ERROR {q['error']}" if q.get("error") else ""))
    print("--- OWN SITE ---")
    for p in d.research_log.get("own_site_pages", []):
        tag = "careers" if p.get("careers_page") else "page"
        print(f"  {'read' if p['ok'] else 'skip'} {tag:7} {p['url']}  {p['reason']}")
    for w in d.warnings:
        print("  WARNING:", w)


def main():
    save = "--save" in sys.argv
    app = create_app()
    with app.app_context():
        for key in ("OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY"):
            if not app.config.get(key):
                print(f"ERROR: {key} not set (check your .env).")
                return 1
        set_active_searcher("accountant")
        os.makedirs(OUT_DIR, exist_ok=True)
        for biz_name, person in SUBJECTS:
            contact = (Contact.query.join(Business)
                       .filter(Business.name == biz_name, Contact.name == person).first())
            print("\n" + "=" * 78 + f"\n{person} -- {biz_name}\n" + "=" * 78)
            if contact is None:
                print("  not found in your saved contacts; skipped")
                continue
            t0 = time.time()
            company = svc.business_to_company_input(contact.business)
            search = ThrottledSearchProvider(svc._search_provider(), min_interval=1.1)
            fetcher = PageFetcher()
            llm = svc._dossier_llm()
            d = build_dossier(svc.contact_to_candidate(contact), company, search=search,
                              fetcher=fetcher, llm=llm,
                              engagement_researcher=SpineEngagementResearcher(search, fetcher, llm),
                              person_search=svc._person_search())
            print(f"Built in {time.time() - t0:.0f}s with {search.calls} Brave calls.")
            show(d)
            out = os.path.join(OUT_DIR, "acct_" + person.lower().replace(" ", "_") + ".json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(dossier_to_dict(d), f, indent=2)
            print(f"\nFull JSON: {out}")
            if save:
                svc._save_dossier(contact, d)
                contact.selected = True
                db.session.commit()
                print("Saved to the app -- open it on the dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
