#!/usr/bin/env sh
# Push a clean SNAPSHOT of the current commit to a Hugging Face Space (Docker SDK).
# - no git history (Hugging Face rejects old binary files in history)
# - the large design mockup is left out (not needed to run the app)
#
# Usage:   ./deploy_hf.sh <hf-username>/<space-name>
# Git will ask for a username (your HF username) and a password: paste an HF access
# token with WRITE permission (huggingface.co/settings/tokens). Never commit the token.
set -e
SPACE="$1"
if [ -z "$SPACE" ]; then echo "usage: ./deploy_hf.sh <hf-username>/<space-name>"; exit 1; fi
if ! git diff --quiet HEAD; then echo "Please commit your changes first."; exit 1; fi

TMP_INDEX="$(git rev-parse --git-dir)/hf-deploy-index"
GIT_INDEX_FILE="$TMP_INDEX" git read-tree HEAD
GIT_INDEX_FILE="$TMP_INDEX" git rm -q --cached --ignore-unmatch "Kisan Claim Mitra Mockup.html"
TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)
rm -f "$TMP_INDEX"
COMMIT=$(git commit-tree "$TREE" -m "Deploy $(git rev-parse --short HEAD)")

echo "Pushing snapshot $COMMIT to https://huggingface.co/spaces/$SPACE"
git push --force "https://huggingface.co/spaces/$SPACE" "$COMMIT:refs/heads/main"
echo "Done. Build logs: https://huggingface.co/spaces/$SPACE?logs=build"
