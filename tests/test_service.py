"""OpenAI response-shape tests for the report-card service, plus one
real HTTP smoke test on an ephemeral port."""
import json
import threading
import urllib.request

from tesla_family_guard.config import Settings
from tesla_family_guard.guard import WeekStats
from tesla_family_guard.server import make_handler
from tesla_family_guard.service import CAPABILITY_BLURB, FamilyGuardService
from http.server import ThreadingHTTPServer


def _stats():
    return {"Model Y": WeekStats(vehicle_name="Model Y", total_miles=120,
                                 night_miles=30, top_speed_mph=92,
                                 speeding_samples=3, harsh_events=1,
                                 curfew_trips=1, geofence_exits=1)}


def _service(**kw):
    s = Settings()
    s.ai_mode = "never"
    for k, v in kw.items():
        setattr(s, k, v)
    return FamilyGuardService(s, stats_provider=_stats)


def _chat(svc, text):
    return svc.chat_completions({"model": "tesla-family-guard",
                                 "messages": [{"role": "user", "content": text}]})


def test_models_shape():
    resp = _service().models_list()
    assert resp["object"] == "list"
    assert resp["data"][0]["id"] == "tesla-family-guard"


def test_report_card_answer_shape_and_content():
    resp = _chat(_service(), "weekly report for the Model Y")
    assert resp["object"] == "chat.completion"
    assert resp["model"] == "tesla-family-guard"
    assert resp["choices"][0]["message"]["role"] == "assistant"
    text = resp["choices"][0]["message"]["content"]
    assert "92 mph" in text and "Weekly report card" in text


def test_speeding_question_answered_without_ai():
    text = _chat(_service(), "was anyone speeding this week?")["choices"][0]["message"]["content"]
    assert "92 mph" in text


def test_unrelated_question_falls_back_to_capabilities():
    text = _chat(_service(), "what is the weather?")["choices"][0]["message"]["content"]
    assert text == CAPABILITY_BLURB


def test_embeddings_shape_and_determinism():
    svc = _service()
    body = {"input": "speeding on Wednesday night"}
    r1 = svc.embeddings(body)
    r2 = svc.embeddings(body)
    assert r1["object"] == "list"
    assert len(r1["data"][0]["embedding"]) == 384
    assert r1["data"][0]["embedding"] == r2["data"][0]["embedding"]
    assert svc.embeddings({"input": "curfew driving"})["data"][0]["embedding"] != \
        r1["data"][0]["embedding"]


def test_http_smoke():
    svc = _service()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models") as r:
            data = json.load(r)
        assert data["data"][0]["id"] == "tesla-family-guard"
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"model": "tesla-family-guard",
                             "messages": [{"role": "user",
                                           "content": "weekly report"}]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            data = json.load(r)
        assert "Weekly report card" in data["choices"][0]["message"]["content"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as r:
            assert json.load(r)["status"] == "ok"
    finally:
        httpd.shutdown()
        httpd.server_close()
