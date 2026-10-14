"""
OpenAI-backed DossierLLM  (Responses API, strict JSON-schema outputs)

Concrete implementation of the ``DossierLLM`` seam from contact_dossier.py,
using OpenAI (default model ``gpt-5.5``) via the Responses API. This keeps
contact_dossier.py provider-free: the backend binding lives entirely here.

None of these methods uses web search — they reason over text the spine
has already fetched (the ``Doc`` lists) — so each call is a plain
text-in / structured-JSON-out completion with a strict json_schema, which is
where OpenAI Structured Outputs are strongest.

The OpenAI client is injectable (pass ``client=`` in tests); the single network
call is isolated in ``_complete`` so parsing/mapping can be tested offline.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from contact_dossier import (
    DossierLLM,
    PersonSignals,
    BackgroundFact,
    ReachValue,
    EngagementItem,
    OrgInference,
    RapportHook,
    OutreachAngle,
    OutreachBrief,
    SellerContext,
    PersonSearch,
    Doc,
    ContactCandidate,
    CompanyInput,
    _now,
    _TOP_ROLE_RE,
)


def social_pass_wanted(contact, setting: str | None = None) -> bool:
    """Whether to run the second, social-posts web search for this contact.
    DOSSIER_SOCIAL_SEARCH: "top" (default) = only for owners / founders /
    CEOs / presidents / managing partners / dealer principals; "all" = every
    contact (the behaviour before Oct 2026); "off" = never.
    The social pass was ~40% of a dossier's tokens (65k of 159k input for a
    law-firm administrator) and finds most for owner-operators who market
    themselves in community groups (Steven Tison's Facebook posts)."""
    mode = (setting or os.environ.get("DOSSIER_SOCIAL_SEARCH") or "top").strip().lower()
    if mode in ("all", "on", "1", "true", "yes"):
        return True
    if mode in ("off", "0", "false", "no", "none"):
        return False
    return bool(_TOP_ROLE_RE.search(contact.title or ""))
from contact_discovery import SearchResult

DEFAULT_MODEL = "gpt-6.1-sol"


class DossierLLMError(RuntimeError):
    """Raised when an OpenAI DossierLLM call fails or returns unusable output.
    The message names the provider and the failing method, so a downstream
    warning distinguishes an OpenAI fault from a Gemini/Brave one."""


# -----------------------------------------------------------------------------
# Strict JSON schemas (one per method). Strict mode requires every property to
# be listed in "required" and additionalProperties=False; optional fields are
# expressed as nullable unions rather than omitted.
# -----------------------------------------------------------------------------

def _nullable_str() -> dict:
    return {"type": ["string", "null"]}


def _obj(props: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


_URL_NOTE = _obj({"url": {"type": "string"}, "note": {"type": "string"}},
                 ["url", "note"])

SIGNALS_SCHEMA = _obj(
    {
        "present_urls": {"type": "array", "items": {"type": "string"}},
        "departure_signals": {"type": "array", "items": _URL_NOTE},
        "current_title_notes": {"type": "array", "items": _URL_NOTE},
    },
    ["present_urls", "departure_signals", "current_title_notes"],
)

_IDENTITY_DESC = ("confirmed | probable | possible -- is this really the same "
                  "person? (see prompt)")

BACKGROUND_SCHEMA = _obj(
    {
        "facts": {
            "type": "array",
            "items": _obj(
                {
                    "claim": {"type": "string"},
                    "source_url": {"type": "string"},
                    "date": _nullable_str(),
                    "confidence": {"type": "string"},
                    "identity": {"type": "string", "description": _IDENTITY_DESC},
                    "identity_note": {"type": "string"},
                },
                ["claim", "source_url", "date", "confidence", "identity",
                 "identity_note"],
            ),
        }
    },
    ["facts"],
)

REACH_SCHEMA = _obj(
    {
        "values": {
            "type": "array",
            "items": _obj(
                {
                    "value": {"type": "string"},
                    "kind": {"type": "string"},
                    "how_obtained": {"type": "string"},
                    "source_url": {"type": "string"},
                    "confidence": {"type": "string"},
                    "note": {"type": "string"},
                },
                ["value", "kind", "how_obtained", "source_url", "confidence", "note"],
            ),
        }
    },
    ["values"],
)

ENGAGEMENT_SCHEMA = _obj(
    {
        "items": {
            "type": "array",
            "items": _obj(
                {
                    "url": {"type": "string"},
                    "kind": {"type": "string"},
                    "title": {"type": "string"},
                    "date": _nullable_str(),
                    "summary": {"type": "string"},
                    "identity_confidence": {"type": "string"},
                },
                ["url", "kind", "title", "date", "summary",
                 "identity_confidence"],
            ),
        }
    },
    ["items"],
)

ORG_SCHEMA = _obj(
    {
        "inferences": {
            "type": "array",
            "items": _obj(
                {
                    "claim": {"type": "string"},
                    "basis": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string"},
                },
                ["claim", "basis", "confidence"],
            ),
        }
    },
    ["inferences"],
)


RAPPORT_SCHEMA = _obj(
    {
        "hooks": {
            "type": "array",
            "items": _obj(
                {
                    "detail": {"type": "string"},
                    "kind": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                ["detail", "kind", "source_url"],
            ),
        }
    },
    ["hooks"],
)

OUTREACH_SCHEMA = _obj(
    {
        "angles": {
            "type": "array",
            "items": _obj(
                {
                    "angle": {"type": "string"},
                    "opener": {"type": "string"},
                    "rationale": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                ["angle", "opener", "rationale", "evidence"],
            ),
        },
        "likely_needs": {"type": "array", "items": {"type": "string"}},
        "why_now": _nullable_str(),
        "avoid": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "channel": {"type": "string"},
        "tone": {"type": "string"},
    },
    ["angles", "likely_needs", "why_now", "avoid", "open_questions",
     "channel", "tone"],
)


# -----------------------------------------------------------------------------
# Prompt building
# -----------------------------------------------------------------------------

_FIRST_NAME_ONLY_NOTE = (
    "Only this person's FIRST name is known. First establish their full name "
    "from public business sources (the company's own pages, state business "
    "registration, chamber/association listings, press, the business's posts "
    "or review replies) and cite where you found it; then search for them by "
    "full name. If the full name can't be established, say so.\n"
)


def _first_name_only(contact) -> bool:
    return len([t for t in (contact.name or "").split() if t.strip(".,")]) == 1


def _seller_block(seller: SellerContext | None) -> str:
    """Who the outreach is for. Without it, 'relevant' defaults to a generic
    B2B rep, which is how dossiers ended up describing the prospect's
    brochure instead of what the seller can use."""
    if seller is None:
        return ("Seller: a B2B sales rep preparing cold outreach (no seller "
                "profile available).\n\n")
    lines = [
        "Seller (who is doing the outreach and what they sell):",
        f"- {seller.display_name}: {seller.description}",
    ]
    if seller.sales_rationale:
        lines.append(f"- Why they sell to this kind of business: {seller.sales_rationale}")
    return "\n".join(lines) + "\n\n"


def _render_docs(documents: list[Doc], per_doc_chars: int) -> str:
    if not documents:
        return "(no evidence documents)"
    blocks = []
    for i, d in enumerate(documents):
        blocks.append(
            f"[{i}] {d.source_type} | {getattr(d, 'purpose', '') or '-'} | {d.url} | "
            f"fetched_at={d.fetched_at or 'n/a'}\n"
            f"{(d.text or '')[:per_doc_chars]}"
        )
    return "\n\n".join(blocks)


# -----------------------------------------------------------------------------
# The implementation
# -----------------------------------------------------------------------------

def _usage_entry(resp, call: str, model: str) -> dict:
    """Token counts for one Responses API call (0 when the SDK omits them),
    plus how many web searches the model ran."""
    u = getattr(resp, "usage", None)
    searches = sum(1 for o in (getattr(resp, "output", None) or [])
                   if getattr(o, "type", "") == "web_search_call")
    return {"call": call, "model": model,
            "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
            "web_searches": searches}


class _UsageMixin:
    """Keeps a per-instance log of every model call's token counts so a
    dossier can report what it cost (research_log["usage"])."""

    def _record_usage(self, resp, call: str) -> None:
        if not hasattr(self, "_usage_lock"):
            self._usage_lock = threading.Lock()
            self.usage = []
        with self._usage_lock:
            self.usage.append(_usage_entry(resp, call, getattr(self, "model", "")))

    def usage_log(self) -> list[dict]:
        return list(getattr(self, "usage", []) or [])


class OpenAIDossierLLM(_UsageMixin, DossierLLM):
    def __init__(
        self,
        client: Any | None = None,
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 6000,
        per_doc_chars: int = 6000,      # matches contact_dossier's focus_text budget
        max_findings_chars: int = 30000,
    ):
        self._client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.per_doc_chars = per_doc_chars
        self.max_findings_chars = max_findings_chars

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # lazy: module imports without the SDK
            self._client = OpenAI()
        return self._client

    def _complete(self, schema_name: str, schema: dict, prompt: str) -> dict:
        """The single network boundary. Returns parsed JSON or raises."""
        try:
            resp = self._get_client().responses.create(
                model=self.model,
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    }
                },
                max_output_tokens=self.max_output_tokens,
            )
        except Exception as ex:
            raise DossierLLMError(
                f"OpenAI DossierLLM '{schema_name}' call failed: {ex}"
            ) from ex
        self._record_usage(resp, schema_name)
        if getattr(resp, "status", None) == "incomplete":
            reason = getattr(getattr(resp, "incomplete_details", None), "reason", "unknown")
            raise DossierLLMError(
                f"OpenAI DossierLLM '{schema_name}' response was truncated "
                f"({reason}); raise max_output_tokens or reduce evidence size."
            )
        try:
            return json.loads(resp.output_text)
        except Exception as ex:
            raise DossierLLMError(
                f"OpenAI DossierLLM '{schema_name}' returned non-JSON: {ex}"
            ) from ex

    def _context(self, contact: ContactCandidate, company: CompanyInput,
                 documents: list[Doc], seller: SellerContext | None = None) -> str:
        return (
            _seller_block(seller)
            + "Contact under research:\n"
            f"- name: {contact.name}\n"
            f"- title (as discovered): {contact.title or 'unknown'}\n"
            f"- company: {company.canonical_name}\n"
            f"- company website: {company.website or company.domain or 'unknown'}\n"
            f"- location: {company.city}, {company.state}\n\n"
            "Evidence documents (index, source_type, purpose, url, fetched_at, then text).\n"
            "source_type: own_domain_page = the company's own site; external_page = "
            "another site, fetched; search_snippet / social_snippet / linkedin_snippet = "
            "only a search-engine title+snippet (full page NOT read). '[...]' marks "
            "text elided around the person's name.\n"
            f"{_render_docs(documents, self.per_doc_chars)}\n"
        )

    # --- the seam methods --------------------------------------------------

    def detect_person_signals(self, contact, company, documents) -> PersonSignals:
        prompt = self._context(contact, company, documents) + """
Task: using ONLY the evidence above, assess whether this person currently holds
this role at this company.
- Some documents may be about a DIFFERENT person with the same name (search
  results include namesakes). Ignore any document you cannot tie to this
  person (same company, same profession/area, or a known URL).
- present_urls: URLs whose text shows the person is CURRENTLY affiliated with
  the company in this or a similar role.
- current_title_notes: short {url, note} entries confirming the current title.
- departure_signals: include a {url, note} entry ONLY when the evidence
  POSITIVELY indicates THIS person has LEFT or changed employer (a named
  successor in the same seat, "formerly", a different current employer). NEVER
  infer departure from mere absence of the person from a page. A second,
  concurrent role elsewhere is NOT departure. If there is no positive
  departure evidence, return an empty departure_signals array.
Return JSON matching the schema.
"""
        data = self._complete("person_signals", SIGNALS_SCHEMA, prompt)
        return PersonSignals(
            present_urls=list(data.get("present_urls", [])),
            departure_signals=list(data.get("departure_signals", [])),
            current_title_notes=list(data.get("current_title_notes", [])),
        )

    def extract_background_facts(self, contact, company, documents,
                                 seller=None) -> list[BackgroundFact]:
        prompt = self._context(contact, company, documents, seller) + """
Task: extract background facts about THE PERSON that would help the seller
open a cold conversation.
- Focus on the person, not the company brochure: career history and prior
  employers, credentials/licenses, education if role-relevant, how and when
  they started or joined this business, tenure, board or association roles.
- Do NOT include public activity -- posts, talks, panels, podcasts,
  interviews, articles, case studies, award listings, events. A separate
  Engagement section lists those; repeating them here doubles the dossier.
- Return AT MOST 6 facts, the most useful for the seller first. One sentence
  each.
- Do NOT restate the company's service list, pricing, or marketing copy. At
  most ONE fact about the business itself, and only if it says something
  about the person's role (e.g. "founded the firm in 2016").
- EXCLUDE personal-life details (hobbies, pets, family) -- a separate step
  handles self-published personal details.
- If only a first name was known and a business source gives the person's
  FULL name, state it as a fact (e.g. "Full name: Hannah X, per the Georgia
  business filing") with its source and identity level.
- identity (required for every fact):
    "confirmed" = the source ties this name to THIS company (e.g. the company
                  site, or a page naming both);
    "probable"  = same name AND matching profession/area, but the source does
                  not mention this company (e.g. a past employer's staff page
                  in the same metro and field);
    "possible"  = same name, weak or partial match.
  Drop documents clearly about a different person (different field or
  region, unrelated news). identity_note: one short phrase on why (e.g.
  "Atlanta CPA firm staff page; same name and field; ACE not mentioned").
- Date each fact where the evidence supports it; use null when unknown.
- Cite a source_url for every fact. Do not invent facts.
Return JSON matching the schema.
"""
        data = self._complete("background", BACKGROUND_SCHEMA, prompt)
        return [
            BackgroundFact(
                claim=f.get("claim", ""),
                source_url=f.get("source_url", ""),
                date=f.get("date"),
                confidence=f.get("confidence", "low"),
                identity=(f.get("identity") or "possible").lower(),
                identity_note=f.get("identity_note", ""),
            )
            for f in data.get("facts", [])
        ]

    def associate_reach(self, contact, company, documents) -> list[ReachValue]:
        prompt = self._context(contact, company, documents) + """
Task: extract contact-reach info that the evidence EXPLICITLY ties to THIS
person.
- Include only emails/phones/profile URLs the evidence associates with this
  specific person (not generic company info unless it is the person's own).
  At a one- or two-person firm, the firm's main email/phone on its own site
  counts as the person's, with confidence "medium".
- how_obtained: "listed" if directly stated in a source; "snippet" if only from
  a search snippet. Do NOT guess or pattern-invent addresses (deterministic
  email-pattern inference is handled elsewhere).
- Cite source_url. Do not invent values.
Return JSON matching the schema.
"""
        data = self._complete("reach", REACH_SCHEMA, prompt)
        now = _now()
        return [
            ReachValue(
                value=v.get("value", ""),
                kind=v.get("kind", "other"),
                how_obtained=v.get("how_obtained", "snippet"),
                source_url=v.get("source_url", ""),
                confidence=v.get("confidence", "low"),
                fetched_at=now,
                note=v.get("note", ""),
            )
            for v in data.get("values", [])
        ]

    def summarize_engagement(self, contact, company, documents,
                             seller=None) -> list[EngagementItem]:
        prompt = self._context(contact, company, documents, seller) + """
Task: identify PUBLIC activity BY or prominently FEATURING this person that
the seller could reference in a cold opener: posts (including posts in local
community or business groups), articles, interviews, podcasts, talks, awards,
association or chamber involvement, replies to reviews, directory listings
that show what they're doing. For EVERY item, apply all three checks:
1) DISAMBIGUATION: confirm the content is THIS person (same company/role/
   location, or a known URL), not a namesake. Set identity_confidence
   (high/medium/low); drop items you cannot plausibly tie to this person.
2) RELEVANCE: include items useful for a professional conversation with
   this seller. Exclude unrelated personal or historical trivia (e.g. college
   sports, crime or court news about a namesake).
3) RECENCY: prefer recent items; include a date where supported, else null.
- An item seen only as a search/social snippet is allowed: say so in the
  summary ("from search snippet; full text not read").
Skip roster or directory listings (coach lists, advisory-board alumni pages,
staff directories) unless they show recent activity -- the Background
section covers roles.
Return AT MOST 5 items: the most recent and most relevant to the seller's
offer. If two items cover the same thing, keep one. Give each a ONE-sentence
summary of what it says; do not add advice on how to use it (the seller
brings their own approach).
Return JSON matching the schema.
"""
        data = self._complete("engagement", ENGAGEMENT_SCHEMA, prompt)
        return [
            EngagementItem(
                url=i.get("url", ""),
                kind=i.get("kind", "other"),
                title=i.get("title", ""),
                date=i.get("date"),
                summary=i.get("summary", ""),
                identity_confidence=i.get("identity_confidence", "low"),
                relevance=i.get("relevance", ""),
            )
            for i in data.get("items", [])
        ]

    def infer_reporting(self, contact, company, evidence) -> list[OrgInference]:
        prompt = self._context(contact, company, evidence) + """
Task: infer this person's likely reporting relationships and area of
responsibility. This is LOW CONFIDENCE by nature.
- If the evidence shows an owner-operator or a firm of one or two people
  (the person is the founder/owner and no other staff are named), return
  EXACTLY ONE inference, e.g. "Owner-operator; sole decision-maker", and
  nothing else.
- Every inference MUST cite at least one concrete source_url (in "basis") drawn
  from the evidence. If you cannot cite evidence, DO NOT include the inference.
- Do not restate plain employment facts or the company's service list as org
  clues; include only genuine reporting/responsibility inferences.
- Return AT MOST 3 inferences -- the most important only.
- "basis" must contain source URLs only, never quoted or paraphrased evidence
  text. Keep each "claim" to a single sentence.
Return JSON matching the schema.
"""
        data = self._complete("org_inference", ORG_SCHEMA, prompt)
        return [
            OrgInference(
                claim=o.get("claim", ""),
                basis=list(o.get("basis", [])),
                confidence=o.get("confidence", "low"),
            )
            for o in data.get("inferences", [])
        ]

    def extract_rapport_hooks(self, contact, company, documents,
                              seller=None) -> list[RapportHook]:
        prompt = self._context(contact, company, documents, seller) + """
Task: find personal details THIS PERSON CHOSE TO PUBLISH about themselves
that would make a warm, natural opener in a cold message -- e.g. an office
dog or mascot, hobbies or interests named in their bio, why they started the
business, hometown or school they mention, causes or community groups they
promote.
STRICT BOUNDARY -- include a detail only if ALL are true:
- it comes from a source the person controls or authored: their company's own
  site (own_domain_page) or their own post/profile (social/linkedin snippet
  clearly authored by them);
- it is about them, not about family members (no spouse/children names);
- it is NOT home address, health, religion, politics, finances, or anything
  from people-search, background-check or data-aggregator sites, or news.
Return [] if nothing qualifies -- that is a normal outcome.
Return AT MOST 3 hooks. For each: detail (one sentence), kind (pet | hobby |
interest | origin_story | community | other), and source_url. No advice on
how to use it.
Return JSON matching the schema.
"""
        data = self._complete("rapport", RAPPORT_SCHEMA, prompt)
        return [
            RapportHook(
                detail=h.get("detail", ""),
                kind=h.get("kind", "other"),
                source_url=h.get("source_url", ""),
                suggested_use=h.get("suggested_use", ""),
            )
            for h in data.get("hooks", [])
        ]

    def synthesize_outreach(self, contact, company, findings,
                            seller=None) -> OutreachBrief:
        prompt = (
            _seller_block(seller)
            + "Research findings about the prospect (JSON; every item carries "
              "its source URL):\n"
            + json.dumps(findings, indent=1, default=str)[: self.max_findings_chars]
            + """

Task: write a short cold-outreach brief for the seller above.
- angles: 2-3 distinct ways to open. Each has a short label, an opener of 1-2
  plain, specific sentences the seller could adapt (no flattery, no
  "I hope this finds you well"), a rationale tying it to the SELLER'S offer,
  and evidence = the source URLs it rests on. Build openers ONLY from facts
  whose identity is "confirmed" or "probable" and engagement items with
  identity_confidence high/medium. A rapport detail may be one light touch,
  never the whole pitch.
- likely_needs: 1-3 hypotheses about what this prospect might need from the
  seller, phrased as hypotheses and grounded in the findings.
- If the findings include "team_photos" (a count of real vs placeholder vs
  missing photos on the prospect's team/staff page), treat it as concrete,
  checkable evidence: cite the page URL and the numbers. Because "no image
  source" can occasionally mean script-loaded photos, phrase it so it holds
  up ("your staff page shows placeholders for most of the team") and add an
  open question to confirm by viewing the page. If every slot has a real
  photo, do NOT imply photos are missing: the angle is consistency across the
  team, photos taken at different times (see photo_years when present), or
  keeping new hires matching -- and say the look of the photos should be
  checked by eye.
- If the findings include "finance_signals" (an accounting seller's site
  checks: hiring for bookkeeping/office/payroll roles, a new location, move or
  new ownership, the year the business started, and the payment or
  accounting tools its site shows), treat each item as checkable evidence and
  cite its URL. A finance-role job posting is the strongest timing reason
  (they are trying to hire work the seller does); a young business or new
  location is a natural "set up the books right" moment; person-to-person
  apps or "cash/check only" suggest informal bookkeeping, a point-of-sale or
  booking platform means sales that need reconciling, and named accounting
  software is a software-specific angle. Phrase these as observations, never
  as claims about the state of their books.
- why_now: a concrete timing reason if the findings support one (new
  business, recent move, recent post, growth), else null. Do not invent one.
- avoid: things that would land badly (e.g. leading with a detail only seen
  on a third-party site; if the prospect's business competes with the
  seller's, say so here).
- open_questions: identity doubts and contradictions to resolve before
  relying on them (e.g. a "possible"/"probable" prior employer that may or
  may not be current), each phrased as a question.
- channel: the best first channel given what was found (email, phone, a
  specific community group, LinkedIn) and why, in one sentence.
- tone: one short phrase (e.g. "friendly local peer", "brief and formal").
Use only the findings above; do not invent facts.
Return JSON matching the schema.
"""
        )
        data = self._complete("outreach", OUTREACH_SCHEMA, prompt)
        return OutreachBrief(
            angles=[
                OutreachAngle(
                    angle=a.get("angle", ""),
                    opener=a.get("opener", ""),
                    rationale=a.get("rationale", ""),
                    evidence=list(a.get("evidence", [])),
                )
                for a in data.get("angles", [])
            ],
            likely_needs=list(data.get("likely_needs", [])),
            why_now=data.get("why_now"),
            avoid=list(data.get("avoid", [])),
            open_questions=list(data.get("open_questions", [])),
            channel=data.get("channel", ""),
            tone=data.get("tone", ""),
        )


# -----------------------------------------------------------------------------
# Open-web person search (OpenAI hosted web_search tool)
# -----------------------------------------------------------------------------

_MD_LINK_RE = re.compile(r"\(\[[^\]]*\]\([^)]*\)\)|\[([^\]]*)\]\([^)]*\)")


def _field(obj, name, default=None):
    """Attribute-or-key access: SDK objects in production, dicts in tests."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class OpenAIWebPersonSearch(_UsageMixin, PersonSearch):
    """
    One agentic web search per dossier using OpenAI's hosted ``web_search``
    tool -- the same kind of search that found Steven Tison's Facebook group
    posts when Brave's index returned nothing.

    Provenance rule: only URLs the model actually CITED (``url_citation``
    annotations attached by the tool) become results; any URL that appears
    only in the model's prose is ignored. The snippet is the model's own
    one-line note for that citation, so downstream steps treat it like any
    search snippet: identity and relevance are still checked, and pages are
    fetched (unless denylisted, e.g. Facebook/LinkedIn) before being relied on.
    """
    engine = "openai_web"

    def __init__(self, client: Any | None = None, model: str = DEFAULT_MODEL,
                 max_output_tokens: int = 8000, max_results: int = 15,
                 social_pass: bool = True):
        self._client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.max_results = max_results
        # A second, narrower call aimed only at posts in community/social
        # groups. The broad call tends to stop at a few authoritative pages
        # (own site, staff directories) and never looks in group posts.
        self.social_pass = social_pass

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI()
        return self._client

    def _prompt(self, contact, company, seller) -> str:
        return (
            _seller_block(seller)
            + f"Research this person on the public web for a cold-outreach dossier:\n"
            f"- name: {contact.name}\n"
            f"- title: {contact.title or 'unknown'}\n"
            f"- company: {company.canonical_name} ({company.website or company.domain or 'no website'})\n"
            f"- location: {company.city}, {company.state}\n\n"
            "Find distinct public pages about THIS person (not namesakes), especially:\n"
            "- their own posts or introductions in local community / business groups "
            "(Facebook groups, Nextdoor, chamber pages), and their LinkedIn profile;\n"
            "- past and current employers (staff directories, firm bios), licenses or "
            "credentials, education;\n"
            "- articles, interviews, podcasts, talks, awards, association involvement;\n"
            "- business listings or review pages that quote or reply as them.\n"
            "Do NOT use people-search, background-check or data-broker sites, and skip "
            "pages about other people with the same name.\n"
            + (_FIRST_NAME_ONLY_NOTE if _first_name_only(contact) else "")
            + "\n"
            "Answer as a plain list, one line per page (up to 15), each line citing exactly "
            "that page: what it shows about the person, any date, and whether it is clearly "
            "this person or only possibly. If you find nothing reliable, say so."
        )

    def _social_prompt(self, contact, company) -> str:
        words = [w for w in re.split(r"[\s&,.-]+", company.canonical_name) if w]
        acronym = "".join(w[0] for w in words).upper() if len(words) >= 2 else ""
        alias = f' or "{acronym}"' if acronym else ""
        return (
            f"Search social media and community sites for public posts or comments BY "
            f"{contact.name}, who runs \"{company.canonical_name}\"{alias} in "
            f"{company.city}, {company.state}.\n"
            "Look especially for: posts introducing or promoting the business in local "
            "Facebook groups (town, neighborhood, small-business or networking groups in "
            f"{company.city} and nearby towns), Nextdoor posts, LinkedIn posts or profile, "
            "Instagram, and YouTube.\n"
            f"Try several searches, e.g. \"{contact.name}\" facebook group; "
            f"\"{company.canonical_name}\" facebook; \"{contact.name}\" {acronym or company.canonical_name} "
            f"{company.city}; \"{contact.name}\" linkedin.\n"
            "Skip people-search/data-broker sites and other people with the same name.\n"
            "Answer as a plain list, one line per post or profile found, each line citing "
            "exactly that page: what it says, the group or site, any date, and whether it is "
            "clearly this person. A post you can only see in search results still counts -- "
            "cite it and say so. If you find none, say so."
        )

    def _create(self, **kw):
        """Try the GA tool with the company's area as the search location, then
        without the location, then the older preview tool name -- API versions
        differ in what they accept. Raises the last error if all fail."""
        responses = self._get_client().responses
        loc = {k: v for k, v in (getattr(self, "_loc", None) or {}).items() if v}
        attempts = []
        if len(loc) > 2:
            attempts.append({"type": "web_search", "user_location": loc})
        attempts += [{"type": "web_search"}, {"type": "web_search_preview"}]
        last: Exception | None = None
        for tool in attempts:
            try:
                return responses.create(tools=[tool], **kw)
            except Exception as ex:
                last = ex
                msg = str(ex).lower()
                if "401" in msg or "api key" in msg or "429" in msg:
                    break               # auth/rate problems won't fix themselves
        raise last

    def find(self, contact, company, seller=None) -> list[SearchResult]:
        from concurrent.futures import ThreadPoolExecutor
        self._loc = {"type": "approximate", "country": "US",
                     "city": company.city or None, "region": company.state or None}
        prompts = [("general", self._prompt(contact, company, seller))]
        if self.social_pass and social_pass_wanted(contact):
            prompts.append(("social", self._social_prompt(contact, company)))

        def run(label, prompt):
            resp = self._create(model=self.model, input=prompt,
                                max_output_tokens=self.max_output_tokens)
            self._record_usage(resp, f"web_search_{label}")
            return resp

        with ThreadPoolExecutor(max_workers=len(prompts)) as pool:
            futures = [(label, pool.submit(run, label, p)) for label, p in prompts]
        out: list[SearchResult] = []
        seen: set[str] = set()
        errors: list[str] = []
        for label, fut in futures:
            try:
                batch = self._results_from(fut.result())
            except Exception as ex:
                errors.append(f"{label}: {ex}")
                continue
            for r in batch:
                if r.url not in seen:
                    seen.add(r.url)
                    out.append(r)
        if errors and not out:
            raise DossierLLMError("OpenAI web search failed: " + "; ".join(errors))
        return out

    def _results_from(self, resp) -> list[SearchResult]:
        out: list[SearchResult] = []
        seen: set[str] = set()
        for item in _field(resp, "output", None) or []:
            if _field(item, "type") != "message":
                continue
            for part in _field(item, "content", None) or []:
                text = _field(part, "text", "") or ""
                for ann in _field(part, "annotations", None) or []:
                    if _field(ann, "type") != "url_citation":
                        continue
                    url = (_field(ann, "url", "") or "").split("?utm_", 1)[0]
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    start = _field(ann, "start_index", 0) or 0
                    line_start = text.rfind("\n", 0, start) + 1
                    line_end = text.find("\n", start)
                    line = text[line_start: line_end if line_end >= 0 else len(text)]
                    note = _MD_LINK_RE.sub(lambda m: m.group(1) or "", line)
                    note = note.strip(" -*•\t")
                    out.append(SearchResult(
                        title=_field(ann, "title", "") or url,
                        url=url,
                        snippet=f"(web-search note) {note}"[:600],
                        query="(openai web search)",
                    ))
                    if len(out) >= self.max_results:
                        return out
        return out
