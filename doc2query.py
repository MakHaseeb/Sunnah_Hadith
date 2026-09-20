"""
Document expansion (doc2query): for each hadith, generate the everyday
questions a person would actually ask that this hadith answers. Those
questions get embedded alongside the hadith text, so a plain-language
query matches a QUESTION rather than 7th-century prose.

WHY THIS, AND NOT QUERY EXPANSION OR A BETTER EMBEDDING MODEL
--------------------------------------------------------------
Measured on 11 hand-labelled common questions against the 14,940-hadith
corpus:

  embedding model swap (free, no LLM)
      multi-qa-MiniLM-L6-cos-v1  (384d)  recall@1  9%   recall@3 36%
      BAAI/bge-base-en-v1.5      (768d)  recall@1 18%   recall@3 18%
      intfloat/e5-base-v2        (768d)  recall@1  9%   recall@3 18%

  same model, question rewritten into the source's own vocabulary
      recall@1 64%   recall@3 82%

So the bottleneck is not model capacity -- three models agree. It is that
"how should I treat my parents" and "Who is more entitled to be treated
with the best companionship by me?" share almost no words.

That rewrite experiment was deliberately optimistic: the rewrites were
written knowing the target hadith. HyDE and runtime query expansion have
to GUESS the answer's wording from the question alone, so they cannot
reliably reach that number.

doc2query does not have to guess. At index time the hadith is right
there, so the model writes questions FOR a passage it can actually read.
The "cheating" that made the experiment work is exactly what doing this
offline makes legitimate -- and it costs nothing per query afterwards,
which matters for an app that must stay free.
"""
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "data", "doc2query")

# Models whose thinking/effort controls follow the 4.6+ family conventions.
# Haiku 4.5 rejects `effort` and uses the older budget_tokens form, so it is
# simply called without either rather than with guessed parameters.
ADAPTIVE_MODELS = {"claude-opus-5", "claude-sonnet-5", "claude-opus-4-8", "claude-fable-5-1"}

N_QUESTIONS = 6

PROMPT = """You are helping build a search index for a hadith app used by ordinary Muslims.

Below is one hadith. Write {n} short questions that an ordinary person \
might type into a search box, which THIS hadith genuinely answers.

Rules:
- Use everyday plain English, the way a real person asks. Not scholarly phrasing.
- Vary the phrasing: some direct ("can I ...", "how do I ..."), some topical \
("rules about ...", "what did the Prophet say about ...").
- Only write questions this hadith actually answers. If it is a narrative with \
little practical content, write fewer questions rather than inventing any.
- Do NOT quote the hadith's own wording. The whole point is to capture how \
someone who has never read it would ask.
- Do not add rulings, opinions, or information that is not in the text.

Return ONLY a JSON array of strings. No commentary.

Hadith ({collection}, {book}):
{text}"""


def build_prompt(record):
    return PROMPT.format(
        n=N_QUESTIONS,
        collection=record.get("collection", "?"),
        book=record.get("book_name") or f"Book {record.get('book_number')}",
        text=" ".join(record["text"].split())[:4000],
    )


def parse_questions(raw):
    """Tolerant parsing: a JSON array is expected, but a model that wraps it
    in prose or a code fence should not cost us the whole record."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end > start:
        try:
            items = json.loads(raw[start:end + 1])
            return [str(q).strip() for q in items if str(q).strip()]
        except json.JSONDecodeError:
            pass
    # Last resort: one question per line.
    lines = [re.sub(r'^\s*[-*\d.)"\']+\s*', "", ln).strip().strip('",')
             for ln in raw.splitlines()]
    return [ln for ln in lines if ln.endswith("?")]


def make_client():
    try:
        import anthropic
    except ImportError:
        raise SystemExit("pip3 install anthropic")
    from env_config import load_env, ENV_PATH
    load_env()
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise SystemExit(
            "No API credentials found.\n\n"
            f"Create {ENV_PATH} containing one line:\n"
            "    ANTHROPIC_API_KEY=sk-ant-...\n\n"
            "(A key exported in an interactive shell is not visible here -- the\n"
            " shell environment is snapshotted at session start. The .env file is\n"
            " read at runtime instead, and is gitignored.)\n"
        )
    return anthropic.Anthropic()


def generate_one(client, record, model):
    kwargs = dict(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": build_prompt(record)}],
    )
    if model in ADAPTIVE_MODELS:
        # Writing questions for a passage in front of you is not a hard
        # reasoning task -- low effort keeps quality while cutting spend.
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "low"}
    resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        return [], resp.usage
    text = "".join(b.text for b in resp.content if b.type == "text")
    return parse_questions(text), resp.usage


def _progress_path(model):
    return os.path.join(OUT_DIR, f"progress_{model}.jsonl")


def load_progress(model):
    """Return {id: payload} already completed in a previous run."""
    path = _progress_path(model)
    done = {}
    if not os.path.exists(path):
        return done
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn final line from a hard kill; just drop it
            rid = rec.pop("id", None)
            if rid:
                done[rid] = rec
    return done


def generate(records, model, workers=8, progress=True, resume=True):
    """
    Generate questions for `records`, saving each result as it completes.

    WHY INCREMENTAL, AND WHY RESUME
    -------------------------------
    The first version of this held every result in memory and wrote the
    file only after the whole pool finished. That was fine for a 50-record
    sample and wrong for 14,940: a Ctrl+C at record 1,780 threw away every
    completed call and the money spent on it (~$1.50).

    Now each result is appended to a JSONL file the moment it lands, and a
    re-run skips whatever is already there. Stopping the job costs only
    the handful of calls in flight, and restarting picks up where it left
    off. JSONL rather than JSON specifically because it can be appended to
    without rewriting or re-parsing the whole file, and a torn last line
    from a hard kill costs one record instead of the entire file.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    done = load_progress(model) if resume else {}
    todo = [r for r in records if r["id"] not in done]

    if done:
        print(f"  resuming: {len(done)} already done, {len(todo)} remaining",
              file=sys.stderr, flush=True)
    if not todo:
        return done, {"input": 0, "output": 0}

    client = make_client()
    usage = {"input": 0, "output": 0}
    lock = threading.Lock()
    counter = [0]
    out_file = open(_progress_path(model), "a")

    def work(rec):
        try:
            qs, u = generate_one(client, rec, model)
            payload = {"questions": qs}
        except Exception as e:
            payload = {"error": f"{type(e).__name__}: {e}"}
            u = None
        with lock:
            if u is not None:
                usage["input"] += u.input_tokens
                usage["output"] += u.output_tokens
            # Persist BEFORE anything else can go wrong.
            out_file.write(json.dumps({"id": rec["id"], **payload},
                                      ensure_ascii=False) + "\n")
            out_file.flush()
            counter[0] += 1
            if progress and counter[0] % 25 == 0:
                print(f"    {counter[0]}/{len(todo)}", file=sys.stderr, flush=True)
        return rec["id"], payload

    interrupted = False
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, r) for r in todo]
            for fut in as_completed(futures):
                rid, payload = fut.result()
                done[rid] = payload
    except KeyboardInterrupt:
        interrupted = True
        print(f"\n  interrupted -- {counter[0]} results saved to "
              f"{_progress_path(model)}", file=sys.stderr, flush=True)
        print("  re-run the same command to resume from here.",
              file=sys.stderr, flush=True)
    finally:
        out_file.close()

    if interrupted:
        raise SystemExit(1)
    return done, usage



# ---------------------------------------------------------------- Batch API

def _batch_state_path(model):
    return os.path.join(OUT_DIR, f"batch_{model}.json")


# The Batch API enforces custom_id =~ ^[a-zA-Z0-9_-]{1,64}$.
#
# Deriving the custom_id from the hadith id by substitution looked fine and
# was not: ids like "bukhari:6895.2" (the structured source numbers some
# sub-narrations with a decimal) still carry an illegal '.' after the colon
# is replaced, and the whole 14,890-request batch is rejected on the first
# offender. Rather than chase which characters are legal, requests get
# plain sequential ids and the mapping back to hadith ids is stored
# alongside the batch. That cannot break on any id the corpus ever grows.
CUSTOM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def submit_batch(records, model):
    """
    Submit every record as one asynchronous batch at 50% of standard price.

    Batches run up to 24 hours (usually well under one), so the batch id is
    written to disk immediately. Losing the terminal, or Ctrl+C while
    polling, therefore cannot orphan a batch you have already paid for --
    re-running the same command finds the id and resumes waiting.
    """
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = make_client()
    requests = []
    id_map = {}
    for i, rec in enumerate(records):
        custom_id = f"r{i}"
        id_map[custom_id] = rec["id"]
        params = dict(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": build_prompt(rec)}],
        )
        if model in ADAPTIVE_MODELS:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": "low"}
        requests.append(Request(
            custom_id=custom_id,
            params=MessageCreateParamsNonStreaming(**params),
        ))

    # Validate locally before spending a round trip -- the API rejects the
    # ENTIRE batch on one bad id, so finding it here is much cheaper.
    bad = [r["custom_id"] for r in requests if not CUSTOM_ID_RE.match(r["custom_id"])]
    if bad:
        raise SystemExit(f"invalid custom_id(s), e.g. {bad[:3]}")

    batch = client.messages.batches.create(requests=requests)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_batch_state_path(model), "w") as f:
        json.dump({"batch_id": batch.id, "model": model,
                   "submitted": len(requests), "id_map": id_map}, f, indent=2)
    print(f"  submitted batch {batch.id} ({len(requests)} requests)")
    print(f"  batch id saved to {_batch_state_path(model)}")
    return batch.id


def wait_for_batch(batch_id, poll_seconds=30):
    import time
    client = make_client()
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return batch
        counts = batch.request_counts
        print(f"    {batch.processing_status}: {counts.succeeded} done, "
              f"{counts.processing} processing, {counts.errored} errored",
              file=sys.stderr, flush=True)
        time.sleep(poll_seconds)


def collect_batch(batch_id, model):
    """Append finished batch results to the same progress file the
    synchronous path writes, so downstream code cannot tell them apart."""
    client = make_client()
    state = json.load(open(_batch_state_path(model)))
    id_map = state.get("id_map", {})
    os.makedirs(OUT_DIR, exist_ok=True)
    n_ok = n_err = 0
    with open(_progress_path(model), "a") as out_file:
        for result in client.messages.batches.results(batch_id):
            rid = id_map.get(result.custom_id, result.custom_id)
            kind = result.result.type
            if kind == "succeeded":
                msg = result.result.message
                text = "".join(b.text for b in msg.content if b.type == "text")
                payload = {"questions": parse_questions(text)}
                n_ok += 1
            else:
                # errored / canceled / expired all mean "no output"; recorded
                # so a re-run retries only these rather than everything.
                payload = {"error": kind}
                n_err += 1
            out_file.write(json.dumps({"id": rid, **payload},
                                      ensure_ascii=False) + "\n")
    print(f"  collected: {n_ok} succeeded, {n_err} failed")
    return n_ok, n_err


def cost(usage, model):
    rates = {"claude-opus-5": (5, 25), "claude-sonnet-5": (2, 10),
             "claude-haiku-4-5": (1, 5), "claude-opus-4-8": (5, 25)}
    i, o = rates.get(model, (5, 25))
    return usage["input"] / 1e6 * i + usage["output"] / 1e6 * o


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--batch", action="store_true",
                    help="use the Batch API: 50%% of the price, asynchronous "
                         "(usually under an hour, up to 24h)")
    args = ap.parse_args()

    import random
    corpus = json.load(open(os.path.join(SCRIPT_DIR, "data", "corpus.json")))
    full_run = args.limit >= len(corpus)

    # The sample must include the hadith we have ground truth for, otherwise
    # the recall measurement afterwards has nothing to measure.
    gold_ids = ["bukhari:5971", "bukhari:6977", "muslim:6593", "bukhari:5889",
                "bukhari:5890", "bukhari:5891", "muslim:5265", "bukhari:7240",
                "bukhari:7488", "bukhari:6116", "muslim:6644", "muslim:5852",
                "muslim:5855", "bukhari:597", "bukhari:5778"]
    by_id = {r["id"]: r for r in corpus}
    if full_run:
        sample = corpus
        print(f"Generating questions for the FULL corpus "
              f"({len(sample)} hadith) with {args.model}...")
    else:
        sample = [by_id[i] for i in gold_ids if i in by_id]
        rest = [r for r in corpus if r["id"] not in set(gold_ids)]
        random.seed(args.seed)
        sample += random.sample(rest, max(0, args.limit - len(sample)))
        print(f"Generating questions for {len(sample)} hadith with {args.model} "
              f"({len(gold_ids)} ground-truth + {len(sample)-len(gold_ids)} random)...")

    if args.batch:
        done = load_progress(args.model)
        todo = [r for r in sample if r["id"] not in done]
        state_path = _batch_state_path(args.model)
        if os.path.exists(state_path):
            batch_id = json.load(open(state_path))["batch_id"]
            print(f"  found an existing batch ({batch_id}); waiting on it")
        elif not todo:
            batch_id = None
            print("  nothing left to generate")
        else:
            print(f"  submitting {len(todo)} requests to the Batch API "
                  f"(~50% of standard price)...")
            batch_id = submit_batch(todo, args.model)
        if batch_id:
            wait_for_batch(batch_id)
            collect_batch(batch_id, args.model)
            os.remove(state_path)
        results = load_progress(args.model)
        usage = {"input": 0, "output": 0}   # batch usage is reported in the Console
    else:
        results, usage = generate(sample, args.model)

    os.makedirs(OUT_DIR, exist_ok=True)
    prefix = "full" if full_run else "sample"
    path = os.path.join(OUT_DIR, f"{prefix}_{args.model}.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    ok = [v for v in results.values() if "questions" in v]
    errs = [v for v in results.values() if "error" in v]
    nq = sum(len(v["questions"]) for v in ok)
    c = cost(usage, args.model)
    print(f"\n  succeeded: {len(ok)}/{len(sample)}   failed: {len(errs)}")
    print(f"  questions generated: {nq} (avg {nq/max(len(ok),1):.1f}/hadith)")
    print(f"  tokens: {usage['input']:,} in / {usage['output']:,} out")
    print(f"  cost this run: ${c:.4f}   (only newly-generated records are billed)")
    if not full_run:
        per = c / max(len([v for v in ok]), 1)
        print(f"  extrapolated full corpus ({len(corpus)}): ${per*len(corpus):.2f} "
              f"(${per*len(corpus)/2:.2f} via Batch API)")
    if errs:
        print(f"\n  first error: {errs[0]['error']}")
    print(f"\n  wrote {path}")
