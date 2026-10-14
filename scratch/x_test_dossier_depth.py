"""
x_test_dossier_depth.py -- OFFLINE checks for the deeper Stage 3 research.

No network, no API keys: search, fetch and the LLM are all stubbed. Models
the Steven Tison case that produced a thin dossier: a one-page firm site whose
bio sits ~60% down the page (past the old truncation point), a past-employer
staff page that never names his firm, and Facebook group posts visible only
as search snippets.

Run:  python scratch/x_test_dossier_depth.py      (exit 0 = all checks pass)
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SEARCHER"] = "photographer"

from contact_discovery import CompanyInput, ContactCandidate, SearchResult, SearchProvider
from fetch_and_extract import FetchResult, extract_links
from contact_dossier import (
    BackgroundFact, EngagementItem, MockDossierLLM, MockEngagementResearcher, MockPersonSearch, OutreachAngle, OutreachBrief,
    PersonSignals, RapportHook, SpineEngagementResearcher, ThrottledSearchProvider,
    build_dossier, build_research_queries, dossier_to_dict, focus_text,
)
import dossier_llm_openai as dlo

HOME = "https://accountingconsultantexperts.com/"
FILLER = ("Bookkeeping packages, payroll support, tax preparation pricing and "
          "frequently asked questions about QuickBooks Online. ") * 70
BIO = ("Meet Our Team. Steven Tison, Founder. Steven started ACE in Duluth after "
       "years in public accounting. Outside work he loves music and travel. "
       "Cooper, the Ace the Accounting Hound, is our unofficial mascot.")
HOME_TEXT = FILLER[: int(len(FILLER) * 0.6)] + BIO + FILLER[: int(len(FILLER) * 0.4)]

PAGES = {
    HOME: ("ACE", HOME_TEXT, [
        {"href": HOME + "#section-9I6t8B1c1W", "text": "Meet Steven & ACE"},
        {"href": HOME + "#section-VRWmdnseoH", "text": "About"},
        {"href": HOME + "contact-us", "text": "Contact"},
        {"href": HOME + "calendar-752312", "text": "Book a Consultation"},
        {"href": "https://appealally.com/", "text": "AppealAlly"},
    ]),
    HOME + "contact-us": ("Contact", "Call (470) 253-4381. Duluth, Georgia.", []),
    "https://www.cbtcpa.com/staffnew.php": ("Staff",
        "Our staff. Steven Tison joined the firm in 2017 and works on "
        "government and nonprofit audits and tax returns.", []),
}

RESULTS = {
    "identity": [("ACE", HOME, "Accounting Consultant Experts - Meet Steven")],
    "career": [("Staff | Carmichael, Brasher, Tuvell & Company",
                "https://www.cbtcpa.com/staffnew.php",
                "Steven Tison joined in 2017; government and nonprofit audits.")],
    "local": [("Man charged after shooting in Duluth", "https://news.example.com/crime",
               "Police in Duluth charged a man ...")],
    "social": [("Steven Tison - Duluth business group",
                "https://www.facebook.com/groups/2315634442007751/posts/4582589801978859/",
                "Hi all! I'm Steven and I started ACE, the ace of accounting, here in Duluth.")],
    "linkedin": [("Steven Wilson - Ellucian | LinkedIn",
                  "https://www.linkedin.com/in/steven-wilson-b58363156/", "Steven Wilson ...")],
}


class FixtureSearch(SearchProvider):
    def __init__(self):
        self.queries = []

    def search(self, query, max_results=5):
        self.queries.append(query)
        purpose = next((p for p, q in build_research_queries(CONTACT, COMPANY, 9) if q == query), None)
        return [SearchResult(t, u, sn, query) for t, u, sn in RESULTS.get(purpose, [])][:max_results]


class StubFetcher:
    """Mimics PageFetcher: social hosts are denylisted, unknown URLs 404."""
    def __init__(self):
        self.log = []

    def fetch(self, url):
        self.log.append(url)
        if "facebook.com" in url or "linkedin.com" in url:
            return FetchResult(url=url, skipped_reason="denylisted:facebook.com")
        if url not in PAGES:
            return FetchResult(url=url, ok=False, error="http_404")
        title, text, links = PAGES[url]
        contacts = {"emails": ["steven@accountingconsultantexperts.com"],
                    "phones": ["(470) 253-4381"]} if url == HOME else {}
        return FetchResult(url=url, ok=True, final_url=url, status_code=200,
                           title=title, text=text, links=links, contacts=contacts)


CONTACT = ContactCandidate(
    name="Steven Tison", title="Owner", company="Accounting Consultant Experts",
    evidence=[{"url": HOME, "snippet": "Meet Steven & ACE", "query": "(seed)"}],
    confidence="high", why_relevant="Founder/owner.",
)
COMPANY = CompanyInput(
    canonical_name="Accounting Consultant Experts", input_name="Accounting Consultant Experts",
    city="Duluth", state="GA", places_type="accounting",
    website=HOME, domain="accountingconsultantexperts.com",
)

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def main():
    print("Unit checks")
    ft = focus_text(HOME_TEXT, "Steven Tison", 6000)
    check("focus_text keeps a bio located 60% down a long page",
          "Cooper" in ft and len(ft) <= 6000, f"{len(HOME_TEXT)} chars -> {len(ft)}")
    check("old head-truncation would have lost it", "Cooper" not in HOME_TEXT[:4000])
    check("focus_text leaves short text alone", focus_text("abc", "x y", 100) == "abc")
    links = extract_links('<nav><a href="/about">About Steven</a></nav><a href="mailto:x@y.z">m</a>',
                          "https://ex.com/")
    check("extract_links keeps nav links, drops mailto",
          links == [{"href": "https://ex.com/about", "text": "About Steven"}], str(links))
    qs = build_research_queries(CONTACT, COMPANY, 5)
    check("5 differently-anchored queries", len(qs) == 5 and len({q for _, q in qs}) == 5,
          "; ".join(q for _, q in qs))

    class Inner(SearchProvider):
        def search(self, q, max_results=5):
            return []
    t = ThrottledSearchProvider(Inner(), min_interval=0.2)
    t0 = time.monotonic()
    for _ in range(4):
        t.search("q")
    check("throttle paces searches", time.monotonic() - t0 >= 0.55)

    print("\nPipeline (mock LLM)")
    llm = MockDossierLLM(
        signals=PersonSignals(present_urls=[HOME]),
        background=[
            BackgroundFact("Senior auditor at CBT CPA from 2017",
                           "https://www.cbtcpa.com/staffnew.php", "2017", "medium",
                           "probable", "same name+field; ACE not mentioned"),
            BackgroundFact("Founded ACE in Duluth", HOME, None, "high", "confirmed"),
        ],
        rapport=[RapportHook("Office dog Cooper is the firm's mascot", "pet", HOME, "Light P.S."),
                 RapportHook("uncited", "other", "", "")],
        engagement=[EngagementItem(RESULTS["social"][0][1], "post", "Intro post", None,
                                   "from search snippet", "medium", "Local group marketing")],
        outreach=OutreachBrief(
            angles=[OutreachAngle("New founder", "Saw you started ACE...", "Founder headshot",
                                  [HOME]),
                    OutreachAngle("Uncited", "x", "y", [])],
            open_questions=["Is Steven still at CBT?"]),
    )
    search = FixtureSearch()
    fetcher = StubFetcher()
    FB2 = "https://www.facebook.com/groups/2315634442007751/posts/4582759321961907/"
    web = MockPersonSearch([
        SearchResult("Flowery Branch group", FB2, "(web-search note) Steven promotes ACE bookkeeping", "w"),
        SearchResult("Staff", "https://www.cbtcpa.com/staffnew.php", "(web-search note) staff page", "w"),
    ])
    d = build_dossier(CONTACT, COMPANY, search=search, fetcher=fetcher, llm=llm,
                      engagement_researcher=SpineEngagementResearcher(search, fetcher, llm),
                      person_search=web, min_seniority=0, outreach_brief=True)

    check("ran 5 searches", len(search.queries) == 5)
    li = next(q for q in d.research_log["queries"] if q["purpose"] == "linkedin")
    check("namesake LinkedIn result dropped (Brave ignored the quotes)",
          li["results"] == 1 and li["new"] == 0 and li["dropped_namesakes"] == 1, str(li))
    by_url = {r["url"]: r["engines"] for r in d.research_log["results"]}
    check("web-search-only result tracked as mock_web", by_url.get(FB2) == ["mock_web"], str(by_url.get(FB2)))
    check("result found by both engines tracked as both",
          by_url.get("https://www.cbtcpa.com/staffnew.php") == ["brave", "mock_web"])
    check("web search logged as its own query row",
          any(q["engine"] == "mock_web" and q["results"] == 2 for q in d.research_log["queries"]))
    att = d.research_log["attribution"]["counts"]
    check("kept findings attributed by source",
          att.get("own_site", 0) >= 1 and att.get("brave+mock_web", 0) >= 1, str(att))
    check("footer email reaches the evidence",
          any("steven@accountingconsultantexperts.com" in doc.text for doc in llm.seen["reach"]))
    own_urls = [doc.url for doc in llm.seen["background"] if doc.source_type == "own_domain_page"]
    check("crawl read homepage + followed the site's Contact link",
          HOME in own_urls and HOME + "contact-us" in own_urls, str(own_urls))
    check("no blind seed-path guesses when the site exposes links",
          not any(u.endswith(("/about", "/team", "/our-team")) for u in fetcher.log),
          str(fetcher.log))
    bg_text = " ".join(doc.text for doc in llm.seen["background"])
    check("bio (Cooper, music) reaches background + rapport", "Cooper" in bg_text and
          "Cooper" in " ".join(doc.text for doc in llm.seen["rapport"]))
    check("past-employer page fetched and handed to background",
          any(doc.url.startswith("https://www.cbtcpa.com") and doc.source_type == "external_page"
              for doc in llm.seen["background"]))
    check("Facebook post reaches engagement as a snippet (never fetched as a page)",
          any(doc.source_type == "social_snippet" for doc in llm.seen["engagement"])
          and not any(doc.source_type == "external_page" and "facebook" in doc.url
                      for doc in llm.seen["engagement"]))
    check("namesake crime story not fetched (no surname match)",
          "https://news.example.com/crime" not in fetcher.log)
    check("seller context is the photographer profile",
          getattr(llm.seen.get("seller"), "searcher_id", None) == "photographer")
    check("background sorted confirmed-first", [f.identity for f in d.background] == ["confirmed", "probable"])
    check("uncited rapport hook dropped", len(d.rapport) == 1)
    check("uncited outreach angle dropped", [a.angle for a in d.outreach.angles] == ["New founder"])
    check("engagement status recorded", d.research_log["engagement"]["status"] == "found",
          json.dumps(d.research_log["engagement"]))
    check("outreach findings include identity levels",
          llm.seen["outreach_findings"]["background"][1]["identity"] == "probable")
    raw = json.dumps(dossier_to_dict(d))
    check("serializes; nav links not stored", '"links"' not in raw)

    print("\nOpenAI DossierLLM parsing (fake client)")

    class FakeResp:
        status = "completed"
        def __init__(self, text): self.output_text = text

    class FakeClient:
        def __init__(self): self.prompts = []
        class _R:
            def __init__(self, outer): self.outer = outer
            def create(self, **kw):
                self.outer.prompts.append(kw)
                name = kw["text"]["format"]["name"]
                payload = {
                    "background": {"facts": [{"claim": "c", "source_url": "u", "date": None,
                                              "confidence": "high", "identity": "Probable",
                                              "identity_note": "n"}]},
                    "rapport": {"hooks": [{"detail": "dog", "kind": "pet", "source_url": "u",
                                           "suggested_use": "s"}]},
                    "outreach": {"angles": [{"angle": "a", "opener": "o", "rationale": "r",
                                             "evidence": ["u"]}], "likely_needs": ["n"],
                                 "why_now": None, "avoid": [], "open_questions": ["q"],
                                 "channel": "email", "tone": "friendly"},
                }[name]
                return FakeResp(json.dumps(payload))
        @property
        def responses(self): return self._R(self)

    fc = FakeClient()
    real = dlo.OpenAIDossierLLM(client=fc)
    from contact_dossier import seller_context_for
    seller = seller_context_for(COMPANY)
    docs = llm.seen["background"]
    bf = real.extract_background_facts(CONTACT, COMPANY, docs, seller=seller)
    rh = real.extract_rapport_hooks(CONTACT, COMPANY, docs, seller=seller)
    ob = real.synthesize_outreach(CONTACT, COMPANY, {"background": []}, seller=seller)
    check("background parses with lowercased identity", bf[0].identity == "probable")
    check("rapport + outreach parse", rh[0].kind == "pet" and ob.angles[0].evidence == ["u"])
    check("prompts carry the seller's offer",
          all("headshot" in p["input"].lower() for p in fc.prompts))
    for p in fc.prompts:
        json.dumps(p["text"]["format"]["schema"])
    check("strict schemas list every property as required", all(
        set(s["properties"]) == set(s["required"])
        for s in (dlo.BACKGROUND_SCHEMA["properties"]["facts"]["items"],
                  dlo.RAPPORT_SCHEMA["properties"]["hooks"]["items"],
                  dlo.OUTREACH_SCHEMA, dlo.OUTREACH_SCHEMA["properties"]["angles"]["items"])))

    print("\nOpenAI web search parsing (fake response)")
    resp = {"output": [
        {"type": "web_search_call"},
        {"type": "message", "content": [{"type": "output_text",
         "text": "- Steven introduces ACE in a Duluth group, 2024 ([facebook.com](https://facebook.com/groups/1/posts/2))\n- Unrelated https://made-up.example.com",
         "annotations": [{"type": "url_citation", "url": "https://facebook.com/groups/1/posts/2?utm_source=openai",
                          "title": "Duluth Business Group", "start_index": 50, "end_index": 90}]}]},
    ]}
    rs = dlo.OpenAIWebPersonSearch(client=object())._results_from(resp)
    check("only cited URLs become results", [r.url for r in rs] == ["https://facebook.com/groups/1/posts/2"],
          str([r.url for r in rs]))
    check("snippet is the cited line, markdown link stripped",
          rs and "Duluth group, 2024" in rs[0].snippet and "](" not in rs[0].snippet, rs[0].snippet if rs else "")

    class FailingResponses:
        def __init__(self): self.tools = []
        def create(self, tools, **kw):
            self.tools.append(tools[0]["type"])
            if tools[0]["type"] != "web_search_preview":
                raise ValueError("400 unsupported tool")
            return {"output": []}
    class FC2:
        def __init__(self): self.responses = FailingResponses()
    fc2 = FC2()
    ws = dlo.OpenAIWebPersonSearch(client=fc2, social_pass=False)
    ws.find(CONTACT, COMPANY)
    check("falls back through tool variants", fc2.responses.tools ==
          ["web_search", "web_search", "web_search_preview"], str(fc2.responses.tools))

    class TwoCallResponses:
        def __init__(self): self.inputs = []
        def create(self, tools, input, **kw):
            self.inputs.append(input)
            url = "https://facebook.com/groups/9/posts/1" if "social media" in input else "https://a.com/"
            return {"output": [{"type": "message", "content": [{"type": "output_text",
                    "text": "- found it", "annotations": [
                        {"type": "url_citation", "url": url, "title": "t", "start_index": 2},
                        {"type": "url_citation", "url": "https://a.com/", "title": "t", "start_index": 2}]}]}]}
    class FC3:
        def __init__(self): self.responses = TwoCallResponses()
    fc3 = FC3()
    got = dlo.OpenAIWebPersonSearch(client=fc3).find(CONTACT, COMPANY)
    check("social pass runs as a second call and results are merged/deduped",
          len(fc3.responses.inputs) == 2 and sorted(r.url for r in got) ==
          ["https://a.com/", "https://facebook.com/groups/9/posts/1"], str([r.url for r in got]))
    check("social prompt uses the company acronym",
          any('"ACE"' in i for i in fc3.responses.inputs))

    print("\nFirst-name-only contact, placeholder email, skipped business type")
    from fetch_and_extract import extract_contacts
    from contact_dossier import collect_evidence
    from contact_discovery import discover_contacts, MockSearchProvider
    from searcher_profiles import get_profile
    salon = CompanyInput(canonical_name="L\u2019Amour Nail Boutique", input_name="x",
                         city="Duluth", state="GA", places_type="nail_salon",
                         website="https://www.lamournailboutique.com/",
                         domain="lamournailboutique.com")
    hannah = ContactCandidate(name="Hannah", title="Founder", company=salon.canonical_name)
    qs = build_research_queries(hannah, salon, 5)
    check("first-name-only queries are anchored on the business",
          all("Amour Nail Boutique" in q for _, q in qs) and not any(q.strip() == '"Hannah"' for _, q in qs),
          "; ".join(q for _, q in qs))
    check("curly apostrophe normalised for quoted search", all("\u2019" not in q for _, q in qs))

    class SalonSearch(SearchProvider):
        def search(self, q, max_results=5):
            return [SearchResult("Hannah Smith - Realtor", "https://www.linkedin.com/in/hannah-smith", "", q),
                    SearchResult("L'Amour Nail Boutique | LinkedIn", "https://www.linkedin.com/company/lamour", "", q)]
    class NoFetch:
        def fetch(self, url): return FetchResult(url=url, ok=False, error="http_404")
    ev = collect_evidence(hannah, salon, search=SalonSearch(), get_page=NoFetch().fetch, max_queries=5)
    li = next(q for q in ev.query_log if q["purpose"] == "linkedin")
    check("without a surname, namesakes are filtered by the business name",
          li["dropped_namesakes"] == 1 and li["results"] == 2, str(li))

    found = extract_contacts('<footer>Email: email@example.com  Call (678) 243-5009</footer>')
    check("template email@example.com dropped, phone kept",
          found["emails"] == [] and found["phones"] == ["(678) 243-5009"], str(found))
    from contact_dossier import find_emails
    check("reach regex ignores placeholder emails",
          find_emails("write to email@example.com or info@lamour.com") == ["info@lamour.com"])

    os.environ["SEARCHER"] = "photographer"
    run = discover_contacts(salon, get_profile("photographer"), MockSearchProvider(), None)
    check("photographer profile skips nail salons (by design) with a clear warning",
          not run.candidates and any("does not target segment" in w for w in run.warnings))
    dealer = CompanyInput(canonical_name="Duluth Motors", input_name="x", city="Duluth",
                          state="GA", places_type="car_dealer")
    from contact_discovery import resolve_segment, resolve_play
    seg, _ = resolve_segment(dealer)
    play, _ = resolve_play(get_profile("photographer"), seg)
    check("photographer profile now covers car dealerships",
          play is not None and play.roles[0].role.key == "marketing_director",
          seg.segment_id)
    check("seller description no longer says only tech/finance/law",
          "dealership" in get_profile("photographer").description)

    print("\nDealership: discovery follows site links; team-photo signal per profile")
    from fetch_and_extract import audit_images
    from contact_discovery import fetch_own_domain_pages
    from contact_dossier import seller_context_for
    D = "https://www.gwinnettplacenissan.com/"
    STAFF = D + "dealership/staff.htm"
    staff_html = ("<html><head><title>Meet Our Staff</title></head><body>"
                  + "".join(f'<div><img src="https://pictures.dealer.com/portrait-placeholder-v1.png" alt="x"><h3>Person {i}</h3><p>Sales</p></div>' for i in range(21))
                  + "".join(f'<div><img alt="Staff photo"><h3>Tech {i}</h3></div>' for i in range(38))
                  + "<p>Michael Cappelluti, General Manager</p></body></html>")
    dealer_pages = {
        D: ("Gwinnett Place Nissan", "New and used Nissan in Duluth.",
            [{"href": D + "dealership/about.htm", "text": "About Us"},
             {"href": STAFF, "text": "Meet Our Staff"},
             {"href": D + "new-inventory/index.htm", "text": "New Inventory"},
             {"href": D + "contact.htm", "text": "Contact Us"}], {}),
        STAFF: ("Meet Our Staff", "Michael Cappelluti General Manager. Person 0 Sales. ...", [],
                audit_images(staff_html)),
        D + "dealership/about.htm": ("About", "About Gwinnett Place Nissan.", [], {}),
        D + "contact.htm": ("Contact", "Call us.", [], {}),
    }

    class DealerFetcher:
        def __init__(self): self.log = []
        def fetch(self, url):
            self.log.append(url)
            if url not in dealer_pages:
                return FetchResult(url=url, ok=False, error="http_404")
            t, txt, links, audit = dealer_pages[url]
            return FetchResult(url=url, ok=True, final_url=url, status_code=200, title=t,
                               text=txt, links=links, image_audit=audit)

    dealer = CompanyInput(canonical_name="Gwinnett Place Nissan", input_name="x", city="Duluth",
                          state="GA", places_type="car_dealer", website=D,
                          domain="gwinnettplacenissan.com")
    df = DealerFetcher()
    pages, _ = fetch_own_domain_pages(dealer, [], df, max_pages=8)
    check("discovery follows 'Meet Our Staff' to /dealership/staff.htm",
          STAFF in [p.url for p in pages], str(df.log))
    check("discovery skips inventory links and blind path guesses",
          not any(u.endswith(("/about", "/team", "/our-team", "new-inventory/index.htm")) for u in df.log),
          str(df.log))

    gm = ContactCandidate(name="Michael Cappelluti", title="General Manager",
                          company="Gwinnett Place Nissan", evidence=[{"url": STAFF}])
    os.environ["SEARCHER"] = "photographer"
    photog = seller_context_for(dealer)
    check("photographer seller context enables team_photos", photog.site_signals == ["team_photos"])
    llm2 = MockDossierLLM(signals=PersonSignals(present_urls=[STAFF]))
    d2 = build_dossier(gm, dealer, search=FixtureSearch(), fetcher=DealerFetcher(), llm=llm2,
                       engagement_researcher=MockEngagementResearcher(), seller=photog,
                       min_seniority=0)
    tp = d2.research_log.get("site_signals", {}).get("team_photos", [])
    check("photo check counts 0 real / 21 placeholder / 38 missing on the staff page",
          tp and tp[0]["url"] == STAFF and (tp[0]["real"], tp[0]["placeholder"], tp[0]["no_source"]) == (0, 21, 38),
          str(tp))
    check("photo check reaches the evidence; brief is off by default",
          any("Team-page photo check" in doc.text for doc in llm2.seen["background"])
          and d2.outreach is None and "outreach_findings" not in llm2.seen)

    os.environ["SEARCHER"] = "accountant"
    acct = seller_context_for(dealer)
    llm3 = MockDossierLLM(signals=PersonSignals(present_urls=[STAFF]))
    d3 = build_dossier(gm, dealer, search=FixtureSearch(), fetcher=DealerFetcher(), llm=llm3,
                       engagement_researcher=MockEngagementResearcher(), seller=acct,
                       min_seniority=0)
    check("other profiles don't get the photo check",
          acct.site_signals == ["finance_signals"]
          and "team_photos" not in d3.research_log.get("site_signals", {})
          and not any("Team-page photo check" in doc.text for doc in llm3.seen["background"]))
    os.environ["SEARCHER"] = "photographer"

    print("\nPediatrics: photo check on a 'Providers' page with all photos present")
    P = "https://www.gwinnettpeds.com/"
    PROV = P + "gwinnett-pediatricians.php"
    names = ["suzanne-molock", "sharon-steele", "yvette-quisling-2021", "lisa-roberts-2021",
             "keyana-washington-2021", "yolanda-johnson-2022"] + [f"doc-{i}" for i in range(19)]
    prov_html = ("<html><head><title>Gwinnett Pediatricians</title></head><body>"
                 + "".join(f'<div><img src="/images/dr-{n}.jpg" alt=""><h3>Dr {n}</h3></div>' for n in names)
                 + '<img src="/wp-content/uploads/2019/03/office.jpg" alt="">'
                 + "</body></html>")
    audit = audit_images(prov_html)
    check("file-name years counted; upload-folder years ignored",
          audit["real"] == 26 and audit["photo_years"] == {"2021": 3, "2022": 1, "undated": 22},
          str(audit["photo_years"]))

    ped_pages = {
        P: ("Gwinnett Pediatrics", "Pediatric care in Gwinnett.",
            [{"href": PROV, "text": "Providers"}, {"href": P + "about-us.php", "text": "About GPAM"}], {}),
        PROV: ("Our Providers", "Dr. Suzanne Molock, MD. Dr. Sharon Steele, MD.", [], audit),
        P + "about-us.php": ("About", "Founded in 1974.", [], {}),
    }

    class PedFetcher:
        def fetch(self, url):
            if url not in ped_pages:
                return FetchResult(url=url, ok=False, error="http_404")
            t, txt, links, a = ped_pages[url]
            return FetchResult(url=url, ok=True, final_url=url, status_code=200, title=t,
                               text=txt, links=links, image_audit=a)

    peds = CompanyInput(canonical_name="Gwinnett Pediatrics & Adolescent Medicine", input_name="x",
                        city="Lawrenceville", state="GA", places_type="doctor", website=P,
                        domain="gwinnettpeds.com")
    molock = ContactCandidate(name="Suzanne Molock", title="Pediatrician", company=peds.canonical_name)
    llm4 = MockDossierLLM(signals=PersonSignals(present_urls=[PROV]))
    d4 = build_dossier(molock, peds, search=FixtureSearch(), fetcher=PedFetcher(), llm=llm4,
                       engagement_researcher=MockEngagementResearcher(),
                       seller=seller_context_for(peds), min_seniority=0)
    tp4 = d4.research_log.get("site_signals", {}).get("team_photos", [])
    check("check runs on a page reached via a 'Providers' link (no 'team' in its address)",
          tp4 and tp4[0]["url"] == PROV and tp4[0]["real"] == 26 and tp4[0]["placeholder"] == 0, str(tp4))
    ev_text = " ".join(doc.text for doc in llm4.seen["background"])
    check("all-photos case framed as consistency, not missing photos",
          "consistency or a refresh, not missing photos" in ev_text and "different times" in ev_text)

    class FakeFR:
        title = "Our Physicians"
        final_url = None
        image_audit = {"real": 5, "placeholder": 0, "no_source": 0, "total": 5}
    from contact_dossier import team_photo_check
    check("profession words in a page title count as a people page",
          team_photo_check(FakeFR(), "https://x.com/page-12.php") is not None)
    FakeFR.title = "Services"
    check("ordinary pages with real images are not reported",
          team_photo_check(FakeFR(), "https://x.com/services.php") is None)

    print("\nAccountant: finance signals on a young salon's site")
    import finance_signals as fs
    from fetch_and_extract import extract_chrome_text
    S = "https://glowstudio.example.com/"
    html = ("<html><body><header>Glow Studio</header><main>Hi, I'm Dana.</main>"
            "<footer>Proudly serving Suwanee since 2023 · We accept Zelle</footer></body></html>")
    check("header/footer text captured for signals",
          "since 2023" in extract_chrome_text(html) and "Zelle" in extract_chrome_text(html))
    salon_pages = {
        S: ("Glow Studio", "Hi, I'm Dana Park, founder of Glow Studio. Grand opening of our "
            "second location in Buford this spring!",
            [{"href": S + "about", "text": "About Dana"},
             {"href": S + "careers", "text": "Careers"},
             {"href": "https://glowstudio.square.site/", "text": "Book & pay online"},
             {"href": S + "financing", "text": "Apply for financing"}],
            extract_chrome_text(html)),
        S + "about": ("About", "Dana Park opened Glow Studio after ten years as an esthetician. "
                      "Meet Jess, our office manager. Join our team!", [], ""),
        S + "careers": ("Careers", "Join us! Open roles: front desk coordinator; part-time "
                        "bookkeeper (QuickBooks), 15 hrs/week.", [], ""),
    }

    class SalonFetcher:
        def __init__(self):
            self.log = []

        def fetch(self, url):
            self.log.append(url)
            if url not in salon_pages:
                return FetchResult(url=url, ok=False, error="http_404")
            t, txt, links, chrome = salon_pages[url]
            return FetchResult(url=url, ok=True, final_url=url, status_code=200, title=t,
                               text=txt, links=links, chrome_text=chrome)

    class JobSearch(SearchProvider):
        def __init__(self):
            self.queries = []

        def search(self, query, max_results=5):
            self.queries.append(query)
            if "jobs OR hiring" in query:
                return [SearchResult("Payroll Specialist - Glow Studio - Suwanee, GA | Indeed",
                                     "https://www.indeed.com/viewjob?jk=1", "Glow Studio is hiring a payroll specialist.", query),
                        SearchResult("Bookkeeper - Other Salon | Indeed",
                                     "https://www.indeed.com/viewjob?jk=2", "Other Salon is hiring a bookkeeper.", query)]
            return []

    salon = CompanyInput(canonical_name="Glow Studio", input_name="Glow Studio", city="Suwanee",
                         state="GA", places_type="beauty_salon", website=S,
                         domain="glowstudio.example.com")
    dana = ContactCandidate(name="Dana Park", title="Founder", company="Glow Studio",
                            evidence=[{"url": S}])
    os.environ["SEARCHER"] = "accountant"
    acct_salon = seller_context_for(salon)
    sf, js = SalonFetcher(), JobSearch()
    llm5 = MockDossierLLM(signals=PersonSignals(present_urls=[S]))
    d5 = build_dossier(dana, salon, search=js, fetcher=sf, llm=llm5,
                       engagement_researcher=MockEngagementResearcher(), seller=acct_salon,
                       min_seniority=0)
    fin = d5.research_log.get("site_signals", {}).get("finance_signals") or {}
    roles = {h["role"]: h for h in fin.get("hiring", [])}
    check("careers page followed (not the financing link)",
          S + "careers" in sf.log and S + "financing" not in sf.log, str(sf.log))
    check("bookkeeper posting found on the careers page",
          "bookkeeper" in roles and roles["bookkeeper"]["source"] == "own_site", str(fin.get("hiring")))
    check("'Meet Jess, our office manager' is not read as a job posting",
          "office manager" not in roles)
    check("job-board hit kept only for this business",
          "payroll specialist" in roles and roles["payroll specialist"]["source"] == "search"
          and all("jk=2" not in (h.get("url") or "") for h in fin.get("hiring", [])))
    check("expansion, start year and payment tools found",
          any("second location" in e["snippet"] for e in fin.get("expansion", []))
          and (fin.get("start") or {}).get("year") == 2023 and (fin.get("start") or {}).get("young")
          and {"Zelle", "Square", "QuickBooks"} <= {p["tool"] for p in fin.get("payments", [])},
          json.dumps(fin)[:600])
    check("signals reach the evidence but careers pages are not evidence docs",
          any("Accounting-need signals" in doc.text for doc in llm5.seen["background"])
          and not any(doc.url == S + "careers" for doc in llm5.seen["background"]))
    check("hiring search logged, results kept out of the person evidence",
          any(q["purpose"] == "hiring_signal" for q in d5.research_log["queries"])
          and not any("indeed.com" in r["url"] for r in d5.research_log["results"]))

    os.environ["SEARCHER"] = "photographer"
    photog_salon = seller_context_for(salon)
    js2 = JobSearch()
    d6 = build_dossier(dana, salon, search=js2, fetcher=SalonFetcher(), llm=MockDossierLLM(
                           signals=PersonSignals(present_urls=[S])),
                       engagement_researcher=MockEngagementResearcher(), seller=photog_salon,
                       min_seniority=0)
    check("photographer never runs the finance checks or the job search",
          "finance_signals" not in d6.research_log.get("site_signals", {})
          and not any("jobs OR hiring" in q for q in js2.queries))

    class EmptyFR:
        title = "Home"
        final_url = None
        text = "Welcome to our office."
        chrome_text = ""
        links = []
    check("'26 years of experience' (a staff bio) is not the business's age",
          fs.find_founded("With more than 26 years of experience in physical therapy", 2026) == [])
    check("one announcement with several growth words is reported once",
          len(fs.find_expansion("Grand Opening Friday! We are expanding to include a new clinic.")) == 1)
    check("a site hosted on a booking platform is reported as such",
          "hosted on GlossGenius" in fs.find_payments("", [], "https://x.glossgenius.com/about")[0]["where"])
    from contact_dossier import _seniority_score
    from roles import search_terms
    from searcher_profiles.base import effective_play
    from searcher_profiles import get_profile
    titles = [t for rr in effective_play(get_profile("accountant"), "auto_dealership").roles
              for t in search_terms(rr.role.key)]
    check("a dealership Controller clears the accountant's seniority bar",
          _seniority_score("Controller", titles) >= 1)
    check("a page with nothing to report returns None",
          fs.finance_signal_check(EmptyFR(), "https://x.com/") is None)
    check("merge with nothing found returns None", fs.merge_signals([], []) is None)

    ok = all(checks)
    print(f"\n{sum(checks)}/{len(checks)} checks passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
