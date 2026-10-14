"""
finance_signals.py -- the accountant profile's site signals.

The photographer's "why now" is a staff page full of missing photos. An
accounting/bookkeeping seller's equivalent is a business showing, on its own
site or in job listings, that its money work is growing or informal:

  * hiring    -- a posting for a bookkeeper, office manager, payroll or
                 accounting role (they are trying to hire work the seller does)
  * expansion -- a new location, a move, new ownership, an acquisition
  * founded   -- the year the business started (a young business is often
                 still on do-it-yourself books)
  * payments  -- the payment / invoicing tools the site shows: person-to-person
                 apps or "pay by check" (informal), point-of-sale or booking
                 platforms (sales that need reconciling), or accounting /
                 invoicing software (QuickBooks, Xero ... -- a software angle)

Everything here is pattern matching on text the business published; it reports
what was SEEN, with the snippet and page, and leaves interpretation to the
reader (and the outreach prompt). Nothing here raises.

Switched on per profile with ``site_signals=["finance_signals"]``.
"""

from __future__ import annotations

import re
from datetime import date

SIGNAL = "finance_signals"

# Roles whose work an outsourced bookkeeping/accounting firm can take on.
FINANCE_ROLE_RE = re.compile(
    r"\b(full[- ]charge bookkeeper|bookkeeper|bookkeeping (?:clerk|assistant|specialist)"
    r"|staff accountant|senior accountant|accountant"
    r"|accounting (?:clerk|assistant|specialist|manager|coordinator|associate)"
    r"|controller|comptroller|chief financial officer|\bcfo"
    r"|payroll (?:specialist|clerk|administrator|coordinator|manager|assistant)"
    r"|accounts (?:payable|receivable)(?: (?:clerk|specialist|coordinator))?"
    r"|billing (?:specialist|coordinator|manager|clerk)"
    r"|business office manager|office manager|office administrator"
    r"|finance (?:manager|assistant|coordinator|director))\b", re.I)

# Words that put a role mention in a hiring context on an ordinary page. Kept
# strict: a staff page that says "Jane, our Office Manager" next to a generic
# "Join our team" button is not a job posting.
HIRING_RE = re.compile(
    r"\b(now hiring|we(?:'re|’re| are) hiring|hiring (?:a|an|for)|job openings?|open positions?"
    r"|positions? available|accepting applications|job description"
    r"|apply (?:now|today|online|here)|seeking (?:a|an) (?:full|part|experienced))\b", re.I)

EXPANSION_RE = re.compile(
    r"\b(new location|second location|third location|another location|additional location"
    r"|now open in|grand opening|opening soon|coming soon to|we(?:'ve|’ve| have) moved"
    r"|new office|new building|new facility|expanded|expanding|expansion"
    r"|new (?:clinic|store|showroom|studio|branch|campus)"
    r"|recently (?:opened|acquired|merged)|under new ownership|new owner(?:ship)?"
    r"|acquired by|merged with|now part of)\b", re.I)

FOUNDED_RE = re.compile(
    r"\b(founded|established|est\.?|since|opened(?: (?:our|its) doors)?|started|"
    r"in business since|family[- ]owned since|serving [^.]{0,60}? since)\s*(?:in\s+)?"
    r"((?:18|19|20)\d{2})\b", re.I)

# Only claims about the BUSINESS. "26 years of experience" on a team page is
# about a staff member (Duluth Chiropractic's physical therapist), not the firm.
YEARS_CLAIM_RE = re.compile(
    r"\b(?:over|more than|nearly|almost)?\s*(\d{1,3})\+?\s+years\s+"
    r"(?:in business|of business|serving (?:the|our)|of serving|in (?:the|our) community)", re.I)

# Payment / money tools: name -> (kind, url fragments, text phrases).
# kind: p2p (person-to-person apps), manual (cash/check), pos (point-of-sale /
# booking platforms that take payments), software (accounting / invoicing).
PAYMENT_TOOLS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "Zelle": ("p2p", (), ("zelle",)),
    "Venmo": ("p2p", ("venmo.com",), ("venmo",)),
    "Cash App": ("p2p", ("cash.app",), ("cash app", "cashapp")),
    "PayPal": ("p2p", ("paypal.com", "paypal.me"), ("paypal",)),
    "Cash or check only": ("manual", (), ("cash only", "cash or check only", "checks only",
                                          "pay by check", "checks payable to",
                                          "mail a check", "mail your check", "make checks payable")),
    "Square": ("pos", ("square.site", "squareup.com", "square.link"), ()),
    "Stripe payment link": ("pos", ("buy.stripe.com", "checkout.stripe.com"), ()),
    "Clover": ("pos", ("clover.com",), ()),
    "Toast": ("pos", ("toasttab.com",), ()),
    "GlossGenius": ("pos", ("glossgenius.com",), ()),
    "Vagaro": ("pos", ("vagaro.com",), ()),
    "Mindbody": ("pos", ("mindbodyonline.com", "mindbody.io"), ()),
    "Booksy": ("pos", ("booksy.com",), ()),
    "QuickBooks": ("software", ("quickbooks.intuit.com", "connect.intuit.com",
                                "payments.intuit.com"), ("quickbooks",)),
    "Xero": ("software", ("xero.com",), ()),
    "FreshBooks": ("software", ("freshbooks.com",), ("freshbooks",)),
    "Wave": ("software", ("waveapps.com",), ()),
    "HoneyBook": ("software", ("honeybook.com",), ("honeybook",)),
    "Bill.com": ("software", ("bill.com",), ()),
    "Invoice2go": ("software", ("invoice2go.com",), ()),
}
KIND_LABEL = {"p2p": "person-to-person app", "manual": "cash/check",
              "pos": "point-of-sale/booking platform", "software": "accounting/invoicing software"}

# Links worth following to find job postings on the business's own site, and
# applicant-tracking hosts small businesses use for their careers pages.
CAREERS_LINK_WORDS = ("career", "jobs", "job-", "/job", "hiring", "join our team",
                      "join-our-team", "joinourteam", "employment", "work with us",
                      "work-with-us", "openings", "opportunities", "apply")
ATS_HOSTS = ("applytojob.com", "bamboohr.com", "workable.com", "paylocity.com",
             "jobs.lever.co", "greenhouse.io", "indeed.com", "ziprecruiter.com",
             "breezy.hr", "jazzhr.com", "recruitee.com", "gusto.com", "adp.com",
             # Dealership and multi-location employers (Gwinnett Place Nissan
             # lists its jobs at careers.hireology.com/gwinnettplacenissan).
             "hireology.com", "paycomonline.net", "ultipro.com", "ukg.com",
             "icims.com", "dayforcehcm.com", "myworkdayjobs.com", "applicantpro.com",
             "harri.com", "workstream.us")
# Hosts whose pages list ONE employer's openings (worth opening from a job
# search). Aggregators like Indeed/ZipRecruiter mix employers and are judged
# on their snippets only.
EMPLOYER_JOB_HOSTS = tuple(h for h in ATS_HOSTS if h not in ("indeed.com", "ziprecruiter.com"))
CAREERS_PAGE_WORDS = ("career", "job", "hiring", "employment", "join", "opening",
                      "position", "apply")

def _snippet(text: str, start: int, end: int, width: int = 110) -> str:
    a = max(0, start - width)
    b = min(len(text), end + width)
    s = re.sub(r"\s+", " ", text[a:b]).strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


_SENT_END = re.compile(r"[.!?\n]")


def _sentence_context(text: str, start: int, end: int) -> str:
    """The sentence holding [start:end], plus the sentence before it when that
    one is a short heading ("Now Hiring!" above "Bookkeeper -- full time")."""
    a = max((m.end() for m in _SENT_END.finditer(text, 0, start)), default=0)
    nxt = _SENT_END.search(text, end)
    b = nxt.end() if nxt else len(text)
    k = a
    while k > 0 and (text[k - 1] in ".!?\n" or text[k - 1].isspace()):
        k -= 1
    prev_a = max((m.end() for m in _SENT_END.finditer(text, 0, k)), default=0)
    prev = text[prev_a:a]
    return (prev if len(prev.strip()) <= 40 else "") + text[a:b]


def _canon_role(role: str) -> str:
    r = re.sub(r"\s+", " ", role.lower().replace("-", " ")).strip()
    return {"chief financial officer": "cfo", "comptroller": "controller"}.get(r, r)


# On a careers page, a role counts only near job-listing wording. Blueprint
# Smiles' "Join Our Team" link led to its leadership page, and the CEO's "Chief
# Financial Officer" title was reported as a CFO opening.
CAREERS_CONTEXT_RE = re.compile(
    r"\b(hiring|positions?|openings?|open roles?|job|jobs|apply|application|"
    r"careers?|vacanc\w*|join us|full[- ]time|part[- ]time|now accepting)\b", re.I)
_CAREERS_WINDOW = 250


def find_hiring(text: str, careers_page: bool = False, listing: bool = False) -> list[dict]:
    """Finance-role mentions in a hiring context.
    listing=True (a job-board title/snippet): every finance role counts.
    careers_page=True: a job-listing word must be within ~250 characters.
    Otherwise: a hiring phrase must be in the same sentence."""
    out: list[dict] = []
    seen: set[str] = set()
    for m in FINANCE_ROLE_RE.finditer(text or ""):
        role = _canon_role(m.group(1))
        if role in seen:
            continue
        if listing:
            ok = True
        elif careers_page:
            near = text[max(0, m.start() - _CAREERS_WINDOW): m.end() + _CAREERS_WINDOW]
            ok = bool(CAREERS_CONTEXT_RE.search(near))
        else:
            ok = bool(HIRING_RE.search(_sentence_context(text, m.start(), m.end())))
        if ok:
            seen.add(role)
            out.append({"role": role, "snippet": _snippet(text, m.start(), m.end())})
        if len(out) >= 4:
            break
    return out


def find_expansion(text: str) -> list[dict]:
    """Growth/change phrases. Several phrases in one announcement ("Grand
    Opening ... is expanding to include ...") are reported once."""
    out, seen, kept_at = [], set(), []
    for m in EXPANSION_RE.finditer(text or ""):
        key = m.group(1).lower()
        if key in seen or any(abs(m.start() - k) < 200 for k in kept_at):
            continue
        seen.add(key)
        kept_at.append(m.start())
        out.append({"phrase": m.group(1), "snippet": _snippet(text, m.start(), m.end())})
        if len(out) >= 4:
            break
    return out


def find_founded(text: str, this_year: int | None = None) -> list[dict]:
    this_year = this_year or date.today().year
    out, seen = [], set()
    for m in FOUNDED_RE.finditer(text or ""):
        year = int(m.group(2))
        if not (1850 <= year <= this_year) or year in seen:
            continue
        seen.add(year)
        out.append({"year": year, "snippet": _snippet(text, m.start(), m.end(), 70)})
    for m in YEARS_CLAIM_RE.finditer(text or ""):
        n = int(m.group(1))
        if 1 <= n <= 150:
            out.append({"years_claim": n, "snippet": _snippet(text, m.start(), m.end(), 70)})
            break
    return out[:4]


def find_payments(text: str, links: list[dict] | None, page_url: str = "") -> list[dict]:
    from urllib.parse import urlparse
    low = (text or "").lower()
    hrefs = [((l.get("href") or "").lower(), l.get("href") or "") for l in (links or [])]
    page_host = (urlparse(page_url).netloc or "").lower()
    out = []
    for name, (kind, url_bits, phrases) in PAYMENT_TOOLS.items():
        where = None
        if page_host and any(b in page_host for b in url_bits):
            # e.g. jrskinstudio.glossgenius.com -- the business's whole site
            # (booking and checkout) runs on the platform.
            where = f"the business's own website is hosted on {name} ({page_host})"
        for low_h, h in ([] if where else hrefs):
            if any(b in low_h for b in url_bits):
                where = f"link: {h[:120]}"
                break
        if where is None:
            for p in phrases:
                m = re.search(r"\b" + re.escape(p) + r"\b", low)
                if m:
                    where = "text: " + _snippet(text, m.start(), m.end(), 60)
                    break
        if where:
            out.append({"tool": name, "kind": kind, "where": where})
    return out


def is_careers_page(url: str, title: str | None) -> bool:
    blob = f"{url} {title or ''}".lower()
    return any(w in blob for w in CAREERS_PAGE_WORDS)


def score_careers_link(link: dict, own_domain: str) -> int:
    """>0 when a link looks like it leads to the business's job postings
    (on its own site or a known applicant-tracking host)."""
    from urllib.parse import urlparse
    href = link.get("href") or ""
    host = (urlparse(href).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or not (host == own_domain or host.endswith("." + own_domain)
                        or any(host == a or host.endswith("." + a) for a in ATS_HOSTS)):
        return 0
    blob = f"{link.get('text') or ''} {urlparse(href).path}".lower()
    if not any(w in blob for w in CAREERS_LINK_WORDS):
        return 0
    # "Apply for financing" / "credit application" on dealer and medical sites
    # are not job pages.
    if any(w in blob for w in ("financ", "credit", "loan", "insurance", "patient", "lease")):
        return 0
    return 2 if any(w in blob for w in ("career", "job", "hiring", "employment", "join")) else 1


def finance_signal_check(fr, url: str, careers_page: bool = False,
                         this_year: int | None = None) -> dict | None:
    """Signals on one fetched page (main text + header/footer text + links).
    None when nothing was seen."""
    text = (getattr(fr, "text", "") or "")
    chrome = getattr(fr, "chrome_text", "") or ""
    full = text + ("\n" + chrome if chrome else "")
    careers_page = careers_page or is_careers_page(fr.final_url or url, fr.title)
    found = {
        "hiring": find_hiring(text, careers_page=careers_page),
        "expansion": find_expansion(text),
        "founded": find_founded(full, this_year),
        "payments": find_payments(full, getattr(fr, "links", None), fr.final_url or url),
    }
    if not any(found.values()):
        return None
    found["url"] = fr.final_url or url
    found["summary"] = page_summary(found)
    return found


def page_summary(found: dict) -> str:
    parts = []
    if found.get("hiring"):
        parts.append("hiring/job mention for " + ", ".join(
            f'{h["role"]} ("{h["snippet"][:140]}")' for h in found["hiring"]))
    if found.get("expansion"):
        parts.append("growth/change: " + "; ".join(
            f'"{e["snippet"][:140]}"' for e in found["expansion"]))
    yrs = [f for f in found.get("founded") or [] if f.get("year")]
    if yrs:
        parts.append("start year: " + ", ".join(str(f["year"]) for f in yrs))
    if found.get("payments"):
        parts.append("payment/money tools shown: " + ", ".join(
            f'{p["tool"]} ({KIND_LABEL[p["kind"]]})' for p in found["payments"]))
    return "[Accounting-need signals on this page: " + "; ".join(parts) + "]"


def search_hiring_hits(results, co_word: str) -> list[dict]:
    """Job listings from a search (e.g. Indeed) that name the business and a
    finance role. ``results`` are SearchResults."""
    out, seen = [], set()
    for r in results or []:
        blob = f"{r.title} {r.snippet}"
        if co_word and co_word not in f"{blob} {r.url}".lower():
            continue
        for h in find_hiring(blob, listing=True):
            key = (h["role"], r.url)
            if key not in seen:
                seen.add(key)
                out.append({"role": h["role"], "snippet": f"{r.title} — {r.snippet}"[:240],
                            "url": r.url, "source": "search"})
    return out[:5]


def employer_job_pages(results, co_word: str, own_domain: str = "", limit: int = 1) -> list[str]:
    """Job-search results that are the business's own job board (its careers
    page or an applicant-tracking page naming it), worth opening because
    titles and snippets rarely list every role."""
    from urllib.parse import urlparse
    out = []
    for r in results or []:
        host = (urlparse(r.url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        own = own_domain and (host == own_domain or host.endswith("." + own_domain))
        ats = any(host == h or host.endswith("." + h) for h in EMPLOYER_JOB_HOSTS)
        if not (own or ats):
            continue
        if ats and co_word and co_word not in f"{r.title} {r.snippet} {r.url}".lower():
            continue
        if own and not is_careers_page(r.url, r.title):
            continue
        out.append(r.url)
        if len(out) >= limit:
            break
    return out


def merge_signals(page_entries: list[dict], search_hits: list[dict] | None = None,
                  this_year: int | None = None) -> dict | None:
    """One company-level view across every page checked plus job-search hits.
    None when nothing at all was seen."""
    this_year = this_year or date.today().year
    hiring, expansion, payments, founded, claims = [], [], [], [], []
    seen_roles, seen_tools, seen_exp = set(), set(), set()
    for e in page_entries:
        u = e.get("url")
        for h in e.get("hiring") or []:
            if h["role"] not in seen_roles:
                seen_roles.add(h["role"])
                hiring.append({**h, "url": u, "source": "own_site"})
        for x in e.get("expansion") or []:
            if x["phrase"].lower() not in seen_exp:
                seen_exp.add(x["phrase"].lower())
                expansion.append({**x, "url": u})
        for f in e.get("founded") or []:
            (founded if f.get("year") else claims).append({**f, "url": u})
        for p in e.get("payments") or []:
            if p["tool"] not in seen_tools:
                seen_tools.add(p["tool"])
                payments.append({**p, "url": u})
    for h in search_hits or []:
        if h["role"] not in seen_roles:
            seen_roles.add(h["role"])
            hiring.append(h)
    if not (hiring or expansion or payments or founded or claims):
        return None
    start = None
    if founded:
        # The earliest stated year is the safest reading of "since/established".
        f0 = min(founded, key=lambda f: f["year"])
        start = {"year": f0["year"], "years_in_business": this_year - f0["year"],
                 "snippet": f0["snippet"], "url": f0["url"],
                 "young": this_year - f0["year"] <= 3}
    elif claims:
        c0 = claims[0]
        start = {"year": None, "years_in_business": c0["years_claim"],
                 "snippet": c0["snippet"], "url": c0["url"], "young": c0["years_claim"] <= 3}
    return {"hiring": hiring[:5], "expansion": expansion[:4], "start": start,
            "payments": payments[:8]}
