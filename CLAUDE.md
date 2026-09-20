# Hadith RAG App — Project Handoff for Claude Code

This document captures the full history of this project so far, built and prototyped in a chat conversation before moving here to Claude Code for the real build. Read this fully before starting any work.

## Who this is for

Haseeb is building this app to learn RAG deeply — not just to have it built for him. He wants to understand every architectural decision well enough to explain the whole build process, problems encountered, and fixes, in a future job interview. **Continue explaining reasoning behind decisions, not just implementing them.** He prefers a test-driven, proof-of-concept-first approach: prove something works on a small slice before scaling it up, and has done this at every phase so far.

## The goal

A free web (and eventually mobile) app where a Muslim user asks an everyday question in plain language ("what are the benefits of cutting nails", "ruling on waking up early") and receives an answer grounded strictly in retrieved hadith text — never the model's own outside knowledge — with an exact citation (book + hadith number) for every claim. Intended to be free for the community.

## Key decisions already made

- **No "login with ChatGPT/Claude account" for AI usage.** This doesn't exist as a product feature from any provider. The app will pay for its own API usage (like every real AI wrapper app), funded by whatever pricing/ads model comes later. Confirmed via direct research into this early on.
- **Data source: Sahih Bukhari PDF**, downloaded from islamhouse.com (`d1.islamhouse.com/data/en/ih_books/single/en_Sahih_Al-Bukhari.pdf`), 1,700 pages, translated by M. Muhsin Khan. A structured source (sunnah.com-style) was considered as an alternative but never finalized — the PDF approach is now extremely well-proven (see below), so sticking with it is reasonable, but this is worth a deliberate final decision rather than defaulting silently.
- **Dagu** identified as the right tool for orchestrating the data ingestion pipeline (parse → chunk → embed) as a scheduled, retryable job. Dagu is a **workflow/DAG orchestrator** (a lightweight self-hosted alternative to Airflow), **not a CI/CD tool** — a real distinction the user specifically asked about and wanted clarified. A separate CI/CD tool (e.g. GitHub Actions) is still needed for deploying the app itself.
- **Free tier cost control:** Google Sign-In for auth + a per-user daily query cap (~10/day), to bound worst-case API cost while the app is free. Not yet built.
- **UX decision, validated by research:** show the top 2–3 ranked candidate hadith with confidence, rather than forcing a single authoritative answer. This was the user's own instinct, and research confirmed it's recommended practice for high-stakes RAG, not a compromise.

## What's fully built and validated (small-slice prototype)

Everything below was built and tested against pages 1–15 of Sahih Bukhari (20 hadith, Book 1: Revelation + start of Book 2: Belief). This is a complete, working, tested pipeline — not a sketch.

**Files and what each does:**
- `parse_bukhari.py` — extracts text via `pdftotext`, strips page headers/footers, splits into hadith using the `Volume X, Book Y, Number Z:` marker pattern. Auto-locates the PDF next to itself; fails loudly with a clear message instead of silently returning empty results.
- `chunking.py` — splits hadith longer than ~180 words into sub-chunks before embedding (see bug #4 below for why).
- `tfidf_store.py` — TF-IDF retriever (scikit-learn), operates on chunks.
- `embed_and_retrieve.py` — neural embedding retriever using `sentence-transformers`, model `multi-qa-MiniLM-L6-cos-v1` (chosen specifically because it's trained for asymmetric question→passage retrieval, not general sentence similarity — see bug #3).
- `hybrid_retrieve.py` — combines TF-IDF + neural retrieval via Reciprocal Rank Fusion (RRF, K=60). Confidence gate: `tfidf_score >= 0.1 OR neural_score >= 0.4` — both thresholds empirically tuned against real query results, not guessed.
- `reranker.py` — cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) reranks the hybrid retriever's top-10 shortlist, using each hadith's best-matching chunk text. **Used only to reorder candidates, not to gate confidence** — see bug #6.
- `generate_answer.py` — builds the grounding prompt (answer ONLY from retrieved text, say so if nothing relevant, cite Volume/Book/Number), applies the confidence gate, calls an LLM. **The LLM call is currently stubbed** — the original dev sandbox had no internet/API access, so `llm_call` is injected as a dependency for testing.
- `evaluation_harness.py` — 7 permanent regression test cases, each one a real bug actually found during testing (not hypothetical). Currently 7/7 passing.
- `terminal_app.py` — interactive REPL for manually testing questions against the pipeline.
- `debug_extraction.py`, `debug_embeddings.py` — diagnostic scripts built while chasing specific bugs.

## Every real bug found, and how it was fixed (in order)

This is the actual engineering history — useful both for Claude Code to understand *why* the code looks the way it does, and for Haseeb to reference later.

1. **PDF footer glued mid-word across page breaks.** `pdftotext` sometimes inserts the page footer (e.g. `Volume 1 - 8 / 1700`) directly into a word split across a page break — e.g. "Gabriel" became "Gab" + footer text + "riel". Fixed by removing the whole footer+header page-break block as **one regex unit** (not line-by-line), so the word halves rejoin correctly. Caught by a test asserting footer text never appears inside a hadith's body.

2. **TF-IDF false match on a name fragment.** The query "Hajjat-al-Wida" matched an unrelated hadith purely because the word "al" (from the query, tokenized apart from "Hajjat" and "Wida") happened to appear in the narrator name "Abu Said Al-Khudri" — a coincidental token collision, zero real relevance.

3. **Embedding model choice matters, but doesn't fully solve anything alone.** A general-purpose similarity model (`all-MiniLM-L6-v2`) ranked topically-similar-but-wrong hadith above the actual best match for "actions are judged by intentions" (the most famous hadith in the collection). Switching to a retrieval-tuned model (`multi-qa-MiniLM-L6-cos-v1`, trained on 215M real Q&A pairs) didn't fully fix it either. TF-IDF alone actually retrieved this one correctly, via the rare exact word "intentions". Neither approach wins outright — this is what motivated combining them (hybrid retrieval).

4. **Long hadith produce blurry embeddings.** An 885-token hadith (#3, truncated by the embedding model's ~256–512 token limit) produced an ambiguous whole-hadith embedding that scored a **false** match ("Hajjat-al-Wida") *higher* than a **genuine** match ("revelation") on the same hadith. Fixed by splitting long hadith into ~180-word sub-chunks before embedding, then collapsing to each hadith's single best-scoring chunk before ranking.

5. **Small-corpus IDF artifact.** The query "Nawafil prayers" (Nawafil = voluntary prayers) falsely matched the Five Pillars of Islam hadith, because the generic word "prayers" happened to appear in only 1 of 32 chunks in this tiny 20-hadith test slice — giving it the exact same high IDF weight as a genuinely rare, specific word like "intentions". TF-IDF's whole mechanism for downweighting common words can't work properly with this little data. **Flagged to re-test once the corpus scales to the full 1,700 pages**, where "prayers" should naturally become common and get correctly downweighted. This specific case is now fixed by the combination of hybrid retrieval + reranking, but the root small-corpus-artifact question remains open.

6. **Cross-encoder reranker scores aren't a reliable absolute cutoff on this domain.** After adding reranking, a genuine match ("actions are judged by intentions", raw score −5.784) and a false match ("Nawafil prayers", raw score −6.046) scored nearly identically — likely domain mismatch, since this reranker was trained on general web search queries (MS MARCO), not religious texts. **Fix:** the reranker is used only to reorder the hybrid retriever's shortlist; the actual accept/reject confidence decision stays anchored to the hybrid retriever's own validated TF-IDF/neural thresholds, not the reranker's raw score.

7. **Multiple environment-porting bugs**, hit when moving code from the sandbox to Haseeb's actual Mac: missing files not downloaded together, hardcoded sandbox-only paths (PDF path, cache file path), a missing system dependency (`poppler`/`pdftotext`, fixed via `brew install poppler`), and a filename mismatch (space vs. underscore). All fixed — `parse_bukhari.py` now auto-locates the PDF relative to its own script location and raises clear, actionable errors instead of silently returning empty results.

8. **The two sources use different book-numbering schemes, and the mismatch is silent.** Both label books 1-93, so "are all 93 books present?" passes on both. But the PDF uses the 93-book USC-MSA division and the structured source uses the 97-book Arabic division: "Tawheed" is Book 93 in one and Book 97 in the other; only 3 of 93 books agree on hadith count. This caused a real wrong conclusion mid-session -- "Book 83 (Oaths and Vows) is entirely missing from the PDF" -- inferred from the *number* 83 being absent. The content is in the PDF, as Volume 8 / Book 78, and 76 of its 84 hadith cross-check at high similarity. Lesson: never infer content coverage from identifier coverage across two schemes. The sources are aligned on **text similarity** instead (TF-IDF, 1-2 grams), which matches ~99% of PDF records at >=0.8 similarity with a median of 1.000.

9. **Topic mixing, not length, is what blurs an embedding -- so a word-count chunker cannot catch it.** Scaling to 7,580 hadith dropped Bukhari 1 ("the reward of deeds depends upon the intentions") to **neural rank 695** for the query "actions are judged by intentions". It is ~50 words, so the 180-word rule from bug #4 never split it -- but it contains a ruling AND an unrelated worked example about emigration. Measured: full passage 0.168 vs query, ruling half alone 0.489, emigration half alone 0.003. One vector is an average, and a short two-topic passage averages just as badly as a long one. Fixed by chunking on **sentence boundaries into ~45-word overlapping windows** (1 sentence of overlap, so no statement is severed). Bukhari 1 went from neural rank 695 to **rank 1**. The 20-hadith prototype could never have shown this: TF-IDF's rare word "intentions" carried the query and hid the weakness entirely.

10. **The TF-IDF confidence threshold collapsed at scale -- 100% of in-domain accepted, but only 39% of out-of-domain rejected.** "What is the capital of France" and "best python web framework" both returned CONFIDENT. Cause: TF-IDF score stops discriminating as the corpus grows. Measured over 20 genuine Islamic questions vs 18 clearly out-of-domain ones, in-domain TF-IDF spans 0.171-0.563 and out-of-domain spans 0.000-**0.573** -- "best python web framework" outscores every real question. With 7,580 documents, any query shares incidental vocabulary with something. Fixed by **removing TF-IDF from the gate entirely** (a sweep drove its optimal threshold to 0.00) and gating on neural >= **0.44**, the lowest value rejecting 100% of out-of-domain queries. Costs ~15% of genuine questions, taken deliberately: for this app a false accept is far worse than a false reject. **TF-IDF still earns its place in RETRIEVAL** -- it is half of RRF and finds rare exact terms like "Nawafil" that embeddings miss. Ranking and gating are separate jobs; this is bug #6's lesson arriving from the other direction.

11. **Confidence was judged on rank 1 only, discarding better evidence further down.** RRF ranks by *agreement* between retrievers, not absolute similarity, so a candidate both retrievers like a little can outrank one a single retriever likes a lot. For "actions are judged by intentions" the correct hadith sat at position 3 with neural 0.459 -- above the gate -- while position 1 scored 0.376, so the whole query was declared low-confidence and the right answer thrown away. Now each candidate is judged on its own merits, which also matches the product decision to show 2-3 ranked candidates with confidence. Only confident candidates reach the LLM prompt -- the gate has to bind what the model can *see*, not just what is printed afterwards.

12. **The cross-encoder reranker became actively harmful at scale (extends bug #6) and is now OFF by default.** Bug #6 concluded its scores were untrustworthy as an absolute cutoff but fine for reordering. At 7,580 hadith the reordering itself is worse than no reordering: harness result **7/8 firm cases without it, 6/8 with it**. On the flagship query, hybrid returns Bukhari 1 (0.459) and 2529 (0.451) -- both correct and confident -- and the reranker evicts both in favour of a passage about an army invading the Ka'ba (0.279). Why scale made it worse: at 20 hadith the shortlist held obvious non-matches it could still sort; drawn from 7,580 it holds ten plausible passages, which is exactly where the MS MARCO web-search training mismatch bites. The code and flag are kept -- this is a verdict on *this model on this domain*, not on reranking as a technique.

13. **THE central open problem: the vocabulary gap between everyday questions and scripture.** The app's whole premise is plain-language questions, and that is precisely where retrieval is weakest. The famous "your mother, your mother, your mother, then your father" hadith (Bukhari 5971) ranks **#1** for "who is most deserving of my good companionship" -- the source's own wording -- and **#2,356** for "how should I treat my parents". The hadith never contains the word "parents"; it says "mother", "father", and "companionship". Same root cause fails "what are the benefits of cutting nails": the right Fitra hadith *is* retrieved into the top 3, but scores only ~0.388 because the hadith lists "clipping the nails" among five practices and never discusses "benefits" -- retrieval succeeds, confidence fails. **This cannot be fixed by tuning thresholds** (0.44 is already the lowest value that rejects all out-of-domain queries; out-of-domain tops out at 0.422). It needs query expansion / multi-query retrieval / HyDE, all of which require the LLM -- so it couples directly to the step of replacing the stubbed LLM call.

14. **Collapsing to the best chunk per hadith biases results toward long hadith.** More chunks means more chances for one to score high by coincidence. Measured: corpus averages 3.33 chunks per hadith, but confident top-3 results average **11.68** (3.5x); hadith with >=6 chunks are 14.5% of the corpus and **56%** of confident results. Visible in practice -- "what did the Prophet say about neighbours" returns the correct hadith first, then two long, irrelevant narratives marked CONFIDENT. Needs a length-normalisation or score-penalty step; not yet addressed.

15. **The confidence gate measures the wrong thing: "is this religious?" not "is this the right hadith?"** Tuned against out-of-domain junk ("capital of France", "best python web framework"), neural >= 0.44 rejects 100% of those and looked like a success. Tested against 25 ordinary Muslim questions on the combined 14,940-hadith corpus, it produced a CONFIDENT answer for 23 of 25 (92%) -- while only ~5-6 were actually correct, so real precision is roughly 25% behind a 92% confidence claim. The measurement that explains it: genuine Islamic questions score 0.388-0.750 and out-of-domain junk scores 0.123-0.330, so the gate cleanly separates religious from non-religious -- but a WRONG hadith on a religious topic scores in exactly the same band as a right one. Every hadith is religious, so with 14,940 of them something always scores 0.45-0.75 for any Islamic question. Worked examples: "how should I treat my parents" and "what did the Prophet say about smiling" both return the same hadith about two of the Prophet's wives (the latter at 0.745); "how do I perform wudu" returns a narration about seeking knowledge. **This is more dangerous than a wrong answer, because the app asserts confidence while citing scripture that does not address the question.** Out-of-domain rejection was the easy half of the problem and is solved; in-domain discrimination is unsolved.

16. **Growing the corpus made some answers worse, not better.** Adding Sahih Muslim (7,360 records, corpus now 14,940) displaced correct answers: "what are the benefits of cutting nails" previously returned the Fitra hadith and now returns a Muslim hadith about NOT cutting nails before sacrifice. More documents means more chances to be confidently wrong, so corpus growth must be paired with better discrimination rather than assumed to be an improvement on its own.

17. **Length bias worsened with corpus size, but is NOT the main cause of bad answers.** At 14,940 hadith, confident results average 16.20 chunks against a corpus mean of 3.00 (**5.4x**, up from 3.5x at 7,580); hadith with >=10 chunks are 4.3% of the corpus and 34.1% of confident results. `muslim:7512` is a 2,658-word / 94-chunk narration that wins unrelated queries on sheer surface area. Tested four alternative aggregations against 11 hand-labelled common questions: a log length penalty drops the top result's mean chunk count from 7.2 to 1.0 but moves recall@1 only from 9% to 18%, and recall@3 from 36% to 45%. Worth fixing, but it is a second-order effect -- the dominant failure is that the embedding model cannot match everyday phrasing to scripture wording (bug #13).

18. **A better embedding model does NOT fix the vocabulary gap -- three models agree, so it is not a capacity problem.** Benchmarked on 11 hand-labelled everyday questions over the 14,940-hadith corpus, same chunking, same scoring:

    | model | dim | recall@1 | recall@3 |
    |---|---|---|---|
    | multi-qa-MiniLM-L6-cos-v1 (current) | 384 | 9% | 36% |
    | BAAI/bge-base-en-v1.5 | 768 | 18% | 18% |
    | intfloat/e5-base-v2 | 768 | 9% | 18% |

    Doubling the dimensions and switching to stronger retrieval-tuned models moved nothing. The free fix is ruled out by measurement rather than by assumption.

19. **Rewriting the question into the source's vocabulary fixes it: recall@1 9% -> 64%, recall@3 36% -> 82%.** Same model, same index, same scoring -- only the query wording changed. This isolates the vocabulary gap as *the* bottleneck. The single clearest number in the project: "how should I treat my parents" scores **0.084** against `bukhari:5971`, the hadith that literally answers it, while unrelated hadith on religious topics score 0.50+. **Important caveat: those rewrites were written knowing the target hadith, so 64% is an upper bound, not a forecast.** Runtime query expansion and HyDE must GUESS the answer's wording from the question alone and cannot reliably reach it. doc2query does not have to guess -- at index time the hadith is available to read -- which is why the offline direction was chosen. It also costs nothing per query, which matters for an app that must stay free.

20. **doc2query sample validated on 50 hadith -- it works, and it is the first change that moved real user questions.** Both models generated ~5.9 questions per hadith, 50/50 succeeded, no parsing failures.

    | metric | baseline | Haiku 4.5 | Opus 5 |
    |---|---|---|---|
    | mean similarity to the right hadith | 0.419 | **0.747** | 0.702 |
    | gold questions clearing the 0.44 gate | 5/11 | **11/11** | **11/11** |
    | corpus recall@1 (*optimistic*) | 9% | 91% | 82% |
    | corpus recall@3 (*optimistic*) | 36% | 100% | 91% |

    The flagship case: "how should I treat my parents" vs `bukhari:5971` goes from **0.084 to 0.628**.

    Two honesty notes. (a) The corpus recall figures are OPTIMISTIC -- only 50 of 14,940 hadith are expanded, so the gold hadith have matching surface their competitors lack; the corpus-independent similarity gain is the trustworthy number. (b) Haiku scoring above Opus (+0.328 vs +0.282) is probably measurement bias, not quality: the 11 gold questions were written in a plain literal style closer to Haiku's output than to Opus's more colloquial phrasing. Read the two as equivalent in quality.

    Measured costs from the real sample (extrapolated to 14,940 hadith, Batch API halves it): **Haiku 4.5 $12.52 / $6.26 batch**; **Opus 5 $79.23 / $39.61 batch** -- Opus is ~6x, and materially higher than the pre-sample estimate because actual token usage exceeded the model.

    **Still unresolved after expansion:** the confidence gate (bug #15). Expansion raises the score of the RIGHT hadith, which should widen separation -- but the false-positive rate must be re-measured on the full corpus before trusting it, since wrong-but-religious hadith still score 0.45-0.75.

21. **The free alternatives to LLM-generated questions were tested and both fail -- so the API spend is justified by measurement, not convenience.** Prompted by Haseeb asking whether the API call was really necessary (it was proposed without testing the free options first, which broke this project's own measure-before-choosing habit).

    | approach | cost | mean similarity | gain | clears 0.44 gate | "treat my parents" |
    |---|---|---|---|---|---|
    | baseline | $0 | 0.419 | -- | 5/11 | 0.084 |
    | + book/chapter metadata in the index | $0 | -- | **worse** (recall@3 36%->18%) | -- | -- |
    | local T5 (`doc2query/all-t5-base-v1`) | $0 | 0.511 | +0.092 | 8/11 | 0.236 (still fails) |
    | **Haiku 4.5** | ~$6-12 | **0.747** | **+0.328** | **11/11** | **0.628** |
    | Opus 5 | ~$40-79 | 0.702 | +0.282 | 11/11 | 0.560 |

    **Metadata enrichment backfires:** book names like "Good Manners and Form" are shared by hundreds of hadith, so prepending them dilutes the specific content rather than sharpening it.

    **The local T5 model gives ~28% of the benefit AND fabricates content** -- the disqualifying problem. Real outputs: the *dua before sleeping* hadith produced "How can a Muslim be resurrected after the death of an ex-muslim?"; the *suicide* hadith produced "How come Muslims are not allowed to do sex?"; the *eating with the right hand* hadith produced "Why do some Christians eat or drinks with their left hand?". This is the MS MARCO domain mismatch from bug #6 again. Indexing invented questions against scripture is precisely the failure the grounding architecture exists to prevent, so cost is not the deciding factor here -- faithfulness is.

22. **doc2query executed over the full corpus. 14,940/14,940 hadith, 87,240 generated questions, zero failures, $6.29 via the Batch API.** Batch `msgbatch_01Ub8njmbT7jy1Su1VZ8tmxz`, Haiku 4.5, ~35 minutes end to end.

    Quality checks on the 87,240 questions: median 9 words; 99.8% of hadith got questions (the 24 that got none are pure-narrative passages where the prompt told the model to write fewer rather than invent, which is correct); 6.5% are exact duplicates across the corpus, expected since Bukhari and Muslim repeat many hadith; **only 4 of 87,240 contain scripture-style quoting**, so the "do not quote the hadith's own wording" constraint held.

    **Two process lessons paid for in real money before this run succeeded:**
    - The first attempt at the full run held results in memory and wrote only at the end. Interrupting at 1,780/14,940 discarded every completed call, ~$1.50. Fixed with append-as-you-go JSONL plus resume; a re-run of completed records now bills $0.00.
    - The second attempt was rejected by the API in one second: `custom_id` must match `^[a-zA-Z0-9_-]{1,64}$`, and 26 hadith ids carry a decimal (`bukhari:402.2`) that survived the naive colon substitution. Fixed with sequential ids plus a stored id_map, and local validation of all ids before submission. The lesson is that validating 2 records is not validating 14,890.
    - Before the successful run, a live 5-record batch (~$0.001) exercised submit -> poll -> collect -> id-mapping end to end. That path had never executed. **Haseeb asked for exactly this and it should be the default for any costly or hard-to-repeat run** -- see the `prove-execution-before-spending` memory.

    Indexing: `expansion.py` folds the questions in as extra chunks tagged `chunk_type="question"`, alongside hadith text tagged `"text"`. Retrieval searches both; **only authentic hadith text is ever displayed or cited** -- a generated question must never surface as though the Prophet said it, so the distinction is structural rather than conventional.

23. **doc2query's real payoff was CONFIDENCE SEPARABILITY, not ranking -- and measuring it with the old threshold made a large win look like a regression.**

    First full-corpus measurement looked bad on three of four axes: gold recall@3 5/11 -> 4/11, confident answers 23/25 -> 25/25 with no accuracy gain, out-of-domain rejection 6/6 -> 4/6. Two distinct causes, one real and one an artifact:

    **(a) A real data defect.** Sahih Muslim numbers 1,366 records (9.1% of corpus) whose entire text is a note that the previous hadith came via another chain -- "This hadith has been narrated through other chains of transmitters." Harmless while retrieval matched on scripture wording (a stub has none), but doc2query gave these content-free records six plausible everyday questions each, and a near-verbatim question match (0.94-1.00) beats any real hadith's scripture wording (0.5-0.7). **Empty records started winning retrieval outright.** Fixed in `stub_filter.py` -- excluded from the INDEX, kept in the corpus. A first attempt used a 12-word minimum and wrongly dropped real short hadith ("The Prophet performed ablution by washing the body parts twice", 11 words, a complete ruling); length does not distinguish a stub from a terse hadith, the cross-reference WORDING does.

    **(b) A stale threshold.** Expansion shifted every similarity score upward, and the gate was still 0.44, tuned before expansion existed. Re-measuring the distributions:

    | | pre-expansion | post-expansion |
    |---|---|---|
    | real questions (n=20) | 0.376 - 0.737 | **0.627 - 1.000** |
    | out-of-domain (n=18) | 0.123 - 0.422 | 0.160 - **0.527** |
    | overlap | 0.376-0.422 | **none** |

    Pre-expansion the distributions OVERLAPPED, so 0.44 was the best available compromise and cost ~15% of genuine questions. Post-expansion there is a clean gap, and **0.55 accepts 100% of real questions while rejecting 100% of out-of-domain** -- which is what bug #15 needed and had no solution before.

    **The lesson: after changing what is in the index, re-tune the thresholds BEFORE judging the change.** Every empirically-tuned constant is conditional on the data it was tuned against -- the same mistake as bug #10 and the stale eval ground truth, arriving a third time.

    Caveat kept honest: the 20 test questions are phrased similarly to the generated questions, so 0.627 as a floor is probably optimistic. 0.55 deliberately leaves headroom rather than hugging it. Re-measure against real user queries before tightening.

24. **CORRECTION to #23: the confidence separation was over-fit to the 20 tuning questions. Bug #15 is NOT fixed.**

    #23 reported a clean post-expansion gap -- real questions 0.627-1.000, out-of-domain 0.160-0.527 -- and a 0.55 gate accepting 100% of real questions. That holds only for the 20 questions the gate was tuned on. Tested outside that set it fails immediately.

    Query "actions are judged by intentions":

    | hadith | matched on | neural | gate 0.55 |
    |---|---|---|---|
    | `muslim:7228` (**wrong**) | generated Q: "What happens if you're judged strictly for your actions?" | **0.703** | ACCEPTED |
    | `bukhari:1` (**correct**) | generated Q: "how does Allah judge our actions and intentions" | 0.511 | rejected |

    **The gate accepts the wrong hadith and rejects the right one on the same query.** Raising the threshold did not fix in-domain discrimination; it relocated the failure. The separation doc2query bought is between religious-sounding queries and junk queries -- which was already the solved half. Telling a RIGHT hadith from a WRONG one remains unsolved, and no threshold can fix it because the score does not track correctness.

    **What doc2query genuinely delivered**, on honest accounting:
    - "what are the benefits of cutting nails" moved from documented `known_failure` to passing -- a real vocabulary-gap case fixed (0.627 on the correct Fitra hadith, matched via a generated question).
    - Several answers corrected that the labelled set never covered: "commits suicide" now returns the actual suicide hadith; "treat animals" returns the cat hadith.
    - Ranking on the 11-question labelled set: unchanged, 4/11 @1 and 5/11 @3 throughout.
    - Out-of-domain rejection: 6/6 maintained, at a higher gate.

    **What it did not deliver:** the in-domain right/wrong discrimination that blocks release. Cost $6.29, one-off.

25. **Content-free records had to be excluded, and the filter took five iterations -- each failure found by READING OUTPUT, never by a metric.** Final: 1,656 records excluded (11.1%), almost all Sahih Muslim chain-of-transmission notes. The iterations: (1) a 12-word minimum wrongly dropped real short hadith -- "The Prophet performed ablution by washing the body parts twice" is a complete ruling; length never distinguished a stub from a terse hadith, the cross-reference WORDING does. (2) Patterns anchored on "This hadith..." missed stubs opening with a narrator's name. (3) `[^.]` character classes broke on the abbreviated patronymic "b." (ibn) that pervades these translations. (4) A parenthetical inside "like the (above-mentioned) tradition" broke a contiguous match. (5) Requiring a corroborating "chain"/"authority" word let through "The same hadith has been narrated by Zuhair b. Harb, Waki..." which merely LISTS narrators -- fixed by treating a self-referential OPENING ("This hadith...", "The same hadith...") as conclusive on its own, since no authentic hadith opens by naming itself. A tempting general rule (short record + mentions "hadith") was tested and REJECTED: it would have dropped real hadith such as "Fatima came to Allah's Apostle and asked...". Every version was validated against a 26-record regression guard of known-real hadith.

## Research findings incorporated into the plan

- Even paid, professional legal-AI products (LexisNexis's Lexis+ AI, Thomson Reuters's Westlaw AI) hallucinate an estimated **17–33% of the time** despite using RAG, per a 2025 Stanford study — useful for calibrating expectations. This is a genuinely hard, industry-wide unsolved problem, not a sign of doing something wrong.
- The closest real comparable system found: **Fanar-Sadiq**, an academic multi-agent Islamic QA architecture covering 500K+ documents including six major hadith collections. It uses a much larger embedding model (Qwen3-Embedding-4B, 4096 dimensions vs. our 384), a real vector database (Milvus/Chroma with HNSW indexing), a minimum similarity threshold of 0.3 (same order of magnitude as our independently-tuned 0.4), and an optional cross-encoder reranker — validating several of our own choices.
- A related open-source project ("Multilingual NLP for Islamic Theology", same domain — Quran + Sahih Hadith semantic search) documented the *exact same* failure mode found here: queries matching on surface vocabulary rather than true relevance (their example: "is cricket haram" matching unrelated "haram" content). Their stated mitigation matches ours: treat a low confidence score as a sign to rephrase, not something to trust.
- **RAGAS** (Retrieval-Augmented Generation Assessment System) identified as the standard formal evaluation framework — metrics: Faithfulness, Answer Relevancy, Context Precision, Context Recall — worth adopting as the evaluation harness matures beyond the current small, ad-hoc pass/fail set.

## Current status, plainly

**Data source: SETTLED** -- structured corpus primary + Khan PDF as an independent cross-check (bugs #8-#9).

- **Corpus: 14,940 hadith** -- Sahih Bukhari (7,580, canonical numbering, all 93 books) + Sahih Muslim (7,360). Built by `build_corpus.py` into `data/corpus.json`; 44,841 sentence-window chunks.
- **6,385 hadith (43%) cross-checked** against the independently-parsed Khan PDF. Muslim has no second English source, so its records are marked "single source" -- surfaced in the UI, not hidden, since a reviewing scholar should see which texts were corroborated.
- `parse_bukhari.py` extracts 6,720 hadith from all 1,700 pages with zero header/footer leakage and zero duplicate keys.
- Citations carry both numbering schemes, e.g. `Sahih al-Bukhari 6621 — Book 83: Oaths and Vows [USC-MSA Vol 8, Book 78, No 618]`, plus a provenance line.
- Retrieval runs at ~100-500ms/query; embeddings cached on disk keyed by model+corpus hash (cold build ~2min, warm ~10s).

**Retrieval quality, measured honestly on 25 ordinary questions: roughly 25% correct while claiming 92% confidence.** The pipeline is structurally sound and the data is good; the ranking and the confidence signal are not yet fit for users. See bugs #15-#17. The formal harness reports 8/8 firm cases, which is now known to be a misleadingly easy set -- it tests out-of-domain rejection thoroughly and everyday in-domain accuracy barely at all.

API credentials now work (`.env`, read at runtime by `env_config.py` -- a shell export cannot reach the tooling because the shell environment is snapshotted at session start). Generation in `generate_answer.py` is **still stubbed**; the only real API calls so far are the doc2query samples. Storage is still in-memory.

## Next steps, in order

1. **Run doc2query (bug #19).** `doc2query.py` and `measure_doc2query.py` are built and dry-tested; only an `ANTHROPIC_API_KEY` is missing. Plan agreed with Haseeb: sample 50 hadith first (including the 15 ground-truth ones), inspect the generated questions and the measured gain, then decide the model for the full run. Sample costs cents; full corpus is ~$6 (Haiku 4.5 + Batch) to ~$32 (Opus 5 + Batch), one-off, zero recurring.
2. **Rebuild the confidence gate (bug #15) -- doc2query will NOT fix this.** Better retrieval raises the hit rate but the gate will still overclaim, because it measures "is this religious?" not "is this right?". Options to test: rerank against the generated questions, or a cheap LLM relevance check on the top 3 before answering. Until this is fixed the app must not be shown to users, since it asserts confidence while citing scripture that does not address the question.
3. **Replace the stubbed LLM call** in `generate_answer.py` with a real API call (same key unblocks it).
4. **Fix the long-hadith bias (bug #17).** A log length penalty is already measured: top-1 mean chunk count 7.2 -> 1.0, recall@1 9% -> 18%. Second-order, but cheap and real.
4. **Expand the evaluation harness.** 11 cases is far too few to tune on -- the threshold sweep used only 20 in-domain and 18 out-of-domain probes. Adopt RAGAS metrics (Faithfulness, Answer Relevancy, Context Precision, Context Recall) once generation is real.
5. **Move to a real vector database** (Pinecone or Supabase/pgvector). 25,210 vectors still fit comfortably in memory, so this is not yet urgent -- it becomes urgent with Sahih Muslim.
6. **Ingest Sahih Muslim** -- same schema, same pipeline, `load_collection("muslim")`.
7. **Wrap ingestion in Dagu** (parse -> chunk -> embed -> cross-check) as a scheduled, retryable job with real logging.
8. **Build the app layer** (web first). Show top 2-3 ranked hadith with confidence, never a single forced answer.
9. **Add Google Sign-In + per-user daily query cap** to bound cost while free.
10. **Get scholar/imam review before any real release.** Non-negotiable.

### Open questions worth a deliberate decision
- **Licensing/provenance of the structured source** before any public release. The text is the widely-distributed Khan translation, but the dataset is a community GitHub mirror. The PDF cross-check helps the integrity story; it does not settle licensing.
- **Embedding model.** `multi-qa-MiniLM-L6-cos-v1` is 384-dim; Fanar-Sadiq (the closest comparable system) uses Qwen3-Embedding-4B at 4096-dim. Several failures here are embedding-quality failures.
- **Environment.** Running on system Python 3.9.6 with packages in user site-packages, and `pdftotext` lives at `/opt/homebrew/bin`, which is not on every shell's PATH. Worth a virtualenv + pinned `requirements.txt` before this grows.

## What "done" looks like

A free app where a user's plain-language question returns an answer grounded strictly in retrieved hadith text, with exact citations, shown as multiple ranked candidates with visible confidence rather than one forced answer, clearly saying "I couldn't find a clear answer" when confidence is genuinely low — reviewed and signed off by a qualified scholar before any wide release.
