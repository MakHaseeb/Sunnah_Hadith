"""
Full retrieval pipeline.

  hybrid retrieval (TF-IDF + neural, fused with RRF)
      -> optional cross-encoder reranking   [OFF by default, see below]

THE CROSS-ENCODER IS DISABLED BY DEFAULT -- THIS IS AN EVIDENCE-BASED REVERSAL
------------------------------------------------------------------------------
Bug #6 (found at 20 hadith) established that this cross-encoder's raw
scores are not a trustworthy ABSOLUTE cutoff on religious text -- it was
trained on MS MARCO web-search queries. The response then was to keep it
for REORDERING only, and anchor accept/reject to the hybrid retriever's
own thresholds. Reasonable at the time.

At 7,580 hadith that compromise no longer holds: the reranker is not
just poorly calibrated, it actively makes ranking WORSE.

Measured on the evaluation harness:

    hybrid only ........ 7/8 firm cases, 1 regression
    hybrid + rerank .... 6/8 firm cases, 2 regressions

The clearest single case, query "actions are judged by intentions":

    hybrid top 3   bukhari:6493 (0.376)
                   bukhari:2529 (0.451)  <- correct, confident
                   bukhari:1    (0.459)  <- THE canonical hadith, confident

    reranked top 3 bukhari:2118 (0.279)  <- "an army will invade the Ka`ba"
                   bukhari:2641 (0.416)
                   bukhari:6953 (0.387)

Reranking evicts both correct, confident results in favour of a passage
about an army invading the Ka`ba. Why it got worse with scale: at 20
hadith the shortlist contained obvious non-matches the cross-encoder
could still sort; drawn from 7,580 the shortlist is ten plausible
passages, and separating those is exactly where the domain mismatch
between web-search training data and classical religious text bites.

The code is kept, and the flag with it, because this is a statement
about THIS model on THIS domain -- a reranker trained on or adapted to
religious text could well earn its place. Re-test before re-enabling;
do not switch it on because reranking is conventionally a good idea.
"""
from hybrid_retrieve import HybridStore
from reranker import Reranker

CANDIDATE_POOL_SIZE = 10


class RerankedStore:
    def __init__(self, hadiths, use_reranker=False):
        self.hybrid_store = HybridStore(hadiths)
        self.use_reranker = use_reranker
        # Loading the cross-encoder costs time and memory; skip it entirely
        # when it is not going to be used.
        self.reranker = Reranker() if use_reranker else None

    def retrieve(self, query, k=3):
        if not self.use_reranker:
            return self.hybrid_store.retrieve(query, k=k)
        candidates = self.hybrid_store.retrieve(query, k=CANDIDATE_POOL_SIZE)
        reranked = self.reranker.rerank(query, candidates)
        return reranked[:k]

    def is_confident(self, tfidf_score, neural_score):
        return self.hybrid_store.is_confident(tfidf_score, neural_score)


if __name__ == "__main__":
    import json
    from citations import format_citation

    hadiths = json.load(open("data/bukhari_verified.json"))
    store = RerankedStore(hadiths)
    for q in ["actions are judged by intentions", "Nawafil prayers",
              "is it permissible to break an oath", "best python web framework"]:
        print(f"\nQuery: {q!r}")
        for item in store.retrieve(q, k=3):
            h, _, _, tfidf, neural = item[0], item[1], item[2], item[3], item[4]
            mark = "CONFIDENT" if store.is_confident(tfidf, neural) else "low      "
            print(f"  {mark} tfidf={tfidf:.3f} neural={neural:.3f}  "
                  f"{format_citation(h, include_usc=False)}")
