# Satya Parihara — AI-verified grievance closure

Before a grievance can close, an automated call asks the citizen in Kannada, Hindi or English: *was it actually fixed?*
"No" reopens the ticket and escalates it one level. Hotspot Radar groups repeat complaints by place and issue.

```
pip install -r requirements.txt
python -m demo.seed
uvicorn app.main:app --reload    # open http://localhost:8000
python -m pytest -q
```

| File | Does |
|---|---|
| `app/engine.py` | Ticket state machine, attempt plan, shadow mode, metrics |
| `app/classifier.py` | Citizen answer → yes / no / partly / unclear (Kannada, Hindi, English, keypad) |
| `app/prompts.py` | Call and message scripts in three languages |
| `app/telephony.py` | Provider interface: console simulator + template for a real vendor |
| `app/hotspot.py` | Repeat-complaint clustering by place and issue |
| `app/main.py` | REST API: ingest, CSV upload, run verifications, answer webhook, metrics |
| `app/dashboard.html` | Officer dashboard |
| `demo/seed.py`, `tests/` | Demo data and tests |

Ticket flow: `open → pending_verification → verified_closed | reopened | supervisor_review | unverifiable`.
Attempts: three calls at different times, then a WhatsApp/SMS, then `unverifiable`. Shadow mode asks citizens about
tickets closed before the pilot and records a baseline without reopening anything.

Demo helpers: `POST /verifications/run?advance_hours=5` moves the engine clock so retries become due.
The database path is `SATYA_DB` (default `satya.db`).

Not yet built: real telephony vendor, speech-to-text, LLM classifier, PostgreSQL, officer login, 90-day phone deletion, calling-hours/DND checks.
