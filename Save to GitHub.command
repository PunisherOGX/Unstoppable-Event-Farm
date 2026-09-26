#!/bin/bash

# Navigate to the project folder (same folder as this file)
cd "$(dirname "$0")"

# Make sure this folder is its own git repo
if [ ! -d .git ]; then
  echo ""
  echo "⚠️  This folder is not a git repository yet."
  echo "Create the new repo on GitHub, then run here:"
  echo "    git init && git branch -M main"
  echo "    git remote add origin <your-new-repo-url>"
  echo ""
  exit 1
fi

# Make sure the remote exists
if ! git remote get-url origin > /dev/null 2>&1; then
  echo ""
  echo "⚠️  No git remote 'origin' found."
  echo "Please set one up: git remote add origin <your-repo-url>"
  echo ""
  exit 1
fi

# Prompt for a commit message
echo ""
echo "What would you like to name this save?"
read -p "> " COMMIT_MSG

# Fall back to timestamp if they just hit Enter
if [ -z "$COMMIT_MSG" ]; then
  COMMIT_MSG="save: $(date '+%Y-%m-%d %H:%M')"
fi

# Remove any stale git lock files
rm -f .git/index.lock .git/HEAD.lock .git/MERGE_HEAD.lock .git/CHERRY_PICK_HEAD.lock .git/packed-refs.lock
find .git/refs -name "*.lock" -delete 2>/dev/null

# Stage everything, commit, and push
git add -A

if git diff --staged --quiet; then
  echo "ℹ️  Nothing new to commit."
else
  git commit -m "$COMMIT_MSG" || { echo ""; echo "❌ Commit failed — see error above."; exit 1; }
fi

git push origin main

echo ""
echo "✅ Saved to GitHub!"
echo ""
echo "You can close this window."
