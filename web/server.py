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
import hmac
import json
import os
import threading
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
import usage_cap                                                # noqa: E402
import topics as topics_mod                                     # noqa: E402
from durable_store import DurableStore, ensure_repo             # noqa: E402

FEEDBACK_PATH = os.path.join(PROJECT_DIR, "data", "feedback.jsonl")
PICKS_PATH = os.path.join(PROJECT_DIR, "data", "picks.jsonl")

# Where feedback and visitor counts are kept so they survive a restart.
# Container disk does not: Hugging Face wipes it every time the Space
# restarts, which was silently throwing away every report anyone sent.
# Unset on a server with a real disk, and this falls back to plain files.
DATA_REPO = os.environ.get("HADITH_DATA_REPO", "").strip()
HF_TOKEN = (os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()

# Guards the endpoints that exist for the person RUNNING the site, not for
# its visitors: the reports people sent, the visitor counts, and what the
# app is spending. None of these were protected, and all three were served
# to anyone who asked.
OWNER_KEY = os.environ.get("HADITH_OWNER_KEY", "").strip()


def _owner_only(key, what):
    """Shared gate. Refuses when no key is configured rather than falling
    open -- the failure that matters here is exposure, not inconvenience."""
    if not OWNER_KEY:
        raise HTTPException(
            status_code=503,
            detail=f"Reading {what} is switched off. Set HADITH_OWNER_KEY.")
    if not hmac.compare_digest(key, OWNER_KEY):
        raise HTTPException(status_code=401, detail="Wrong key.")
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
    # Storage first: if a report arrives seconds after boot it must already
    # have somewhere durable to go.
    if DATA_REPO and HF_TOKEN:
        ensure_repo(DATA_REPO, HF_TOKEN)
    STATE["feedback"] = DurableStore(
        FEEDBACK_PATH, repo=DATA_REPO, token=HF_TOKEN,
        filename="feedback.jsonl", interval=5.0, name="feedback")
    # Kept apart from feedback on purpose. A report says "this is wrong";
    # a pick says "of the ones you showed me, THIS was right". The second is
    # ground truth and converts straight into evaluation cases, so mixing it
    # with free-text complaints would make both harder to use.
    STATE["picks"] = DurableStore(
        PICKS_PATH, repo=DATA_REPO, token=HF_TOKEN,
        filename="picks.jsonl", interval=5.0, name="picks")

    # Restoring is three separate network round trips, and doing them one
    # after another added 40s to startup -- paid by whoever wakes a sleeping
    # Space. They do not depend on each other, so they run together.
    #
    # They still BLOCK startup rather than running in the background: until
    # a restore finishes, the local file looks empty, and a report arriving
    # in that window would create a fresh file that the restore then
    # declines to overwrite -- silently dropping every earlier record. A
    # slower start is a fair price for not having that race.
    restored = 0
    threads = []
    results = {}

    def _restore(key, fn):
        try:
            results[key] = fn()
        except Exception as e:
            results[key] = 0
            print(f"  restore {key} failed: {str(e)[:120]}")

    for key, fn in (("feedback", STATE["feedback"].restore),
                    ("picks", STATE["picks"].restore),
                    ("events", lambda: analytics.attach_durable(
                        DATA_REPO, HF_TOKEN))):
        t = threading.Thread(target=_restore, args=(key, fn), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=45)
    restored = results.get("feedback") or 0

    STATE["feedback"].start()
    STATE["picks"].start()
    with open(os.path.join(PROJECT_DIR, "data", "corpus.json")) as f:
        corpus = json.load(f)
    STATE["store"] = HybridStore(corpus, expansions=load_expansions())
    STATE["topics"] = topics_mod.build_index(STATE["store"].hadiths)
    STATE["client"] = None
    if USE_RELEVANCE_CHECK:
        try:
            from relevance_check import make_client
            STATE["client"] = make_client()
        except SystemExit as e:
            # No API key: run search-only rather than refusing to start.
            print(f"  relevance check disabled: {e}")
    fb = STATE["feedback"].status()
    print(f"  ready in {time.time()-t0:.1f}s — "
          f"{len(STATE['store'].hadiths):,} hadith, "
          f"relevance check {'ON' if STATE['client'] else 'OFF'}, "
          f"feedback {'durable' if fb['durable'] else 'LOCAL ONLY (lost on restart)'}"
          + (f", {restored} restored" if restored else ""))
    if fb["error"]:
        print(f"  !! feedback storage: {fb['error']}")


class SearchRequest(BaseModel):
    question: str
    visitor: Optional[str] = ""


class FeedbackRequest(BaseModel):
    # What the user was actually looking at. Sent by the page so the report
    # is self-explanatory later -- nobody can be expected to remember which
    # hadith they were shown by the time they open a feedback form.
    shown_ids: Optional[list] = None
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
        # Shown on every result from the Sunan, which grade each report.
        # Bukhari and Muslim carry none: the collection is the grading.
        "grade": hadith.get("grade_label"),
        "collection": hadith.get("collection"),
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
    degraded = False
    capped = None

    # Has this search been allowed a paid relevance check today?
    if client:
        ok, why = usage_cap.allow(req.visitor or "")
        if not ok:
            capped = why
            client = None        # fall through to the free path below

    if not client:
        chosen = [(item, None) for item in retrieved[:MAX_SHOWN]]
    else:
        from relevance_check import filter_relevant, Unavailable
        try:
            keep, verdicts, _usage = filter_relevant(
                question, retrieved, client=client, k=SHORTLIST)
            usage_cap.record(req.visitor or "")   # only count what actually ran
            keep_ids = {id(k) for k in keep}
            chosen = [(item, v) for item, v in zip(retrieved, verdicts)
                      if id(item) in keep_ids]
            # Shortest first: a long narration that wanders through several
            # subjects is a worse answer than a short one stating the ruling.
            chosen.sort(key=lambda pair: len(pair[0][0]["text"].split()))
            chosen = chosen[:MAX_SHOWN]
        except Unavailable as e:
            # No credit, rate limited, or the network is down. Fall back to
            # plain search rather than an error page: the search itself is
            # local and free, so the site can still be useful -- just less
            # accurate. The page is told so it can say as much, because
            # quietly serving worse results would be the wrong kind of
            # failure for this app.
            print(f"  relevance check unavailable: {str(e)[:160]}")
            degraded = True
            chosen = [(item, None) for item in retrieved[:MAX_SHOWN]]

    analytics.record("answered" if chosen else "no_answer", req.visitor)
    return {
        "results": [_payload(item[0], item[4], (v or {}).get("why"))
                    for item, v in chosen],
        "checked": bool(client) and not degraded,
        # `degraded` means the check could not run (no credit, outage);
        # `capped` means it was deliberately skipped to stay inside budget.
        # Different causes, different wording for the user.
        "degraded": degraded,
        "capped": capped,
    }


class EventRequest(BaseModel):
    event: str
    visitor: Optional[str] = ""


@app.post("/api/event")
def event(req: EventRequest):
    ok = analytics.record(req.event, req.visitor)
    return {"ok": ok}


@app.get("/api/usage")
def usage(key: str = ""):
    """Today's spend against the cap. For the site owner."""
    _owner_only(key, "spend")
    return usage_cap.status()


@app.get("/api/stats")
def stats(key: str = "", days: int = 30):
    """Counts for the site owner. No identities, by design."""
    _owner_only(key, "visitor counts")
    out = analytics.summary(days=days)
    # The owner is also the only person who should see whether durable
    # storage is actually working, including why it is not.
    out["storage"] = {
        "feedback": STATE["feedback"].status() if STATE.get("feedback") else None,
        "events": analytics.status(),
        "picks": STATE["picks"].status() if STATE.get("picks") else None,
    }
    out["ranking"] = _rank_summary()
    return out


@app.get("/api/auth")
def auth_config():
    """Tells the page whether sign-in is switched on, and what it gates."""
    return {
        "enabled": google_auth.configured(),
        "client_id": google_auth.client_id() or None,
        "required_for": ["feedback"],
    }


def _rank_summary():
    """
    Where the right answer actually lands, according to the people reading
    it. The single most useful number this app can collect about itself.
    """
    rows = STATE["picks"].read_all() if STATE.get("picks") else []
    if not rows:
        return {"picks": 0}
    counts = {}
    for r in rows:
        counts[r.get("rank")] = counts.get(r.get("rank"), 0) + 1
    n = len(rows)
    return {
        "picks": n,
        "by_rank": dict(sorted(counts.items(), key=lambda kv: (kv[0] or 99))),
        "right_first_time": round(counts.get(1, 0) / n, 3),
    }


def _storage_summary(st):
    if not st:
        return {"durable": False, "healthy": False}
    return {
        "durable": bool(st.get("durable")),
        "rows": st.get("rows", 0),
        "pending": bool(st.get("pending")),
        "healthy": bool(st.get("durable")) and not st.get("error"),
    }


class PickRequest(BaseModel):
    question: str
    chosen: str                       # the hadith the reader says answers it
    shown: list                       # everything they were shown, in order
    visitor: Optional[str] = ""


@app.post("/api/best")
def best_answer(req: PickRequest):
    """
    "Of the answers you gave me, THIS is the one that answers my question."

    WHY THIS IS NOT FEEDBACK, AND NOT LEARNING
    ------------------------------------------
    Nothing here changes retrieval. The app does not train on these clicks
    and should not: scripture retrieval quietly drifting because of taps is
    the last thing this project wants. What a pick produces is a labelled
    example -- question, the candidates shown, and which was right -- which
    is exactly the ground truth the evaluation harness has never had. Eleven
    hand-written cases become as many real ones as people are willing to
    mark. `picks_to_eval.py` turns them into harness cases offline, where a
    human can look at them first.

    The RANK is the point. If the right answer is routinely second or third,
    that is a ranking problem with a number attached -- which is what bug #15
    has been missing since it was written.

    WHY NO SIGN-IN
    --------------
    Feedback needs sign-in because it is free text and free text attracts
    abuse. A pick is one tap from a fixed list: the chosen hadith must be one
    the server actually showed, so the worst a bad actor can do is claim the
    wrong one of three. Putting a Google sign-in in front of a single tap
    would cost most of the data, and the data is the entire point.
    """
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="No question given.")

    shown = [str(x) for x in (req.shown or [])][:MAX_SHOWN]
    chosen = str(req.chosen or "")
    # A pick is only meaningful about results we actually served. This also
    # means nobody can post arbitrary ids into the ground-truth set.
    if chosen not in shown:
        raise HTTPException(
            status_code=400,
            detail="That answer was not among the ones shown.")

    store = STATE.get("store")
    known = {h["id"] for h in store.hadiths} if store else set()
    if chosen not in known:
        raise HTTPException(status_code=400, detail="Unknown hadith.")

    record = {
        "id": uuid.uuid4().hex[:12],
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "question": question[:500],
        "chosen": chosen,
        "shown": shown,
        # 1-based, so "rank 1" reads as "we got it right first time".
        "rank": shown.index(chosen) + 1,
        "by": (req.visitor or "")[:32],
    }
    STATE["picks"].append(record)
    analytics.record("best_pick", req.visitor)
    return {"ok": True, "rank": record["rank"]}


@app.get("/api/health")
def health():
    """Cheap status, read from memory and config. Calls no model, so a
    monitor can poll it as often as it likes for nothing."""
    store = STATE.get("store")
    return {
        "ok": store is not None,
        "hadith": len(store.hadiths) if store else 0,
        "chunks": len(store.chunks) if store else 0,
        "expansions": len(getattr(store, "expansions", {}) or {}) if store else 0,
        "relevance_check": STATE.get("client") is not None,
        "usage": usage_cap.status(),
        "sign_in": google_auth.configured(),
        "support_link": bool(SUPPORT_URL),
        # Reported rather than assumed: if the durable mirror is broken,
        # feedback is being collected and quietly thrown away, which looks
        # identical from the outside to everything working.
        # Public, because a monitor polls it -- so it says WHETHER storage is
        # healthy without naming the private repo or echoing raw error text.
        # The detail is available to the owner through /api/stats.
        "feedback_storage": _storage_summary(
            STATE["feedback"].status() if STATE.get("feedback") else None),
        "events_storage": _storage_summary(analytics.status()),
        "picks_storage": _storage_summary(
            STATE["picks"].status() if STATE.get("picks") else None),
    }


@app.get("/api/topics")
def list_topics():
    """Everyday subjects people can browse. Free -- no AI call."""
    return {"topics": topics_mod.listing(STATE["topics"])}


@app.get("/api/topic")
def topic(name: str, limit: int = 8, offset: int = 0):
    """
    Hadith within one topic, already ordered and deduplicated by
    topics.build_index -- see the note there on why "shortest first" was
    wrong. The ordering is computed once at startup rather than per
    request, because it depends only on the corpus.
    """
    hits = STATE["topics"].get(name)
    if hits is None:
        raise HTTPException(status_code=404, detail="Unknown topic.")
    window = hits[offset:offset + max(1, min(limit, 20))]
    return {
        "name": name,
        "total": len(hits),
        "offset": offset,
        "results": [_payload(h, 1.0) for h in window],
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
        "shown": (req.shown_ids or [])[:5],
        # An opaque token, not a name or an email. Enough to spot one person
        # sending fifty reports; not enough to know who they are.
        "by": user,
        "reason": req.reason[:64],
        "detail": (req.detail or "")[:1000],
    }
    STATE["feedback"].append(record)
    analytics.record("feedback", req.visitor)
    return {"ok": True, "id": record["id"]}


@app.get("/api/feedback")
def list_feedback(limit: int = 100, key: str = ""):
    """
    Everything people have reported. For the owner, to decide what to fix.

    This used to be open to anyone. It should not have been: the reports are
    free text a stranger typed, sent in the expectation that the person
    running the site would read them -- not the whole internet. Set
    HADITH_OWNER_KEY and pass ?key=... to read it.
    """
    _owner_only(key, "feedback")
    rows = STATE["feedback"].read_all()
    return {"count": len(rows), "reports": rows[-limit:][::-1]}


@app.get("/")
def index():
    return FileResponse(os.path.join(SCRIPT_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(SCRIPT_DIR, "static")),
          name="static")
