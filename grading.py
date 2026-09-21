"""
Authenticity grading, for the collections that carry it.

WHY THIS MATTERS MORE THAN ANYTHING ELSE IN THIS PROJECT
--------------------------------------------------------
Sahih al-Bukhari and Sahih Muslim are, by their compilers' own criteria,
collections of authenticated hadith. The four Sunan are not: they gather
material and record what scholars judged of it. Abu Dawud carries 3,482
reports graded *daif* (weak) and Tirmidhi 2,148.

A weak hadith is not a forgery, but most scholars hold it cannot be relied
on to establish a ruling. Showing one to somebody asking "what should I
do?" -- in the same frame, same styling, same confidence as a sahih hadith
from Bukhari -- would misrepresent the sources this app exists to serve
faithfully. That is a worse failure than returning no answer.

So: hadith graded weak are excluded from the searchable index, and every
result carries its grading where one exists.

HOW A GRADE IS DECIDED
----------------------
Each hadith may carry several gradings from different scholars, and they
disagree. Al-Albani may call a report weak where Zubair Ali Zai calls it
hasan. The rule here is deliberately cautious in the direction of caution:

  * any grader saying mawdu (fabricated),
    batil (false) or matruk           -> excluded outright, no matter
                                         what anyone else said
  * otherwise, any grader saying
    sahih or hasan                    -> acceptable, keep it
  * no grader saying either, and at
    least one saying daif or worse    -> weak, exclude it
  * no grading at all                 -> treated as acceptable

Fabrication is exempt from the generous rule on purpose. "Weak" is a
statement about how well a chain of transmission is preserved; scholars
routinely differ on it and a weak report may still be genuine. "Fabricated"
is a statement that the words were falsely put in the Prophet's mouth. A
single qualified scholar making that charge is reason enough for this app
to stay out of it, whatever another scholar concluded.

Where graders disagree and the report is kept, the badge says so --
"Hasan (scholars differ)" rather than picking a winner. Printing one side's
verdict alone would hide exactly the thing the reader needs to know.

That last case covers Bukhari and Muslim, whose entries carry no grades
field precisely because the collection itself is the grading.

Being generous where scholars disagree is a choice, not an oversight: this
software is not equipped to adjudicate between them, and excluding a report
that a recognised scholar considers sound would be its own kind of
misrepresentation. The grade is shown either way, so a reader can see that
judgements differ and take it to someone qualified.
"""
import re

_SOUND = re.compile(r"\b(sahih|hasan|saheeh|hassan)\b", re.I)
_WEAK = re.compile(r"\b(daif|da'if|dhaeef|weak|munkar|mawdu|maudu|fabricated|"
                   r"batil|matrook|matruk|shadh)\b", re.I)
# Charges no amount of scholarly disagreement can outvote -- see the note
# on fabrication above.
_FABRICATED = re.compile(r"\b(mawdu|maudu|maudoo|fabricated|batil|baatil|"
                         r"matrook|matruk)\b", re.I)


def _texts(record):
    out = []
    for g in record.get("grades") or []:
        if isinstance(g, dict):
            v = str(g.get("grade", "")).strip()
            if v:
                out.append(v)
        elif isinstance(g, str) and g.strip():
            out.append(g.strip())
    return out


def classify(record):
    """
    Returns (verdict, label).

      verdict: "sound" | "weak" | "ungraded"
      label:   short human-readable grading, or None
    """
    grades = _texts(record)
    if not grades:
        return "ungraded", None

    from collections import Counter

    if any(_FABRICATED.search(g) for g in grades):
        return "weak", Counter(grades).most_common(1)[0][0][:48]

    sound = [g for g in grades if _SOUND.search(g) and not _WEAK.search(g)]
    weak = [g for g in grades if _WEAK.search(g)]

    if sound:
        # Label from the sound gradings only: this report is being kept
        # because of those, so quoting a dissenting "Daif" as *the* grade
        # would contradict the decision the app just made.
        label = Counter(sound).most_common(1)[0][0][:48]
        if weak:
            return "disputed", f"{label} (scholars differ)"
        return "sound", label
    if weak:
        return "weak", Counter(weak).most_common(1)[0][0][:48]
    return "ungraded", Counter(grades).most_common(1)[0][0][:48]


def is_weak(record):
    return classify(record)[0] == "weak"


if __name__ == "__main__":
    import json, urllib.request, collections
    CDN = "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions"
    for ed, name in [("eng-abudawud", "Abu Dawud"), ("eng-tirmidhi", "Tirmidhi")]:
        d = json.loads(urllib.request.urlopen(f"{CDN}/{ed}.json", timeout=120).read())
        hs = [h for h in d["hadiths"] if str(h.get("text") or "").strip()]
        counts = collections.Counter(classify(h)[0] for h in hs)
        keep = counts["sound"] + counts["ungraded"]
        print(f"\n  {name}: {len(hs):,} hadith")
        for k in ("sound", "weak", "ungraded"):
            print(f"     {k:9s} {counts[k]:6,}")
        print(f"     -> {keep:,} searchable, {counts['weak']:,} excluded as weak")
        weak = [h for h in hs if classify(h)[0] == "weak"][:2]
        for h in weak:
            print(f"        e.g. [{classify(h)[1]}] {' '.join(str(h['text']).split())[:70]}")
