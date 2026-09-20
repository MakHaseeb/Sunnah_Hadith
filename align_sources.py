"""
Cross-check the structured corpus against the independently-parsed PDF.

THE POINT
---------
Two sources, produced by completely different routes (a published PDF run
through pdftotext + regex parsing, vs. a community JSON dataset), should
agree on the text of the same hadith. Where they agree, we have real
evidence the text is faithful. Where they disagree, we have a concrete
list to inspect rather than a vague hope that the data is fine.

For an app that puts scripture in front of people and will go to a
scholar for review, "every verified hadith was matched against a second
independent source, and here are the exceptions" is a far stronger
position than "we trusted one download".

WHY MATCH ON TEXT AND NOT ON NUMBERS
------------------------------------
The obvious approach -- align on (book, position within book) -- does not
work, and fails deceptively. Both sources label books 1-93, so a
presence check passes. But the PDF uses the 93-book USC-MSA division and
the structured source uses the 97-book Arabic division: "Tawheed" is
Book 93 in one and Book 97 in the other. Only 3 of 93 books agree on
hadith count, and the drift grows through the corpus.

Since both carry the same Khan translation, the text itself is the
reliable join key. TF-IDF over word 1-2 grams + cosine similarity
matches ~99% of PDF records at >=0.8 similarity, with a median of 1.000
(exact match after normalisation).

NORMALISATION
-------------
The two editions differ systematically in ways that are not substantive:
"Allah's Apostle" (PDF) vs "Allah's Messenger (peace be upon him)"
(structured), and the structured side strips terminal punctuation. Those
are folded away before comparison so they don't masquerade as real
disagreements.
"""
import json
import os
import re
import unicodedata

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Tuned against the observed score distribution (p10=0.946, p50=1.000):
# genuine matches cluster near 1.0, and manual inspection of everything
# below 0.80 found real mismatches there, so that is where the line sits.
VERIFIED_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.60
BATCH = 500  # keeps the similarity matrix ~30MB instead of ~400MB


def normalise(text):
    t = unicodedata.normalize("NFKD", str(text))
    t = t.replace("ﷺ", "").replace("صلى", "")
    t = t.lower()
    # Fold the two editions' different renderings of the same title.
    t = re.sub(r"\ballah'?s? (apostle|messenger)\b", " prophet ", t)
    t = re.sub(r"\bthe prophet\b", " prophet ", t)
    t = re.sub(r"[^a-z ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _pdf_citation(h):
    return {
        "volume": h["volume"],
        "book": h["book"],
        "number": h["number"],
        "number_suffix": h.get("number_suffix", ""),
    }


def align(structured, pdf_hadiths):
    """
    Match every PDF hadith to its best structured counterpart.

    Returns (matches, stats). Each match records both citation schemes,
    the similarity, and the word-count delta -- the delta is what proves
    the structured source's missing punctuation isn't lost CONTENT.
    """
    struct_norm = [normalise(r["text"]) for r in structured]
    pdf_norm = [
        normalise(f"{h.get('narrator') or ''} {h['text']}") for h in pdf_hadiths
    ]

    vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1)
    struct_matrix = vec.fit_transform(struct_norm)

    matches = []
    for start in range(0, len(pdf_norm), BATCH):
        block = pdf_norm[start:start + BATCH]
        sims = linear_kernel(vec.transform(block), struct_matrix)
        best_idx = sims.argmax(axis=1)
        best_score = sims.max(axis=1)
        for offset, (j, score) in enumerate(zip(best_idx, best_score)):
            h = pdf_hadiths[start + offset]
            s = structured[j]
            matches.append({
                "pdf": _pdf_citation(h),
                "structured_id": s["id"],
                "similarity": float(score),
                "pdf_words": len(h["text"].split()),
                "structured_words": len(s["text"].split()),
            })

    # One structured hadith should not be the best match for several PDF
    # hadith. Where it is, the highest-scoring claim wins and the rest are
    # demoted to "contested" -- silently keeping duplicates would produce
    # wrong citations.
    by_target = {}
    for m in matches:
        key = m["structured_id"]
        if key not in by_target or m["similarity"] > by_target[key]["similarity"]:
            by_target[key] = m
    winners = {id(m) for m in by_target.values()}

    for m in matches:
        if m["similarity"] >= VERIFIED_THRESHOLD and id(m) in winners:
            m["status"] = "verified"
        elif id(m) not in winners:
            m["status"] = "contested"
        elif m["similarity"] >= REVIEW_THRESHOLD:
            m["status"] = "review"
        else:
            m["status"] = "unmatched"

    stats = {
        "pdf_total": len(pdf_hadiths),
        "structured_total": len(structured),
        "verified": sum(1 for m in matches if m["status"] == "verified"),
        "review": sum(1 for m in matches if m["status"] == "review"),
        "contested": sum(1 for m in matches if m["status"] == "contested"),
        "unmatched": sum(1 for m in matches if m["status"] == "unmatched"),
    }
    return matches, stats


def apply_verification(structured, matches):
    """Stamp each structured record with its PDF cross-check result."""
    best = {}
    for m in matches:
        if m["status"] != "verified":
            continue
        key = m["structured_id"]
        if key not in best or m["similarity"] > best[key]["similarity"]:
            best[key] = m

    for rec in structured:
        m = best.get(rec["id"])
        if m:
            rec["usc_reference"] = m["pdf"]
            rec["verification"] = {
                "verified_against_pdf": True,
                "similarity": round(m["similarity"], 4),
                "word_delta": m["structured_words"] - m["pdf_words"],
            }
        else:
            # Not a defect: the PDF is missing Book 83 entirely and ~800
            # other hadith, so these simply have no second source.
            rec["verification"] = {"verified_against_pdf": False}
    return structured


if __name__ == "__main__":
    import sys
    from load_structured import load_collection
    from parse_bukhari import extract_pages, clean_and_split

    print("Loading structured corpus...")
    structured = load_collection("bukhari")
    print(f"  {len(structured)} records")

    print("Parsing PDF (independent second source)...")
    pdf_hadiths = clean_and_split(extract_pages(1, 1700))
    print(f"  {len(pdf_hadiths)} records")

    print("Aligning on text similarity...")
    matches, stats = align(structured, pdf_hadiths)

    print("\n=== CROSS-CHECK RESULT ===")
    for k, v in stats.items():
        print(f"  {k:18s} {v}")
    pct = stats["verified"] / stats["pdf_total"]
    print(f"  verified share of PDF corpus: {pct:.1%}")

    sims = np.array([m["similarity"] for m in matches])
    print(f"\n  similarity p10={np.percentile(sims,10):.3f} "
          f"p50={np.percentile(sims,50):.3f} p90={np.percentile(sims,90):.3f}")

    ver = [m for m in matches if m["status"] == "verified"]
    deltas = np.array([m["structured_words"] - m["pdf_words"] for m in ver])
    print(f"\n  CONTENT PARITY on {len(ver)} verified pairs (word count delta,")
    print(f"  structured minus PDF -- near zero means the structured source's")
    print(f"  missing punctuation is NOT missing content):")
    print(f"    mean={deltas.mean():+.2f}  median={np.median(deltas):+.1f}  "
          f"|delta|>5: {(np.abs(deltas)>5).sum()} ({(np.abs(deltas)>5).mean():.1%})")

    structured = apply_verification(structured, matches)

    out = os.path.join(SCRIPT_DIR, "data", "bukhari_verified.json")
    with open(out, "w") as f:
        json.dump(structured, f, indent=2, ensure_ascii=False)
    report = os.path.join(SCRIPT_DIR, "data", "cross_check_report.json")
    with open(report, "w") as f:
        json.dump({"stats": stats, "matches": matches}, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out}")
    print(f"Wrote {report}")

    flagged = [m for m in matches if m["status"] in ("review", "unmatched")]
    print(f"\n=== {len(flagged)} FLAGGED FOR INSPECTION (showing up to 10) ===")
    sidx = {r["id"]: r for r in structured}
    for m in sorted(flagged, key=lambda x: x["similarity"])[:10]:
        p = m["pdf"]
        s = sidx[m["structured_id"]]
        print(f"\n  [{m['status']}] sim={m['similarity']:.3f}  "
              f"PDF V{p['volume']} B{p['book']} N{p['number']}{p['number_suffix']}"
              f"  vs  {m['structured_id']}")
        print(f"    PDF: {' '.join(next(h['text'] for h in pdf_hadiths if _pdf_citation(h)==p).split())[:150]}")
        print(f"    ST : {' '.join(s['text'].split())[:150]}")
