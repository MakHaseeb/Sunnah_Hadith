"""
Permanent regression guard for the stub filter.

WHY THIS FILE EXISTS
--------------------
Bug #25 records that this filter took five iterations, and that every
failure was found by reading output rather than by any metric. It also
mentions "a 26-record regression guard" -- which was ad hoc, lived only in
that session, and was gone by the time the filter regressed again. Chain
notes were later found sitting in the live index and at the top of the
topic browser.

So the guard is a file now. Every record below was read individually before
being listed, and each one is a case the filter has actually got wrong at
some point or could plausibly get wrong next.

THE RULE THE CASES ENCODE
-------------------------
A stub is a record that *starts* as a chain note and never delivers
content. A real hadith either states its content first and mentions the
chain afterwards, or introduces the content with a colon. The wording alone
cannot separate them -- `muslim:438` and `muslim:230` both read "...
narrated/reported it ..." and only one is a stub.

Run: python3 test_stub_filter.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stub_filter import is_stub          # noqa: E402

# Content-free bookkeeping. Must NOT reach the index.
MUST_DROP = {
    "muslim:438":  "Abu Bakr b. Abi Shaiba narrated it on the same authorities",
    "muslim:855":  "Abu Mu'awiya narrated it on the authority of A'mash with the same chain of transmitters",
    "muslim:205":  "Imam Muslim has reported this hadith by Hasan b. 'Ali al-Halwani and other traditions",
    "muslim:243":  "A hadith like this as narrated by Ibn 'Umar has also been transmitted by Abu Sa'id al-Khudri",
    "muslim:846":  "A hadith like this has been transmitted by Hisham",
    "bukhari:4204": "narration about the chain of narrators",
}

# Real hadith. Must reach the index. Several are deliberately the near
# misses: same vocabulary as the stubs above, but carrying a ruling.
MUST_KEEP = {
    # Content first, chain note appended in parentheses. The word
    # "narrated" appears, but after a complete statement.
    "bukhari:1219": "It was forbidden to keep the hands on the hips during the prayer. (This is narrated by Abu Huraira from the Prophet)",
    "bukhari:5594": "the Prophet (صلى الله عليه وسلم) forbade the use of Ad-Dubba' and Al Muzaffat. A'mash also narrated this",
    # "reported it" -- identical opening to muslim:438 -- but a colon
    # introduces the actual ruling. This pair is the whole point.
    "muslim:230":   "Jarir b. Abdullah reported it from the Holy Prophet:When the slave runs away from his master, his prayer is not accepted",
    "muslim:281":   "Iyas b. Salama narrated from his father that the Apostle (ص) observed:He who draws the sword against us is not of us",
    # Short but complete rulings -- the 12-word-minimum mistake from
    # iteration (1) of bug #25.
    "_short_1":     "The Prophet performed ablution by washing the body parts twice",
    "_short_2":     "The Prophet (ص) forbade that a man should drink while standing",
    # Opens by naming a person, like a stub, but tells a story.
    "_named_1":     "Fatima came to Allah's Apostle and asked for a servant",
}


def main():
    bad = []
    for key, text in MUST_DROP.items():
        if not is_stub({"text": text}):
            bad.append(("SHOULD BE DROPPED, was kept", key, text))
    for key, text in MUST_KEEP.items():
        if is_stub({"text": text}):
            bad.append(("SHOULD BE KEPT, was dropped", key, text))

    print(f"  {len(MUST_DROP)} must-drop, {len(MUST_KEEP)} must-keep")
    if not bad:
        print("  all pass")
        return 0
    print(f"\n  {len(bad)} FAILURE(S):")
    for what, key, text in bad:
        print(f"    [{what}] {key}")
        print(f"       {text[:96]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
