"""
LLM relevance gate: decide whether a retrieved hadith ACTUALLY answers the
question, instead of inferring it from a similarity score.

WHY A DIFFERENT MECHANISM IS REQUIRED
-------------------------------------
Similarity scoring cannot do this job, and there is a decisive measurement
proving it. On the query "actions are judged by intentions":

    bukhari:1   (the CORRECT answer) ............ 0.511
    "recipe for chicken biryani" (junk query) ... 0.527
    muslim:7228 (a WRONG hadith) ................ 0.703

The correct answer scores LOWER than an unrelated query. Any threshold
admitting bukhari:1 also admits the junk; any threshold rejecting the junk
also rejects the correct answer. No amount of tuning fixes that, because
the score measures textual similarity and the question being asked is
"does this passage answer this question" -- a different question.

An LLM can be asked the actual question directly.

ARCHITECTURE
------------
Retrieval (free) casts a WIDE net -- a deliberately permissive similarity
gate -- and the LLM judges only the shortlist. This keeps the per-query
cost to one small call instead of paying to reason about 13,284 hadith,
and keeps obvious junk from reaching the model at all.

The model is asked to be STRICT: an answer that is merely on the same
topic is not an answer. For religious content, returning "no clear answer"
is the correct output far more often than a loosely-related hadith, and
the prompt says so explicitly.
"""
import json
import os
import re

MODEL = "claude-haiku-4-5"
SHORTLIST = 5
MAX_CHARS = 700

PROMPT = """A user asked this question:

    {question}

Below are {n} hadith retrieved by a search system. For EACH one, decide \
whether it genuinely answers the user's question.

Be strict. A hadith that is merely on a related topic does NOT answer the \
question. A hadith that mentions a word from the question but addresses \
something else does NOT answer it. Only say yes if a person reading this \
hadith would consider their question answered.

{candidates}

Return ONLY a JSON array, one object per hadith, in order:
[{{"n": 1, "answers": true|false, "why": "<8 words max>"}}, ...]"""


def build_prompt(question, candidates):
    blocks = []
    for i, (hadith, _score) in enumerate(candidates, 1):
        text = " ".join(hadith["text"].split())[:MAX_CHARS]
        blocks.append(f"[{i}] {text}")
    return PROMPT.format(question=question, n=len(candidates),
                         candidates="\n\n".join(blocks))


def _parse(raw, n):
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start, end = raw.find("["), raw.rfind("]")
    verdicts = [{"answers": False, "why": "unparsed"} for _ in range(n)]
    if start == -1 or end <= start:
        return verdicts
    try:
        items = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return verdicts
    for item in items:
        try:
            idx = int(item.get("n", 0)) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < n:
            verdicts[idx] = {"answers": bool(item.get("answers")),
                             "why": str(item.get("why", ""))[:60]}
    return verdicts


# ---------------------------------------------------------------------------
# Providers
#
# The relevance check is one small, well-defined judgement -- "does this
# passage answer this question" -- repeated once per search. That makes it
# the one place in this app where the model is genuinely swappable, and
# worth keeping swappable: it is also the only recurring cost.
#
# Groq is here because its free tier needs no credit card. For a personal
# project with no budget that is not a marginal saving, it is the
# difference between the relevance check running and not running -- and
# with it switched off the app drops from roughly 80% to 25% correct.
#
# WHAT IS NOT ASSUMED: that a smaller model does this job as well. The
# check is the single change that produced that 80%, so a provider swap
# has to be MEASURED against the evaluation harness before it is trusted.
# compare_providers.py exists for exactly that.
# ---------------------------------------------------------------------------

GROQ_MODEL = os.environ.get("HADITH_GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class _Usage:
    """Mimics the field names the Anthropic SDK returns, so callers that
    log token counts do not have to care which provider answered."""

    def __init__(self, input_tokens=0, output_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class AnthropicClient:
    name = "anthropic"

    def __init__(self, model=None):
        import anthropic
        self.model = model or MODEL
        self._c = anthropic.Anthropic()

    def complete(self, prompt, max_tokens=600):
        kwargs = dict(model=self.model, max_tokens=max_tokens,
                      messages=[{"role": "user", "content": prompt}])
        if self.model.startswith("claude-opus") or self.model.startswith("claude-sonnet-5"):
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": "low"}
        resp = self._c.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            return None, resp.usage
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, resp.usage


class GroqClient:
    """
    Groq's OpenAI-compatible endpoint, called over plain HTTP.

    No SDK on purpose: this is one POST with a JSON body, and adding a
    dependency to a container that already ships 300 MB of vectors to save
    ten lines is a poor trade.
    """

    name = "groq"

    def __init__(self, model=None):
        import httpx
        self.model = model or GROQ_MODEL
        self._key = os.environ.get("GROQ_API_KEY", "").strip()
        self._http = httpx.Client(timeout=60.0)

    def complete(self, prompt, max_tokens=600):
        r = self._http.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {self._key}",
                     "Content-Type": "application/json"},
            json={"model": self.model, "max_tokens": max_tokens,
                  "temperature": 0,
                  "messages": [{"role": "user", "content": prompt}]},
        )
        if r.status_code != 200:
            raise RuntimeError(f"groq {r.status_code}: {r.text[:200]}")
        d = r.json()
        u = d.get("usage") or {}
        return (d["choices"][0]["message"]["content"],
                _Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)))


def make_client(provider=None, model=None):
    """
    Pick a provider. Explicit argument wins, then HADITH_LLM_PROVIDER, then
    whichever key is actually present -- so a key running out does not have
    to mean editing config to fall back to the other one.
    """
    from env_config import load_env
    load_env()
    provider = (provider or os.environ.get("HADITH_LLM_PROVIDER", "")).strip().lower()
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY")
                         or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    has_groq = bool(os.environ.get("GROQ_API_KEY"))
    if not provider:
        provider = "anthropic" if has_anthropic else ("groq" if has_groq else "")
    if provider == "groq":
        if not has_groq:
            raise SystemExit("HADITH_LLM_PROVIDER=groq but GROQ_API_KEY is not set.")
        return GroqClient(model)
    if provider == "anthropic":
        if not has_anthropic:
            raise SystemExit("HADITH_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set.")
        return AnthropicClient(model)
    raise SystemExit("No API credentials. Set ANTHROPIC_API_KEY or GROQ_API_KEY — see .env.example")


class Unavailable(Exception):
    """The relevance check could not run -- no credit, rate limited, network
    down. Distinct from 'the model said no': the caller must be able to tell
    'this hadith does not answer the question' from 'we could not ask'."""


def check(question, candidates, client=None, model=MODEL):
    """
    candidates: [(hadith, score)]. Returns (verdicts, usage).
    A verdict is {"answers": bool, "why": str} aligned to candidates.

    Raises Unavailable if the call itself could not be made. Returning
    "nothing answers this" in that case would be a lie that looks exactly
    like a confident refusal -- the user would be told no hadith addresses
    their question when in truth nobody looked.
    """
    if not candidates:
        return [], None
    client = client or make_client()
    try:
        text, usage = client.complete(build_prompt(question, candidates))
    except Exception as e:
        raise Unavailable(str(e)) from e
    if text is None:                      # the model declined to answer
        return [{"answers": False, "why": "refused"} for _ in candidates], usage
    return _parse(text, len(candidates)), usage


def filter_relevant(question, retrieved, client=None, model=MODEL, k=SHORTLIST):
    """
    Return only the retrieved items the model says actually answer the
    question, preserving retrieval order.

    Propagates Unavailable so the caller can fall back to plain search
    rather than showing the user an error page.
    """
    short = retrieved[:k]
    pairs = [(item[0], item[4]) for item in short]
    verdicts, usage = check(question, pairs, client=client, model=model)
    kept = [item for item, v in zip(short, verdicts) if v["answers"]]
    return kept, verdicts, usage
