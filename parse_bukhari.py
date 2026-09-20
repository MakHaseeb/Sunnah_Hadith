import re
import json
import os
import subprocess

# Auto-locate files relative to THIS script's folder, not the current
# working directory -- so it works no matter where you run it from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PDF = os.path.join(SCRIPT_DIR, "Sahih_Bukhari.pdf")


def extract_pages(start, end):
    if not os.path.exists(PDF):
        raise FileNotFoundError(
            f"Couldn't find the PDF at: {PDF}\n"
            f"Put 'Sahih_Bukhari.pdf' in the same folder as this script, "
            f"or edit the PDF variable at the top of parse_bukhari.py."
        )
    result = subprocess.run(
        ["pdftotext", "-f", str(start), "-l", str(end), PDF, "-"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pdftotext failed (is poppler installed? try: brew install poppler)\n"
            f"stderr: {result.stderr}"
        )
    if not result.stdout.strip():
        raise RuntimeError(
            "pdftotext ran but returned no text -- the PDF may be a different "
            "file than expected, corrupted, or the page range is out of bounds."
        )
    return result.stdout


def clean_and_split(raw_text):
    text = raw_text

    # The page footer ("Volume 1 - 8 / 1700") gets glued directly onto body
    # text with NO space when a word is split across a page break (e.g.
    # "...through GabVolume 1 - 8 / 1700\n\n\x0cSAHIH BUKHARI\n\nVOLUME 1 >
    # BOOK 1: R...riel) then..." -- the real word is "Gabriel"). Removed as
    # ONE unit so "Gab" and "riel" rejoin correctly.
    page_break_block = re.compile(
        r"Volume \d+ - \d+ / \d+\s*\x0c\s*SAHIH BUKHARI\s*\n*VOLUME \d+ > BOOK \d+:[^\n]*\n*"
    )
    text = page_break_block.sub("", text)

    # Catch any remaining standalone header/footer lines not caught above
    leftover_patterns = [
        r"^SAHIH BUKHARI\s*$",
        r"^VOLUME \d+ > BOOK \d+:.*$",
        r"^Volume \d+ - \d+ / \d+\s*$",
        r"^Book \d+: .*$",
    ]
    lines = text.replace("\f", "\n").split("\n")
    cleaned_lines = [ln for ln in lines if not any(re.match(p, ln.strip()) for p in leftover_patterns)]
    cleaned = "\n".join(cleaned_lines)

    # Number carries an OPTIONAL letter suffix: the source numbers two
    # narrations of the same report as e.g. "790a" / "790b". A strict
    # r"Number (\d+):" regex silently dropped all 70 of these across the
    # full corpus -- they showed up as holes in otherwise contiguous
    # per-book numbering, which is how they were found.
    marker = re.compile(r"Volume (\d+), Book (\d+), Number (\d+)([a-z]?):")
    parts = marker.split(cleaned)

    hadiths = []
    for i in range(1, len(parts), 5):
        volume, book, number, suffix, body = parts[i], parts[i+1], parts[i+2], parts[i+3], parts[i+4]
        body = body.strip()
        narrator_match = re.match(r"Narrated ([^:\n]+):", body)
        narrator = narrator_match.group(1).strip() if narrator_match else None
        text_body = body[narrator_match.end():].strip() if narrator_match else body
        hadiths.append({
            "volume": int(volume),
            "book": int(book),
            "number": int(number),
            # "" for the normal case, "a"/"b"/... for sub-narrations. Kept
            # separate from `number` so numeric sorting still works.
            "number_suffix": suffix,
            "narrator": narrator,
            "text": text_body
        })
    return hadiths


if __name__ == "__main__":
    raw = extract_pages(7, 12)
    hadiths = clean_and_split(raw)
    print(f"Parsed {len(hadiths)} hadith chunks\n")
    for h in hadiths:
        print(f"--- Vol {h['volume']}, Book {h['book']}, Number {h['number']} ---")
        print(f"Narrator: {h['narrator']}")
        print(f"Text ({len(h['text'])} chars): {h['text'][:150]}...")
        print()
    with open(os.path.join(SCRIPT_DIR, "sample_hadiths.json"), "w") as f:
        json.dump(hadiths, f, indent=2, ensure_ascii=False)
