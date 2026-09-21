# Hugging Face Spaces (Docker SDK).
#
# The search index takes about four minutes to build. That is fine once and
# intolerable on every cold start, so it is built HERE, during the image
# build, and baked into the image. A Space that wakes from sleep then serves
# its first visitor immediately instead of making them wait.
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

# Fetch the collections, assemble the corpus, download the embedding model
# and build the index -- all now, so none of it happens while someone waits.
# The cross-check against the PDF is skipped: the PDF is not in the repo, and
# build_corpus falls back to the structured source alone, which only means
# records show as "single source" rather than "cross-checked".
RUN python load_structured.py \
 && python build_corpus.py \
 && python -c "import json, sys; sys.path.insert(0,'.'); \
from hybrid_retrieve import HybridStore; from expansion import load_expansions; \
c=json.load(open('data/corpus.json')); \
s=HybridStore(c, expansions=load_expansions()); \
print(f'index built: {len(s.hadiths)} hadith, {len(s.chunks)} chunks')"

# Spaces routes to 7860.
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "7860"]
