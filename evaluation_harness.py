"""
Evaluation harness, rebuilt for the full 7,580-hadith corpus.

WHAT CHANGED AND WHY
--------------------
The previous harness ran against a 20-hadith slice and reported 7/7.
That number was real but could not mean much: with 20 documents, almost
any retriever looks good, and the cases had been collected while
debugging THAT slice. Three things forced a rewrite:

  1. The corpus is now 7,580 hadith on canonical numbering, so the old
     Volume/Book/Number expectations no longer address anything.
  2. Two of the old cases became WRONG at scale. "Nawafil prayers" was
     expected to be rejected -- correct when the slice contained no
     prayer material, but the full corpus has hadith that literally use
     the word "Nawafil", so rejecting it is now the bug.
  3. Scaling surfaced failures the slice structurally could not show.

HONEST REPORTING
----------------
Cases carry an `expect` of "pass" or "known_failure". Known failures are
real, reproducible, currently-unsolved problems, kept in the suite and
reported separately rather than deleted to keep the score green. A
harness that reports 100% while the app mishandles everyday questions
would be worse than useless -- it would hide the single biggest issue.

A regression is a "pass" case that fails, OR a "known_failure" that
starts passing without anyone intending it (that means something moved).
"""
import json
import os

CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "corpus.json")

# expected_ids: retrieval succeeds if ANY of these lands in the top k.
# Sahih Bukhari deliberately repeats the same report across books, so
# pinning a single id would fail the retriever for being right in a
# different place.
EVAL_SET = [
    # ---- core retrieval, source-like vocabulary ----
    {"query": "actions are judged by intentions",
     "expected_ids": ["bukhari:1", "bukhari:2529", "bukhari:6689", "bukhari:6953", "bukhari:5070"],
     "expect": "known_failure",
     "note": "THE definitive demonstration of bug #15, and the reason no "
             "threshold can fix it. On this query: the CORRECT hadith "
             "(bukhari:1) scores 0.511, while a WRONG one (muslim:7228) scores "
             "0.703 and an out-of-domain query ('recipe for chicken biryani') "
             "scores 0.527. The correct answer scores LOWER than junk. Any "
             "gate that admits bukhari:1 also admits the junk, and any gate "
             "that rejects the junk also rejects bukhari:1. The similarity "
             "score does not track correctness, so in-domain relevance needs a "
             "different MECHANISM -- an LLM relevance check on the shortlist, "
             "not another tuning pass."},
    {"query": "what are the benefits of cutting nails",
     "expected_ids": ["bukhari:5889", "bukhari:5890", "bukhari:5891"],
     "expect": "pass",
     "note": "FIXED BY doc2query. Was a documented vocabulary-gap failure: the "
             "right Fitra hadith reached the top 3 but scored only ~0.388, "
             "because it lists 'clipping the nails' among five practices and "
             "never discusses 'benefits'. It now matches the generated question "
             "'What did the Prophet say about cutting nails?' at 0.627 and is "
             "confident. This is the clearest case of expansion working."},
    {"query": "Nawafil prayers",
     "expected_ids": ["bukhari:1000", "bukhari:4140", "bukhari:1109"],
     "expect": "pass",
     "note": "Bug #5 inverted. The 20-hadith slice had no prayer material so "
             "rejection was right then; at full scale hadith literally "
             "containing 'Nawafil' exist, so rejecting is now the failure."},
    {"query": "is it permissible to break an oath",
     "expected_ids": ["bukhari:6621", "bukhari:6625", "bukhari:6626", "bukhari:6649",
                      "bukhari:4549", "bukhari:6647",
                      # Added when Sahih Muslim was ingested. The harness
                      # flagged this as a regression; it was not one -- the
                      # TEST was stale. muslim:4276 ("he who took an oath but
                      # found something better should do the better and break
                      # his oath") answers the question more directly than the
                      # Bukhari hadith it displaced. Ground truth written
                      # against a one-collection corpus silently becomes wrong
                      # when the corpus grows.
                      "muslim:4276", "muslim:4275"],
     "expect": "pass",
     "note": "Oaths. Reachable from both collections."},
    {"query": "who is most deserving of my good companionship",
     "expected_ids": ["bukhari:5971"], "expect": "pass",
     "note": "Uses the SOURCE's wording. Ranks #1. Paired deliberately with "
             "the everyday-vocabulary case below."},

    # ---- everyday vocabulary: the app's actual use case ----
    {"query": "how should I treat my parents",
     "expected_ids": ["bukhari:5971"], "expect": "known_failure",
     "note": "THE central open problem. Same target as the case above, which "
             "ranks #1; this phrasing ranks #2356. The hadith never says "
             "'parents' -- it says 'mother' and 'father', and asks about "
             "'companionship'. Plain-language questions do not share "
             "vocabulary with 7th-century scripture in formal translation. "
             "Needs query expansion / HyDE, not threshold tuning."},
    {"query": "ruling on waking up early",
     "expected_ids": [], "expect": "known_failure",
     "note": "Returns confident but unrelated results (Tayammum, Times of "
             "Prayer). No clear ground truth identified yet; recorded so the "
             "behaviour is tracked rather than forgotten."},

    # ---- out-of-domain: MUST be rejected ----
    {"query": "chocolate cake recipe", "expected_ids": [], "expect": "pass",
     "reject": True, "note": "Correctly rejected."},
    {"query": "how do I fix a flat tyre on my car", "expected_ids": [],
     "expect": "pass", "reject": True,
     "note": "FIXED. Was falsely confident: tfidf ~0.19-0.42 cleared the old "
             "0.1 OR-branch that had been tuned on 20 documents. Removing "
             "TF-IDF from the gate entirely resolved it -- TF-IDF's in-domain "
             "and out-of-domain ranges now overlap almost completely."},
    {"query": "what is the capital of France", "expected_ids": [],
     "expect": "pass", "reject": True},
    {"query": "best python web framework", "expected_ids": [],
     "expect": "pass", "reject": True},
]


def load_corpus():
    with open(CORPUS_PATH) as f:
        return json.load(f)


def evaluate(store, eval_set=EVAL_SET, k=3):
    from generate_answer import confident_candidates

    results = []
    for case in eval_set:
        retrieved = store.retrieve(case["query"], k=k)
        top_ids = [h["id"] for h, *_ in retrieved]
        # Judge each candidate on its own confidence, mirroring what the
        # app actually shows the user, rather than gating on rank 1.
        confident = confident_candidates(store, retrieved)
        confident_ids = [h["id"] for h, *_ in confident]

        if case.get("reject"):
            passed = not confident
            detail = "rejected" if passed else f"ACCEPTED {confident_ids[0]}"
        else:
            hit = any(i in case["expected_ids"] for i in confident_ids)
            passed = bool(confident) and hit
            if hit:
                detail = f"hit ({len(confident_ids)}/{len(top_ids)} confident)"
            elif any(i in case["expected_ids"] for i in top_ids):
                detail = "retrieved but NOT confident"
            else:
                detail = f"miss (got {top_ids[0] if top_ids else '-'})"

        results.append({
            "query": case["query"], "expect": case["expect"],
            "passed": passed, "detail": detail, "top_ids": top_ids,
            "note": case.get("note", ""),
        })
    return results


def summarise(results):
    firm = [r for r in results if r["expect"] == "pass"]
    known = [r for r in results if r["expect"] == "known_failure"]
    return {
        "regressions": [r for r in firm if not r["passed"]],
        "firm_passed": sum(r["passed"] for r in firm),
        "firm_total": len(firm),
        "known_failures_still_failing": sum(not r["passed"] for r in known),
        "known_failures_now_passing": [r for r in known if r["passed"]],
        "known_total": len(known),
    }


if __name__ == "__main__":
    from reranked_retrieve import RerankedStore

    corpus = load_corpus()
    print(f"Corpus: {len(corpus)} hadith")
    store = RerankedStore(corpus)
    results = evaluate(store)

    print("\n" + "=" * 96)
    for r in results:
        tag = "PASS" if r["passed"] else ("fail" if r["expect"] == "known_failure" else "FAIL")
        marker = "" if r["expect"] == "pass" else "  (known)"
        print(f"[{tag}] {r['query'][:52]:52s} {r['detail']}{marker}")
    print("=" * 96)

    s = summarise(results)
    print(f"\nFirm cases:     {s['firm_passed']}/{s['firm_total']} passing")
    print(f"Known failures: {s['known_failures_still_failing']}/{s['known_total']} still failing (expected)")
    if s["regressions"]:
        print(f"\n!! {len(s['regressions'])} REGRESSION(S):")
        for r in s["regressions"]:
            print(f"   {r['query']!r}: {r['detail']}")
    if s["known_failures_now_passing"]:
        print(f"\n** {len(s['known_failures_now_passing'])} known failure(s) NOW PASSING "
              f"-- verify and promote to 'pass':")
        for r in s["known_failures_now_passing"]:
            print(f"   {r['query']!r}")
