#!/usr/bin/env bash
# End-to-end exercise of board.py against a throwaway investigation.
# Usage: tests/test_board.sh [workdir]   (exits non-zero on the first failed check)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="$HERE/../investigate/kit"
S="${1:-$(mktemp -d)}/board-test-inv"
# Only ever delete a directory this script created (marked with .board-test).
if [ -e "$S" ] && [ ! -f "$S/.board-test" ]; then
  echo "refusing to reuse $S: it exists and was not created by this test"; exit 1
fi
rm -rf "$S" && mkdir -p "$S/bin" && touch "$S/.board-test"
cp "$KIT/bin/board.py" "$S/bin/" && cp "$KIT/templates/manifest.example.json" "$S/manifest.json"
b() { python3 "$S/bin/board.py" "$@"; }
ok() { echo "  ok: $*"; }
fail() { echo "  FAIL: $*"; exit 1; }
expect_fail() { local why="$1"; shift; if "$@" >/dev/null 2>&1; then fail "expected rejection: $why"; else ok "rejected: $why"; fi; }

echo "== setup"
b validate >/dev/null && b scaffold >/dev/null && ok "validate + scaffold"

echo "== plans"
echo '{"tasks":[{"id":"static-r01-01","title":"Map IPC read path","objective":"Trace recv loop","deliverable":"call graph","resources":["repo"],"kind":"trace"},
 {"id":"static-r01-02","title":"Check alignment","objective":"Find unaligned casts","deliverable":"file:line list","deps":["static-r01-01"],"verify":"adversarial"}],"notes":"first pass"}' \
  | b plan save --lane static --as static/plan | grep -q '"version": 1' && ok "plan v1 saved with dispatch list"
expect_fail "unknown resource" sh -c "echo '{\"tasks\":[{\"id\":\"experiments-r01-01\",\"title\":\"x\",\"objective\":\"o\",\"deliverable\":\"d\",\"resources\":[\"nope\"]}]}' | python3 $S/bin/board.py plan save --lane experiments"
expect_fail "unknown dependency" sh -c "echo '{\"tasks\":[{\"id\":\"static-r01-09\",\"title\":\"x\",\"objective\":\"o\",\"deliverable\":\"d\",\"deps\":[\"ghost-r01-01\"]}]}' | python3 $S/bin/board.py plan save --lane static"
expect_fail "task id from another lane" sh -c "echo '{\"tasks\":[{\"id\":\"logs-r01-01\",\"title\":\"x\",\"objective\":\"o\",\"deliverable\":\"d\"}]}' | python3 $S/bin/board.py plan save --lane static"
expect_fail "over max_tasks_per_lane_round" sh -c "echo '{\"tasks\":[{\"id\":\"logs-r01-01\",\"title\":\"a\",\"objective\":\"o\",\"deliverable\":\"d\"},{\"id\":\"logs-r01-02\",\"title\":\"b\",\"objective\":\"o\",\"deliverable\":\"d\"},{\"id\":\"logs-r01-03\",\"title\":\"c\",\"objective\":\"o\",\"deliverable\":\"d\"},{\"id\":\"logs-r01-04\",\"title\":\"d\",\"objective\":\"o\",\"deliverable\":\"d\"}]}' | python3 $S/bin/board.py plan save --lane logs"

echo "== task lifecycle"
b task start --id static-r01-01 --as static/static-r01-01 | grep -q '"status": "running"' && ok "start -> running"
b task note --id static-r01-01 --text "recv loop in src/ipc/recv.c:40" --as static/static-r01-01 >/dev/null
[ "$(b task started --id static-r01-01 --what 'http.server on :9000' --stop 'kill 12345' --as static/static-r01-01)" = S1 ] && ok "side effect recorded as S1"
ID1=$(b post --lane static --kind finding --subject "recv casts buffer to struct hdr*" --body "src/ipc/recv.c:88 casts char* at offset 3" --tags ipc,alignment --refs src/ipc/recv.c:88 --confidence med --as static/static-r01-01)
ID2=$(b post --lane static --kind finding --subject "Header cast is misaligned" --body "same thing, other words" --tags alignment --as static/static-r01-01)
[ "$ID1" = B-static-0001 ] && [ "$ID2" = B-static-0002 ] && ok "board ids sequential ($ID1, $ID2)"
b task finish --id static-r01-01 --status done --summary "mapped; 1 suspicious cast" --board-ids "$ID1,$ID2" --as static/static-r01-01 | grep -q WARNING && ok "finish warns about unstopped side effect"
b leftovers | grep -q "kill 12345" && ok "leftovers lists it"
b task stopped --id static-r01-01 --ref S1 --as static/static-r01-01 >/dev/null
b leftovers | grep -q "no leftovers" && ok "stopped clears leftovers"
b task review --id static-r01-01 --verdict redo --summary "no caller evidence" --objection "cite callers" --as static/challenger >/dev/null
b plan show --lane static | grep -q "static-r01-01 \[needs_redo" && ok "redo verdict -> needs_redo in plan"

echo "== board: supersede, amend, query"
b post --lane shared --kind finding --subject "Misaligned header cast in recv path" --body merged --supersedes "$ID1,$ID2" --confidence med --as synth >/dev/null
b query --lane all | grep -q "$ID1" && fail "superseded entry still visible" || ok "superseded entries hidden"
b query --lane all --include-superseded | grep -q "$ID1" && ok "--include-superseded shows them"
b amend --id B-shared-0001 --set status=confirmed --note "experiment confirmed" --as judge >/dev/null
b query --lane shared --status confirmed | grep -q B-shared-0001 && ok "amend status -> confirmed"
[ "$(b query --lane shared --as someone/else | grep -c '^B-')" -ge 1 ] && ok "--as does not filter query results (regression: shared dest with --author)"
b query --lane shared --author synth | grep -q B-shared-0001 && ok "--author filters by author prefix"
b query --lane shared --author nobody | grep -q "no entries" && ok "--author with no match returns nothing"
b query --tag alignment --include-superseded --format json | python3 -c "import sys,json;[json.loads(l) for l in sys.stdin]" && ok "json format parses"

echo "== mail"
M=$(b mail send --to logs --subject "Which commit changed recv?" --body "need date" --type query --as static/plan)
R=$(b mail send --to nonexistent --subject "odd" --body "route me" --as logs/x)
[[ "$R" == M-skunkworks-* ]] && ok "unknown recipient rerouted to skunkworks"
b mail reply --id "$M" --body "commit abc on 2026-08-01" --as logs/logs-r01-01 >/dev/null
b mail list --lane static | grep -q "Re: Which commit" && ok "reply delivered to sender lane"
b mail list --lane logs | grep -q "$M" && fail "replied mail still open" || ok "original marked done"

echo "== human questions + steering"
Q=$(b ask --question "Which SSH key for armbox?" --context "publickey denied" --as experiments/experiments-r01-01)
b status | grep -q "Which SSH key" && ok "status surfaces open question"
b answer --id "$Q" --body "use ~/.ssh/arm_ed25519" >/dev/null
b questions | grep -q "no open questions" && ok "answer closes it"
b mail list --lane experiments | grep -q "Human answered" && ok "answer mailed to asking lane"
b steer list | grep -q "arm_ed25519" && ok "answer recorded as steering"
b steer add --body "Focus on alignment; ignore TLS" --lane static >/dev/null
b steer list --lane logs | grep -q "ignore TLS" && fail "lane steering leaked" || ok "lane-scoped steering filtered"

echo "== replan"
b task start --id static-r01-02 --as x >/dev/null   # simulate in-flight long task
expect_fail "resubmitting an in-flight task" sh -c "echo '{\"tasks\":[{\"id\":\"static-r01-02\",\"title\":\"t\",\"objective\":\"o\",\"deliverable\":\"d\"}]}' | python3 $S/bin/board.py plan save --lane static --inflight static-r01-02"
echo '{"tasks":[{"id":"static-r01-01","title":"Map IPC read path (redo)","objective":"Trace recv loop + callers","deliverable":"call graph"},{"id":"static-r02-01","title":"Callers of recv","objective":"o","deliverable":"d"}]}' \
  | b plan save --lane static --round 2 --inflight static-r01-02 --as static/plan >/dev/null
b plan show --lane static | grep -q "static-r01-01 \[queued/.*att2" && ok "needs_redo task requeued as attempt 2"
b plan show --lane static | grep -q "static-r01-02 \[running" && ok "in-flight task left running"
[ -f "$S/lanes/static/archive/plan.v001.json" ] && ok "previous plan archived"
expect_fail "dropped task still queued after drop" sh -c "echo '{\"tasks\":[{\"id\":\"static-r02-01\",\"title\":\"t\",\"objective\":\"o\",\"deliverable\":\"d\"}],\"drop\":[\"static-r01-01\"]}' | python3 $S/bin/board.py plan save --lane static --round 2 --inflight static-r01-02 && python3 $S/bin/board.py plan show --lane static | grep -q 'static-r01-01 \[queued'"

echo "== judge, state, wf-args"
echo '{"met":false,"progress":true,"gaps":["need reproducer"],"summary":"hypothesis formed"}' | b judge save --round 1 --as judge >/dev/null
python3 -c "import json;assert json.load(open('$S/state.json'))['round']==2" && ok "judge advances round to 2"
b wf-args --rounds 1 | python3 -c "import sys,json;a=json.load(sys.stdin);assert a['start_round']==2 and a['budget']['rounds_per_checkpoint']==1 and a['exclusive']==['armbox_port_9000'];print('  ok: wf-args', a['lanes'])"
b segment close --start 1 --end 1 --reason checkpoint >/dev/null && ok "segment closed"

echo "== write guard"
echo hi | b write --path lanes/static/scope/round-01.md >/dev/null && ok "write inside inv dir"
expect_fail "writing manifest.json" sh -c "echo hi | python3 $S/bin/board.py write --path manifest.json"
expect_fail "path escape" sh -c "echo hi | python3 $S/bin/board.py write --path ../escape.md"
expect_fail "writing a jsonl log" sh -c "echo hi | python3 $S/bin/board.py write --path shared/board.jsonl"

echo "== concurrency: 40 parallel posts"
for i in $(seq 1 40); do b post --lane logs --kind note --subject "n$i" --as logs/p >/dev/null & done; wait
python3 - "$S" <<'EOF'
import json, sys
ids = [json.loads(l)["id"] for l in open(sys.argv[1] + "/lanes/logs/board.jsonl")]
assert len(ids) == 40 and len(set(ids)) == 40, (len(ids), len(set(ids)))
print("  ok: 40 concurrent appends, 40 unique ids")
EOF
echo "ALL BOARD TESTS PASSED ($S)"
