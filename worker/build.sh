#!/usr/bin/env bash
# Copy the parts of the backend the API needs into the Worker bundle.
# (Scrapers and their dependencies stay out: the Worker only serves data.)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/../backend/hackmash"
dst="$here/src/hackmash"
rm -rf "$dst"
mkdir -p "$dst"
for f in __init__.py api.py query.py ics.py models.py; do
  cp "$src/$f" "$dst/$f"
done
echo "bundled: $(ls "$dst" | tr '\n' ' ')"
