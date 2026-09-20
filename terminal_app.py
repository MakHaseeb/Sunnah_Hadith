"""
Ask a question, see the hadith that answer it.

How it works, in order:
  1. Search finds the 5 closest hadith (free, runs on this machine).
  2. A small AI model reads those 5 and says which actually ANSWER the
     question, rather than merely resembling it (~$0.0014 per question).
  3. Only the ones that pass are shown, with their citation.

Step 2 exists because word-similarity alone could not tell a right hadith
from a wrong one -- on "actions are judged by intentions" the correct
hadith scored LOWER than the query "recipe for chicken biryani". No
threshold could separate those; asking the question directly can.

Run with --no-check to skip step 2 and see what search alone returns.
"""
import argparse
import json
import os
import sys

from citations import format_citation, verification_note
from expansion import load_expansions
from hybrid_retrieve import HybridStore

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(SCRIPT_DIR, "data", "corpus.json")
SHORTLIST = 10   # wider net: the AI check discards the bad ones, and a
                 # correct answer at rank 8 was being lost to a top-5 cut
MAX_SHOWN = 3        # the product decision: 2-3 candidates, not one forced answer
PREVIEW_WORDS = 110  # long narrations get trimmed; the citation lets you read the rest


def load_corpus():
    if not os.path.exists(CORPUS_PATH):
        raise SystemExit(
            f"Corpus not found at {CORPUS_PATH}\n"
            f"Build it with:  python3 align_sources.py && python3 build_corpus.py")
    with open(CORPUS_PATH) as f:
        return json.load(f)


def focus_score(item):
    """
    Rank the hadith that passed the relevance check, shortest first.

    A long narration that wanders through several subjects is a worse
    ANSWER than a short one that states the ruling, even when both are
    genuinely relevant. Sorting by length is a blunt proxy for "how
    directly does this address the question", but it is the right
    direction: the 400-word narration about Sa'd that drifts into spoils
    of war and wine outranked three short hadith that answer "how should
    I treat my parents" in one line each.
    """
    return len(item[0]["text"].split())


def show(hadith, score, verdict=None, rank=1):
    print(f"\n  {rank}. {format_citation(hadith)}")
    if verdict and verdict.get("why"):
        print(f"     why this one: {verdict['why']}")
    narrator = hadith.get("narrator")
    if narrator:
        print(f"     Narrated {narrator}:")
    words = " ".join(hadith["text"].split()).split()
    truncated = len(words) > PREVIEW_WORDS
    text = " ".join(words[:PREVIEW_WORDS]) + (" ..." if truncated else "")
    # wrap at ~96 chars for readability
    line, out = "", []
    for word in text.split():
        if len(line) + len(word) + 1 > 96:
            out.append(line); line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    for l in out:
        print(f"     {l}")
    if truncated:
        print(f"     ... ({len(words)} words in total — see the citation above "
              f"for the full text)")
    print(f"     [{verification_note(hadith)}, match {score:.2f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-check", action="store_true",
                    help="skip the AI relevance check (free, but much less accurate)")
    args = ap.parse_args()

    corpus = load_corpus()
    expansions = load_expansions()
    store = HybridStore(corpus, expansions=expansions)

    client = None
    if not args.no_check:
        from relevance_check import make_client
        client = make_client()

    verified = sum(1 for h in corpus
                   if (h.get("verification") or {}).get("verified_against_pdf"))
    print(f"\nSearching {len(store.hadiths):,} hadith from Sahih al-Bukhari and Sahih Muslim.")
    print(f"  {verified:,} have been cross-checked against a second source.")
    print(f"  Relevance check: {'OFF (search only)' if args.no_check else 'ON'}")
    print("\nType a question, or 'quit' to stop.\n")

    spent = {"in": 0, "out": 0}
    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if query.lower() in ("quit", "exit"):
            break
        if not query:
            continue

        retrieved = store.retrieve(query, k=SHORTLIST)
        if not retrieved:
            print("\n  Nothing found.\n")
            continue

        if args.no_check:
            kept = [(item, None) for item in retrieved[:3]]
        else:
            from relevance_check import filter_relevant
            # Pass SHORTLIST explicitly: filter_relevant defaults to its own
            # smaller cap, which silently re-trimmed the wider net and
            # dropped a correct answer sitting at rank 8.
            keep, verdicts, usage = filter_relevant(
                query, retrieved, client=client, k=SHORTLIST)
            if usage:
                spent["in"] += usage.input_tokens
                spent["out"] += usage.output_tokens
            keep_ids = {id(k) for k in keep}
            kept = [(item, v) for item, v in zip(retrieved, verdicts)
                    if id(item) in keep_ids]

        if not kept:
            print("\n  I couldn't find a hadith that clearly answers that.")
            print("  Try rephrasing it, or asking about something more specific.\n")
            continue

        kept.sort(key=lambda pair: focus_score(pair[0]))
        shown = kept[:MAX_SHOWN]
        more = len(kept) - len(shown)
        print(f"\n  Found {len(kept)} hadith that answer this"
              f"{f' (showing the {len(shown)} most direct)' if more else ''}:")
        for i, (item, verdict) in enumerate(shown, 1):
            show(item[0], item[4], verdict, rank=i)
        print()

    if spent["in"]:
        cost = spent["in"] / 1e6 * 1 + spent["out"] / 1e6 * 5
        print(f"This session used ${cost:.4f} of API credit.\n")


if __name__ == "__main__":
    main()
