"""
x_check_site.py -- why can't the app read a website?

    venv\\Scripts\\python scratch\\x_check_site.py https://www.blueprintsmiles.com/

Prints the site's robots.txt, then what the app's PageFetcher gets for the
homepage (status, skip reason, text length, links), and -- for comparison
only -- what a plain browser-like request gets. Reads 2-3 pages; no API keys.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from urllib.parse import urlparse
from fetch_and_extract import PageFetcher, DEFAULT_USER_AGENT

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.blueprintsmiles.com/"
p = urlparse(url)
robots = f"{p.scheme}://{p.netloc}/robots.txt"
print(f"== {robots}")
try:
    r = requests.get(robots, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=15)
    print(f"status {r.status_code}\n{r.text[:1500]}")
except Exception as ex:
    print("error:", ex)

print(f"\n== App fetcher (User-Agent: {DEFAULT_USER_AGENT})")
fr = PageFetcher().fetch(url)
print(f"ok={fr.ok} status={fr.status_code} skipped={fr.skipped_reason} error={fr.error} "
      f"final_url={fr.final_url}\ntitle={fr.title!r} text_chars={len(fr.text)} links={len(fr.links)}")
print(fr.text[:300])

print("\n== Plain browser-like request (comparison only, robots not checked)")
try:
    r = requests.get(url, timeout=15, headers={"User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"})
    print(f"status {r.status_code}, {len(r.text)} bytes, server={r.headers.get('server')}")
except Exception as ex:
    print("error:", ex)
