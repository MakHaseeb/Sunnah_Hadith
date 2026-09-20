"""
Real neural embeddings via sentence-transformers, replacing the TF-IDF
stand-in used earlier (that was only necessary because the original dev
sandbox had no internet access to reach an embedding model).

Requires (run once on your machine):
    pip3 install sentence-transformers

First run will also download the model weights (~90 MB, one-time,
cached locally afterward) -- needs internet for that first run only.
"""
import hashlib
import os

from sentence_transformers import SentenceTransformer
import numpy as np

from tfidf_store import _corpus_text

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache")

# multi-qa-MiniLM-L6-cos-v1, not all-MiniLM-L6-v2: this one is trained on
# 215M real (question, answer) pairs specifically for ASYMMETRIC retrieval
# -- a short question matched against a longer passage, which is exactly
# our case. all-MiniLM-L6-v2 is a general sentence-similarity model and,
# tested here, ranked topically-similar-but-wrong hadith above the actual
# best match for "actions are judged by intentions" -- a real, measured
# difference, not a hypothetical one.
MODEL_NAME = "multi-qa-MiniLM-L6-cos-v1"

# NOTE: on some Mac Python setups (older Accelerate/BLAS builds), the very
# FIRST matrix multiply in a process can print spurious "divide by zero /
# overflow / invalid value" RuntimeWarnings even though the result is
# completely valid -- confirmed here by checking embeddings for NaN/Inf
# (none found) and that all norms were exactly 1.0. Safe to ignore.


class HadithVectorStore:
    def __init__(self, chunks, use_cache=True):
        self.chunks = chunks
        self.model = SentenceTransformer(MODEL_NAME)
        corpus = [_corpus_text(c) for c in chunks]

        # Embedding 8,793 chunks takes ~1 minute on CPU. That was irrelevant
        # at 20 hadith and is intolerable at full corpus scale, where it is
        # paid on EVERY run -- including every evaluation-harness run, which
        # is exactly the loop that needs to stay fast. The cache key hashes
        # the model name AND the corpus text, so changing either (a re-parse,
        # a different model) invalidates it automatically rather than
        # silently serving stale vectors -- the kind of bug that would show
        # up much later as inexplicably wrong retrieval.
        self.embeddings = None
        cache_path = None
        if use_cache:
            digest = hashlib.sha256(
                (MODEL_NAME + "\x00" + "\x00".join(corpus)).encode("utf-8")
            ).hexdigest()[:16]
            os.makedirs(CACHE_DIR, exist_ok=True)
            cache_path = os.path.join(CACHE_DIR, f"emb_{digest}.npy")
            if os.path.exists(cache_path):
                self.embeddings = np.load(cache_path)

        if self.embeddings is None:
            # normalize_embeddings=True makes vectors unit length, so a plain
            # dot product below IS cosine similarity -- no separate library needed
            self.embeddings = self.model.encode(
                corpus, normalize_embeddings=True,
                batch_size=64, show_progress_bar=len(corpus) > 1000,
            )
            if cache_path:
                np.save(cache_path, self.embeddings)

    def retrieve(self, query, k=3):
        query_vec = self.model.encode([query], normalize_embeddings=True)[0]
        scores = self.embeddings @ query_vec  # cosine similarity per chunk
        ranked = sorted(
            zip(self.chunks, scores), key=lambda pair: pair[1], reverse=True
        )
        return ranked[:k]


if __name__ == "__main__":
    import json
    import os

    # Use whichever hadith file already exists from earlier runs
    for candidate in ["hadiths_p1_15.json", "sample_hadiths.json"]:
        if os.path.exists(candidate):
            with open(candidate) as f:
                hadiths = json.load(f)
            print(f"Loaded {len(hadiths)} hadith from {candidate}\n")
            break
    else:
        raise FileNotFoundError(
            "No hadith JSON found. Run terminal_app.py once first to generate it."
        )

    from chunking import chunk_hadiths
    chunks = chunk_hadiths(hadiths)
    store = HadithVectorStore(chunks)

    test_queries = [
        "actions are judged by intentions",
        "the Byzantine emperor Heraclius and the letter from the Prophet",
        "the Prophet's generosity during Ramadan",
        "revelation",              # previously failed on TF-IDF (synonym gap)
        "Hajjat-al-Wida",          # previously false-matched on TF-IDF
        "chocolate cake recipe",   # should stay low-confidence
    ]

    for q in test_queries:
        print(f"\nQuery: {q!r}")
        for chunk, score in store.retrieve(q, k=2):
            print(
                f"  score={score:.3f}  Vol {chunk['volume']} Book {chunk['book']} "
                f"Number {chunk['number']} chunk#{chunk['chunk_index']}  ({chunk['narrator']})"
            )
