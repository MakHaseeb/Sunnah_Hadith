"""
Web server for the hadith search app.

WHAT IT DOES
------------
  GET  /              the page
  POST /api/search    question -> the hadith that answer it
  POST /api/feedback  a user says an answer was wrong, and why
  GET  /api/feedback  read what people have reported (for you, not users)

DESIGN NOTES
------------
No AI-written answers. The page shows the authentic hadith text with its
citation and nothing else. That was a deliberate product decision: an AI
paraphrase of scripture can be subtly wrong in ways a reader cannot
check, and showing the real text with a reference removes that risk
entirely. It is also free to run.

The search index is built ONCE at startup (~18s) and held in memory.
Building it per request would take 18 seconds per question.

Feedback is appended to a JSON Lines file -- one line per report, written
immediately. No database to set up, nothing to lose on a crash, and it is
trivially readable. It can move to a real database when volume justifies
one, which it will not for a long time.
"""
import json
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
import sys
sys.path.insert(0, PROJECT_DIR)

from citations import format_citation, verification_note      # noqa: E402
from expansion import load_expansions                          # noqa: E402
from hybrid_retrieve import HybridStore                        # noqa: E402
from daily_hadith import hadith_for, SUPPORT_HADITH_ID          # noqa: E402
import analytics                                                # noqa: E402
import google_auth                                              # noqa: E402

FEEDBACK_PATH = os.path.join(PROJECT_DIR, "data", "feedback.jsonl")
SHORTLIST = 10
MAX_SHOWN = 3
USE_RELEVANCE_CHECK = os.environ.get("HADITH_RELEVANCE_CHECK", "1") != "0"

# Where the "support this work" button sends people. Deliberately NOT built
# in: taking payments means an account in the owner's name, their identity
# and their bank details. Set HADITH_SUPPORT_URL to a Ko-fi, Buy Me a Coffee,
# PayPal.me or Stripe link. Until it is set, the button is hidden rather than
# shown broken.
SUPPORT_URL = os.environ.get("HADITH_SUPPORT_URL", "").strip()

app = FastAPI(title="Hadith Search")
STATE = {}


@app.on_event("startup")
def startup():
    t0 = time.time()
    with open(os.path.join(PROJECT_DIR, "data", "corpus.json")) as f:
        corpus = json.load(f)
    STATE["store"] = HybridStore(corpus, expansions=load_expansions())
    STATE["client"] = None
    if USE_RELEVANCE_CHECK:
        try:
            from relevance_check import make_client
            STATE["client"] = make_client()
        except SystemExit as e:
            # No API key: run search-only rather than refusing to start.
            print(f"  relevance check disabled: {e}")
    print(f"  ready in {time.time()-t0:.1f}s — "
          f"{len(STATE['store'].hadiths):,} hadith, "
          f"relevance check {'ON' if STATE['client'] else 'OFF'}")


class SearchRequest(BaseModel):
    question: str
    visitor: Optional[str] = ""


class FeedbackRequest(BaseModel):
    # hadith_id is optional: the same endpoint takes both "this result is
    # wrong" reports and general feedback about the site, so there is one
    # place to read everything people tell us.
    question: Optional[str] = ""
    hadith_id: Optional[str] = ""
    reason: str
    detail: Optional[str] = ""
    credential: Optional[str] = ""   # Google ID token, when sign-in is on
    visitor: Optional[str] = ""


def _payload(hadith, score, why=None):
    return {
        "id": hadith["id"],
        "citation": format_citation(hadith),
        "narrator": hadith.get("narrator"),
        "text": " ".join(hadith["text"].split()),
        "provenance": verification_note(hadith),
        "cross_checked": bool((hadith.get("verification") or {})
                              .get("verified_against_pdf")),
        "why": why,
        "match": round(float(score), 2),
    }


@app.post("/api/search")
def search(req: SearchRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please type a question.")
    if len(question) > 500:
        raise HTTPException(status_code=400, detail="That question is too long.")

    analytics.record("search", req.visitor)
    store = STATE["store"]
    retrieved = store.retrieve(question, k=SHORTLIST)
    if not retrieved:
        analytics.record("no_answer", req.visitor)
        return {"results": [], "checked": False}

    client = STATE.get("client")
    if not client:
        chosen = [(item, None) for item in retrieved[:MAX_SHOWN]]
    else:
        from relevance_check import filter_relevant
        keep, verdicts, _usage = filter_relevant(
            question, retrieved, client=client, k=SHORTLIST)
        keep_ids = {id(k) for k in keep}
        chosen = [(item, v) for item, v in zip(retrieved, verdicts)
                  if id(item) in keep_ids]
        # Shortest first: a long narration that wanders through several
        # subjects is a worse answer than a short one stating the ruling.
        chosen.sort(key=lambda pair: len(pair[0][0]["text"].split()))
        chosen = chosen[:MAX_SHOWN]

    analytics.record("answered" if chosen else "no_answer", req.visitor)
    return {
        "results": [_payload(item[0], item[4], (v or {}).get("why"))
                    for item, v in chosen],
        "checked": bool(client),
    }


class EventRequest(BaseModel):
    event: str
    visitor: Optional[str] = ""


@app.post("/api/event")
def event(req: EventRequest):
    ok = analytics.record(req.event, req.visitor)
    return {"ok": ok}


@app.get("/api/stats")
def stats(days: int = 30):
    """Counts for the site owner. No identities, by design."""
    return analytics.summary(days=days)


@app.get("/api/auth")
def auth_config():
    """Tells the page whether sign-in is switched on, and what it gates."""
    return {
        "enabled": google_auth.configured(),
        "client_id": google_auth.CLIENT_ID or None,
        "required_for": ["feedback"],
    }


@app.get("/api/daily")
def daily():
    """The hadith of the day. Same for everyone, changes at midnight."""
    store = STATE["store"]
    by_id = {h["id"]: h for h in store.hadiths}
    rid = hadith_for()
    hadith = by_id.get(rid)
    if not hadith:
        return {"hadith": None}
    return {"date": time.strftime("%Y-%m-%d"), "hadith": _payload(hadith, 1.0)}


@app.get("/api/support")
def support():
    """Whether a support link is configured, and the hadith shown with it."""
    store = STATE["store"]
    by_id = {h["id"]: h for h in store.hadiths}
    hadith = by_id.get(SUPPORT_HADITH_ID)
    return {
        "url": SUPPORT_URL or None,
        "hadith": _payload(hadith, 1.0) if hadith else None,
    }


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    # Sign-in gates feedback only, and only when it has been configured.
    # If it is switched off the site still works exactly as before, rather
    # than silently rejecting everyone.
    user = None
    if google_auth.configured():
        user = google_auth.verify(req.credential)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Please sign in first — it keeps this free of spam.")

    record = {
        "id": uuid.uuid4().hex[:12],
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "question": (req.question or "")[:500],
        "hadith_id": (req.hadith_id or "")[:64],
        "kind": "result" if req.hadith_id else "general",
        # An opaque token, not a name or an email. Enough to spot one person
        # sending fifty reports; not enough to know who they are.
        "by": user,
        "reason": req.reason[:64],
        "detail": (req.detail or "")[:1000],
    }
    os.makedirs(os.path.dirname(FEEDBACK_PATH), exist_ok=True)
    with open(FEEDBACK_PATH, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
    analytics.record("feedback", req.visitor)
    return {"ok": True, "id": record["id"]}


@app.get("/api/feedback")
def list_feedback(limit: int = 100):
    """Everything people have reported. For you, to decide what to fix."""
    if not os.path.exists(FEEDBACK_PATH):
        return {"count": 0, "reports": []}
    rows = []
    with open(FEEDBACK_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return {"count": len(rows), "reports": rows[-limit:][::-1]}


@app.get("/")
def index():
    return FileResponse(os.path.join(SCRIPT_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(SCRIPT_DIR, "static")),
          name="static")
