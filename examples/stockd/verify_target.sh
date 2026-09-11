#!/usr/bin/env bash
# Check that a built stockd target behaves as designed:
#   - unit tests pass at every commit that has them
#   - the integration test passes reliably before the race commit (stage 11)
#   - it fails intermittently (not never, not always) from the race commit on
# Usage: examples/stockd/verify_target.sh <out dir from build_target.py> [runs per commit, default 12]
set -euo pipefail
OUT="$(cd "$1" && pwd)"; RUNS="${2:-12}"
REPO="$OUT/repo"
WT="$(mktemp -d)/wt"
mapfile_commits() { git -C "$REPO" rev-list --reverse main; }
COMMITS=($(mapfile_commits))
check() {  # $1 = stage (1-based commit index), prints "stage sha fails/runs"
  local stage=$1 sha=${COMMITS[$(( $1 - 1 ))]} f=0
  git -C "$REPO" worktree add -q --detach "$WT" "$sha"
  (cd "$WT" && python3 -m unittest discover -s tests -t . -p 'test_inventory.py' >/dev/null 2>&1) \
    || { echo "stage $stage ${sha:0:7}: UNIT TESTS FAIL"; git -C "$REPO" worktree remove --force "$WT"; exit 1; }
  for _ in $(seq 1 "$RUNS"); do (cd "$WT" && python3 -m unittest tests.test_integration >/dev/null 2>&1) || f=$((f + 1)); done
  git -C "$REPO" worktree remove --force "$WT"
  echo "$f"
}
status=0
for stage in 8 9 10; do
  f=$(check $stage); echo "stage $stage (before race): $f/$RUNS failures"
  [ "$f" -eq 0 ] || { echo "  FAIL: pre-race commit should never fail"; status=1; }
done
for stage in 11 13 18; do
  f=$(check $stage); echo "stage $stage (race present): $f/$RUNS failures"
  { [ "$f" -gt 0 ] && [ "$f" -lt "$RUNS" ]; } || { echo "  FAIL: should fail intermittently"; status=1; }
done
[ $status -eq 0 ] && echo "TARGET BEHAVES AS DESIGNED" || echo "TARGET CHECK FAILED"
exit $status
