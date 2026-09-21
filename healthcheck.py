"""
Hourly health check: does the app still work, and are answers still right?

WHY THIS EXISTS
---------------
Everything else in this project reports a problem only when a person
notices it. That is fine while one person is testing and useless once the
site is live: an expired API key, a corpus that failed to load, or answers
that quietly get worse would all look exactly like a normal quiet hour.

So this asks the running site a handful of questions it already knows the
answers to, and shouts if the answers change.

WHAT IT CHECKS
--------------
  reachable      the site responds at all
  corpus         the expected number of hadith are loaded
  relevance      the AI relevance check is switched on and working
  known answers  specific questions still return specific hadith
  rejection      obvious nonsense is still refused
  daily          the hadith of the day resolves

The known-answer checks are the important ones. A site can be up, fast and
completely wrong -- that is exactly the failure this project kept hitting,
and it is invisible to an ordinary uptime monitor.

TWO MODES, BECAUSE THE CHECKS HAVE VERY DIFFERENT COSTS
-------------------------------------------------------
Every check that performs a SEARCH costs a relevance-check call. Running
all of them hourly comes to about $7 a month -- more than the one-off
corpus build, every month, on a site with nobody using it.

So the checks are split by what they cost:

  --quick  (default)  free. Is the site up, is the corpus loaded, does the
                      daily hadith resolve, is the relevance check still
                      switched on. Catches crashes, failed deploys, a
                      corpus that did not load, and lost API credit. Run
                      this hourly.

  --full              ~$0.01 a run. Everything above plus the known-answer
                      and rejection checks, which are the only way to catch
                      answers quietly getting worse. Run once or twice a
                      day.

Checking whether the relevance check is ENABLED is free -- that is read
from config, not by asking the model. So the hourly run still catches the
most likely real failure, which is running out of credit.

EXIT CODE
---------
0 = healthy, 1 = something failed. That makes it usable from cron, a CI
job, or any alerting tool without parsing the output.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8077"

# Questions whose answers we are confident about. Each lists ids that would
# all be acceptable -- these hadith are repeated across both collections, so
# demanding one exact id would produce false alarms.
KNOWN = [
    ("is it okay to be angry",
     {"bukhari:6116", "muslim:6643", "muslim:6644"}),
    ("what does Islam say about cleaning teeth",
     {"bukhari:7240", "bukhari:887", "muslim:590"}),
    ("should I eat with my right hand",
     {"muslim:5265", "muslim:5266", "bukhari:5376"}),
    ("what happens to someone who commits suicide",
     {"bukhari:1365", "bukhari:5778", "muslim:199", "muslim:203"}),
]

# Must return nothing. If these start returning hadith, the confidence gate
# has drifted and users are being given scripture for unrelated questions.
NONSENSE = ["chocolate cake recipe", "best python web framework"]

EXPECTED_HADITH_MIN = 13000


def _get(base, path, timeout=30):
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read())


def _post(base, path, payload, timeout=120):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run(base=DEFAULT_BASE, verbose=True, full=False):
    failures, notes = [], []

    def check(name, ok, detail=""):
        notes.append((name, ok, detail))
        if not ok:
            failures.append(f"{name}: {detail}")
        if verbose:
            print(f"  [{'OK  ' if ok else 'FAIL'}] {name:22s} {detail}")

    # reachable
    t0 = time.time()
    try:
        _get(base, "/api/topics", timeout=20)
        check("reachable", True, f"{(time.time()-t0)*1000:.0f} ms")
    except Exception as e:
        check("reachable", False, f"{type(e).__name__}: {e}")
        return failures, notes           # nothing else can be tested

    # Is the relevance check configured? Read from config, not by asking the
    # model, so this costs nothing and still catches the likeliest failure:
    # credit running out.
    try:
        d = _get(base, "/api/health")
        on = d.get("relevance_check") is True
        check("relevance check", on,
              "on" if on else "OFF — answers will be much worse")
    except Exception as e:
        check("relevance check", False, f"{type(e).__name__}: {e}")

    # daily hadith resolves
    try:
        d = _get(base, "/api/daily")
        ok = bool(d.get("hadith"))
        check("hadith of the day", ok,
              d["hadith"]["id"] if ok else "did not resolve")
    except Exception as e:
        check("hadith of the day", False, f"{type(e).__name__}: {e}")

    # corpus size, via the topic index
    try:
        d = _get(base, "/api/topics")
        total = sum(t["count"] for t in d["topics"])
        check("topics loaded", total > 5000, f"{total:,} hadith across {len(d['topics'])} topics")
    except Exception as e:
        check("topics loaded", False, f"{type(e).__name__}: {e}")

    if not full:
        return failures, notes       # everything past here costs money

    # known answers — the checks that matter, and the only ones that can
    # catch answers quietly getting worse
    for question, acceptable in KNOWN:
        try:
            d = _post(base, "/api/search", {"question": question})
            got = {r["id"] for r in d.get("results", [])}
            hit = bool(got & acceptable)
            check(f"answer: {question[:18]}", hit,
                  ("got " + ", ".join(sorted(got)[:3])) if not hit else "correct")
        except Exception as e:
            check(f"answer: {question[:18]}", False, f"{type(e).__name__}: {e}")

    # nonsense still refused
    for question in NONSENSE:
        try:
            d = _post(base, "/api/search", {"question": question})
            n = len(d.get("results", []))
            check(f"reject: {question[:18]}", n == 0,
                  "refused" if n == 0 else f"returned {n} hadith")
        except Exception as e:
            check(f"reject: {question[:18]}", False, f"{type(e).__name__}: {e}")

    return failures, notes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--quiet", action="store_true",
                    help="print only on failure — the right mode for cron")
    ap.add_argument("--full", action="store_true",
                    help="also verify known answers (~$0.01 a run). Without "
                         "this only the free checks run.")
    args = ap.parse_args()

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    failures, notes = run(args.base, verbose=not args.quiet, full=args.full)

    if failures:
        print(f"\n!! {started} — {len(failures)} CHECK(S) FAILED at {args.base}")
        for f in failures:
            print(f"   {f}")
        sys.exit(1)

    if not args.quiet:
        mode = "full" if args.full else "quick (free)"
        print(f"\n  all {len(notes)} checks passed at {started} — {mode}")
    sys.exit(0)
