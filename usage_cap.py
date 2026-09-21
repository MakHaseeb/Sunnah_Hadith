"""
Bounds what the site can spend in a day.

TWO LIMITS, BECAUSE ONE IS NOT ENOUGH
-------------------------------------
**Per visitor** stops ordinary overuse -- a stuck page, someone hammering
the box, a badly written script. It is keyed on the token the browser
makes for itself, so clearing site data resets it. That is a known
weakness and it is fine: this limit exists to prevent accidents, not to
stop a determined person.

**Whole site, per day** is the real protection, and it is the one that
actually bounds the bill. It cannot be bypassed by clearing anything,
because it counts what the SERVER has spent, not what any visitor claims.
Once the day's allowance of paid relevance checks is used, the site keeps
working -- searching, browsing, the daily hadith are all free and local --
but new searches skip the paid step until midnight.

WHY DEGRADE RATHER THAN REFUSE
------------------------------
Turning people away protects the bill and destroys the site. Falling back
to plain search keeps it useful and honest: the page already says plainly
when results are unchecked, so nobody is quietly given worse answers
without being told.

The counters live in memory. A restart resets them, which is the safe
direction to be wrong in for a trial -- it fails toward the site working
rather than toward it being locked out. Move them to a file or a database
when several server processes are running, since each would otherwise keep
its own count.
"""
import os
import threading
import time
from collections import defaultdict

# Paid searches allowed across the whole site per day. At ~$0.0014 each,
# 2,000 is about $2.80 a day, so roughly $84 a month at the absolute
# worst. Set HADITH_DAILY_CAP to whatever ceiling you actually want.
DAILY_CAP = int(os.environ.get("HADITH_DAILY_CAP", "2000"))

# Paid searches one visitor may use per day.
PER_VISITOR_CAP = int(os.environ.get("HADITH_VISITOR_CAP", "40"))

_lock = threading.Lock()
_state = {"day": None, "total": 0, "per": defaultdict(int)}


def _today():
    return time.strftime("%Y-%m-%d")


def _roll():
    day = _today()
    if _state["day"] != day:
        _state["day"] = day
        _state["total"] = 0
        _state["per"] = defaultdict(int)


def allow(visitor=""):
    """
    May this search use the paid relevance check?

    Returns (allowed, reason). reason is None when allowed, otherwise
    'site' or 'visitor' so the caller can say something useful.
    """
    with _lock:
        _roll()
        if _state["total"] >= DAILY_CAP:
            return False, "site"
        if visitor and _state["per"][visitor] >= PER_VISITOR_CAP:
            return False, "visitor"
        return True, None


def record(visitor=""):
    """Count one paid search. Called only when the check actually ran."""
    with _lock:
        _roll()
        _state["total"] += 1
        if visitor:
            _state["per"][visitor] += 1


def status():
    with _lock:
        _roll()
        return {
            "day": _state["day"],
            "used": _state["total"],
            "daily_cap": DAILY_CAP,
            "remaining": max(0, DAILY_CAP - _state["total"]),
            "per_visitor_cap": PER_VISITOR_CAP,
            "visitors_today": len(_state["per"]),
            "est_spend_usd": round(_state["total"] * 0.0014, 4),
            "est_cap_usd": round(DAILY_CAP * 0.0014, 2),
        }


if __name__ == "__main__":
    print(f"  daily cap        {DAILY_CAP:,} paid searches "
          f"(~${DAILY_CAP*0.0014:.2f}/day, ~${DAILY_CAP*0.0014*30:.2f}/month worst case)")
    print(f"  per visitor      {PER_VISITOR_CAP}/day")
    print("\n  simulating a visitor hammering the box:")
    for i in range(1, PER_VISITOR_CAP + 3):
        ok, why = allow("greedy")
        if ok:
            record("greedy")
        elif i <= PER_VISITOR_CAP + 2:
            print(f"    search {i}: blocked ({why}) — falls back to free search")
            break
    print(f"\n  status: {status()}")
