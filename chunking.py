"""
Split hadith into sub-chunks before embedding.

HISTORY -- WHY THIS FILE EXISTS AT ALL
--------------------------------------
Originally: hadith #3 (885 tokens) blew past the embedding model's
optimal range and produced an ambiguous, "blurry" whole-hadith vector --
it scored a FALSE match higher than a genuine one. Fix at the time: cut
anything over 180 words into 180-word blocks, then let the retriever
collapse each hadith to its single best-scoring chunk.

WHY THAT FIX WAS NOT ENOUGH (found when scaling from 20 to 7,580 hadith)
------------------------------------------------------------------------
At full corpus scale the most famous hadith in the collection --
Bukhari 1, "the reward of deeds depends upon the intentions" -- fell to
NEURAL RANK 695 for the query "actions are judged by intentions".

It is ~50 words, so the 180-word rule never split it. But it contains
two semantically unrelated halves:

    (a) the ruling      "the reward of deeds depends upon the intentions"
    (b) a worked example "whoever emigrated for worldly benefits..."

Measured against the query "actions are judged by intentions":

    full passage as indexed .... 0.168
    ruling half alone .......... 0.489     <-- ~3x higher
    emigration half alone ...... 0.003     <-- drags the average down

One vector per passage is an AVERAGE of everything in it. A short
passage covering two topics is just as blurry as a long one -- length
was never the real variable, TOPIC MIXING was. A word-count threshold
cannot see that, which is why the 20-hadith prototype passed: with only
20 documents, TF-IDF's rare word "intentions" carried the query and hid
the weakness entirely.

THE FIX
-------
Chunk on SENTENCE boundaries into small overlapping windows, so each
window is topically tight, and let the retriever's existing
best-chunk-per-hadith step pick the window that actually matches. The
ruling and the example land in different windows, so the ruling can be
matched on its own terms.

Overlap matters: a hard split would sever a statement that straddles a
boundary. One sentence of overlap means every adjacent sentence pair
appears together in at least one window.
"""
import re

# Kept as the hard ceiling for a single window.
MAX_WORDS_PER_CHUNK = 180

# Target window size. Deliberately small: the failure above was a
# two-topic passage of only ~50 words, so windows need to be smaller than
# that to separate topics reliably.
TARGET_WORDS = 45
# Sentences of overlap between consecutive windows.
OVERLAP_SENTENCES = 1

# Sentence boundary: ., ! or ? (optionally followed by closing quotes or
# brackets) then whitespace then something that starts a new sentence.
# Guarded against the abbreviations that actually occur in this corpus --
# splitting "No. 673" or "i.e. Pilgrimage" mid-sentence would scatter a
# single statement across windows.
_ABBREV = r"(?<!\bNo)(?<!\bi\.e)(?<!\be\.g)(?<!\bvol)(?<!\bVol)(?<!\bpp)(?<!\bSt)(?<!\bMr)(?<!\bDr)"
_SENTENCE_END = re.compile(
    _ABBREV + r'(?<=[.!?])["\'”\)\]]*\s+(?=[A-Z"\'“\(])'
)


def split_sentences(text):
    text = " ".join(text.split())
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    return parts or [text]


def _windows(sentences, target_words, max_words, overlap):
    """Group sentences into overlapping windows of ~target_words."""
    if not sentences:
        return []
    out = []
    i = 0
    while i < len(sentences):
        current, count = [], 0
        j = i
        while j < len(sentences):
            w = len(sentences[j].split())
            # Always take at least one sentence, even an over-long one --
            # dropping content is never acceptable here.
            if current and count + w > target_words:
                break
            current.append(sentences[j])
            count += w
            j += 1
            if count >= target_words:
                break
        # A single sentence longer than the hard ceiling gets word-split,
        # falling back to the original strategy for that one case.
        if len(current) == 1 and count > max_words:
            words = current[0].split()
            for s in range(0, len(words), max_words):
                out.append(" ".join(words[s:s + max_words]))
        else:
            out.append(" ".join(current))
        if j >= len(sentences):
            break
        i = max(j - overlap, i + 1)
    return out


def chunk_hadiths(hadiths, target_words=TARGET_WORDS,
                  max_words=MAX_WORDS_PER_CHUNK, overlap=OVERLAP_SENTENCES):
    chunks = []
    for h in hadiths:
        sentences = split_sentences(h["text"])
        texts = _windows(sentences, target_words, max_words, overlap)
        if not texts:
            texts = [h["text"]]
        for idx, t in enumerate(texts):
            # chunk_type distinguishes authentic hadith text from
            # doc2query-generated questions, which share the index but must
            # never be displayed or cited as scripture (see expansion.py).
            chunks.append({**h, "chunk_index": idx, "chunk_text": t,
                           "chunk_type": "text"})
    return chunks


if __name__ == "__main__":
    import json
    hadiths = json.load(open("data/bukhari_verified.json"))
    h1 = [h for h in hadiths if h["id"] == "bukhari:1"][0]
    print("bukhari:1 windows:")
    for c in chunk_hadiths([h1]):
        print(f"  [{c['chunk_index']}] ({len(c['chunk_text'].split())}w) {c['chunk_text']}")
    all_chunks = chunk_hadiths(hadiths)
    print(f"\n{len(hadiths)} hadith -> {len(all_chunks)} chunks "
          f"(x{len(all_chunks)/len(hadiths):.2f})")
    lens = sorted(len(c["chunk_text"].split()) for c in all_chunks)
    print(f"chunk words: p50={lens[len(lens)//2]} p90={lens[int(len(lens)*.9)]} max={lens[-1]}")
