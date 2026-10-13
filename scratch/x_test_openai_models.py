"""
x_test_openai_models.py -- OFFLINE checks for the OpenAI switch in Discover
(gpt-6-luna) and Enrich (gpt-6.1-sol). A fake client records each request.

Run:  python scratch/x_test_openai_models.py      (exit 0 = all checks pass)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SEARCHER"] = "photographer"

from contact_discovery import (CompanyInput, SearchResult, OpenAIExtractor,
                               resolve_segment, resolve_play)
from searcher_profiles import get_profile

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


class Resp:
    def __init__(self, text): self.output_text = text


class FakeResponses:
    def __init__(self, reject_strict=False):
        self.calls, self.reject_strict = [], reject_strict

    def create(self, **kw):
        self.calls.append(kw)
        if self.reject_strict and kw["text"]["format"]["type"] == "json_schema":
            raise ValueError("400 Invalid value for text.format: json_schema not supported")
        return Resp(json.dumps({"people": [
            {"name": "Michael Cappelluti", "title": "General Manager", "evidence_idx": [0],
             "confidence": "high", "why_relevant": "Owns the staff page and website."}]}))


class FakeClient:
    def __init__(self, **kw): self.responses = FakeResponses(**kw)


dealer = CompanyInput(canonical_name="Gwinnett Place Nissan", input_name="x", city="Duluth",
                      state="GA", places_type="car_dealer", domain="gwinnettplacenissan.com")
seg, _ = resolve_segment(dealer)
play, _ = resolve_play(get_profile("photographer"), seg)
results = [SearchResult("Meet Our Staff", "https://www.gwinnettplacenissan.com/dealership/staff.htm",
                        "Michael Cappelluti General Manager", "q")]

print("Discover extractor")
fc = FakeClient()
ext = OpenAIExtractor(client=fc)
people = ext.extract(dealer, seg, play, results)
call = fc.responses.calls[0]
check("defaults to gpt-6-luna with reasoning effort low",
      call["model"] == "gpt-6-luna" and call["reasoning"] == {"effort": "low"}, str(call["model"]))
check("uses a strict JSON schema", call["text"]["format"]["type"] == "json_schema"
      and call["text"]["format"]["strict"] is True)
check("prompt asks for the {people: [...]} wrapper", '{"people"' in call["input"]
      and "Return ONLY a JSON array" not in call["input"])
check("candidate parsed with evidence", len(people) == 1 and people[0].name == "Michael Cappelluti"
      and people[0].evidence[0]["url"].endswith("staff.htm"))

fc2 = FakeClient(reject_strict=True)
people2 = OpenAIExtractor(client=fc2).extract(dealer, seg, play, results)
check("falls back to plain JSON mode if strict schema is rejected",
      [c["text"]["format"]["type"] for c in fc2.responses.calls] == ["json_schema", "json_object"]
      and len(people2) == 1)

os.environ["DISCOVERY_MODEL"] = "gpt-6.1-sol"
os.environ["DISCOVERY_REASONING_EFFORT"] = "none"
e3 = OpenAIExtractor(client=FakeClient())
check("DISCOVERY_MODEL / DISCOVERY_REASONING_EFFORT override", e3.model == "gpt-6.1-sol"
      and e3.reasoning_effort == "none")
del os.environ["DISCOVERY_MODEL"], os.environ["DISCOVERY_REASONING_EFFORT"]

print("\nApp wiring")
from app import create_app
app = create_app()
with app.app_context():
    from services import contacts as sc
    app.config["OPENAI_API_KEY"] = "test-key"
    check("Discover uses the OpenAI extractor by default", type(sc._extractor()).__name__ == "OpenAIExtractor")
    os.environ["DISCOVERY_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = app.config.get("GEMINI_API_KEY") or "g-test"
    g = sc._extractor()
    check("DISCOVERY_PROVIDER=gemini switches back (3.8 Flash default)",
          type(g).__name__ == "GeminiExtractor" and g.model == "gemini-3.8-flash", g.model)
    del os.environ["DISCOVERY_PROVIDER"]

    import services.intel as si
    captured = {}

    class IntelResponses:
        def create(self, **kw):
            captured.update(kw)
            class R:
                output = [type("M", (), {"type": "message", "content": [
                    type("C", (), {"text": json.dumps({k: "x" for k in si.EXTRACTION_SCHEMA["schema"]["required"]})})()]})()]
            return R()

    class IntelClient:
        def __init__(self, **kw): self.responses = IntelResponses()

    si.OpenAI = IntelClient
    out = si.extract_intel("Gwinnett Place Nissan", "Duluth GA", "[Page: x] Michael Cappelluti GM")
    check("Enrich uses gpt-6.1-sol with reasoning effort low",
          captured.get("model") == "gpt-6.1-sol" and captured.get("reasoning") == {"effort": "low"},
          str(captured.get("model")))
    check("Enrich output still parses", out.get("key_contacts") == "x")

print(f"\n{sum(checks)}/{len(checks)} checks passed")
sys.exit(0 if all(checks) else 1)
