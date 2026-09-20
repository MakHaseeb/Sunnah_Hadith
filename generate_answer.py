"""
Retrieval + generation on top of RerankedStore. Confidence is decided by
the hybrid retriever's own validated thresholds, not the cross-encoder's
raw score (see reranker.py for why).
"""
from citations import format_citation

# The citation instruction must describe the format the model is ACTUALLY
# shown. It previously said "cite the Volume, Book, and Number", which
# stopped matching once citations moved to canonical numbering -- asking a
# model to produce a format it cannot see is a direct invitation to invent
# one. It is now told to copy the bracketed citation verbatim, which is a
# copying task rather than a construction task.
SYSTEM_INSTRUCTIONS = (
    "You are answering a question using ONLY the hadith text provided below. "
    "Do not use any outside knowledge, and do not add rulings, context, or "
    "interpretation that is not present in the provided text.\n\n"
    "Every hadith below is preceded by its citation in square brackets. "
    "After each claim you make, copy the relevant citation VERBATIM, exactly "
    "as it appears in the brackets. Never invent, abbreviate, or renumber a "
    "citation.\n\n"
    "If the provided hadith do not clearly answer the question, say so "
    "plainly instead of guessing. Answering 'the provided hadith do not "
    "clearly address this' is always preferable to an unsupported answer."
)


def build_prompt(query, retrieved):
    # Items are (hadith, chunk_text, rrf, tfidf, neural) and carry a sixth
    # cross-encoder score ONLY when the reranker is enabled. Index rather
    # than unpack a fixed arity -- fixed unpacking broke the moment the
    # reranker was turned off by default, and the eval harness missed it
    # because it unpacks as `h, *_`.
    context_blocks = []
    for item in retrieved:
        hadith = item[0]
        # The citation is placed INSIDE the context block, so the model is
        # copying a citation that sits next to the text it is quoting
        # rather than reconstructing one from separate fields -- fewer
        # moving parts is fewer ways to mis-cite.
        narrator = hadith.get("narrator")
        attribution = f"Narrated {narrator}: " if narrator else ""
        context_blocks.append(
            f"[{format_citation(hadith)}] {attribution}{hadith['text']}"
        )
    context = "\n\n".join(context_blocks)
    user_prompt = f"Question: {query}\n\nRetrieved hadith:\n{context}"
    return SYSTEM_INSTRUCTIONS, user_prompt


def confident_candidates(store, retrieved):
    """
    Keep only the candidates that clear the confidence gate.

    WHY NOT JUST CHECK retrieved[0]
    -------------------------------
    The old code gated on the single top-ranked result. That quietly
    assumed rank 1 is always the strongest evidence, which is false here
    for two independent reasons:

      * Fusion (RRF) ranks by AGREEMENT between two retrievers, not by
        absolute similarity, so a candidate both retrievers like a little
        can outrank one that a single retriever likes a lot.
      * The cross-encoder reorders the shortlist, and its scores are not
        trustworthy on this domain (bug #6).

    Measured consequence: for "actions are judged by intentions" the
    correct hadith (bukhari:1) sat at position 3 with neural 0.459 --
    comfortably above the 0.44 gate -- while position 1 scored 0.376. The
    whole query was declared low-confidence and the right answer thrown
    away.

    Judging each candidate on its own merits also matches the product
    decision to show 2-3 ranked candidates WITH their confidence, rather
    than forcing one authoritative answer.
    """
    return [item for item in retrieved if store.is_confident(item[3], item[4])]


def generate_answer(query, store, llm_call, k=3):
    retrieved = store.retrieve(query, k=k)
    if not retrieved:
        return {"answer": "No hadith loaded to search.", "citations": [],
                "ids": [], "llm_called": False}

    confident = confident_candidates(store, retrieved)

    if not confident:
        return {
            "answer": "I couldn't find a hadith in this collection that clearly answers that question.",
            "citations": [],
            "ids": [],
            "llm_called": False,
        }

    # Only confident hadith reach the prompt. Passing marginal ones as
    # context invites the model to cite them, which would defeat the
    # confidence gate entirely -- the gate has to bind what the model can
    # SEE, not just what we print afterwards.
    system_prompt, user_prompt = build_prompt(query, confident)
    llm_response = llm_call(system_prompt, user_prompt)

    citations = [format_citation(item[0]) for item in confident]
    ids = [item[0]["id"] for item in confident]
    return {
        "answer": llm_response,
        "citations": citations,
        "ids": ids,
        "llm_called": True,
    }


if __name__ == "__main__":
    import json
    from reranked_retrieve import RerankedStore

    with open("data/bukhari_verified.json") as f:
        hadiths = json.load(f)
    store = RerankedStore(hadiths)

    def fake_llm_call(system_prompt, user_prompt):
        return "Actions are judged by the intentions behind them, per the hadith cited."

    print(json.dumps(generate_answer("actions are judged by intentions", store, fake_llm_call), indent=2))
    print(json.dumps(generate_answer("Nawafil prayers", store, fake_llm_call), indent=2))
