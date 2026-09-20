# Sunnah Hadith Search

Ask a question in plain English and get the hadith that actually answer it,
with a citation you can check. Answers come only from **Sahih al-Bukhari**
and **Sahih Muslim** — nothing is written or paraphrased by an AI.

> **Early trial.** Roughly one answer in six is still wrong or weak, and no
> scholar has reviewed this yet. It is not a substitute for asking a
> qualified scholar. If an answer looks wrong, please report it — see below.

## How it works

1. **Search** finds the 10 closest hadith using three signals together:
   word matching, meaning matching, and letter-pattern matching (so
   "Tahajjut" still finds "Tahajjud").
2. **A relevance check** shows those 10 to a small AI model and asks which
   ones genuinely *answer* the question, rather than merely resembling it.
3. **The hadith are shown** — real text, real citation, shortest and most
   direct first. Up to three. No AI-written answer.

Step 2 exists because matching words alone could not tell a right hadith
from a wrong one. On "actions are judged by intentions" the correct hadith
scored **0.511** while the unrelated query "recipe for chicken biryani"
scored **0.527** — the right answer scored *lower* than nonsense. No cut-off
can separate those. Asking the question directly can, and does.

## Reporting a wrong answer

Every result has a **Report** button. It asks what went wrong — nothing to do
with the question, related but doesn't answer it, there's a better-known
hadith, the wording looks wrong, or something else — plus an optional note.

Reports are appended to `data/feedback.jsonl` and can be read at
`/api/feedback`. They are the main way this improves: a reported answer
becomes a test case, the cause gets fixed, and the case stays in the test
set so it cannot quietly break again.

Reports are **not** applied automatically. Nothing reshuffles which hadith
are shown based on votes. For scripture that would be a bad idea — people
can be mistaken, and silent drift would be impossible to notice.

## Running it

```bash
pip3 install -r requirements.txt
cp .env.example .env        # then put your Anthropic API key in it
                            # .env is gitignored — never commit it

python3 load_structured.py                      # downloads both collections
python3 build_corpus.py                         # assembles the corpus
python3 -m uvicorn web.server:app --port 8077   # first run builds the index (~4 min)
```

Then open <http://127.0.0.1:8077>.

Terminal version: `python3 terminal_app.py`
(add `--no-check` to skip the AI relevance check — free, but much less accurate)

Check quality against the test set: `python3 evaluation_harness.py`

Optional second-source cross-check: put `Sahih_Bukhari.pdf` (from
islamhouse.com) in this folder, install `poppler`, and run
`python3 align_sources.py` before `build_corpus.py`.

## What it costs to run

Search runs locally and is free. The relevance check costs about
**$0.0014 per question** (~$1.40 per 1,000). Generating the 87,240
search-helper questions was a one-off **$6.29** and never repeats.

There is no usage limit yet. Add one before putting this anywhere public,
or anyone who finds it can run up your bill.

## The data

- **14,940 hadith**; **13,284** are searchable. The other 1,656 are
  chain-of-transmission notes carrying no content ("This hadith has been
  narrated through other chains of transmitters") and are excluded — once
  they were given generated search questions they began outranking real
  hadith.
- **6,385** are verified word-for-word against an independently parsed PDF of
  the same translation. The rest are marked "single source" in the interface.
- Citations carry **both** numbering schemes in circulation, because they
  disagree: "Oaths and Vows" is Book 83 in one and Book 78 in the other.

### Sources and credit

- Hadith text: the M. Muhsin Khan English translation, via the open
  [hadith-api](https://github.com/fawazahmed0/hadith-api) dataset.
- Cross-check source: *Sahih Al-Bukhari* PDF published by
  [islamhouse.com](https://islamhouse.com).
- The hadith themselves are the sayings of the Prophet ﷺ as preserved by
  Imam al-Bukhari and Imam Muslim. Any error here is in this software, never
  in them.

## Known limitations

- About 1 answer in 6 is wrong or weak. "How should I treat orphans" is a
  known bad one.
- It sometimes refuses questions it should answer.
- Each search takes ~1 second, so a question takes ~3 seconds end to end.
- No sign-in, no usage limits, no scholarly review yet. **Scholarly review is
  the one thing that must happen before any wide release.**

## Development history

`CLAUDE.md` documents every bug found while building this and how each was
fixed — including the ones that cost real money to learn, and the times a
measurement said something was working when it was not.

## Licence

No licence chosen yet. Until one is added, treat this as all rights reserved
and ask before reusing it.
