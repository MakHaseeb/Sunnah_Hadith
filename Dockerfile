# Hugging Face Spaces (Docker SDK).
#
# The search index takes about four minutes to build. That is fine once and
# intolerable on every cold start, so it is built HERE, during the image
# build, and baked into the image. A Space that wakes from sleep then serves
# its first visitor immediately instead of making them wait.
FROM python:3.11-slim

# Torch pulls ~2GB of CUDA libraries by default and none of it is usable on a
# CPU-only Space. The CPU wheel is a fraction of the size and identical for
# our purposes, which keeps the image small enough to build quickly.
ENV PIP_NO_CACHE_DIR=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence-transformers

WORKDIR /app

RUN pip install --no-cache-dir \
      torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

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
