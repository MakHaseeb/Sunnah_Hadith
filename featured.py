"""
Hadith worth knowing — a hand-picked set shown before anyone asks anything.

WHY A FIXED LIST AND NOT SOMETHING COMPUTED
-------------------------------------------
The page previously gave a visitor three things to do: type a question,
browse a topic, or read the one hadith of the day. Someone who does not yet
know what to ask is left facing an empty box. This is the answer to that:
hadith that are famous by any reckoning, there to be read rather than
searched for.

Nothing here is retrieved, ranked, or generated. It is a list of ids, and
every word displayed comes from the corpus like any other result, with the
same citation and the same grading badge. That matters more than it might
seem: "famous hadith" is exactly the category where circulated wording
drifts from the authenticated text, and the only defence is to serve the
corpus record rather than a remembered version of it.

HOW THE LIST WAS CHOSEN
-----------------------
Most are from the Forty of Imam al-Nawawi, the standard collection of the
reports every Muslim is expected to know, plus a few as widely known outside
it. Each was located in the corpus by searching for a distinctive phrase and
then READ IN FULL before being listed -- not accepted on a regex match.
Ones that came back truncated or fragmentary were dropped, including
Bukhari's wording of the seven whom Allah shades, which names only one of
the seven and reads as incomplete on its own.

WHAT IS DELIBERATELY ABSENT
---------------------------
"Paradise lies at the feet of mothers" is among the most quoted sayings in
the Muslim world and is NOT here, because it is not in the corpus: its
authenticity is contested and the grading filter excluded it. Several other
popular sayings went the same way. That is the system working -- a famous
saying and an authenticated hadith are different categories, and an app that
blurred them would be doing the opposite of its job.
"""

# (hadith id, the short label a reader recognises it by)
#
# The label is our own plain-English handle for the hadith, never a summary
# of its ruling and never shown in place of the text. It exists so the list
# can be skimmed.
FEATURED = [
    ("bukhari:1",      "Deeds are by intentions"),
    ("bukhari:8",      "Islam is built on five"),
    ("tirmidhi:2515",  "Love for your brother what you love for yourself"),
    ("muslim:6501",    "Your mother, then your father"),
    ("bukhari:6136",   "Speak good, or keep silent"),
    ("bukhari:6114",   "The strong one controls himself in anger"),
    ("bukhari:6116",   "Do not become angry"),
    ("tirmidhi:3895",  "The best of you is best to his family"),
    ("tirmidhi:2504",  "Safe from his tongue and his hand"),
    ("muslim:172",     "Your neighbour must be safe from you"),
    ("muslim:6589",    "The believers are like one body"),
    ("tirmidhi:1922",  "Mercy shown is mercy received"),
    ("tirmidhi:1956",  "A smile is charity"),
    ("tirmidhi:1425",  "Relieve another's burden"),
    ("bukhari:6125",   "Make things easy"),
    ("tirmidhi:2317",  "Leave what does not concern you"),
    ("bukhari:6465",   "Small deeds done regularly"),
    ("muslim:196",     "Religion is sincerity"),
    ("muslim:534",     "Cleanliness is half of faith"),
]


def build(hadiths):
    """
    Resolve the ids against the corpus, in the order above.

    Silently skips anything missing rather than failing: a future change to
    the grading rules could legitimately remove one of these, and the right
    response is to show the rest, not to break the page. The count is
    returned so a missing entry is visible in the health check instead of
    passing unnoticed.
    """
    by_id = {h["id"]: h for h in hadiths}
    out = []
    for hid, label in FEATURED:
        h = by_id.get(hid)
        if h:
            out.append((h, label))
    return out


if __name__ == "__main__":
    import json, os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from stub_filter import split_indexable
    from citations import format_citation
    keep, _ = split_indexable(json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "corpus.json"))))
    got = build(keep)
    print(f"  {len(got)} of {len(FEATURED)} resolved")
    missing = {i for i, _ in FEATURED} - {h["id"] for h, _ in got}
    if missing:
        print(f"  MISSING: {missing}")
    for h, label in got:
        t = " ".join(h["text"].split())
        print(f"   {label:48s} {h['id']:15s} {len(t.split()):3d}w  "
              f"[{h.get('grade_label') or '—'}]")
