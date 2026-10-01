"""
Compare relevance-check providers on the same questions, same shortlist.

WHY THIS IS NOT OPTIONAL BEFORE SWITCHING
-----------------------------------------
The relevance check is the single change that took this app from roughly
25% correct to roughly 80% (bugs #15, #24). Everything else -- chunking,
doc2query, the confidence gate -- improved retrieval without fixing the
thing that actually blocked release: telling a RIGHT hadith from a WRONG
one on the same topic. Swapping the model behind that on price alone would
be betting the app's only working quality mechanism on an assumption.

So: run both over identical inputs and compare the verdicts directly. The
retrieval is deterministic and shared, so any difference in output is the
model's judgement and nothing else.

WHAT TO LOOK AT
---------------
Agreement is the headline, but read the DISAGREEMENTS -- they are the
whole point. A cheaper model that keeps more hadith is not being generous,
it is being less strict, and for this app a loose "yes" is the expensive
kind of wrong: the reader is shown scripture that does not address their
question, with a citation that makes it look authoritative.

    python3 compare_providers.py                 # anthropic vs groq
    python3 compare_providers.py --only groq     # one provider alone
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Ordinary questions, not the ones the thresholds were tuned on. A few are
# deliberately out-of-domain: a provider that keeps hadith for those is
# worse than one that costs more.
QUESTIONS = [
    "how should I treat my parents",
    "what to say when entering the toilet",
    "is it okay to be angry",
    "what are the rights of a Muslim on another Muslim",
    "how should a husband treat his wife",
    "is backbiting a sin",
    "what should I say before eating",
    "how to deal with a difficult neighbour",
    "what is the reward for attending a funeral",
    "actions are judged by intentions",
    "best python web framework",          # out of domain
    "what is the capital of France",      # out of domain
]

# Per-million token prices, for the cost column only.
PRICES = {
    "anthropic": (1.00, 5.00),            # claude-haiku-4-5
    "groq": (0.59, 0.79),                 # llama-3.3-70b-versatile
}


def run(provider, store, k):
    import relevance_check as rc
    client = rc.make_client(provider)
    rows, tin, tout, failed = [], 0, 0, 0
    t0 = time.time()
    for q in QUESTIONS:
        retrieved = store.retrieve(q, k=k)
        try:
            keep, verdicts, usage = rc.filter_relevant(q, retrieved, client=client, k=k)
        except rc.Unavailable as e:
            failed += 1
            rows.append({"q": q, "kept": None, "ids": [], "error": str(e)[:90]})
            continue
        if usage:
            tin += getattr(usage, "input_tokens", 0)
            tout += getattr(usage, "output_tokens", 0)
        rows.append({"q": q, "kept": len(keep),
                     "ids": [h[0]["id"] for h in keep][:3], "error": None})
    pin, pout = PRICES.get(provider, (0, 0))
    return {
        "provider": provider, "model": getattr(client, "model", "?"),
        "rows": rows, "in": tin, "out": tout, "failed": failed,
        "seconds": time.time() - t0,
        "cost": tin / 1e6 * pin + tout / 1e6 * pout,
    }


def report(results):
    for r in results:
        n = len(QUESTIONS)
        print(f"\n=== {r['provider']} ({r['model']}) ===")
        print(f"  {r['seconds']:.0f}s for {n} questions"
              f" | {r['in']:,} in / {r['out']:,} out"
              f" | ${r['cost']:.4f} total, ${r['cost']/n:.5f} per search")
        if r["failed"]:
            print(f"  !! {r['failed']} call(s) failed")
        for row in r["rows"]:
            if row["error"]:
                print(f"    {row['q'][:42]:44s} ERROR {row['error']}")
            else:
                print(f"    {row['q'][:42]:44s} kept {row['kept']}  {', '.join(row['ids'])}")

    if len(results) < 2:
        return
    a, b = results[0], results[1]
    print(f"\n=== {a['provider']} vs {b['provider']} ===")
    same_top = agree_count = 0
    for ra, rb in zip(a["rows"], b["rows"]):
        if ra["error"] or rb["error"]:
            continue
        if ra["kept"] == rb["kept"]:
            agree_count += 1
        if ra["ids"][:1] == rb["ids"][:1]:
            same_top += 1
    n = len(QUESTIONS)
    print(f"  same top result : {same_top}/{n}")
    print(f"  same keep count : {agree_count}/{n}")
    print(f"  cost ratio      : {a['cost']/b['cost']:.1f}x" if b["cost"] else "")
    print("\n  disagreements -- READ THESE, they are the decision:")
    for ra, rb in zip(a["rows"], b["rows"]):
        if ra["error"] or rb["error"] or ra["ids"][:1] == rb["ids"][:1]:
            continue
        print(f"    {ra['q']}")
        print(f"      {a['provider']:10s} kept {ra['kept']}: {', '.join(ra['ids']) or '(nothing)'}")
        print(f"      {b['provider']:10s} kept {rb['kept']}: {', '.join(rb['ids']) or '(nothing)'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run just one provider (anthropic|groq)")
    ap.add_argument("-k", type=int, default=10, help="shortlist size")
    a = ap.parse_args()

    from hybrid_retrieve import HybridStore
    from expansion import load_expansions
    corpus = json.load(open(os.path.join(HERE, "data", "corpus.json")))
    store = HybridStore(corpus, expansions=load_expansions())

    providers = [a.only] if a.only else ["anthropic", "groq"]
    results = []
    for p in providers:
        try:
            results.append(run(p, store, a.k))
        except SystemExit as e:
            print(f"\n=== {p} === skipped: {e}")
    report(results)


if __name__ == "__main__":
    main()
