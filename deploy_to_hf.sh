#!/usr/bin/env bash
# Push this project to a Hugging Face Space.
#
# The Space gets a SINGLE COMMIT with no history. Two reasons:
#
#   1. Hugging Face rejects binary files in a plain git push and wants Git
#      LFS for them. The background photograph is the only binary here, and
#      requiring an extra tool for one image is a poor trade -- so it is left
#      out and the Dockerfile fetches it from the public GitHub repo while
#      building. Removing it from the latest commit alone was NOT enough:
#      Hugging Face scans every commit being pushed, and found it in the
#      commit that originally added it.
#
#   2. The Space has no use for the project history anyway, and the push is
#      far smaller without it.
#
# Your GitHub branch and README are left untouched whatever happens.
set -euo pipefail

SPACE="${1:-}"
if [ -z "$SPACE" ] || [[ "$SPACE" == *YOUR-USERNAME* ]] || [[ "$SPACE" != */* ]]; then
  cat <<'USAGE'
usage: ./deploy_to_hf.sh <hf-username>/<space-name>

  example: ./deploy_to_hf.sh haseebahmed0806/hadith-search

  Use your real username and Space name -- do not paste the placeholder.
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

echo "==> building a single-commit snapshot (no history)"
git branch -D hf-deploy >/dev/null 2>&1 || true
git checkout -q --orphan hf-deploy
git reset -q                                  # unstage everything inherited

echo "==> swapping in the Space README"
cp README.md README_GITHUB.md
cp README_SPACE.md README.md

echo "==> leaving the background image out (fetched during the build)"
git add -A
git rm -q --cached web/static/bg-photo.jpg README_GITHUB.md 2>/dev/null || true
git commit -q -m "Hadith Search — deployed from github.com/MakHaseeb/Sunnah_Hadith"

# Refuse to push if any binary slipped through, rather than discovering it
# from a rejected push.
if git ls-files -z | xargs -0 -I{} sh -c 'head -c 8000 "{}" | grep -qP "\x00" && echo "{}"' 2>/dev/null | grep -q .; then
  echo "A binary file is still staged. Aborting before the push."
  git ls-files -z | xargs -0 -I{} sh -c 'head -c 8000 "{}" | grep -qP "\x00" && echo "  {}"' 2>/dev/null
  exit 1
fi
echo "    snapshot: $(git ls-files | wc -l | tr -d ' ') files, $(git rev-list --count HEAD) commit, no binaries"

echo "==> pushing to https://huggingface.co/spaces/$SPACE"
echo
echo "    Username: your Hugging Face username"
echo "    Password: a WRITE access token from huggingface.co/settings/tokens"
echo
git remote add hf "https://huggingface.co/spaces/$SPACE"
git push -f hf hf-deploy:main

cat <<'DONE'

Pushed. The Space is building now -- expect 10-15 minutes the first time,
because PyTorch is installed and the search index is built during the build
so that visitors never wait for it.

Watch it under "Building" on the Space page.
DONE
