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
  # -f because the background image is tracked on the original branch but
  # untracked on the orphan one, so a plain checkout refuses to overwrite it.
  # Safe: the file on disk is identical either way, only git's view differs.
  git checkout -qf "$ORIGINAL_BRANCH" 2>/dev/null || true
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

# Hugging Face refuses binary files in a plain git push and wants Git LFS
# for them. Rather than require an extra tool for a single image, the photo
# is left out of the push entirely -- the Dockerfile fetches it from the
# public GitHub repo while building.
echo "==> removing the background image (fetched at build time instead)"
git rm -q --cached web/static/bg-photo.jpg 2>/dev/null || true
echo "web/static/bg-photo.jpg" >> .gitignore
git add .gitignore

git commit -q -m "Space metadata header; background fetched during build"

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
