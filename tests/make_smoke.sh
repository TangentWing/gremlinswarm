#!/usr/bin/env bash
# Build a fresh smoke-test investigation from the kit and a fixture manifest.
# Usage: tests/make_smoke.sh [fixture-name]   (default: toy-ringbuf)
# Creates investigations/<fixture-name>/ (replacing a previous smoke-test copy of it).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:-toy-ringbuf}"
FIXTURE="$ROOT/tests/fixtures/$NAME.manifest.json"
TARGET="$ROOT/examples/$NAME"
DIR="$ROOT/investigations/$NAME"
[ -f "$FIXTURE" ] || { echo "no fixture $FIXTURE"; exit 1; }
[ -d "$TARGET" ] || { echo "no example target $TARGET"; exit 1; }
# Only replace a directory this script created (marked with .smoke-test).
if [ -e "$DIR" ] && [ ! -f "$DIR/.smoke-test" ]; then
  echo "refusing to replace $DIR: not created by make_smoke.sh"; exit 1
fi
rm -rf "$DIR" && mkdir -p "$DIR" && touch "$DIR/.smoke-test"
cp -R "$ROOT/investigate/kit/bin" "$ROOT/investigate/kit/prompts" "$DIR/"
sed "s#__TOY_ROOT__#$TARGET#g" "$FIXTURE" > "$DIR/manifest.json"
python3 "$DIR/bin/board.py" validate
python3 "$DIR/bin/board.py" scaffold
echo "ready: /investigate:run investigations/$NAME"
