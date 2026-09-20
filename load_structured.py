"""
Loader for the structured hadith source (fawazahmed0/hadith-api, served
from jsDelivr -- open, no API key; sunnah.com's own API returns 403
without one).

WHY THIS EXISTS alongside parse_bukhari.py
------------------------------------------
Auditing the islamhouse PDF across all 1,700 pages turned up a gap the
15-page test slice could never have shown: Book 83 ("Oaths and Vows",
84 hadith) is absent from the PDF entirely -- the string "Book 83" does
not occur anywhere in the extracted text. A missing topic fails in the
worst possible way for this app: the user asks about oaths, and a
confident "I couldn't find a hadith about that" is indistinguishable
from a genuine no-answer.

This source carries the full collection (7,563 canonical numbers) in the
same M. Muhsin Khan translation, so it becomes the PRIMARY corpus. The
PDF is kept as an INDEPENDENT second source to verify text integrity --
see align_sources.py.

A TRAP WORTH KNOWING ABOUT (cost me a wrong assumption)
-------------------------------------------------------
The two sources use DIFFERENT book-numbering schemes, and they overlap
in a way that looks compatible until you check. Both label books 1-93,
so a naive "are all 93 books present?" check passes. But this source
uses Bukhari's 97-book Arabic chapter division, while the PDF uses the
93-book USC-MSA division. Book 97 here ("Tawheed") is Book 93 in the
PDF. Only 3 of 93 books even agree on hadith count.

So the two sources CANNOT be aligned on (book, position). They are
aligned on text similarity instead -- see align_sources.py.

Text quirk: ~80% of records here end without terminal punctuation
(e.g. "...his emigration was for what he emigrated for" with no closing
'."'). Checked against the PDF: this is cosmetic punctuation stripping,
NOT truncated content -- word counts match. Left as-is rather than
"repaired", since inventing punctuation into scripture is worse than
omitting it.
"""
import json
import os
import re
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(SCRIPT_DIR, "data", "raw")

CDN = "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions"

COLLECTIONS = {
    "bukhari": "eng-bukhari",
    "muslim": "eng-muslim",
}


def download_edition(edition, force=False):
    """Fetch one edition's JSON, cached on disk. Network hit happens once."""
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, f"{edition}.json")
    if os.path.exists(path) and not force:
        return path
    url = f"{CDN}/{edition}.json"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = resp.read()
    except Exception as e:
        raise RuntimeError(f"Failed downloading {url}: {e}") from e
    # Validate BEFORE writing, so a truncated/HTML error response can never
    # masquerade as a cached good file on the next run.
    parsed = json.loads(data)
    if "hadiths" not in parsed or not parsed["hadiths"]:
        raise RuntimeError(f"{url} returned no hadiths -- unexpected schema.")
    with open(path, "wb") as f:
        f.write(data)
    return path


# Bukhari's translation opens "Narrated X:body". Sahih Muslim's uses a
# different convention -- "X reported:body", "X reported that ..." -- so a
# Bukhari-only pattern set extracted a narrator for just 9.6% of Muslim
# records. Splitting the attribution off matters for display and keeps the
# first sentence window focused on content rather than on a chain of
# transmitters.
#
# Deliberately NOT handled: Muslim's long isnad chains ("It has been
# narrated through a different chain of transmitters on the authority of
# ... that ..."), ~24% of records. Those name several transmitters, so
# there is no single "the narrator" to extract, and guessing one would
# misattribute a hadith -- worse than leaving it unset. Sentence-window
# chunking already isolates that preamble into its own chunk, so it does
# not blur the content chunks.
_PATTERNS = [
    re.compile(r"^\s*Narrated ([^:\n]{1,120}?)\s*:\s*"),
    re.compile(r"^\s*([A-Z][^:\n]{1,80}? said)\s*:\s*"),
    re.compile(r"^\s*([A-Z][^:\n]{1,80}?) reported\s*:\s*"),
    re.compile(r"^\s*([A-Z][^:\n]{1,80}?) reported that\s+"),
    re.compile(r"^\s*It is narrated on the authority of ([^:\n]{1,80}?)\s*(?:that\s+|:\s*)"),
]


def split_narrator(text):
    for pattern in _PATTERNS:
        m = pattern.match(text)
        if m:
            return m.group(1).strip(), text[m.end():].strip()
    return None, text.strip()


def load_collection(name="bukhari", force_download=False):
    """Return canonical records for one collection."""
    if name not in COLLECTIONS:
        raise ValueError(f"Unknown collection {name!r}; known: {list(COLLECTIONS)}")
    path = download_edition(COLLECTIONS[name], force=force_download)
    with open(path) as f:
        payload = json.load(f)

    sections = payload.get("metadata", {}).get("sections", {}) or {}
    records = []
    for h in payload["hadiths"]:
        text = str(h.get("text") or "").strip()
        if not text:
            continue  # 9 genuinely-empty records in Bukhari; nothing to embed
        narrator, body = split_narrator(text)
        ref = h.get("reference") or {}
        book_no = ref.get("book")
        records.append({
            "id": f"{name}:{h['hadithnumber']}",
            "collection": name,
            # Canonical continuous numbering (1-7563 for Bukhari). This is
            # the citation scheme sunnah.com and most modern references use.
            "hadith_number": h["hadithnumber"],
            "arabic_number": h.get("arabicnumber"),
            "book_number": book_no,
            "book_name": sections.get(str(book_no)) or None,
            "in_book_number": ref.get("hadith"),
            "narrator": narrator,
            "text": body,
            "grades": h.get("grades") or [],
            "source": "structured",
            # Filled in by align_sources.py once cross-checked against the PDF.
            "usc_reference": None,
            "verification": None,
        })
    return records


if __name__ == "__main__":
    recs = load_collection("bukhari")
    print(f"Loaded {len(recs)} Bukhari records")
    named = sum(1 for r in recs if r["book_name"])
    narr = sum(1 for r in recs if r["narrator"])
    print(f"  with book name: {named} ({named/len(recs):.1%})")
    print(f"  with narrator:  {narr} ({narr/len(recs):.1%})")
    b83 = [r for r in recs if r["book_number"] == 83]
    print(f"  Book 83 ({b83[0]['book_name']!r}): {len(b83)} hadith  <- absent from the PDF")
    print()
    r = recs[0]
    print(f"  sample id={r['id']} book={r['book_number']} ({r['book_name']})")
    print(f"    narrator={r['narrator']!r}")
    print(f"    text={r['text'][:120]}...")
