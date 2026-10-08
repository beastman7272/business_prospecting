"""
x_smoke_stage3.py — one-contact LIVE smoke test for Stage 3.

RUN THIS LOCALLY. It makes real Brave + OpenAI calls, so it needs
BRAVE_SEARCH_API_KEY and OPENAI_API_KEY in your .env. It is a throwaway
diagnostic (hence the x_ prefix), not part of the app.

Goal: prove the MECHANICS end-to-end on a real person —
  - gpt-5.5 accepts the DossierLLM params and returns parseable JSON,
  - the fetcher pulls real page text and the LinkedIn/social denylist fires,
  - a real dossier assembles and serializes,
  - no track raises.
It does NOT judge dossier quality — that needs the eval harness and
hand-verified ground truth, not one anecdote.

Subject: Dr. Marta M. Trujillo, owner of Atlas Chiropractic & Wellness Center,
Duluth GA (places_type 'chiropractor' -> healthcare_practice segment).

NOTE ON THE DOMAIN: the practice's current live site is
atlaschiropractic-wellness.com (GoDaddy). An older domain, chiroatlas.com,
still appears in search results but now redirect-loops on deep paths, so it is
NOT used here — a good reminder that Stage 1/2 must capture the *current*
domain or Stage 3's own-domain fetch will hit a dead URL.
"""

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from contact_discovery import CompanyInput, ContactCandidate, BraveSearchProvider
from fetch_and_extract import PageFetcher
from contact_dossier import (
    build_dossier, dossier_to_dict, SpineEngagementResearcher,
)
from dossier_llm_openai import OpenAIDossierLLM

OWN_DOMAIN = "atlaschiropractic-wellness.com"


def build_subject() -> tuple[ContactCandidate, CompanyInput]:
    company = CompanyInput(
        canonical_name="Atlas Chiropractic & Wellness Center",
        input_name="Atlas Chiropractic & Wellness Center",
        city="Duluth", state="GA",
        places_type="chiropractor",                 # -> healthcare_practice
        website=f"https://{OWN_DOMAIN}/",
        domain=OWN_DOMAIN,
        phone="(770) 495-3444",
        address="2800 Peachtree Industrial Blvd Ste F, Duluth, GA 30097",
    )
    contact = ContactCandidate(
        name="Dr. Marta M. Trujillo",
        title="Owner / Lead Chiropractor",
        company="Atlas Chiropractic & Wellness Center",
        # Seed evidence the way Stage 2 would: own-domain pages. Homepage first
        # (confirmed content-rich: bio + phone); about/contact add depth.
        evidence=[
            {"url": f"https://{OWN_DOMAIN}/", "snippet": "Dr. Marta M. Trujillo, D.C.", "query": "(seed)"},
            {"url": f"https://{OWN_DOMAIN}/about", "snippet": "About", "query": "(seed)"},
            {"url": f"https://{OWN_DOMAIN}/contact", "snippet": "Contact", "query": "(seed)"},
        ],
        confidence="high",
        why_relevant="Practice owner/lead doctor; decision-maker for buildouts.",
    )
    return contact, company


class LoggingFetcher(PageFetcher):
    """Real fetcher that records and prints every fetch (so you can watch which
    URLs are hit and confirm the denylist skips social sites)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.log = []

    def fetch(self, url):
        r = super().fetch(url)
        self.log.append(r)
        print(f"  [fetch] ok={r.ok} status={r.status_code} "
              f"skip={r.skipped_reason} err={r.error} "
              f"bytes={len(r.text or '')} :: {url}")
        return r


def summarize(dossier, fetcher) -> bool:
    d = dossier
    checks: list[bool] = []

    def check(name, ok, detail=""):
        checks.append(bool(ok))
        line = f"  [{'PASS' if ok else 'FAIL'}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)

    print("\n================ MECHANICS SUMMARY ================")

    check("dossier returned (no crash)", d is not None)
    check("gate produced a verdict",
          d.gate.currency in ("current", "uncertain", "likely_departed"),
          f"currency={d.gate.currency}, worth={d.gate.worth_deepdive}, "
          f"seniority={d.gate.seniority_score}")

    own = [f for f in fetcher.log
           if f.ok and (f.text or "") and OWN_DOMAIN in f.url]
    check("fetched >=1 own-domain page with real text", len(own) > 0,
          f"{len(own)} own-domain page(s)")

    denied = sorted({f.skipped_reason for f in fetcher.log
                     if f.skipped_reason and f.skipped_reason.startswith("denylisted")})
    check("denylist enforced (informational)", True,
          (", ".join(denied)) if denied else "no denylisted URLs appeared this run")

    provider_fail = [w for w in d.warnings if "failed" in w.lower()]
    check("no provider-failure warnings", len(provider_fail) == 0,
          "; ".join(provider_fail) if provider_fail else "clean")

    try:
        json.dumps(dossier_to_dict(d))
        ser_ok = True
    except Exception as e:
        ser_ok = False
        print("   serialization error:", e)
    check("dossier serializes to JSON", ser_ok)

    print("\n  Track counts: "
          f"reach={len(d.reach)}, background={len(d.background)}, "
          f"engagement={len(d.engagement)}, org={len(d.org_inferences)}")
    if d.warnings:
        print("  Warnings:")
        for w in d.warnings:
            print("   -", w)

    all_ok = all(checks)
    print("\n  RESULT:", "MECHANICS OK" if all_ok else "MECHANICS FAILED")
    print("==================================================")
    return all_ok


def main() -> int:
    for key in ("OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY"):
        if not os.environ.get(key):
            print(f"ERROR: {key} not set (check your .env). Aborting.")
            return 1

    contact, company = build_subject()
    print(f"Smoke-test subject: {contact.name} @ {company.canonical_name}\n")

    search = BraveSearchProvider()
    fetcher = LoggingFetcher()
    llm = OpenAIDossierLLM()                    # model defaults to gpt-5.5
    engagement = SpineEngagementResearcher(
        search=search, fetcher=fetcher, llm=llm, max_pages=3
    )

    print("Running build_dossier (LIVE)...\n")
    dossier = build_dossier(
        contact, company,
        search=search, fetcher=fetcher, llm=llm,
        engagement_researcher=engagement,
        min_seniority=0,       # don't let the gate short-circuit the test subject
        max_pages=3,           # keep the run small
    )

    print("\n---------------- FULL DOSSIER JSON ----------------")
    print(json.dumps(dossier_to_dict(dossier), indent=2))

    ok = summarize(dossier, fetcher)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
