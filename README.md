# Sunnah Hadith Search

Ask a question in plain English and get the hadith that actually answer it,
with a citation you can check. Answers come only from **Sahih al-Bukhari**
and **Sahih Muslim** — nothing is written or paraphrased by an AI.

> **Early trial.** Roughly one answer in six is still wrong or weak. This is
> not a substitute for asking a qualified scholar, and it has not yet been
> reviewed by one.

## How it works

1. **Search** finds the 10 closest hadith, using three signals together:
   word matching, meaning matching, and letter-pattern matching (so
   "Tahajjut" still finds "Tahajjud").
2. **A relevance check** shows those 10 to a small AI model and asks which
   ones genuinely *answer* the question, rather than merely resembling it.
3. **The hadith are shown** — real text, real citation. No AI-written answer.

Step 2 exists because matching words alone could not tell a right hadith from
a wrong one. On "actions are judged by intentions" the correct hadith scored
*lower* than the unrelated query "recipe for chicken biryani". No cut-off
could separate those; asking the question directly can.

## Running it

```bash
pip3 install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env      # never commit this file

python3 load_structured.py                      # downloads both collections
python3 build_corpus.py                         # assembles the corpus
python3 -m uvicorn web.server:app --port 8077   # first run builds the index (~4 min)
```

Then open <http://127.0.0.1:8077>.

There is also a terminal version: `python3 terminal_app.py`

Optional, for the second-source cross-check: put `Sahih_Bukhari.pdf`
(from islamhouse.com) in this folder, install `poppler`, and run
`python3 align_sources.py` before `build_corpus.py`.

## Costs

Search is free and runs locally. The relevance check costs about
**$0.0014 per question** (~$1.40 per 1,000). The one-off generation of
87,240 search-helper questions cost $6.29 and never repeats.

## Data

- ~14,900 hadith; ~13,300 are searchable (chain-of-transmission notes with no
  content are excluded).
- 6,385 have been cross-checked, word for word, against an independently
  parsed PDF of the same translation. The rest are marked "single source".
- Citations carry both numbering schemes, since the two in circulation
  disagree — e.g. "Oaths and Vows" is Book 83 in one and Book 78 in the other.

## Honest limitations

- About 1 answer in 6 is wrong or weak. "How should I treat orphans" is a
  known bad one.
- It sometimes refuses questions it should answer.
- No scholarly review yet. This is the one thing that must happen before any
  wide release.

`CLAUDE.md` documents every bug found during development and how each was
fixed, including the ones that cost money to learn.
