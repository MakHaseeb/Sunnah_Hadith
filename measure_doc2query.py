"""
Measure whether generated questions actually close the vocabulary gap.

AVOIDING A FLATTERING MEASUREMENT
---------------------------------
The obvious test -- expand 50 hadith, then measure recall over the whole
14,940-hadith corpus -- is rigged in our favour. Those 50 gain extra
matching surface that the other 14,890 do not have, so recall goes up
whether or not the generated questions are any good.

So the PRIMARY metric here is corpus-independent:

    baseline  = max cosine(user's real question, hadith's own text chunks)
    expanded  = max cosine(user's real question, hadith's GENERATED questions)

If the generated questions genuinely capture how people ask, `expanded`
is much higher than `baseline` -- and that comparison involves only the
one hadith, so no other document's presence or absence can flatter it.

The corpus-wide rank is also reported, clearly labelled OPTIMISTIC,
because it is useful directionally but cannot be quoted as the real
number until the whole corpus is expanded.
"""
import json
import os
import sys

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# The user's real, plain-language question -> the hadith that answers it.
GOLD = [
    ("how should I treat my parents", ["bukhari:5971"]),
    ("what does Islam say about being kind to neighbours", ["bukhari:6977"]),
    ("what did the Prophet say about backbiting", ["muslim:6593"]),
    ("what are the benefits of cutting nails", ["bukhari:5889", "bukhari:5890", "bukhari:5891"]),
    ("should I eat with my right hand", ["muslim:5265"]),
    ("what does Islam say about cleaning teeth", ["bukhari:7240"]),
    ("what should I say before sleeping", ["bukhari:7488"]),
    ("is it okay to be angry", ["bukhari:6116", "muslim:6644"]),
    ("how should I treat animals", ["muslim:5852", "muslim:5855"]),
    ("what should I do if I miss a prayer", ["bukhari:597"]),
    ("what happens to someone who commits suicide", ["bukhari:5778"]),
]


def main(sample_path):
    from sentence_transformers import SentenceTransformer
    from chunking import chunk_hadiths
    from embed_and_retrieve import MODEL_NAME

    with open(sample_path) as f:
        generated = json.load(f)
    corpus = json.load(open(os.path.join(SCRIPT_DIR, "data", "corpus.json")))
    by_id = {r["id"]: r for r in corpus}

    model = SentenceTransformer(MODEL_NAME)

    print(f"sample: {len(generated)} hadith expanded\n")
    print(f"{'user question':44s} {'own text':>9s} {'generated':>10s} {'gain':>7s}")
    print("-" * 74)

    base_all, exp_all, improved = [], [], 0
    for question, targets in GOLD:
        target = next((t for t in targets if t in generated
                       and "questions" in generated[t]), None)
        if not target:
            print(f"{question[:44]:44s} {'(not in sample)':>28s}")
            continue
        qv = model.encode([question], normalize_embeddings=True)[0]

        own = [c["chunk_text"] for c in chunk_hadiths([by_id[target]])]
        base = float(np.max(model.encode(own, normalize_embeddings=True) @ qv))

        gen = generated[target]["questions"]
        if not gen:
            print(f"{question[:44]:44s} {'(no questions generated)':>28s}")
            continue
        exp = float(np.max(model.encode(gen, normalize_embeddings=True) @ qv))

        base_all.append(base); exp_all.append(exp)
        improved += exp > base
        print(f"{question[:44]:44s} {base:9.3f} {exp:10.3f} {exp-base:+7.3f}")

    if not base_all:
        print("\nNothing measurable -- no ground-truth hadith in the sample.")
        return
    print("-" * 74)
    print(f"{'MEAN':44s} {np.mean(base_all):9.3f} {np.mean(exp_all):10.3f} "
          f"{np.mean(exp_all)-np.mean(base_all):+7.3f}")
    print(f"\nimproved on {improved}/{len(base_all)} questions")
    print(f"generated questions clear the 0.44 confidence gate on "
          f"{sum(1 for e in exp_all if e >= 0.44)}/{len(exp_all)} "
          f"(own text: {sum(1 for b in base_all if b >= 0.44)}/{len(base_all)})")

    print("\n--- sample of what was generated ---")
    for rid, payload in list(generated.items())[:3]:
        if "questions" not in payload:
            continue
        print(f"\n  {rid}: {' '.join(by_id[rid]['text'].split())[:88]}")
        for q in payload["questions"]:
            print(f"     - {q}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        SCRIPT_DIR, "data", "doc2query", "sample_claude-opus-5.json")
    if not os.path.exists(path):
        raise SystemExit(f"No sample at {path}\nRun:  python3 doc2query.py --model <model> --limit 50")
    main(path)
