"""
Assemble the searchable corpus from every ingested collection.

Sahih Bukhari carries PDF cross-check stamps from align_sources.py.
Sahih Muslim has NO second source -- there is no independently-produced
English edition of it in hand -- so every Muslim record is marked
`verified_against_pdf: False`, meaning "single source", not "failed".
That distinction is surfaced in the UI rather than hidden: a reader (or
a reviewing scholar) should be able to see which texts were corroborated
and which rest on one source.

Why Muslim was added before the doc2query/vocabulary work: matching
Nawawi's 40 -- the most widely taught hadith collection, and the closest
available proxy for "what people actually ask about" -- against a
Bukhari-only corpus found only ~14% present, because Nawawi draws
heavily on Muslim. Expanding the corpus first means the expensive
document-expansion step runs once over the final corpus instead of twice.
"""
import json
import os

from load_structured import load_collection

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
BUKHARI_VERIFIED = os.path.join(DATA_DIR, "bukhari_verified.json")
CORPUS_PATH = os.path.join(DATA_DIR, "corpus.json")

COLLECTIONS = ["bukhari", "muslim"]


def build(collections=COLLECTIONS):
    corpus = []
    for name in collections:
        if name == "bukhari" and os.path.exists(BUKHARI_VERIFIED):
            # Prefer the cross-checked build so the PDF verification
            # stamps and USC-MSA references survive.
            with open(BUKHARI_VERIFIED) as f:
                records = json.load(f)
            source = "structured + PDF cross-check"
        else:
            records = load_collection(name)
            for r in records:
                r.setdefault("usc_reference", None)
                r["verification"] = {"verified_against_pdf": False}
            source = "structured only"
        print(f"  {name:9s} {len(records):5d} records  ({source})")
        corpus.extend(records)

    ids = [r["id"] for r in corpus]
    assert len(ids) == len(set(ids)), "duplicate record ids across collections"
    return corpus


if __name__ == "__main__":
    print("Building corpus...")
    corpus = build()
    with open(CORPUS_PATH, "w") as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)

    verified = sum(
        1 for r in corpus if (r.get("verification") or {}).get("verified_against_pdf")
    )
    print(f"\nTOTAL: {len(corpus)} hadith  ->  {CORPUS_PATH}")
    print(f"  cross-checked against a second source: {verified} ({verified/len(corpus):.0%})")
    print(f"  single source:                         {len(corpus)-verified}")
