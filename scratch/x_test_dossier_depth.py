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
    BackgroundFact, EngagementItem, MockDossierLLM, MockPersonSearch, OutreachAngle, OutreachBrief,
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
        purpose = next(p for p, q in build_research_queries(CONTACT, COMPANY, 9) if q == query)
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
                      person_search=web, min_seniority=0)

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

    ok = all(checks)
    print(f"\n{sum(checks)}/{len(checks)} checks passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
