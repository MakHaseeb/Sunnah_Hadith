---
title: Hadith Search
emoji: 📖
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Search four hadith collections in plain English
---

# Hadith Search

Ask a question in your own words and get the hadith that actually answer it,
with a citation you can check. Answers come only from **Sahih al-Bukhari**,
**Sahih Muslim**, **Sunan Abu Dawud** and **Jami' at-Tirmidhi** — nothing is
written or paraphrased by an AI.

Reports the Sunan record as weak are excluded, and every result shows its
authenticity grading. Where recognised scholars disagree, the grading says
so rather than picking a side.

> **Early trial.** Roughly one answer in six is still wrong or weak, and no
> scholar has reviewed this yet. It is not a substitute for asking a
> qualified scholar. If an answer looks wrong, please report it.

Source code and full development notes:
<https://github.com/MakHaseeb/Sunnah_Hadith>

## Space settings this needs

**Secrets** (Settings → Variables and secrets):

| Name | Why |
|---|---|
| `HF_TOKEN` | Read access to the private dataset holding the prebuilt index. **The build fails without it** — see the Dockerfile. |
| `ANTHROPIC_API_KEY` | The relevance check. Without it the app still searches, and says on the page that answers are unchecked. |
| `GOOGLE_CLIENT_ID` | Sign-in, which is needed only to send feedback — never to search. |
| `HADITH_ID_SALT` | Salts the hash of a sign-in id so no account identifier is stored. |

The search index is **not** built here. It is built by `publish_index.py` and
downloaded as a pinned, checksummed artifact, so this Space runs on free
hardware — see the comments in that file.
