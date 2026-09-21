#!/usr/bin/env bash
# Push this project to a Hugging Face Space.
#
# The Space needs a README.md with a metadata header that GitHub does not
# want, so the Space gets its own copy pushed onto a separate branch. Your
# GitHub README is left alone.
set -euo pipefail

SPACE="${1:-}"
if [ -z "$SPACE" ]; then
  echo "usage: ./deploy_to_hf.sh <your-hf-username>/<space-name>"
  echo "example: ./deploy_to_hf.sh MakHaseeb/hadith-search"
  exit 1
fi

echo "==> preparing a deploy branch"
git rev-parse --verify hf-deploy >/dev/null 2>&1 && git branch -D hf-deploy
git checkout -q -b hf-deploy

echo "==> swapping in the Space README (with its metadata header)"
cp README.md README_GITHUB.md
cp README_SPACE.md README.md
git add README.md README_GITHUB.md
git commit -q -m "Space metadata header for Hugging Face"

echo "==> pushing to https://huggingface.co/spaces/$SPACE"
git remote remove hf 2>/dev/null || true
git remote add hf "https://huggingface.co/spaces/$SPACE"
git push -f hf hf-deploy:main

echo "==> back to main"
git checkout -q main
git branch -D hf-deploy >/dev/null

cat <<'DONE'

Pushed. The Space will now build — expect 10-15 minutes the first time,
because it installs PyTorch and builds the search index during the build so
that visitors never wait for it.

Watch progress on the Space page under "Building".
DONE
