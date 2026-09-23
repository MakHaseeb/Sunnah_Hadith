# Hugging Face Spaces (Docker SDK).
#
# The search index is NOT built here. It is built once by publish_index.py and
# downloaded as a pinned artifact -- see that file for the full reasoning. The
# short version: embedding 184,557 chunks is the heaviest CPU work in the
# project, and asking a free Space's two shared cores to redo it on every
# build is what made the free tier look incapable of running this app. It is
# not. Downloading 300 MB takes a moment; recomputing it takes an hour.
#
# The corpus ships with its vectors rather than being rebuilt from the
# community CDN, because the embedding cache is keyed on the chunk text: if
# that source drifted by one character the cache would miss and the container
# would either re-embed everything or serve a corpus nobody had reviewed.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Torch pulls ~2GB of CUDA libraries by default and none of it is usable on a
# CPU-only Space. The CPU wheel is a fraction of the size and identical for
# our purposes, which keeps the image small enough to build quickly.
ENV PIP_NO_CACHE_DIR=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence-transformers

WORKDIR /app

# Torch first, from the CPU-only index. The default PyPI wheel drags in
# ~2GB of CUDA libraries that a CPU Space can never use.
#
# The version is pinned to match requirements.txt exactly. Installing a
# different torch here and letting the next step resolve the rest is what
# broke the first build: pip pulled the newest sentence-transformers, which
# required a newer transformers, which was incompatible with the torch
# already present -- "PyTorch was not found", then a NameError inside
# transformers. With both pinned to the same version, the second install
# sees its torch requirement already satisfied and leaves it alone.
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      torch==2.8.0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -c "import torch, sentence_transformers, transformers; \
print(f'torch {torch.__version__}, sentence-transformers {sentence_transformers.__version__}, transformers {transformers.__version__}')"

# ---- the pinned index artifact -------------------------------------------
# The manifest is copied on its own and FIRST, so this download layer is
# invalidated exactly when the index changes and not when ordinary code
# changes. A code-only deploy reuses the cached 300 MB rather than fetching
# it again.
COPY data/index_manifest.json ./data/index_manifest.json

# HF_TOKEN is a Space secret with read access to the private dataset holding
# the corpus and its vectors. required=true, and every file is checked against
# the SHA-256 in the manifest.
#
# This step FAILS THE BUILD if anything is missing or does not match. That is
# deliberate. The tempting alternative -- fall back to rebuilding from the
# CDN -- would quietly deploy a corpus nobody had reviewed, and this project
# has learned twice now (bugs #26, #28) that its worst failures are the ones
# that keep working while being wrong. A failed build is visible; a silently
# unpinned corpus is not.
ARG INDEX_REPO=haseebahmed0806/hadith-index
RUN --mount=type=secret,id=HF_TOKEN,mode=0444,required=true \
    set -eu; \
    BASE="https://huggingface.co/datasets/$INDEX_REPO/resolve/main"; \
    AUTH="Authorization: Bearer $(cat /run/secrets/HF_TOKEN)"; \
    mkdir -p data/cache; \
    EMB=$(python -c "import json;print(json.load(open('data/index_manifest.json'))['embedding_file'])"); \
    echo "fetching corpus and $EMB from $INDEX_REPO"; \
    curl -fsSL --retry 3 -H "$AUTH" -o data/corpus.json      "$BASE/corpus.json"; \
    curl -fsSL --retry 3 -H "$AUTH" -o "data/cache/$EMB"     "$BASE/$EMB"; \
    python -c "\
import hashlib, json, sys; \
m = json.load(open('data/index_manifest.json')); \
[sys.exit(f'{p}: sha256 mismatch -- artifact does not match the manifest') \
 for p, want in (('data/corpus.json', m['corpus_sha256']), \
                 ('data/cache/' + m['embedding_file'], m['embedding_sha256'])) \
 if hashlib.sha256(open(p,'rb').read()).hexdigest() != want]; \
print('artifact verified:', m['hadith'], 'hadith,', m['chunks'], 'chunks')"
# --------------------------------------------------------------------------

COPY . .

# Hugging Face rejects binary files in a normal git push, and the background
# photograph is the only binary in the project. Rather than require Git LFS
# just for one image, the deploy strips it from the push and the container
# fetches it from the public GitHub repo during the build. If the download
# ever fails the page still works -- the CSS falls back to a plain dark
# background -- so this cannot break the site.
ARG BG_URL=https://raw.githubusercontent.com/MakHaseeb/Sunnah_Hadith/main/web/static/bg-photo.jpg
RUN curl -fsSL --retry 3 -o web/static/bg-photo.jpg "$BG_URL" \
      && echo "background image fetched" \
      || echo "background image unavailable — page falls back to plain dark"

# Warm the sentence-transformers model into the image. Only the model is
# downloaded here -- nothing is embedded, because the vectors already exist.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('multi-qa-MiniLM-L6-cos-v1'); print('embedding model cached')"

# Prove the index loads and answers, so a broken artifact fails the BUILD
# rather than the first visitor.
RUN python -c "import json, sys, time; sys.path.insert(0,'.'); \
from hybrid_retrieve import HybridStore; from expansion import load_expansions; \
t=time.time(); \
s=HybridStore(json.load(open('data/corpus.json')), expansions=load_expansions()); \
assert s.retrieve('how should I treat my parents', k=3), 'retrieval returned nothing'; \
print(f'index ready: {len(s.hadiths)} hadith, {len(s.chunks)} chunks, {time.time()-t:.0f}s')"

# Spaces routes to 7860.
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "7860"]
