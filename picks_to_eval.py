"""
Turn real people's "this one answers it" clicks into evaluation cases.

WHY THIS STEP IS DELIBERATELY MANUAL
------------------------------------
The app does not learn from picks, and nothing here changes retrieval. This
script reads what people marked and prints candidate test cases for a human
to look at before any of them go into the harness. That ordering is the
whole safety argument: an app that quietly re-ranked scripture because of
taps would be unreviewable, and this project's standing rule is that a
scholar signs off on what users see.

WHAT THE PICKS ARE WORTH
------------------------
The evaluation harness has eleven cases, all written by the two people
building the thing -- a set CLAUDE.md already describes as "misleadingly
easy". Every pick is a labelled example produced by somebody who actually
wanted an answer: the question in their words, the candidates served, and
which one was right.

THE NUMBER THAT MATTERS MOST
----------------------------
Where the right answer LANDED. Bug #15 says the confidence score cannot tell
a right hadith from a wrong one on the same topic, and bug #17 says long
hadith crowd out short ones -- both were measured against questions we wrote
ourselves. Rank counts from real use say how often the answer was there all
along but shown second or third, which is a different and much cheaper
problem to fix than "retrieval missed it".

DISAGREEMENT IS DATA
--------------------
Two people can pick differently for the same question and neither be wrong:
several hadith may answer it. A question where everyone agrees is a strong
test case. One where they split is worth reading before trusting.
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, "data", "picks.jsonl")


def load(path=LOCAL, repo=None, token=None):
    if repo and token and not os.path.exists(path):
        try:
            from huggingface_hub import hf_hub_download
            path = hf_hub_download(repo_id=repo, repo_type="dataset",
                                   filename="picks.jsonl", token=token)
        except Exception as e:
            print(f"could not fetch picks from {repo}: {str(e)[:120]}")
            return []
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def report(rows):
    if not rows:
        print("No picks yet. Mark some answers in the app first.")
        return {}

    ranks = collections.Counter(r.get("rank") for r in rows)
    n = len(rows)
    print(f"\n{n} picks from {len({r.get('by') for r in rows})} people\n")
    print("  where the right answer actually was:")
    for rank in sorted(k for k in ranks if k):
        bar = "#" * int(40 * ranks[rank] / n)
        print(f"    position {rank}:  {ranks[rank]:4d}  {ranks[rank]/n:5.1%}  {bar}")
    first = ranks.get(1, 0) / n
    print(f"\n  right first time: {first:.1%}")
    if first < 0.8 and n >= 10:
        print("  -> the answer is often FOUND but shown too low. That is a"
              "\n     ranking problem, not a retrieval one -- cheaper to fix.")

    by_q = collections.defaultdict(list)
    for r in rows:
        by_q[(r.get("question") or "").strip().lower()].append(r)

    agreed, split = [], []
    for q, picks in by_q.items():
        chosen = collections.Counter(p.get("chosen") for p in picks)
        top, count = chosen.most_common(1)[0]
        (split if len(chosen) > 1 else agreed).append(
            {"question": picks[0].get("question"), "chosen": top,
             "votes": count, "of": len(picks), "alternatives": dict(chosen)})
    print(f"\n  {len(agreed)} questions everyone agreed on"
          f", {len(split)} where people differed")
    return {"agreed": agreed, "split": split}


def emit_cases(agreed, limit=None):
    if not agreed:
        return
    print("\n" + "=" * 70)
    print("Candidate harness cases -- READ THESE before pasting them in.")
    print("A pick means the reader found it useful, not that a scholar")
    print("agrees it is the best answer to the question.")
    print("=" * 70 + "\n")
    for c in agreed[:limit]:
        q = c["question"].replace('"', '\\"')
        print(f'    {{"query": "{q}",')
        print(f'     "expected_ids": ["{c["chosen"]}"],')
        print(f'     "expect": "pass",')
        print(f'     "note": "From {c["votes"]} reader pick(s) in the live app."}},')


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--repo", default=os.environ.get("HADITH_DATA_REPO", ""))
    ap.add_argument("--emit", action="store_true",
                    help="print candidate harness cases for the agreed questions")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    rows = load(repo=a.repo or None, token=os.environ.get("HF_TOKEN"))
    out = report(rows)
    if a.emit and out:
        emit_cases(out["agreed"], a.limit)
        if out["split"]:
            print("\n  Questions people disagreed on (read, do not auto-add):")
            for c in out["split"]:
                print(f"    {c['question']!r} -> {c['alternatives']}")


if __name__ == "__main__":
    main()
