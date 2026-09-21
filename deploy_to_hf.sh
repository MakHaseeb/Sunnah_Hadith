#!/usr/bin/env bash
# Push this project to a Hugging Face Space.
#
# The Space needs a README.md carrying a metadata header that GitHub does not
# want, so the Space gets its own copy on a throwaway branch. Your GitHub
# README is left alone.
#
# Whatever happens -- success, failure, Ctrl+C -- the trap below puts you back
# on main with the right README. An earlier version exited on a failed push
# and left the repo stranded on the deploy branch.
set -euo pipefail

SPACE="${1:-}"
if [ -z "$SPACE" ] || [[ "$SPACE" == *YOUR-USERNAME* ]] || [[ "$SPACE" != */* ]]; then
  cat <<'USAGE'
usage: ./deploy_to_hf.sh <hf-username>/<space-name>

  example: ./deploy_to_hf.sh haseebahmed0806/hadith-search

  Replace the whole thing with your real username and Space name -- do not
  paste the placeholder.
USAGE
  exit 1
fi

ORIGINAL_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

cleanup() {
  git checkout -q "$ORIGINAL_BRANCH" 2>/dev/null || true
  git branch -D hf-deploy >/dev/null 2>&1 || true
  git remote remove hf >/dev/null 2>&1 || true
  rm -f README_GITHUB.md
}
trap cleanup EXIT

if [ -n "$(git status --porcelain)" ]; then
  echo "You have uncommitted changes. Commit or stash them first."
  exit 1
fi

echo "==> checking the Space exists"
if ! curl -sf -o /dev/null "https://huggingface.co/spaces/$SPACE"; then
  echo "Cannot reach https://huggingface.co/spaces/$SPACE"
  echo "Create the Space first (SDK: Docker), or check the name."
  exit 1
fi

echo "==> preparing a deploy branch"
git branch -D hf-deploy >/dev/null 2>&1 || true
git checkout -q -b hf-deploy

echo "==> swapping in the Space README"
cp README.md README_GITHUB.md
cp README_SPACE.md README.md
git add README.md README_GITHUB.md
git commit -q -m "Space metadata header for Hugging Face"

echo "==> pushing to https://huggingface.co/spaces/$SPACE"
echo
echo "    Username: your Hugging Face username"
echo "    Password: a WRITE access token from huggingface.co/settings/tokens"
echo "              (your account password will NOT work)"
echo
git remote add hf "https://huggingface.co/spaces/$SPACE"
git push -f hf hf-deploy:main

cat <<'DONE'

Pushed. The Space is now building -- expect 10-15 minutes the first time,
because PyTorch is installed and the search index is built during the build
so that visitors never wait for it.

Watch it under "Building" on the Space page.
DONE
