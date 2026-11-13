#!/bin/sh
# Opens the easy streaming window.
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD/src"
exec python3 -m lightstream gui
