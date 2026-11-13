#!/bin/sh
# Simple launcher. Usage: ./start-stream.sh [twitch|youtube] [preset]
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD/src"
PLATFORM="${1:-twitch}"
PRESET="${2:-light}"
exec python3 -m lightstream start --platform "$PLATFORM" --preset "$PRESET"
