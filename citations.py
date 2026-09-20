"""
Citation formatting.

Two numbering schemes are in play and they disagree for the same hadith:

  * canonical / sunnah.com   -- one continuous run, 1..7563
  * USC-MSA (the Khan PDF)   -- Volume + Book + Number, restarting per volume,
                                over a DIFFERENT 93-book chapter division

"Oaths and Vows" is Book 83 canonically and Volume 8 / Book 78 in the PDF.
A reader who knows one scheme will not recognise the other, so where the
cross-check established both, BOTH are shown. Being able to point at a
hadith in whichever scheme a scholar or user already uses is worth the
extra few words on screen -- and the app's whole premise is that every
claim is checkable.
"""

COLLECTION_NAMES = {
    "bukhari": "Sahih al-Bukhari",
    "muslim": "Sahih Muslim",
}


def format_citation(record, include_usc=True):
    name = COLLECTION_NAMES.get(record.get("collection"), record.get("collection", "?"))
    parts = [f"{name} {record['hadith_number']}"]

    book_no = record.get("book_number")
    book_name = record.get("book_name")
    if book_no is not None and book_name:
        parts.append(f"Book {book_no}: {book_name}")
    elif book_no is not None:
        parts.append(f"Book {book_no}")

    citation = " — ".join(parts)

    usc = record.get("usc_reference")
    if include_usc and usc:
        citation += (
            f" [USC-MSA Vol {usc['volume']}, Book {usc['book']}, "
            f"No {usc['number']}{usc.get('number_suffix', '')}]"
        )
    return citation


def verification_note(record):
    """Human-readable provenance line. Absence of a PDF match is NOT a
    defect -- the PDF only covers ~94% of the corpus -- so it is phrased
    as 'single source', not as a failure."""
    v = record.get("verification") or {}
    if v.get("verified_against_pdf"):
        return f"cross-checked against the Khan PDF (similarity {v['similarity']:.3f})"
    return "single source (no PDF counterpart)"


if __name__ == "__main__":
    import json
    recs = json.load(open("data/bukhari_verified.json"))
    for r in (recs[0], next(x for x in recs if x["book_number"] == 83),
              next(x for x in recs if not x["verification"]["verified_against_pdf"])):
        print(format_citation(r))
        print(f"    {verification_note(r)}")
