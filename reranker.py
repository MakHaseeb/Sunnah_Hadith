"""
Cross-encoder reranking: reorders the hybrid retriever's shortlist using a
model that reads the query and each candidate TOGETHER, catching fine
distinctions bi-encoders structurally can't.

IMPORTANT finding from real testing: this cross-encoder's raw scores are
NOT reliably calibrated as an absolute accept/reject cutoff on this domain
-- a genuine match ("actions are judged by intentions", -5.784) and a
false one ("Nawafil prayers", -6.046) scored nearly identically. Likely
domain mismatch: this model was trained on general web search queries
(MS MARCO), not religious texts. So reranking is used here ONLY to choose
the best candidate among the hybrid retriever's shortlist -- the actual
accept/reject decision stays anchored to HybridStore's own thresholds,
which were validated against real evidence across 7 test cases.
"""
from sentence_transformers import CrossEncoder

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    def __init__(self):
        self.model = CrossEncoder(RERANKER_MODEL)

    def rerank(self, query, candidates):
        """
        candidates: list of (hadith, chunk_text, rrf_score, tfidf_score,
        neural_score) from HybridStore.retrieve(). Reranks using
        chunk_text (the specific matched sub-chunk), not the full hadith
        text -- the same reasoning that made chunking necessary for
        embeddings applies here: a long hadith's full text could get
        truncated by the cross-encoder's own token limit.

        Returns the SAME tuples, reordered by cross-encoder relevance,
        with the raw cross-encoder score appended for reference/display
        (NOT used for the accept/reject decision -- see module docstring).
        """
        pairs = [(query, item[1]) for item in candidates]
        raw_scores = self.model.predict(pairs)
        results = [
            (*item, float(raw_score))
            for item, raw_score in zip(candidates, raw_scores)
        ]
        results.sort(key=lambda x: x[-1], reverse=True)
        return results
