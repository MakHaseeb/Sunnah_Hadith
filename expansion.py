"""
Load doc2query-generated questions and fold them into the search index.

HOW THIS CHANGES RETRIEVAL
--------------------------
Without expansion, a user's plain-language question is matched against
7th-century scripture in formal translation, and the two share almost no
vocabulary -- "how should I treat my parents" scores 0.084 against the
hadith that literally answers it.

With expansion, each hadith also carries ~6 generated questions written
in everyday language. The user's question is then matched against a
QUESTION, which is a like-for-like comparison, and the retriever's
existing best-chunk-per-hadith step picks whichever representation --
original text or generated question -- matches best.

Measured on the 50-hadith sample: mean similarity to the correct hadith
rose 0.419 -> 0.747, and 11/11 labelled questions cleared the 0.44
confidence gate versus 5/11 on raw text alone.

WHY THE GENERATED QUESTIONS ARE NEVER SHOWN TO THE USER
-------------------------------------------------------
They are machine-written and are NOT scripture. They exist only to be
matched against; what gets displayed and cited is always the original
hadith text. Chunks are tagged with `chunk_type` so this distinction
cannot be lost by accident downstream -- a generated question must never
end up quoted as though the Prophet said it.
"""
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "data", "doc2query")

DEFAULT_MODEL = "claude-haiku-4-5"


def load_expansions(model=DEFAULT_MODEL, path=None):
    """
    Return {hadith_id: [questions]} from the doc2query progress file.

    Reads the JSONL progress file rather than the assembled JSON, so
    expansions are usable while a run is still in flight -- and so a
    partially-complete run still helps the hadith it has reached.
    """
    path = path or os.path.join(OUT_DIR, f"progress_{model}.jsonl")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = rec.get("id")
            qs = rec.get("questions") or []
            if rid and qs:
                # A later line for the same id supersedes an earlier one
                # (e.g. a retry after an error).
                out[rid] = [q for q in qs if isinstance(q, str) and q.strip()]
    return out


def expansion_chunks(hadiths, expansions):
    """
    Build the extra index entries contributed by generated questions.

    Each question becomes its own chunk. One question per chunk, rather
    than all six concatenated: concatenating would average six different
    topics into a single vector, which is exactly the blurring that made
    whole-hadith embeddings fail (see chunking.py).
    """
    chunks = []
    for h in hadiths:
        for i, q in enumerate(expansions.get(h["id"], [])):
            chunks.append({
                **h,
                "chunk_index": f"q{i}",
                "chunk_text": q,
                "chunk_type": "question",
            })
    return chunks


def coverage(hadiths, expansions):
    have = sum(1 for h in hadiths if expansions.get(h["id"]))
    total_q = sum(len(v) for v in expansions.values())
    return {
        "hadith_with_questions": have,
        "hadith_total": len(hadiths),
        "fraction": have / len(hadiths) if hadiths else 0.0,
        "questions_total": total_q,
    }


if __name__ == "__main__":
    corpus = json.load(open(os.path.join(SCRIPT_DIR, "data", "corpus.json")))
    exp = load_expansions()
    c = coverage(corpus, exp)
    print(f"expansion coverage: {c['hadith_with_questions']:,}/{c['hadith_total']:,} "
          f"hadith ({c['fraction']:.1%})")
    print(f"generated questions: {c['questions_total']:,}")
    if exp:
        rid = next(iter(exp))
        print(f"\nexample — {rid}:")
        for q in exp[rid]:
            print(f"  - {q}")
