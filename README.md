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

## Browsing by topic

A sidebar offers 22 everyday subjects — Prayer, Fasting, Good Manners,
Marriage, Trade — covering 6,455 hadith across both collections.

Browsing is **free and instant**: it reads from memory and makes no AI call,
unlike a search. Results are shortest-first, so you start with hadith that
can be read at a glance.

The list is curated rather than showing all 154 books, because the largest
books are not what an ordinary visitor wants — "Military Expeditions" has
487 hadith and is rarely what someone came to ask about. Each topic gathers
matching books from both collections, since Bukhari and Muslim name the
same subject differently.

## Hadith of the day

The homepage shows one well-known hadith, chosen by the date so everyone
sees the same one and it changes at midnight. The pool is a hand-picked set
of 27 in `daily_hadith.py` — each checked to be self-contained, widely
taught, and short enough to read in one sitting.

It is deliberately **not** random from all 13,000 records. The daily hadith
is served unprompted, with no question to justify it, so it has to be safe
to meet cold on a homepage.

## Supporting the work

An optional "Support this work" button appears only when a payment link is
configured:

```bash
export HADITH_SUPPORT_URL="https://ko-fi.com/yourname"
```

Payments are deliberately **not** built in — taking money needs an account
in the owner's name with their own identity and bank details. The button
simply links out to whatever service the owner has set up (Ko-fi, Buy Me a
Coffee, PayPal.me, Stripe). No payment details ever reach this application.

It is shown with *"Save yourself from Hell-fire even by giving half a
date-fruit in charity"* (Bukhari 1417) — the point being that any amount
counts, and none is expected.

## Signing in

**Searching never requires an account.** Anyone can use the site anonymously
— asking for a sign-in before someone can look up a hadith would turn away
exactly the casual visitor this is for, and there is nothing to protect.

**Feedback requires signing in**, once it is configured. Feedback is written
into a file a person reads and acts on, so it needs to cost enough to abuse
that nobody bothers. A sign-in does that without a CAPTCHA.

```bash
export GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
export HADITH_ID_SALT="any long random string"
```

Create the client id at [console.cloud.google.com](https://console.cloud.google.com)
→ APIs & Services → Credentials → OAuth client ID → Web application, and add
your site's address to the authorised origins.

Until `GOOGLE_CLIENT_ID` is set, sign-in is simply off and feedback stays
open — nothing breaks.

**What is stored:** a salted hash of the Google account id. No email, no
name, no picture. Enough to notice one person sending fifty reports; not
enough to know who they are.

## Analytics

Counts only, at `/api/stats`:

| | |
|---|---|
| `visitors` / `visits` | how many people, how many page opens |
| `searches` / `people_who_searched` | questions asked, and by how many people |
| `answered` / `no_answer` / `answer_rate` | how often a question got an answer |
| `feedback` / `people_who_gave_feedback` | reports received |
| `support_opened` / `support_clicked` | how many looked, how many gave |

Plus a day-by-day breakdown. Read them with `python3 analytics.py`.

**No third-party analytics.** Google Analytics and its equivalents work by
sending your visitors' data to an advertising company — for a religious site
that means telling them who reads hadith and what they searched for. Counting
locally gives the same numbers without any of that.

**What is recorded:** the date, the event name, and a random token the
browser generates for itself. No IP address, no browser string, no location,
no question text, and nothing tied to a Google account. The token exists only
so "how many people searched" can be told apart from "how many searches
happened".

## Knowing when something breaks

`healthcheck.py` asks the running site questions it already knows the
answers to, and fails loudly if they change:

```bash
python3 healthcheck.py --quiet        # prints only on failure
```

It checks the site responds, the corpus is loaded, the relevance check is
switched on, the daily hadith resolves, four known questions still return
the right hadith, and obvious nonsense is still refused. Exit code 0 means
healthy, 1 means something failed — so it works from cron or any alerting
tool without parsing output.

The known-answer checks are the point. **A site can be up, fast and
completely wrong** — that is exactly the failure this project kept hitting,
and an ordinary uptime monitor cannot see it.

Run it hourly:

```
0 * * * * cd /path/to/app && python3 healthcheck.py --quiet --base https://yoursite || echo "hadith app check failed"
```

## Reporting a wrong answer

Every result has a **Report** button. It asks what went wrong — nothing to do
with the question, related but doesn't answer it, there's a better-known
hadith, the wording looks wrong, or something else — plus an optional note.

There is also a general **Send feedback** button for anything not tied to a
specific result.

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
- Background image: carved geometric latticework, from
  [Pexels](https://pexels.com) — free for commercial use. Chosen over a
  calligraphy image deliberately: geometric ornament carries no question
  about whether sacred text is being used decoratively.
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
