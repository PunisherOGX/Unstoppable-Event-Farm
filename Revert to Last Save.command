#!/bin/bash

# Navigate to the project folder (same folder as this file)
cd "$(dirname "$0")"

echo ""
echo "⚠️  REVERT TO LAST SAVE"
echo "──────────────────────────────────────────"
echo "This will PERMANENTLY discard all changes"
echo "made since your last GitHub save."
echo ""
echo "Last save was:"
git log -1 --pretty=format:"  📌 \"%s\" on %cd" --date=format:"%b %d at %I:%M %p"
echo ""
echo "──────────────────────────────────────────"
echo ""
read -p "Are you sure? Type YES to confirm: " CONFIRM

if [ "$CONFIRM" != "YES" ]; then
  echo ""
  echo "❌ Revert cancelled. Nothing was changed."
  echo ""
  exit 0
fi

# Discard all uncommitted changes
git reset --hard HEAD
git clean -fd

echo ""
echo "✅ Reverted to last save successfully!"
echo ""
echo "You can close this window."
