"""Ticket state machine, attempt plan, shadow mode and metrics.

Statuses
  open                  department is working on it
  pending_verification  marked resolved, waiting for / running the citizen check
  verified_closed       citizen said yes (or supervisor closed it)
  reopened              citizen said no; escalated one level
  supervisor_review     partly / unclear twice; a human decides
  unverifiable          no answer after all attempts
  closed_legacy         already closed before the pilot (shadow mode only)
"""
import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from . import hotspot
from .classifier import NO, PARTLY, UNCLEAR, YES, classify
from .prompts import call_script, message_text
from .telephony import ConsoleSimulator

# (channel, wait after this attempt before the next one). Three calls at different times, then a message.
ATTEMPT_PLAN = [("voice", timedelta(hours=4)), ("voice", timedelta(hours=20)), ("voice", timedelta(hours=1)), ("message", timedelta(hours=24))]
MAX_UNCLEAR = 2
LEVELS = ["officer", "supervisor", "department head"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id TEXT PRIMARY KEY, citizen_name TEXT, phone TEXT, language TEXT DEFAULT 'en',
  department TEXT, category TEXT, description TEXT, ward TEXT, lat REAL, lon REAL,
  officer TEXT, supervisor TEXT, head TEXT DEFAULT 'Department Head',
  status TEXT NOT NULL DEFAULT 'open', level INTEGER DEFAULT 0, round INTEGER DEFAULT 1,
  attempts INTEGER DEFAULT 0, unclear INTEGER DEFAULT 0, next_attempt_at TEXT,
  shadow INTEGER DEFAULT 0, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT, round INTEGER, ts TEXT,
  channel TEXT, answered INTEGER, cost REAL, shadow INTEGER);
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT, round INTEGER, ts TEXT,
  outcome TEXT, answer_text TEXT, shadow INTEGER);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT, ts TEXT, event TEXT, detail TEXT);
"""
FIELDS = ["id", "citizen_name", "phone", "language", "department", "category", "description", "ward", "lat", "lon", "officer", "supervisor", "head"]


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def mask_phone(phone):
    phone = phone or ""
    return phone[:2] + "XXXXXX" + phone[-2:] if len(phone) >= 6 else "XXXX"


class Engine:
    def __init__(self, db_path="satya.db", provider=None):
        self.db_path = db_path
        self.provider = provider or ConsoleSimulator()
        self.clock_offset = timedelta()
        with self._db() as db:
            db.executescript(SCHEMA)

    # -- plumbing ---------------------------------------------------------
    def _db(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return _Conn(conn)

    def now(self):
        return datetime.now(timezone.utc).replace(tzinfo=None) + self.clock_offset

    def advance_clock(self, hours):
        """Demo helper: move the engine's clock forward so retries become due."""
        self.clock_offset += timedelta(hours=hours)
        return self.now()

    def _log(self, db, ticket_id, now, event, detail=""):
        db.execute("INSERT INTO audit(ticket_id, ts, event, detail) VALUES (?,?,?,?)", (ticket_id, _iso(now), event, detail))

    def get(self, ticket_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return dict(row) if row else None

    def list_tickets(self, status=None):
        with self._db() as db:
            rows = db.execute("SELECT * FROM tickets" + (" WHERE status=?" if status else "") + " ORDER BY id", (status,) if status else ()).fetchall()
        return [self.public(dict(r)) for r in rows]

    def public(self, t):
        t = dict(t)
        t["phone"] = mask_phone(t["phone"])
        t["escalated_to"] = self.assignee(t)
        return t

    @staticmethod
    def assignee(t):
        names = [t.get("officer"), t.get("supervisor"), t.get("head")]
        return names[min(t["level"], 2)] or LEVELS[min(t["level"], 2)]

    def audit(self, ticket_id):
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM audit WHERE ticket_id=? ORDER BY id", (ticket_id,))]

    # -- ingest -----------------------------------------------------------
    def ingest(self, rows, now=None):
        """Load tickets from the grievance system. Rows with status resolved/closed enter verification."""
        now = now or self.now()
        count = 0
        with self._db() as db:
            for r in rows:
                r = {k: (v if v not in ("", None) else None) for k, v in r.items()}
                tid = r.get("id") or r.get("ticket_id")
                if not tid:
                    continue
                vals = {f: r.get(f) for f in FIELDS}
                vals["id"] = str(tid)
                vals["language"] = (vals["language"] or "en").lower()
                vals["head"] = vals["head"] or "Department Head"
                for f in ("lat", "lon"):
                    vals[f] = float(vals[f]) if vals[f] is not None else None
                incoming = (r.get("status") or "open").lower()
                resolved = incoming in ("resolved", "closed")
                shadow = 1 if r.get("shadow") in (1, True, "1", "true", "True") else 0
                existing = db.execute("SELECT status FROM tickets WHERE id=?", (vals["id"],)).fetchone()
                if existing:
                    sets = ", ".join(f"{f}=:{f}" for f in FIELDS if f != "id")
                    db.execute(f"UPDATE tickets SET {sets} WHERE id=:id", vals)
                    status = existing["status"]
                else:
                    cols = ", ".join(FIELDS)
                    db.execute(f"INSERT INTO tickets({cols}, shadow) VALUES ({', '.join(':' + f for f in FIELDS)}, :shadow)", {**vals, "shadow": shadow})
                    status = "open"
                    self._log(db, vals["id"], now, "ingested", incoming)
                if resolved and status in ("open", "reopened"):
                    self._mark_resolved(db, vals["id"], now, shadow=shadow)
                count += 1
        return count

    def ingest_csv(self, text, now=None):
        return self.ingest(list(csv.DictReader(io.StringIO(text))), now)

    def _mark_resolved(self, db, ticket_id, now, shadow=0):
        # Shadow tickets were closed before the pilot: they are asked but never reopened.
        status = "shadow_pending" if shadow else "pending_verification"
        db.execute("UPDATE tickets SET status=?, attempts=0, unclear=0, shadow=?, resolved_at=?, next_attempt_at=? WHERE id=?",
                   (status, shadow, _iso(now), _iso(now), ticket_id))
        self._log(db, ticket_id, now, "marked_resolved", "shadow" if shadow else "")

    def mark_resolved(self, ticket_id, now=None):
        now = now or self.now()
        t = self.get(ticket_id)
        if t is None:
            raise KeyError(ticket_id)
        if t["status"] not in ("open", "reopened"):
            raise ValueError(f'ticket is {t["status"]}, cannot mark resolved')
        with self._db() as db:
            self._mark_resolved(db, ticket_id, now)

    # -- verification loop ------------------------------------------------
    def run_verifications(self, now=None, shadow=False):
        """Run every due attempt. Returns a small summary of what happened."""
        now = now or self.now()
        status = "shadow_pending" if shadow else "pending_verification"
        summary = {"calls": 0, "messages": 0, "answers": 0, "unverifiable": 0}
        with self._db() as db:
            due = [dict(r) for r in db.execute("SELECT * FROM tickets WHERE status=? AND next_attempt_at<=? ORDER BY id", (status, _iso(now)))]
        for t in due:
            if t["attempts"] >= len(ATTEMPT_PLAN):
                self._finish(t["id"], "unverifiable", None, now)
                summary["unverifiable"] += 1
                continue
            channel, wait = ATTEMPT_PLAN[t["attempts"]]
            reply = self.provider.place_call(t, call_script(t)) if channel == "voice" else self.provider.send_message(t, message_text(t))
            summary["calls" if channel == "voice" else "messages"] += 1
            with self._db() as db:
                db.execute("INSERT INTO attempts(ticket_id, round, ts, channel, answered, cost, shadow) VALUES (?,?,?,?,?,?,?)",
                           (t["id"], t["round"], _iso(now), channel, int(reply.text is not None), reply.cost, t["shadow"]))
                db.execute("UPDATE tickets SET attempts=attempts+1, next_attempt_at=? WHERE id=?", (_iso(now + wait), t["id"]))
                self._log(db, t["id"], now, f"{channel}_attempt", "answered" if reply.text is not None else "no answer")
            if reply.text is not None:
                self.record_answer(t["id"], reply.text, now)
                summary["answers"] += 1
        return summary

    def record_answer(self, ticket_id, text, now=None):
        """Classify an answer (from a call, a message or the webhook) and apply the outcome."""
        now = now or self.now()
        t = self.get(ticket_id)
        if t is None:
            raise KeyError(ticket_id)
        if t["status"] not in ("pending_verification", "shadow_pending"):
            return {"ticket_id": ticket_id, "label": None, "status": t["status"], "ignored": True}
        label = classify(text)
        if label == UNCLEAR:
            unclear = t["unclear"] + 1
            with self._db() as db:
                db.execute("UPDATE tickets SET unclear=? WHERE id=?", (unclear, ticket_id))
                self._log(db, ticket_id, now, "answer_unclear", text or "")
            if unclear >= MAX_UNCLEAR:
                self._finish(ticket_id, UNCLEAR, text, now)
            else:  # ask again at the next attempt slot
                with self._db() as db:
                    db.execute("UPDATE tickets SET next_attempt_at=? WHERE id=?", (_iso(now), ticket_id))
        else:
            self._finish(ticket_id, label, text, now)
        return {"ticket_id": ticket_id, "label": label, "status": self.get(ticket_id)["status"]}

    def _finish(self, ticket_id, outcome, text, now):
        """Close one verification round and move the ticket accordingly."""
        t = self.get(ticket_id)
        shadow = t["shadow"]
        recorded = "unverifiable" if outcome == "unverifiable" else outcome
        with self._db() as db:
            db.execute("INSERT INTO verifications(ticket_id, round, ts, outcome, answer_text, shadow) VALUES (?,?,?,?,?,?)",
                       (ticket_id, t["round"], _iso(now), recorded, text, shadow))
            if shadow:
                db.execute("UPDATE tickets SET status='shadow_done', next_attempt_at=NULL WHERE id=?", (ticket_id,))
            elif outcome == YES:
                db.execute("UPDATE tickets SET status='verified_closed', next_attempt_at=NULL WHERE id=?", (ticket_id,))
            elif outcome == NO:
                db.execute("UPDATE tickets SET status='reopened', level=level+1, round=round+1, next_attempt_at=NULL WHERE id=?", (ticket_id,))
            elif outcome == "unverifiable":
                db.execute("UPDATE tickets SET status='unverifiable', next_attempt_at=NULL WHERE id=?", (ticket_id,))
            else:  # partly, or unclear twice
                db.execute("UPDATE tickets SET status='supervisor_review', next_attempt_at=NULL WHERE id=?", (ticket_id,))
            self._log(db, ticket_id, now, f"verification_{recorded}", f"round {t['round']}" + (" (shadow)" if shadow else ""))
            if outcome == NO and not shadow:
                self._log(db, ticket_id, now, "reopened_escalated", f"level {t['level'] + 1}: false closure")

    def review(self, ticket_id, decision, now=None):
        """Supervisor decision for partly / unclear tickets: 'close' or 'send_back'."""
        now = now or self.now()
        t = self.get(ticket_id)
        if t is None:
            raise KeyError(ticket_id)
        if t["status"] != "supervisor_review":
            raise ValueError(f'ticket is {t["status"]}, not in supervisor review')
        with self._db() as db:
            if decision == "close":
                db.execute("UPDATE tickets SET status='verified_closed' WHERE id=?", (ticket_id,))
            elif decision == "send_back":
                db.execute("UPDATE tickets SET status='reopened', level=level+1, round=round+1 WHERE id=?", (ticket_id,))
            else:
                raise ValueError("decision must be 'close' or 'send_back'")
            self._log(db, ticket_id, now, f"supervisor_{decision}")

    # -- metrics ----------------------------------------------------------
    def metrics(self):
        with self._db() as db:
            def tally(shadow):
                rows = db.execute("SELECT outcome, COUNT(*) n FROM verifications WHERE shadow=? GROUP BY outcome", (shadow,)).fetchall()
                return {r["outcome"]: r["n"] for r in rows}
            live, base = tally(0), tally(1)
            cost = db.execute("SELECT COALESCE(SUM(cost),0) c FROM attempts WHERE shadow=0").fetchone()["c"]
            counts = {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) n FROM tickets GROUP BY status")}
            officers = db.execute(
                "SELECT t.officer officer, SUM(v.outcome='yes') yes, SUM(v.outcome IN ('yes','no','partly')) answered "
                "FROM verifications v JOIN tickets t ON t.id=v.ticket_id WHERE v.shadow=0 GROUP BY t.officer ORDER BY t.officer").fetchall()
            second = db.execute(
                "SELECT SUM(outcome='yes') yes, SUM(outcome IN ('yes','no','partly')) answered FROM verifications WHERE shadow=0 AND round>1").fetchone()
            reopened = [dict(r) for r in db.execute("SELECT * FROM tickets WHERE status='reopened' ORDER BY level DESC, id")]
            review = [dict(r) for r in db.execute("SELECT * FROM tickets WHERE status='supervisor_review' ORDER BY id")]

        def summarise(c):
            answered = c.get(YES, 0) + c.get(NO, 0) + c.get(PARTLY, 0)
            total = sum(c.values())
            return {
                "rounds_finished": total, "answered": answered, "yes": c.get(YES, 0), "no": c.get(NO, 0), "partly": c.get(PARTLY, 0),
                "unclear": c.get(UNCLEAR, 0), "unverifiable": c.get("unverifiable", 0),
                "confirmed_rate": round(c.get(YES, 0) / answered, 3) if answered else None,
                "false_closure_rate": round(c.get(NO, 0) / answered, 3) if answered else None,
                "reach": round(answered / total, 3) if total else None,
            }

        out = summarise(live)
        out["cost_per_verification"] = round(cost / out["rounds_finished"], 2) if out["rounds_finished"] else None
        out["reopened_fixed_rate"] = round(second["yes"] / second["answered"], 3) if second["answered"] else None
        out["baseline"] = summarise(base)
        out["status_counts"] = counts
        out["officers"] = [{"officer": r["officer"], "answered": r["answered"], "confirmed": r["yes"],
                            "true_resolution_rate": round(r["yes"] / r["answered"], 3) if r["answered"] else None} for r in officers]
        out["reopened"] = [{"id": t["id"], "category": t["category"], "ward": t["ward"], "officer": t["officer"], "supervisor": t["supervisor"],
                            "escalation_level": t["level"], "escalated_to": self.assignee(t)} for t in reopened]
        out["supervisor_review"] = [{"id": t["id"], "category": t["category"], "ward": t["ward"], "supervisor": t["supervisor"]} for t in review]
        out["hotspots"] = self.hotspots()
        return out

    def hotspots(self):
        with self._db() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM tickets")]
        return hotspot.find_hotspots(rows)


class _Conn:
    """Context manager: commit on success, always close."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.conn.commit()
        self.conn.close()
