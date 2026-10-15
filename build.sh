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

# Self-host the stlite runtime instead of loading it from cdn.jsdelivr.net.
# stlite lazy-loads each UI component (the Plotly chart is a 4.7 MB chunk) as
# a separate download; when a jsdelivr edge had not cached a chunk the request
# could hang until the browser gave up with "Failed to fetch dynamically
# imported module". Serving the files from this deployment removes that
# third-party dependency. Source maps are dropped to keep the deploy small.
STLITE_VERSION="0.83.1"
STLITE_DIR="public/stlite"
if [ "$(cat "$STLITE_DIR/.version" 2>/dev/null)" != "$STLITE_VERSION" ]; then
  tmp="$(mktemp -d)"
  (cd "$tmp" && npm pack --silent "@stlite/browser@$STLITE_VERSION" >/dev/null)
  tar -xzf "$tmp/stlite-browser-$STLITE_VERSION.tgz" -C "$tmp"
  rm -rf "$STLITE_DIR"
  mkdir -p "$STLITE_DIR"
  cp -R "$tmp/package/build/." "$STLITE_DIR/"
  find "$STLITE_DIR" -name '*.map' -delete
  echo "$STLITE_VERSION" > "$STLITE_DIR/.version"
  rm -rf "$tmp"
  echo "Bundled stlite $STLITE_VERSION into $STLITE_DIR/"
fi
