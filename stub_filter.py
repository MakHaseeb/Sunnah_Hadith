"""
Exclude content-free records from the search index.

THE PROBLEM
-----------
Sahih Muslim numbers ~1,366 records (9.1% of the corpus) whose entire
text is a note that the PREVIOUS hadith also came via another chain --
"This hadith has been narrated through other chains of transmitters but
with a slight variation of wording." They are legitimate entries in the
collection, but they contain no ruling, no narrative, nothing a question
could be answered from.

They were harmless while retrieval matched on the hadith's own wording:
a stub has almost no wording to match. doc2query changed that. Given a
content-free stub, the model inferred the topic from surrounding context
and wrote six well-phrased everyday questions for it -- "how do you greet
another muslim", "what's the right way to perform wudu". Good questions,
attached to a record that cannot answer them.

The measured effect of leaving them in: out-of-domain rejection fell from
6/6 to 4/6, confident answers rose to 25/25 with no accuracy gain, and
stubs took the top slot for most common questions at 0.94-1.00 similarity
(a near-verbatim question match beats any real hadith's scripture wording).

THE FIX
-------
Keep them in the corpus -- they are part of the collection and dropping
them would misrepresent it -- but exclude them from the retrieval INDEX,
since a record with no content can never be a correct answer. Also skip
generating questions for them in future doc2query runs.
"""
import re

# Anchored at the start: a record that OPENS by describing its own chain
# of transmission and never gets to content. Deliberately conservative --
# a hadith that merely MENTIONS a chain partway through is real content
# and must not be caught.
# Openings that are CONCLUSIVE on their own: a record beginning "This
# hadith...", "The same hadith...", "The above hadith..." is referring to
# another record, full stop. No corroborating "chain"/"authority" needed
# -- requiring one let "The same hadith has been narrated by Zuhair b.
# Harb, Waki, Ishaq b. Mansur" through, because it merely LISTS narrators.
# A real hadith never opens by naming itself.
_STUB_OPENING = re.compile(
    r"^(this|that|the same|the above|the aforesaid|a similar) (hadith|hadeeth|tradition)\b",
    re.I,
)

_STUB = re.compile(
    r"^(this hadith|a hadith|the hadith|the same hadith|the above hadith|this (is|has been)"
    r"|it (has been|is) (narrated|reported|transmitted))[\s\S]{0,140}?"
    r"(chain|authority|transmitter|isnad|same as|like the (one|above))",
    re.I,
)

# The same kind of record, but opening with the NARRATOR'S NAME instead of
# "This hadith": "Muhammad b. Abu Rafi' narrated the hadith on the authority
# of...", "Hisham narrated the hadith like one transmitted by Ibn Numair",
# "Abu Huraira reported this hadith through another chain of transmitters".
# These were missed by the anchored pattern above and were still winning
# retrieval for six of the 25 common questions after the first fix -- found
# by reading the actual answers rather than trusting the metric.
#
# The distinguishing feature is the phrase "the hadith"/"this hadith"/"a
# hadith" used as an OBJECT (narrated *the hadith*), which a real hadith
# never does: a real one narrates content, not a reference to another
# record.
#
# NOTE on [\s\S] rather than [^.]: these translations abbreviate the
# patronymic as "b." (ibn) -- "Humaid b. Hilal", "Muhammad b. Abu Rafi'".
# A no-period character class breaks on the first such name and lets the
# record through, which is how three stubs survived the second fix.
_STUB_NAMED = re.compile(
    r"^[\s\S]{0,90}?\b(narrated|reported|transmitted|related)\b[\s\S]{0,40}?"
    r"\b(a|the|this) (hadith|hadeeth)\b[\s\S]{0,130}?"
    r"(chain|authority|transmitter|isnad|like (the |this )?\(?(above|one)|like this|another|same)",
    re.I,
)

# Cross-reference records: the text points at ANOTHER hadith instead of
# saying anything ("As above", "The Prophet said as above", "The above
# mentioned Statement of `Ali"). These carry no answer either.
_CROSSREF = re.compile(
    r"^(as (above|below|in)\b"
    r"|the above[- ]mentioned\b"
    r"|same as\b"
    r"|(the )?(prophet|messenger)[^.]{0,40}\b(said|narrated) as above\b"
    r"|similar (to|as)\b)",
    re.I,
)

# Only a floor for genuinely empty records. Deliberately LOW: a first pass
# used 12 words and threw away real short hadith -- "The Prophet performed
# ablution by washing the body parts twice" (11 words) is a complete
# ruling, not a stub. Length does not distinguish a stub from a terse
# hadith; the cross-reference WORDING does.
MIN_CONTENT_WORDS = 4


def is_stub(record):
    text = " ".join(str(record.get("text", "")).split())
    if len(text.split()) < MIN_CONTENT_WORDS:
        return True
    return bool(_STUB_OPENING.match(text) or _STUB.match(text)
                or _STUB_NAMED.match(text) or _CROSSREF.match(text))


def split_indexable(corpus):
    """Return (indexable, excluded)."""
    indexable, excluded = [], []
    for r in corpus:
        (excluded if is_stub(r) else indexable).append(r)
    return indexable, excluded


if __name__ == "__main__":
    import json, os, collections
    corpus = json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "corpus.json")))
    keep, drop = split_indexable(corpus)
    print(f"  indexable: {len(keep):,}   excluded: {len(drop):,} "
          f"({len(drop)/len(corpus):.1%})")
    print(f"  excluded by collection: "
          f"{dict(collections.Counter(r['collection'] for r in drop))}")
    print("\n  examples of what is excluded:")
    for r in drop[:6]:
        print(f"   {r['id']:14s} {' '.join(r['text'].split())[:92]}")
    print("\n  spot-check: 6 KEPT records (must all be real content):")
    for r in keep[:3] + keep[len(keep)//2:len(keep)//2+3]:
        print(f"   {r['id']:14s} {' '.join(r['text'].split())[:92]}")
