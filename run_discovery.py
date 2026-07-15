"""
Entry point for contact discovery -- the cutover from the old hardcoded harness.

The original app ran a fixed company through a GC-only pipeline in
contact_discovery.py's __main__. This replaces that: the active searcher comes
from the SEARCHER env var (or --searcher), the company comes from CLI args, and
the same (segment x profile) pipeline serves any registered searcher.

Examples
--------
  # Real run (needs BRAVE_SEARCH_API_KEY + GEMINI_API_KEY; SEARCHER from .env):
  python run_discovery.py --name "Blevins & Hong, PC" --city Duluth --state GA \
      --type lawyer --website https://gwinnettcountylaw.com/

  # Offline wiring check, overriding the searcher:
  python run_discovery.py --searcher accountant --type plumber \
      --name "Ace Plumbing" --city Duluth --state GA --mock

Run from the searcher_refactor/ directory. The optional own-domain fetch
(--fetch-own-domain) needs fetch_and_extract.py importable (it lives one level
up in the project root).
"""

from __future__ import annotations

import argparse
import json

from searcher_profiles import get_profile
from active_profile import get_active_profile
from contact_discovery import (
    CompanyInput, BraveSearchProvider, GeminiExtractor,
    MockSearchProvider, MockExtractor, discover_contacts, run_to_dict,
)


def _domain_from_website(website: str | None) -> str | None:
    if not website:
        return None
    d = website.strip().lower()
    if "://" in d:
        d = d.split("://", 1)[1]
    return d.split("/", 1)[0] or None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run contact discovery for one company.")
    p.add_argument("--name", required=True, help="Company name")
    p.add_argument("--city", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--type", dest="places_type", required=True,
                   help="Google Places type, e.g. lawyer, hospital, plumber")
    p.add_argument("--website", default=None)
    p.add_argument("--address", default=None)
    p.add_argument("--searcher", default=None,
                   help="Override the active searcher key (else SEARCHER env / default gc)")
    p.add_argument("--mock", action="store_true",
                   help="Use offline mock providers (no API keys / no network)")
    p.add_argument("--fetch-own-domain", action="store_true",
                   help="Also read the company's own-domain pages (needs fetch_and_extract)")
    p.add_argument("--max-results", type=int, default=5)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    # Active searcher: explicit flag wins, else env/default via active_profile.
    profile = get_profile(args.searcher) if args.searcher else get_active_profile()

    company = CompanyInput(
        canonical_name=args.name, input_name=args.name,
        city=args.city, state=args.state, places_type=args.places_type,
        website=args.website, domain=_domain_from_website(args.website),
        address=args.address,
    )

    if args.mock:
        search_provider = MockSearchProvider()
        extractor = MockExtractor([])
    else:
        search_provider = BraveSearchProvider()   # reads BRAVE_SEARCH_API_KEY
        extractor = GeminiExtractor()              # reads GEMINI_API_KEY

    run = discover_contacts(
        company, profile, search_provider, extractor,
        max_results_per_query=args.max_results,
        fetch_own_domain=args.fetch_own_domain,
    )
    print(json.dumps(run_to_dict(run), indent=2))


if __name__ == "__main__":
    main()
