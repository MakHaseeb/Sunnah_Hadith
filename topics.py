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
"""
import re

# (label shown, patterns matched against book names)
TOPICS = [
    ("Faith",              [r"\bfaith\b", r"\bbelief\b"]),
    ("Prayer",             [r"book of prayers?\b", r"^prayers? \(salat\)", r"times of the prayers"]),
    ("Purification",       [r"ablution", r"purification", r"bathing", r"tayammum"]),
    ("Fasting",            [r"fasting", r"\bramadan\b", r"taraweeh"]),
    ("Charity & Zakat",    [r"zakat", r"charity"]),
    ("Pilgrimage",         [r"pilgrimage", r"\bhajj\b", r"umrah"]),
    ("Good Manners",       [r"good manners", r"al-adab", r"enjoining good manners"]),
    ("Kindness & Kinship", [r"ties of kinship", r"virtue, enjoining"]),
    ("Marriage",           [r"wedlock", r"marriage", r"nikaah"]),
    ("Divorce",            [r"divorce"]),
    ("Food & Drink",       [r"\bfood\b", r"\bdrinks?\b", r"meals", r"hunting, slaughtering"]),
    ("Dress",              [r"\bdress\b", r"clothing"]),
    ("Medicine & Illness", [r"medicine", r"patients", r"\bsick\b"]),
    ("Supplications",      [r"invocation", r"supplication", r"\bdhikr\b", r"remembrance"]),
    ("Knowledge",          [r"knowledge"]),
    ("Repentance",         [r"repentance", r"forgiveness"]),
    ("The Hereafter",      [r"paradise", r"hell\b", r"day of judgment", r"resurrection", r"heart tender"]),
    ("Trade & Money",      [r"sales and trade", r"business transactions", r"\bloans?\b", r"transactions"]),
    ("Oaths & Vows",       [r"oaths", r"vows"]),
    ("Inheritance",        [r"inheritance", r"faraa'id", r"wills"]),
    ("Dreams",             [r"dreams", r"interpretation of dreams"]),
    ("Funerals",           [r"funeral", r"janaa'iz"]),
]


def build_index(hadiths):
    """topic label -> list of hadith, from every book whose name matches."""
    index = {}
    for label, patterns in TOPICS:
        rx = [re.compile(p, re.I) for p in patterns]
        hits = [h for h in hadiths
                if h.get("book_name") and any(r.search(h["book_name"]) for r in rx)]
        if hits:
            index[label] = hits
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
