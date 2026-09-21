"""
Counts only. Deliberately anonymous.

WHAT IS RECORDED
----------------
One line per event: the date, the event name, and an opaque visitor id.
That is all. No name, no email, no IP address, no browser string, no
question text, no location.

The visitor id is a random string the browser generates for itself and
keeps in local storage. It is never linked to a Google account, never sent
anywhere else, and cannot be traced back to a person -- it exists only so
"how many people searched" can be told apart from "how many searches
happened", which are different questions with very different answers.

WHY A PLAIN FILE AND NOT AN ANALYTICS SERVICE
---------------------------------------------
Google Analytics and its equivalents work by sending your visitors' data to
a third party, which for a religious site means telling an advertising
company who reads hadith and what they searched for. That is a poor trade
for a dashboard. Counting locally gives the same numbers with none of that,
and the file can be read with any text editor.

Appending a line is atomic on POSIX for writes this small, so concurrent
visitors cannot corrupt it. Aggregation happens on read -- at this volume
that costs nothing, and it means no counter can drift out of step.
"""
import json
import os
import time
from collections import Counter, defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EVENTS_PATH = os.path.join(SCRIPT_DIR, "data", "events.jsonl")

# Only these are accepted, so a malicious caller cannot fill the file with
# arbitrary strings.
ALLOWED = {
    "visit",        # someone opened the page
    "search",       # someone asked a question
    "answered",     # the search returned at least one hadith
    "no_answer",    # the search found nothing confident
    "feedback",     # someone reported a result or sent a note
    "support_open", # someone opened the support panel
    "support_click",# someone clicked through to the payment page
    "signin",       # someone signed in with Google
}


def record(event, visitor=None):
    if event not in ALLOWED:
        return False
    row = {
        "d": time.strftime("%Y-%m-%d"),
        "e": event,
        # truncated hard: this is an opaque token, not an identifier we want
        # to be able to do anything else with
        "v": (visitor or "")[:32],
    }
    os.makedirs(os.path.dirname(EVENTS_PATH), exist_ok=True)
    with open(EVENTS_PATH, "a") as f:
        f.write(json.dumps(row) + "\n")
    return True


def _rows():
    if not os.path.exists(EVENTS_PATH):
        return []
    out = []
    with open(EVENTS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def summary(days=30):
    rows = _rows()
    totals = Counter(r["e"] for r in rows)
    people = defaultdict(set)      # event -> distinct visitors
    by_day = defaultdict(Counter)
    day_people = defaultdict(set)
    for r in rows:
        if r.get("v"):
            people[r["e"]].add(r["v"])
            day_people[r["d"]].add(r["v"])
        by_day[r["d"]][r["e"]] += 1

    recent = sorted(by_day)[-days:]
    searches = totals.get("search", 0)
    answered = totals.get("answered", 0)

    return {
        "totals": {
            "visitors": len({r["v"] for r in rows if r.get("v")}),
            "visits": totals.get("visit", 0),
            "searches": searches,
            "people_who_searched": len(people.get("search", ())),
            "answered": answered,
            "no_answer": totals.get("no_answer", 0),
            "answer_rate": round(answered / searches, 3) if searches else None,
            "feedback": totals.get("feedback", 0),
            "people_who_gave_feedback": len(people.get("feedback", ())),
            "support_opened": totals.get("support_open", 0),
            "support_clicked": totals.get("support_click", 0),
        },
        "daily": [
            {
                "date": d,
                "people": len(day_people.get(d, ())),
                **{k: by_day[d].get(k, 0) for k in
                   ("visit", "search", "answered", "no_answer",
                    "feedback", "support_click")},
            }
            for d in recent
        ],
    }


if __name__ == "__main__":
    s = summary()
    print("TOTALS")
    for k, v in s["totals"].items():
        print(f"  {k:26s} {v}")
    if s["daily"]:
        print("\nBY DAY")
        print(f"  {'date':12s} {'people':>7s} {'visits':>7s} {'searches':>9s} "
              f"{'answered':>9s} {'feedback':>9s} {'gifts':>6s}")
        for d in s["daily"]:
            print(f"  {d['date']:12s} {d['people']:7d} {d['visit']:7d} "
                  f"{d['search']:9d} {d['answered']:9d} {d['feedback']:9d} "
                  f"{d['support_click']:6d}")
    else:
        print("\n(no events recorded yet)")
