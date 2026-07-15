"""
OpenAI-backed DossierLLM  (Responses API, strict JSON-schema outputs)

Concrete implementation of the ``DossierLLM`` seam from contact_dossier.py,
using OpenAI (default model ``gpt-5.5``) via the Responses API. This keeps
contact_dossier.py provider-free: the backend binding lives entirely here.

None of these five methods uses web search — they reason over text the spine
has already fetched (the ``Doc`` lists) — so each call is a plain
text-in / structured-JSON-out completion with a strict json_schema, which is
where OpenAI Structured Outputs are strongest.

The OpenAI client is injectable (pass ``client=`` in tests); the single network
call is isolated in ``_complete`` so parsing/mapping can be tested offline.
"""

from __future__ import annotations

import json
from typing import Any

from contact_dossier import (
    DossierLLM,
    PersonSignals,
    BackgroundFact,
    ReachValue,
    EngagementItem,
    OrgInference,
    Doc,
    ContactCandidate,
    CompanyInput,
    _now,
)

DEFAULT_MODEL = "gpt-5.5"


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
                },
                ["claim", "source_url", "date", "confidence"],
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
                    "relevance": {"type": "string"},
                },
                ["url", "kind", "title", "date", "summary",
                 "identity_confidence", "relevance"],
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


# -----------------------------------------------------------------------------
# Prompt building
# -----------------------------------------------------------------------------

def _render_docs(documents: list[Doc], per_doc_chars: int) -> str:
    if not documents:
        return "(no evidence documents)"
    blocks = []
    for i, d in enumerate(documents):
        blocks.append(
            f"[{i}] {d.source_type} | {d.url} | fetched_at={d.fetched_at or 'n/a'}\n"
            f"{(d.text or '')[:per_doc_chars]}"
        )
    return "\n\n".join(blocks)


# -----------------------------------------------------------------------------
# The implementation
# -----------------------------------------------------------------------------

class OpenAIDossierLLM(DossierLLM):
    def __init__(
        self,
        client: Any | None = None,
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 4000,
        per_doc_chars: int = 4000,
    ):
        self._client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.per_doc_chars = per_doc_chars

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
                 documents: list[Doc]) -> str:
        return (
            "Contact under research:\n"
            f"- name: {contact.name}\n"
            f"- title (as discovered): {contact.title or 'unknown'}\n"
            f"- company: {company.canonical_name}\n"
            f"- location: {company.city}, {company.state}\n\n"
            "Evidence documents (index, source_type, url, fetched_at, then text):\n"
            f"{_render_docs(documents, self.per_doc_chars)}\n"
        )

    # --- the five seam methods ---------------------------------------------

    def detect_person_signals(self, contact, company, documents) -> PersonSignals:
        prompt = self._context(contact, company, documents) + """
Task: using ONLY the evidence above, assess whether this person currently holds
this role at this company.
- present_urls: URLs whose text shows the person is CURRENTLY affiliated with
  the company in this or a similar role.
- current_title_notes: short {url, note} entries confirming the current title.
- departure_signals: include a {url, note} entry ONLY when the evidence
  POSITIVELY indicates the person has LEFT or changed employer (a named
  successor in the same seat, "formerly", a different current employer). NEVER
  infer departure from mere absence of the person from a page. If there is no
  positive departure evidence, return an empty departure_signals array.
Return JSON matching the schema.
"""
        data = self._complete("person_signals", SIGNALS_SCHEMA, prompt)
        return PersonSignals(
            present_urls=list(data.get("present_urls", [])),
            departure_signals=list(data.get("departure_signals", [])),
            current_title_notes=list(data.get("current_title_notes", [])),
        )

    def extract_background_facts(self, contact, company, documents) -> list[BackgroundFact]:
        prompt = self._context(contact, company, documents) + """
Task: extract PROFESSIONALLY RELEVANT background facts (tenure, prior roles,
education if role-relevant).
- Include ONLY facts useful to a B2B sales rep preparing outreach.
- EXCLUDE unrelated personal trivia (hobbies, sports history, family) unless
  clearly relevant to a professional conversation.
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
            )
            for f in data.get("facts", [])
        ]

    def associate_reach(self, contact, company, documents) -> list[ReachValue]:
        prompt = self._context(contact, company, documents) + """
Task: extract contact-reach info that the evidence EXPLICITLY ties to THIS
person.
- Include only emails/phones/profile URLs the evidence associates with this
  specific person (not generic company info unless it is the person's own).
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

    def summarize_engagement(self, contact, company, documents) -> list[EngagementItem]:
        prompt = self._context(contact, company, documents) + """
Task: identify recent PUBLIC content BY or prominently FEATURING this person
that is useful for warm-up outreach. For EVERY item, apply all three checks:
1) DISAMBIGUATION: confirm the content is THIS person (same company/role/
   location, or a known URL), not a namesake. Set identity_confidence
   (high/medium/low); drop items you cannot plausibly tie to this person.
2) PROFESSIONAL RELEVANCE: include only items relevant to a professional/
   business conversation. Exclude unrelated personal or historical trivia
   (e.g. college sports) even when it is clearly the same person.
3) RECENCY: prefer recent items; include a date where supported, else null.
Give each item a one-line summary and a relevance note.
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
- Every inference MUST cite at least one concrete source_url (in "basis") drawn
  from the evidence. If you cannot cite evidence, DO NOT include the inference.
- Do not restate plain employment facts as org clues; include only genuine
  reporting/responsibility inferences.
- Return AT MOST 3 inferences — the most important only.
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
