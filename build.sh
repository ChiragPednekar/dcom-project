#!/usr/bin/env bash
# Assemble the static stlite bundle in public/.
#
# The Python modules are COPIED here rather than committed twice, so the repo
# keeps one source of truth: edit app.py at the root and the browser build
# picks the change up on the next build.
set -e
cd "$(dirname "$0")"

MODULES="app.py huffman.py error_control.py channel.py pipeline.py ui_helpers.py make_plots.py"
for f in $MODULES; do
  cp "$f" "public/$f"
done
echo "Copied $(echo $MODULES | wc -w | tr -d ' ') Python modules into public/"
