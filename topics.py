"""
Browse by topic.

WHY A CURATED LIST AND NOT ALL 154
----------------------------------
The corpus carries 154 named books, but the largest are not what an
ordinary visitor is looking for -- "Military Expeditions led by the
Prophet" has 487 hadith and "Prophetic Commentary on the Qur'an" has 498,
and neither is what someone means when they come here with a question
about daily life.

So the sidebar shows a hand-ordered set of everyday subjects, matched
against whatever the collections actually call them (Bukhari and Muslim
name the same subject differently -- "The Book of Prayers" and "Prayers
(Salat)" are both prayer). Each entry gathers hadith from every book whose
name matches, across both collections.

Browsing costs nothing: it reads from memory and makes no AI call, unlike
a search.

WHY THE ORDER INSIDE A TOPIC NEEDED ITS OWN THOUGHT
---------------------------------------------------
The first version showed the shortest hadith first, reasoning that a
browser wants something readable at a glance. The effect was the opposite.
"Faith" opened with "he saw Allah with his heart" and "He who took up arms
against us is not of us" -- both genuinely filed under Faith by the
collectors, both nearly meaningless stripped of their context. The
shortest records are the ones with the least context, so sorting by length
reliably surfaced the most confusing ones.

Semantic ranking was tried and was worse: chain-of-transmission notes carry
generated questions from doc2query, so they scored 0.758 against "what does
it mean to have faith" and took the top spot. That is bug #23 arriving
again from a different direction.

What is used instead is deliberately dull and explainable: prefer a hadith
that actually SAYS something about the subject (its text uses the subject's
own vocabulary) and that is long enough to stand on its own. A reader can
be told why a result is where it is, which matters more here than a
slightly better ordering nobody can account for.
"""
import re

# (label shown, patterns matched against BOOK NAMES, words looked for in
#  the hadith's own TEXT). The second list decides membership, the third
#  decides what rises to the top -- a hadith filed under Faith that never
#  mentions belief is still in the topic, just not the first thing shown.
TOPICS = [
    ("Faith",              [r"\bfaith\b", r"\bbelief\b"], [r"faith", r"believ", r"\bislam\b", r"\biman\b"]),
    ("Prayer",             [r"book of prayers?\b", r"^prayers? \(salat\)", r"times of the prayers"], [r"\bpray", r"\bsalat\b", r"rak.?ah", r"prostrat", r"mosque"]),
    ("Purification",       [r"ablution", r"purification", r"bathing", r"tayammum"], [r"ablut", r"\bwudu", r"\bghusl\b", r"purif", r"\bwash", r"tayammum"]),
    ("Fasting",            [r"fasting", r"\bramadan\b", r"taraweeh"], [r"\bfast", r"ramadan", r"\bsaum\b", r"suhur", r"iftar"]),
    ("Charity & Zakat",    [r"zakat", r"charity"], [r"\bzakat\b", r"charit", r"\balms\b", r"\bsadaqa", r"\bgive\b", r"\bpoor\b", r"\bneedy\b"]),
    ("Pilgrimage",         [r"pilgrimage", r"\bhajj\b", r"umrah"], [r"\bhajj\b", r"pilgrim", r"\bihram\b", r"\bka.?ba\b", r"\bumra", r"tawaf"]),
    ("Good Manners",       [r"good manners", r"al-adab", r"enjoining good manners"], [r"manner", r"\bkind", r"\bgentl", r"\bpatien", r"\bmodest", r"\bhonest", r"\btruthful"]),
    ("Kindness & Kinship", [r"ties of kinship", r"virtue, enjoining"], [r"kinship", r"\brelativ", r"\bparent", r"\bmother\b", r"\bfather\b", r"\bneighbour", r"\bneighbor"]),
    ("Marriage",           [r"wedlock", r"marriage", r"nikaah"], [r"\bmarri", r"\bwife\b", r"\bhusband\b", r"\bwives\b", r"\bnikah\b", r"\bdowry\b", r"\bmahr\b"]),
    ("Divorce",            [r"divorce"], [r"divorc", r"\btalaq\b", r"\bidda", r"separat"]),
    ("Food & Drink",       [r"\bfood\b", r"\bdrinks?\b", r"meals", r"hunting, slaughtering"], [r"\beat", r"\bdrink", r"\bfood\b", r"\bmeal", r"\bwater\b", r"\bmeat\b", r"\bslaughter"]),
    ("Dress",              [r"\bdress\b", r"clothing"], [r"\bdress", r"\bcloth", r"\bgarment", r"\bsilk\b", r"\bveil\b", r"\bhijab\b", r"\bwear"]),
    ("Medicine & Illness", [r"medicine", r"patients", r"\bsick\b"], [r"\bill(ness)?\b", r"\bsick", r"\bdisease", r"\bmedicin", r"\bcure", r"\bheal", r"\bpatient"]),
    ("Supplications",      [r"invocation", r"supplication", r"\bdhikr\b", r"remembrance"], [r"\bsupplicat", r"\binvoc", r"\bdua\b", r"\bpray(er)? for\b", r"\bsay\b.*\bO Allah\b", r"remembrance"]),
    ("Knowledge",          [r"knowledge"], [r"knowledge", r"\blearn", r"\bteach", r"\bscholar", r"\bstudy\b"]),
    ("Repentance",         [r"repentance", r"forgiveness"], [r"repent", r"forgive", r"\bpardon", r"\bsin\b", r"\bmercy\b"]),
    ("The Hereafter",      [r"paradise", r"hell\b", r"day of judgment", r"resurrection", r"heart tender"], [r"paradise", r"\bhell\b", r"resurrect", r"\bgrave\b", r"day of judg", r"hereafter", r"\bafterlife\b"]),
    ("Trade & Money",      [r"sales and trade", r"business transactions", r"\bloans?\b", r"transactions"], [r"\bsell\b", r"\bsale\b", r"\bbuy", r"\btrade", r"\bdebt\b", r"\bloan", r"\busury\b", r"\briba\b", r"\bprice\b"]),
    ("Oaths & Vows",       [r"oaths", r"vows"], [r"\boath", r"\bvow", r"\bswear", r"\bswore\b"]),
    ("Inheritance",        [r"inheritance", r"faraa'id", r"wills"], [r"inherit", r"\bheir", r"\bwill\b", r"bequest", r"estate"]),
    ("Dreams",             [r"dreams", r"interpretation of dreams"], [r"\bdream", r"\bvision\b", r"\bsleep\b"]),
    ("Funerals",           [r"funeral", r"janaa'iz"], [r"funeral", r"\bburial\b", r"\bbury\b", r"\bgrave\b", r"\bdeath\b", r"\bdied\b", r"\bcorpse\b"]),
]


def _display_score(hadith, keyword_rx):
    """
    How good a first impression this hadith makes for its topic.

    Two dull, explainable components. ON TOPIC: the text uses the subject's
    own vocabulary, so a reader can see why it is here -- a hadith filed
    under Faith that never mentions belief is still in the topic, just not
    the first thing shown. STANDS ALONE: long enough to carry its own
    context. The old shortest-first order failed precisely because the
    briefest records are the ones that make no sense without the ones
    around them.
    """
    text = " ".join(hadith["text"].split())
    words = len(text.split())
    on_topic = sum(1 for r in keyword_rx if r.search(text))
    if words < 20:
        length = 0          # usually a fragment of a neighbouring report
    elif words <= 120:
        length = 2          # reads as a complete thought
    elif words <= 250:
        length = 1
    else:
        length = 0          # a wall of text to open a topic with
    # Length band FIRST, then topicality. Ordering by keyword count first
    # was tried and reproduced bug #17 in a new place: a 487-word narration
    # trivially contains more matches than a 45-word ruling, so the longest
    # records took every top slot. Reading it as "of the hadith that are a
    # sensible length, show the ones most clearly about the subject" is
    # both better and easier to explain.
    return (length, min(on_topic, 3), -words)


def build_index(hadiths):
    """
    topic label -> hadith from every book whose name matches, ordered for
    browsing and with duplicate texts collapsed.

    Deduplication matters more than it looks: the collections repeat each
    other, and 401 exact duplicate texts were in the index. "Faith" showed
    "He who took up arms against us is not of us" twice in a row, which
    reads as a bug even when the underlying records are legitimately
    distinct entries in two books.
    """
    index = {}
    for entry in TOPICS:
        label, patterns = entry[0], entry[1]
        keywords = entry[2] if len(entry) > 2 else []
        rx = [re.compile(p, re.I) for p in patterns]
        kw = [re.compile(k, re.I) for k in keywords]
        hits = [h for h in hadiths
                if h.get("book_name") and any(r.search(h["book_name"]) for r in rx)]
        seen, unique = set(), []
        for h in hits:
            key = " ".join(h["text"].lower().split())
            if key in seen:
                continue
            seen.add(key)
            unique.append(h)
        unique.sort(key=lambda h: _display_score(h, kw), reverse=True)
        if unique:
            index[label] = unique
    return index


def listing(index):
    return [{"name": k, "count": len(v)} for k, v in index.items()]


if __name__ == "__main__":
    import json, os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from stub_filter import split_indexable
    corpus = json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "corpus.json")))
    keep, _ = split_indexable(corpus)
    idx = build_index(keep)
    print(f"  topics with matches: {len(idx)}/{len(TOPICS)}")
    missing = [l for l, _ in TOPICS if l not in idx]
    if missing:
        print(f"  MATCHED NOTHING: {missing}")
    total = len({h['id'] for v in idx.values() for h in v})
    print(f"  hadith reachable by browsing: {total:,} of {len(keep):,}\n")
    for label, hits in idx.items():
        books = sorted({h["book_name"] for h in hits})[:2]
        print(f"    {len(hits):5d}  {label:20s} e.g. {'; '.join(b[:38] for b in books)}")
