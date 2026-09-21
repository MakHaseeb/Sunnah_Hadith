"""
Hadith of the day, plus the hadith shown on the support button.

WHY A FIXED, HAND-PICKED LIST
-----------------------------
The daily hadith is the one piece of text on the site nobody asked for --
it is served unprompted, so it must be safe without a question to justify
it. That rules out picking at random from 13,000 records: many are long
chains of narration, many need context to read properly, and a few concern
matters that would be jarring to meet cold on a homepage.

So the pool is a short, deliberately chosen set of well-known hadith,
each checked to be self-contained, widely taught, and short enough to read
in one sitting. Every id here was verified against the corpus.

WHY THE SAME ONE FOR EVERYONE
-----------------------------
The date picks the hadith, so every visitor on a given day sees the same
one, and it changes at midnight. That makes it something people can talk
about ("today's hadith"), and it means a scholar reviewing the site can
check what was shown on a given date.
"""
import datetime
import hashlib

# Well-known, self-contained, and short. Verified present in data/corpus.json.
DAILY_POOL = [
    "bukhari:1",      # the reward of deeds depends upon intentions
    "bukhari:5971",   # your mother, your mother, your mother, then your father
    "muslim:6593",    # do you know what backbiting is
    "bukhari:6116",   # do not become angry
    "muslim:6644",    # the strong man controls himself in rage
    "bukhari:7240",   # the siwak
    "muslim:5265",    # eat and drink with the right hand
    "bukhari:597",    # pray a forgotten prayer when you remember it
    "muslim:5855",    # the woman punished over a cat
    "muslim:6638",    # truth leads to Paradise
    "bukhari:1365",   # suicide
    "muslim:2386",    # the best charity
    "bukhari:5889",   # five practices of the fitra
    "muslim:252",     # the best deeds
    "bukhari:5972",   # do jihad for your parents' benefit
    "muslim:6507",    # go back to your parents and treat them well
    "bukhari:6461",   # when the Prophet rose for Tahajjud
    "muslim:1767",    # pray at the end of the night
    "muslim:6592",    # charity does not decrease wealth
    "bukhari:6092",   # the Prophet used only to smile
    "bukhari:1417",   # save yourself from the Fire with half a date
    "bukhari:5186",   # do not hurt your neighbour
    "bukhari:13",     # wish for your brother what you wish for yourself
    "muslim:6470",    # the best of people
    "bukhari:6018",   # speak good or stay silent
    "bukhari:2442",   # a Muslim is the brother of a Muslim
    "muslim:6541",    # do not nurse grudges
]

# Shown beside the support button. "Even half a date" is precisely the point:
# any amount counts, nobody should feel their contribution is too small.
SUPPORT_HADITH_ID = "bukhari:1417"


def hadith_for(date=None):
    """Which hadith belongs to a given day. Same for every visitor."""
    date = date or datetime.date.today()
    # Hashing the date rather than using day-of-year means consecutive days
    # are unrelated, so the list does not read in a predictable order.
    digest = hashlib.sha256(date.isoformat().encode()).hexdigest()
    return DAILY_POOL[int(digest[:8], 16) % len(DAILY_POOL)]


if __name__ == "__main__":
    import json, os
    corpus = json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "corpus.json")))
    by_id = {r["id"]: r for r in corpus}

    missing = [i for i in DAILY_POOL + [SUPPORT_HADITH_ID] if i not in by_id]
    print(f"pool: {len(DAILY_POOL)} hadith   missing from corpus: {missing or 'none'}")

    today = datetime.date.today()
    print("\nnext 10 days:")
    for n in range(10):
        d = today + datetime.timedelta(days=n)
        rid = hadith_for(d)
        print(f"  {d}  {rid:14s} {' '.join(by_id[rid]['text'].split())[:66]}")

    seen = {hadith_for(today + datetime.timedelta(days=n)) for n in range(120)}
    print(f"\ndistinct hadith over 120 days: {len(seen)}/{len(DAILY_POOL)}")
