#!/usr/bin/env bash
# Launch IoTGuard. Creates the virtualenv on first run.
set -e
cd "$(dirname "$0")"

# On exFAT/FAT drives macOS can't store extended attributes inline, so Finder
# writes them as "._name" AppleDouble sidecars. matplotlib globs *.mplstyle,
# picks up the binary sidecars and dies on a UnicodeDecodeError. Sweep them.
if find . -name '._*' -type f -print -quit 2>/dev/null | grep -q .; then
  echo "Removing macOS AppleDouble sidecar files…"
  find . -name '._*' -type f -delete 2>/dev/null || true
fi

# Invoke streamlit via "python -m" rather than .venv/bin/streamlit: the wrapper
# scripts bake in an absolute path at creation time, so they break if the
# project folder is ever moved or copied to another drive. This form doesn't.
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import streamlit, matplotlib.pyplot" 2>/dev/null; then
  echo "Setting up the virtual environment…"
  rm -rf .venv
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi

exec .venv/bin/python -m streamlit run app.py
