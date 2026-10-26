"""REST API for Satya Parihara. Run: uvicorn app.main:app --reload"""
import os
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .engine import Engine

DASHBOARD = Path(__file__).with_name("dashboard.html")


class TicketIn(BaseModel):
    id: str
    citizen_name: Optional[str] = None
    phone: Optional[str] = None
    language: str = "en"
    department: Optional[str] = None
    category: str
    description: str = ""
    ward: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    officer: Optional[str] = None
    supervisor: Optional[str] = None
    head: Optional[str] = None
    status: str = "open"
    shadow: bool = False


class Answer(BaseModel):
    ticket_id: str
    text: Optional[str] = None
    digits: Optional[str] = None  # keypad press, if the vendor sends it separately


class Review(BaseModel):
    decision: str  # close | send_back


def create_app(engine: Optional[Engine] = None) -> FastAPI:
    engine = engine or Engine(os.environ.get("SATYA_DB", "satya.db"))
    app = FastAPI(title="Satya Parihara")
    app.state.engine = engine

    def guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except KeyError:
            raise HTTPException(404, "ticket not found")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return DASHBOARD.read_text(encoding="utf-8")

    @app.post("/tickets")
    def ingest(tickets: List[TicketIn]):
        return {"ingested": engine.ingest([t.model_dump() for t in tickets])}

    @app.post("/tickets/upload-csv")
    async def upload_csv(file: UploadFile = File(...)):
        text = (await file.read()).decode("utf-8-sig")
        return {"ingested": engine.ingest_csv(text)}

    @app.get("/tickets")
    def tickets(status: Optional[str] = None):
        return engine.list_tickets(status)

    @app.get("/tickets/{ticket_id}")
    def ticket(ticket_id: str):
        t = engine.get(ticket_id)
        if t is None:
            raise HTTPException(404, "ticket not found")
        return {**engine.public(t), "audit": engine.audit(ticket_id)}

    @app.post("/tickets/{ticket_id}/resolve")
    def resolve(ticket_id: str):
        guard(engine.mark_resolved, ticket_id)
        return engine.public(engine.get(ticket_id))

    @app.post("/tickets/{ticket_id}/review")
    def review(ticket_id: str, body: Review):
        guard(engine.review, ticket_id, body.decision)
        return engine.public(engine.get(ticket_id))

    @app.post("/verifications/run")
    def run(shadow: bool = False, advance_hours: float = 0):
        """Run all due verification attempts. advance_hours moves the demo clock first."""
        if advance_hours:
            engine.advance_clock(advance_hours)
        return engine.run_verifications(shadow=shadow)

    @app.post("/webhook/answer")
    def answer(body: Answer):
        return guard(engine.record_answer, body.ticket_id, body.digits or body.text)

    @app.get("/metrics")
    def metrics():
        return engine.metrics()

    @app.get("/hotspots")
    def hotspots():
        return engine.hotspots()

    return app


app = create_app()
