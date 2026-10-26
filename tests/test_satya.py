from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.classifier import classify
from app.engine import Engine
from app.hotspot import find_hotspots
from app.main import create_app
from app.telephony import Provider, Reply

T0 = datetime(2026, 10, 26, 10, 0)


class Scripted(Provider):
    """Replies from a per-ticket list; None means no pickup. Records channels used."""

    def __init__(self, replies):
        self.replies, self.channels = replies, []

    def _next(self, ticket, channel):
        self.channels.append(channel)
        queue = self.replies.get(ticket["id"], [])
        return Reply(queue.pop(0) if queue else None, 1.0)

    def place_call(self, ticket, script):
        return self._next(ticket, "voice")

    def send_message(self, ticket, text):
        return self._next(ticket, "message")


def ticket(i="T1", status="resolved", **kw):
    return {"id": i, "phone": "9876543210", "language": "kn", "category": "Drainage", "description": "Drain overflowing",
            "ward": "Jayanagar", "officer": "Ravi", "supervisor": "Murthy", "head": "Commissioner", "status": status, **kw}


@pytest.fixture
def make(tmp_path):
    def _make(replies=None):
        e = Engine(str(tmp_path / "t.db"), Scripted(replies or {}))
        return e
    return _make


def test_classifier_languages_and_keypad():
    assert classify("1") == "yes" and classify("2") == "no" and classify("3") == "partly"
    assert classify("Yes, it is fixed") == "yes"
    assert classify("not fixed") == "no"
    assert classify("no problem now") == "yes"
    assert classify("partly fixed") == "partly"
    assert classify("नहीं, अभी भी वैसा ही है") == "no"
    assert classify("हाँ ठीक हो गया") == "yes"
    assert classify("ಇಲ್ಲ ಇನ್ನೂ ಆಗಿಲ್ಲ") == "no"
    assert classify("ಹೌದು ಆಯ್ತು") == "yes"
    assert classify("ಸ್ವಲ್ಪ ಆಗಿದೆ") == "partly"
    assert classify("who is this?") == "unclear" and classify("") == "unclear" and classify(None) == "unclear"


def test_yes_closes_ticket(make):
    e = make({"T1": ["1"]})
    e.ingest([ticket()], T0)
    e.run_verifications(T0)
    assert e.get("T1")["status"] == "verified_closed"
    m = e.metrics()
    assert m["confirmed_rate"] == 1.0 and m["false_closure_rate"] == 0.0


def test_no_reopens_escalates_and_round_two(make):
    e = make({"T1": ["2", "1"]})
    e.ingest([ticket()], T0)
    e.run_verifications(T0)
    t = e.get("T1")
    assert t["status"] == "reopened" and t["level"] == 1 and t["round"] == 2
    assert e.assignee(t) == "Murthy"
    assert any(a["event"] == "reopened_escalated" for a in e.audit("T1"))
    e.mark_resolved("T1", T0 + timedelta(days=1))  # officer marks resolved again
    e.run_verifications(T0 + timedelta(days=1))
    assert e.get("T1")["status"] == "verified_closed"
    m = e.metrics()
    assert m["reopened_fixed_rate"] == 1.0 and m["false_closure_rate"] == 0.5


def test_partly_goes_to_supervisor_who_decides(make):
    e = make({"T1": ["3"], "T2": ["partly"]})
    e.ingest([ticket("T1"), ticket("T2")], T0)
    e.run_verifications(T0)
    assert e.get("T1")["status"] == "supervisor_review"
    e.review("T1", "close")
    e.review("T2", "send_back")
    assert e.get("T1")["status"] == "verified_closed"
    assert e.get("T2")["status"] == "reopened" and e.get("T2")["level"] == 1
    with pytest.raises(ValueError):
        e.review("T1", "close")


def test_unclear_twice_goes_to_supervisor(make):
    e = make({"T1": ["umm", "who is this"]})
    e.ingest([ticket()], T0)
    e.run_verifications(T0)
    assert e.get("T1")["status"] == "pending_verification"  # asked again
    e.run_verifications(T0)
    assert e.get("T1")["status"] == "supervisor_review"


def test_attempt_plan_then_unverifiable(make):
    e = make()
    e.ingest([ticket()], T0)
    now = T0
    for _ in range(8):
        e.run_verifications(now)
        now += timedelta(hours=25)
    assert e.provider.channels == ["voice", "voice", "voice", "message"]
    assert e.get("T1")["status"] == "unverifiable"
    m = e.metrics()
    assert m["unverifiable"] == 1 and m["reach"] == 0.0 and m["cost_per_verification"] == 4.0


def test_retry_waits_until_due(make):
    e = make()
    e.ingest([ticket()], T0)
    e.run_verifications(T0)
    e.run_verifications(T0 + timedelta(hours=1))  # too early for the second call
    assert len(e.provider.channels) == 1


def test_shadow_mode_never_reopens(make):
    e = make({"T1": ["2"]})
    e.ingest([ticket(shadow=True)], T0)
    e.run_verifications(T0)  # live run ignores shadow tickets
    assert e.provider.channels == []
    e.run_verifications(T0, shadow=True)
    assert e.get("T1")["status"] == "shadow_done" and e.get("T1")["level"] == 0
    m = e.metrics()
    assert m["baseline"]["false_closure_rate"] == 1.0 and m["rounds_finished"] == 0


def test_hotspots_group_by_place_and_issue():
    rows = [{"id": f"D{i}", "category": "Drainage", "description": d, "ward": "A", "lat": None, "lon": None, "status": s}
            for i, (d, s) in enumerate([("Drain overflowing", "open"), ("Open drain blocked", "verified_closed"), ("Sewage drain smell", "open")])]
    rows += [{"id": "L1", "category": "Streetlight", "description": "Light off", "ward": "A", "lat": None, "lon": None, "status": "open"},
             {"id": "D9", "category": "Drainage", "description": "Drain overflowing", "ward": "B", "lat": None, "lon": None, "status": "open"}]
    hs = find_hotspots(rows)
    assert len(hs) == 1 and hs[0]["place"] == "A" and hs[0]["tickets"] == 3 and hs[0]["unresolved"] == 2


def test_api_flow_csv_webhook_and_dashboard(make):
    e = make()
    c = TestClient(create_app(e))
    csv_text = "ticket_id,citizen_name,phone,language,category,description,ward,officer,supervisor,status\nA1,X,9000000001,hi,Road,Pothole,W1,O1,S1,resolved\n"
    assert c.post("/tickets/upload-csv", files={"file": ("t.csv", csv_text)}).json() == {"ingested": 1}
    assert c.get("/tickets/A1").json()["status"] == "pending_verification"
    assert c.get("/tickets/A1").json()["phone"] == "90XXXXXX01"
    assert c.post("/webhook/answer", json={"ticket_id": "A1", "text": "नहीं"}).json()["label"] == "no"
    assert c.get("/tickets/A1").json()["status"] == "reopened"
    assert c.get("/metrics").json()["reopened"][0]["escalated_to"] == "S1"
    assert c.post("/webhook/answer", json={"ticket_id": "nope", "text": "1"}).status_code == 404
    assert "Satya Parihara" in c.get("/").text
