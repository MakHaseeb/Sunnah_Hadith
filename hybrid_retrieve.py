"""
Hybrid retrieval: TF-IDF (exact/rare keyword matching) + neural embeddings
(semantic/paraphrase matching), combined via Reciprocal Rank Fusion (RRF),
on top of chunked hadith (see chunking.py).
"""
from chunking import chunk_hadiths
from expansion import expansion_chunks, load_expansions
from stub_filter import split_indexable
from tfidf_store import TfidfStore
from char_store import CharStore
from embed_and_retrieve import HadithVectorStore

RRF_K = 60

# CONFIDENCE GATE -- retuned against the full 7,580-hadith corpus.
#
# The original gate was "tfidf >= 0.1 OR neural >= 0.4", tuned on a
# 20-hadith slice. Measured on the full corpus over 20 genuine Islamic
# questions and 18 clearly out-of-domain ones, it accepted 100% of real
# questions but rejected only 39% of the junk -- "what is the capital of
# France" and "best python web framework" both came back CONFIDENT.
#
# The cause is that TF-IDF's score stopped discriminating once the corpus
# grew. Its range on in-domain queries (0.171-0.563) now overlaps almost
# entirely with out-of-domain (0.000-0.573): "best python web framework"
# scores 0.573, HIGHER than every genuine question tested. With 7,580
# documents, any query shares incidental vocabulary with something. The
# OR branch therefore admitted nearly everything.
#
# TF-IDF is still doing useful work -- it is half of the RRF fusion and
# genuinely finds rare exact terms ("Nawafil") that embeddings miss. It
# is only useless as an ABSOLUTE CONFIDENCE signal, which is a different
# job. Ranking and gating are separate concerns; this is the same lesson
# bug #6 taught about the cross-encoder, arriving from the other side.
#
# RETUNED AGAIN after doc2query expansion (see expansion.py).
#
# Pre-expansion the two distributions OVERLAPPED -- in-domain 0.376-0.737
# against out-of-domain 0.123-0.422 -- so 0.44 was the lowest gate that
# rejected all junk, and it cost ~15% of genuine questions.
#
# Indexing 87,240 generated questions removed the overlap entirely:
#
#     in-domain      0.627 - 1.000   (20 real questions)
#     out-of-domain  0.160 - 0.527   (18 clearly unrelated queries)
#
# There is now a clean gap, and 0.55 sits inside it: 100% of real
# questions accepted AND 100% of junk rejected. This is the real payoff
# of doc2query -- it did NOT improve ranking on the labelled set, but it
# made the confidence signal separable, which was the blocker.
#
# CAVEAT worth respecting: the test questions are phrased the way the
# generated questions are phrased, so 0.627 as a floor is probably
# optimistic. A user asking something unusually worded will score lower.
# 0.55 is chosen to leave headroom below that floor rather than hugging
# it. Re-measure against real user queries before tightening.
NEURAL_THRESHOLD = 0.55

# Retained for reference/display only -- NOT part of the gate any more.
TFIDF_THRESHOLD = 0.1


def _hadith_key(chunk):
    # Keyed on the record id, not (volume, book, number). The PDF and the
    # structured source use DIFFERENT book-numbering schemes (93-book
    # USC-MSA vs 97-book Arabic), so a positional tuple is not a stable
    # identity across sources -- and structured records have no volume at
    # all. `id` ("bukhari:6621") is unique and source-independent.
    return chunk["id"]


def _best_chunk_per_hadith(chunk_ranked):
    best = {}
    for chunk, score in chunk_ranked:
        key = _hadith_key(chunk)
        if key not in best or score > best[key][1]:
            best[key] = (chunk, score)
    return sorted(best.values(), key=lambda pair: pair[1], reverse=True)


class HybridStore:
    def __init__(self, hadiths, expansions=None, use_expansions=True,
                 exclude_stubs=True, use_char=True):
        """
        expansions: {hadith_id: [generated questions]}. Passing None loads
        whatever doc2query has produced so far; pass {} to disable, which
        is how the A/B comparison is run.

        Generated questions are added as extra chunks pointing at the same
        hadith. The existing best-chunk-per-hadith step then lets a hadith
        be found either through its own wording or through a question
        phrased the way a user would ask -- which is the entire point.
        """
        # Content-free records (isnad stubs, "as above" cross-references)
        # are excluded from the INDEX but kept on self.hadiths, since they
        # are genuinely part of the collection. A record with no content
        # cannot answer a question, and once doc2query gave those records
        # plausible generated questions they began winning retrieval
        # outright -- see stub_filter.py.
        indexable, self.excluded = (split_indexable(hadiths) if exclude_stubs
                                    else (hadiths, []))
        self.hadiths = indexable
        if expansions is None:
            expansions = load_expansions() if use_expansions else {}
        self.expansions = expansions
        self.chunks = chunk_hadiths(indexable)
        if expansions:
            self.chunks = self.chunks + expansion_chunks(indexable, expansions)
        self.tfidf_store = TfidfStore(self.chunks)
        # Third opinion: letter-pattern matching, so a misspelled or
        # differently-transliterated term still finds its hadith.
        self.char_store = CharStore(self.chunks) if use_char else None
        self.neural_store = HadithVectorStore(self.chunks)

    def retrieve(self, query, k=3):
        n = len(self.chunks)
        tfidf_chunk_ranked = self.tfidf_store.retrieve(query, k=n)
        neural_chunk_ranked = self.neural_store.retrieve(query, k=n)
        char_ranked = (_best_chunk_per_hadith(self.char_store.retrieve(query, k=n))
                       if self.char_store else [])
        char_info = {_hadith_key(c): rank + 1
                     for rank, (c, _s) in enumerate(char_ranked)}

        tfidf_ranked = _best_chunk_per_hadith(tfidf_chunk_ranked)
        neural_ranked = _best_chunk_per_hadith(neural_chunk_ranked)

        tfidf_info = {_hadith_key(c): (rank + 1, score) for rank, (c, score) in enumerate(tfidf_ranked)}
        # Also carry the NEURAL best-matching chunk's TEXT forward -- the
        # reranking stage needs the specific sub-chunk that actually
        # matched, not the full (possibly long, truncation-prone) hadith.
        neural_info = {
            _hadith_key(c): (rank + 1, score, c["chunk_text"])
            for rank, (c, score) in enumerate(neural_ranked)
        }

        fused = []
        for h in self.hadiths:
            key = h["id"]
            # A hadith always has at least one chunk, but .get keeps a
            # malformed record from taking down the whole query.
            if key not in tfidf_info or key not in neural_info:
                continue
            t_rank, t_score = tfidf_info[key]
            n_rank, n_score, n_chunk_text = neural_info[key]
            rrf_score = 1 / (RRF_K + t_rank) + 1 / (RRF_K + n_rank)
            if char_info:
                # Half weight: a third opinion that can rescue a misspelling
                # without outvoting the two signals that are usually right.
                rrf_score += 0.5 / (RRF_K + char_info.get(key, n))
            fused.append((h, n_chunk_text, rrf_score, t_score, n_score))

        fused.sort(key=lambda x: x[2], reverse=True)
        # each item: (hadith, best_chunk_text, rrf_score, tfidf_score, neural_score)
        return fused[:k]

    def is_confident(self, tfidf_score, neural_score):
        # tfidf_score is accepted for signature compatibility and display,
        # but deliberately does not participate -- see NEURAL_THRESHOLD.
        return neural_score >= NEURAL_THRESHOLD


if __name__ == "__main__":
    import json
    with open("hadiths_p1_15.json") as f:
        hadiths = json.load(f)

    store = HybridStore(hadiths)
    for q in ["actions are judged by intentions", "Nawafil prayers"]:
        print(f"\nQuery: {q!r}")
        for h, chunk_text, rrf, t, n in store.retrieve(q, k=3):
            print(f"  rrf={rrf:.4f}  tfidf={t:.3f}  neural={n:.3f}  Number {h['number']:3d}")
