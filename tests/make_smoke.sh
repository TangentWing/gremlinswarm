#!/usr/bin/env bash
# Build a fresh smoke-test investigation from the kit and a fixture manifest.
# Usage: tests/make_smoke.sh [fixture-name]   (default: toy-ringbuf)
#
# Target: examples/<name>/ is used as-is, unless it has a build_target.py, in which case a
# fresh target is generated into targets/<name>/ first. The fixture's __TARGET_ROOT__ (and
# legacy __TOY_ROOT__) placeholders are replaced with the target path.
# Creates investigations/<name>/ (replacing a previous smoke-test copy of it).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:-toy-ringbuf}"
FIXTURE="$ROOT/tests/fixtures/$NAME.manifest.json"
EXAMPLE="$ROOT/examples/$NAME"
DIR="$ROOT/investigations/$NAME"
[ -f "$FIXTURE" ] || { echo "no fixture $FIXTURE"; exit 1; }
[ -d "$EXAMPLE" ] || { echo "no example $EXAMPLE"; exit 1; }
if [ -f "$EXAMPLE/build_target.py" ]; then
  TARGET="$ROOT/targets/$NAME"
  python3 "$EXAMPLE/build_target.py" --out "$TARGET"
else
  TARGET="$EXAMPLE"
fi
# Only replace a directory this script created (marked with .smoke-test).
if [ -e "$DIR" ] && [ ! -f "$DIR/.smoke-test" ]; then
  echo "refusing to replace $DIR: not created by make_smoke.sh"; exit 1
fi
rm -rf "$DIR" && mkdir -p "$DIR" && touch "$DIR/.smoke-test"
cp -R "$ROOT/investigate/kit/bin" "$ROOT/investigate/kit/prompts" "$ROOT/investigate/kit/archetypes" "$DIR/"
sed -e "s#__TARGET_ROOT__#$TARGET#g" -e "s#__TOY_ROOT__#$TARGET#g" "$FIXTURE" > "$DIR/manifest.json"
"$DIR/bin/board.py" validate
"$DIR/bin/board.py" scaffold
echo "ready: /investigate:run investigations/$NAME"
