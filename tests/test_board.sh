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
{ b validate >/dev/null && b scaffold >/dev/null; } || fail "validate + scaffold"; ok "validate + scaffold"

echo "== plans"
{ echo '{"tasks":[{"id":"static-r01-01","title":"Map IPC read path","objective":"Trace recv loop","deliverable":"call graph","resources":["repo"],"kind":"trace"},
 {"id":"static-r01-02","title":"Check alignment","objective":"Find unaligned casts","deliverable":"file:line list","deps":["static-r01-01"],"verify":"adversarial"}],"notes":"first pass"}' \
  | b plan save --lane static --as static/plan | grep -q '"version": 1'; } || fail "plan v1 saved with dispatch list"; ok "plan v1 saved with dispatch list"
expect_fail "unknown resource" sh -c "echo '{\"tasks\":[{\"id\":\"experiments-r01-01\",\"title\":\"x\",\"objective\":\"o\",\"deliverable\":\"d\",\"resources\":[\"nope\"]}]}' | python3 $S/bin/board.py plan save --lane experiments"
expect_fail "unknown dependency" sh -c "echo '{\"tasks\":[{\"id\":\"static-r01-09\",\"title\":\"x\",\"objective\":\"o\",\"deliverable\":\"d\",\"deps\":[\"ghost-r01-01\"]}]}' | python3 $S/bin/board.py plan save --lane static"
expect_fail "task id from another lane" sh -c "echo '{\"tasks\":[{\"id\":\"logs-r01-01\",\"title\":\"x\",\"objective\":\"o\",\"deliverable\":\"d\"}]}' | python3 $S/bin/board.py plan save --lane static"
expect_fail "over max_tasks_per_lane_round" sh -c "echo '{\"tasks\":[{\"id\":\"logs-r01-01\",\"title\":\"a\",\"objective\":\"o\",\"deliverable\":\"d\"},{\"id\":\"logs-r01-02\",\"title\":\"b\",\"objective\":\"o\",\"deliverable\":\"d\"},{\"id\":\"logs-r01-03\",\"title\":\"c\",\"objective\":\"o\",\"deliverable\":\"d\"},{\"id\":\"logs-r01-04\",\"title\":\"d\",\"objective\":\"o\",\"deliverable\":\"d\"}]}' | python3 $S/bin/board.py plan save --lane logs"

echo "== task lifecycle"
{ b task start --id static-r01-01 --as static/static-r01-01 | grep -q '"status": "running"'; } || fail "start -> running"; ok "start -> running"
b task note --id static-r01-01 --text "recv loop in src/ipc/recv.c:40" --as static/static-r01-01 >/dev/null
{ [ "$(b task started --id static-r01-01 --what 'http.server on :9000' --stop 'kill 12345' --as static/static-r01-01)" = S1 ]; } || fail "side effect recorded as S1"; ok "side effect recorded as S1"
ID1=$(b post --lane static --kind finding --subject "recv casts buffer to struct hdr*" --body "src/ipc/recv.c:88 casts char* at offset 3" --tags ipc,alignment --refs src/ipc/recv.c:88 --confidence med --as static/static-r01-01)
ID2=$(b post --lane static --kind finding --subject "Header cast is misaligned" --body "same thing, other words" --tags alignment --as static/static-r01-01)
{ [ "$ID1" = B-static-0001 ] && [ "$ID2" = B-static-0002 ]; } || fail "board ids sequential ($ID1, $ID2)"; ok "board ids sequential ($ID1, $ID2)"
{ b task finish --id static-r01-01 --status done --summary "mapped; 1 suspicious cast" --board-ids "$ID1,$ID2" --as static/static-r01-01 | grep -q WARNING; } || fail "finish warns about unstopped side effect"; ok "finish warns about unstopped side effect"
{ b leftovers | grep -q "kill 12345"; } || fail "leftovers lists it"; ok "leftovers lists it"
b task stopped --id static-r01-01 --ref S1 --as static/static-r01-01 >/dev/null
{ b leftovers | grep -q "no leftovers"; } || fail "stopped clears leftovers"; ok "stopped clears leftovers"
b task review --id static-r01-01 --verdict redo --summary "no caller evidence" --objection "cite callers" --as static/challenger >/dev/null
{ b plan show --lane static | grep -q "static-r01-01 \[needs_redo"; } || fail "redo verdict -> needs_redo in plan"; ok "redo verdict -> needs_redo in plan"

echo "== board: supersede, amend, query"
b post --lane shared --kind finding --subject "Misaligned header cast in recv path" --body merged --supersedes "$ID1,$ID2" --confidence med --as synth >/dev/null
b query --lane all | grep -q "$ID1" && fail "superseded entry still visible" || ok "superseded entries hidden"
{ b query --lane all --include-superseded | grep -q "$ID1"; } || fail "--include-superseded shows them"; ok "--include-superseded shows them"
b amend --id B-shared-0001 --set status=confirmed --note "experiment confirmed" --as judge >/dev/null
{ b query --lane shared --status confirmed | grep -q B-shared-0001; } || fail "amend status -> confirmed"; ok "amend status -> confirmed"
{ [ "$(b query --lane shared --as someone/else | grep -c '^B-')" -ge 1 ]; } || fail "--as does not filter query results (regression: shared dest with --author)"; ok "--as does not filter query results (regression: shared dest with --author)"
{ b query --lane shared --author synth | grep -q B-shared-0001; } || fail "--author filters by author prefix"; ok "--author filters by author prefix"
{ b query --lane shared --author nobody | grep -q "no entries"; } || fail "--author with no match returns nothing"; ok "--author with no match returns nothing"
{ b query --tag alignment --include-superseded --format json | python3 -c "import sys,json;[json.loads(l) for l in sys.stdin]"; } || fail "json format parses"; ok "json format parses"

echo "== mail"
M=$(b mail send --to logs --subject "Which commit changed recv?" --body "need date" --type query --as static/plan)
R=$(b mail send --to nonexistent --subject "odd" --body "route me" --as logs/x)
{ [[ "$R" == M-skunkworks-* ]]; } || fail "unknown recipient rerouted to skunkworks"; ok "unknown recipient rerouted to skunkworks"
b mail reply --id "$M" --body "commit abc on 2026-08-01" --as logs/logs-r01-01 >/dev/null
{ b mail list --lane static | grep -q "Re: Which commit"; } || fail "reply delivered to sender lane"; ok "reply delivered to sender lane"
b mail list --lane logs | grep -q "$M" && fail "replied mail still open" || ok "original marked done"

echo "== human questions + steering"
Q=$(b ask --question "Which SSH key for armbox?" --context "publickey denied" --as experiments/experiments-r01-01)
{ b status | grep -q "Which SSH key"; } || fail "status surfaces open question"; ok "status surfaces open question"
b answer --id "$Q" --body "use ~/.ssh/arm_ed25519" >/dev/null
{ b questions | grep -q "no open questions"; } || fail "answer closes it"; ok "answer closes it"
{ b mail list --lane experiments | grep -q "Human answered"; } || fail "answer mailed to asking lane"; ok "answer mailed to asking lane"
{ b steer list | grep -q "arm_ed25519"; } || fail "answer recorded as steering"; ok "answer recorded as steering"
b steer add --body "Focus on alignment; ignore TLS" --lane static >/dev/null
b steer list --lane logs | grep -q "ignore TLS" && fail "lane steering leaked" || ok "lane-scoped steering filtered"

echo "== replan"
b task start --id static-r01-02 --as x >/dev/null   # simulate in-flight long task
expect_fail "resubmitting an in-flight task" sh -c "echo '{\"tasks\":[{\"id\":\"static-r01-02\",\"title\":\"t\",\"objective\":\"o\",\"deliverable\":\"d\"}]}' | python3 $S/bin/board.py plan save --lane static --inflight static-r01-02"
echo '{"tasks":[{"id":"static-r01-01","title":"Map IPC read path (redo)","objective":"Trace recv loop + callers","deliverable":"call graph"},{"id":"static-r02-01","title":"Callers of recv","objective":"o","deliverable":"d"}]}' \
  | b plan save --lane static --round 2 --inflight static-r01-02 --as static/plan >/dev/null
{ b plan show --lane static | grep -q "static-r01-01 \[queued/.*att2"; } || fail "needs_redo task requeued as attempt 2"; ok "needs_redo task requeued as attempt 2"
{ b plan show --lane static | grep -q "static-r01-02 \[running"; } || fail "in-flight task left running"; ok "in-flight task left running"
{ [ -f "$S/lanes/static/archive/plan.v001.json" ]; } || fail "previous plan archived"; ok "previous plan archived"
expect_fail "dropped task still queued after drop" sh -c "echo '{\"tasks\":[{\"id\":\"static-r02-01\",\"title\":\"t\",\"objective\":\"o\",\"deliverable\":\"d\"}],\"drop\":[\"static-r01-01\"]}' | python3 $S/bin/board.py plan save --lane static --round 2 --inflight static-r01-02 && python3 $S/bin/board.py plan show --lane static | grep -q 'static-r01-01 \[queued'"

echo "== judge, state, wf-args"
echo '{"met":false,"progress":true,"gaps":["need reproducer"],"summary":"hypothesis formed"}' | b judge save --round 1 --as judge >/dev/null
{ python3 -c "import json;assert json.load(open('$S/state.json'))['round']==2"; } || fail "judge advances round to 2"; ok "judge advances round to 2"
b wf-args --rounds 1 | python3 -c "import sys,json;a=json.load(sys.stdin);assert a['start_round']==2 and a['budget']['rounds_per_checkpoint']==1 and a['exclusive']==['armbox_port_9000'];print('  ok: wf-args', a['lanes'])"
{ b segment close --start 1 --end 1 --reason checkpoint >/dev/null; } || fail "segment closed"; ok "segment closed"

echo "== brief + executable CLI"
cp -R "$KIT/prompts" "$S/"
B=$(b wf-args | python3 -c "import sys,json;print(json.load(sys.stdin)['board'])")
{ [ -x "$B" ] && [ "$(cd "$(dirname "$B")" && pwd -P)/board.py" = "$(cd "$S/bin" && pwd -P)/board.py" ]; } || fail "wf-args board is a single executable path"; ok "wf-args board is a single executable path"
{ zsh -c "X=$B; \$X status >/dev/null"; } || fail "board path works from a zsh variable (no word-splitting needed)"; ok "board path works from a zsh variable (no word-splitting needed)"
OUT=$("$B" brief --role scope --lane static --as static/scope)
for want in "Investigation protocol" "Scope agent" "Lane: static" "Manifest essentials" "state: board.py plan show --lane static" "state: board.py steer list --lane static" "end of brief"; do
  grep -q "$want" <<<"$OUT" || fail "brief (scope) missing: $want"
done; ok "brief --role scope has protocol, role, lane, manifest and lane state"
{ grep -q "EXCLUSIVE" <<<"$OUT" && grep -q "armbox_port_9000" <<<"$OUT"; } || fail "brief lists resources with exclusivity"; ok "brief lists resources with exclusivity"
{ "$B" brief --role challenger --lane static --task static-r01-01 | grep -q '"id": "static-r01-01"'; } || fail "brief --role challenger includes task show"; ok "brief --role challenger includes task show"
{ "$B" brief --role plan --lane static --round 1 | grep -q "Scope brief (round 1)"; } || fail "brief --role plan includes the scope brief"; ok "brief --role plan includes the scope brief"
{ "$B" brief --role judge | grep -q "state: board.py judge show"; } || fail "brief --role judge includes the last verdict"; ok "brief --role judge includes the last verdict"
expect_fail "brief with unknown role" "$B" brief --role wizard

echo "== archetypes"
cp -R "$KIT/archetypes" "$S/"
{ b archetypes | grep -q "^bisect "; } || fail "archetypes lists bisect"; ok "archetypes lists the baseline set"
[ "$(b archetypes | grep -c '^[a-z]')" -eq 9 ] || fail "expected 9 archetypes"; ok "9 archetypes, all valid"
{ b archetypes --show static-trace | grep -q "{{mandate}}"; } || fail "archetypes --show"; ok "archetypes --show prints the template"
cp "$S/archetypes/_template.md" "$S/archetypes/broken.md"
expect_fail "archetype whose name doesn't match its file" b archetypes
rm "$S/archetypes/broken.md"
# a second investigation that uses archetypes and resource checks
S2="$S-arch"; rm -rf "$S2"; mkdir -p "$S2"; cp -R "$S/bin" "$S/prompts" "$S/archetypes" "$S2/"
python3 - "$S/manifest.json" "$S2/manifest.json" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
for l in m["lanes"]:
    l.pop("verify_default", None)
m["lanes"][0]["archetype"] = "static-trace"
m["lanes"][2]["archetype"] = "repro-experiment"
m["resources"][0]["check"] = "test -d /"
m["resources"][1]["check"] = "exit 3"
json.dump(m, open(sys.argv[2], "w"))
EOF
b2() { python3 "$S2/bin/board.py" "$@"; }
{ b2 validate | grep -q "manifest OK"; } || fail "manifest with archetypes validates"; ok "manifest with archetypes validates"
b2 scaffold >/dev/null
{ grep -q "^## Method" "$S2/lanes/static/lane.md" && grep -q "symptom's entry point" "$S2/lanes/static/lane.md"; } || fail "lane.md rendered from archetype"; ok "lane.md rendered from the archetype template"
{ ! grep -q "{{" "$S2/lanes/static/lane.md"; } || fail "unreplaced placeholder in lane.md"; ok "all placeholders replaced"
{ grep -q '`repo` \[local-repo\]' "$S2/lanes/static/lane.md"; } || fail "resources rendered with kind"; ok "resources rendered with kind and access"
{ grep -q "EXCLUSIVE" "$S2/lanes/experiments/lane.md"; } || fail "exclusive resource flagged in lane.md"; ok "exclusive resources flagged in lane.md"
{ echo '{"tasks":[{"id":"static-r01-01","title":"t","objective":"o","deliverable":"d"}]}' | b2 plan save --lane static | grep -q '"verify": "adversarial"'; } || fail "verify default from archetype"; ok "task verify defaults to the archetype's (adversarial)"
python3 - "$S2/manifest.json" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1])); m["lanes"][1]["archetype"] = "no-such-thing"; json.dump(m, open(sys.argv[1], "w"))
EOF
expect_fail "unknown archetype in manifest" b2 validate
python3 - "$S2/manifest.json" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1])); m["lanes"][1].pop("archetype"); json.dump(m, open(sys.argv[1], "w"))
EOF

echo "== resource probes"
{ b2 probe --resource repo | grep -q "^ok   repo"; } || fail "passing check"; ok "probe reports a passing check"
expect_fail "probe exits non-zero when a check fails" b2 probe
{ (b2 probe 2>/dev/null || true) | grep -q "^FAIL armbox: exit 3"; } || fail "failing check reported"; ok "probe reports the failing check with its exit code"
{ b2 probe --resource ci_logs | grep -q "no check defined"; } || fail "missing check"; ok "resources without a check are reported, not failed"
{ b2 brief --role scope --lane static | grep -q "state: board.py probe --lane static"; } || fail "scope brief runs probes"; ok "scope brief includes the lane's probe results"

echo "== sweeps"
expect_fail "sweep without items" sh -c "echo '{\"tasks\":[{\"id\":\"logs-r01-01\",\"title\":\"t\",\"kind\":\"sweep\",\"objective\":\"o\",\"deliverable\":\"d\"}]}' | python3 $S2/bin/board.py plan save --lane logs"
expect_fail "items on a non-sweep task" sh -c "echo '{\"tasks\":[{\"id\":\"logs-r01-01\",\"title\":\"t\",\"items\":[\"a\"],\"objective\":\"o\",\"deliverable\":\"d\"}]}' | python3 $S2/bin/board.py plan save --lane logs"
python3 -c "import json;print(json.dumps({'tasks':[{'id':'logs-r01-01','title':'t','kind':'sweep','items':[str(i) for i in range(13)],'objective':'o','deliverable':'d'}]}))" > "$S2/big.json"
expect_fail "more items than max_sweep_items" b2 plan save --lane logs --file "$S2/big.json"
D=$(echo '{"tasks":[{"id":"logs-r01-01","title":"scan logs","kind":"sweep","items":["day-01.log","day-02.log","day-03.log"],"objective":"o","deliverable":"d"}]}' | b2 plan save --lane logs --as logs/plan)
{ grep -q '"kind": "sweep"' <<<"$D" && grep -q '"day-02.log"' <<<"$D"; } || fail "dispatch carries kind and items"; ok "dispatch carries kind and items"
{ b2 task item --id logs-r01-01 --n 2 --status done --summary "3 errors" --board-ids B-logs-0001 --as logs/logs-r01-01 | grep -q "item 2 -> done"; } || fail "task item records"; ok "task item records a result (and starts the task)"
{ b2 plan show --lane logs | grep -q "logs-r01-01 \[running"; } || fail "first item starts task"; ok "first item marks the sweep running"
expect_fail "item number out of range" b2 task item --id logs-r01-01 --n 4 --status done --summary x
OUT=$(b2 task show --id logs-r01-01)
{ grep -q "sweep items (1/3 reported)" <<<"$OUT" && grep -q "2. day-02.log: \[done\] 3 errors" <<<"$OUT" && grep -q "1. day-01.log: (no result)" <<<"$OUT"; } || fail "task show lists items"; ok "task show lists reported and missing items"

echo "== confirm met"
echo '{"met":true,"progress":true,"gaps":[],"summary":"all met"}' | b2 judge save --round 1 --as judge >/dev/null
{ b2 status | grep -q "status met"; } || fail "met sets status"; ok "met verdict sets status met"
{ b2 judge refute --round 1 --objection "criterion 3: bisect used single runs" --as refuter | grep -q "refuted"; } || fail "refute"; ok "refuter can overturn the verdict"
python3 - "$S2/judge/round-01.json" <<'EOF'
import json, sys
v = json.load(open(sys.argv[1]))
assert v["met"] is False and v["met_before_refute"] is True, v
assert v["gaps"][0].startswith("[refuter] criterion 3"), v["gaps"]
assert v["refuted"]["by"] == "refuter"
EOF
ok "refuted verdict keeps history and turns objections into gaps"
{ b2 status | grep -q "status active"; } || fail "refute reopens"; ok "refute reopens the investigation (status active)"
expect_fail "refute without objections" b2 judge refute --round 1
{ b2 brief --role refuter | grep -q "Refuter"; } || fail "refuter brief"; ok "refuter has a brief (role prompt + verdict)"

echo "== glued arguments (shell without word-splitting) + mail show"
GLUED=$(zsh -c "A='--as static/glued'; python3 $S/bin/board.py post --lane static --kind note --subject glued \$A" 2>&1)
{ grep -q '^B-static-' <<<"$GLUED"; } || fail "glued --as is repaired"; ok "glued '--as X' argument is repaired, not rejected"
{ grep -q 'arrived glued' <<<"$GLUED"; } || fail "glued repair warns"; ok "glued repair prints a note naming the cause"
{ b query --lane static --author static/glued | grep -q glued; } || fail "glued author recorded"; ok "repaired argument records the right author"
expect_fail "a genuinely unknown flag is still rejected" b post --lane static --kind note --subject x --bogus y
{ b post --lane static --kind note --subject "value with --as inside" --body "a --as b c" | grep -q '^B-'; } || fail "quoted value untouched"; ok "values containing '--as ' are left alone"
MS=$(b mail send --to static --subject "show me" --body "full body here" --as logs/x)
{ b mail show --id "$MS" | grep -q "full body here"; } || fail "mail show"; ok "mail show --id prints one message in full"
expect_fail "mail show with an unknown id" b mail show --id M-static-9999

echo "== met_unconfirmed"
S3="$S-unconf"; rm -rf "$S3"; mkdir -p "$S3"; cp -R "$S/bin" "$S/prompts" "$S/archetypes" "$S/manifest.json" "$S3/"
python3 "$S3/bin/board.py" scaffold >/dev/null
{ python3 "$S3/bin/board.py" segment close --start 1 --end 1 --reason met_unconfirmed --as checkpoint | grep -q "met_unconfirmed"; } || fail "segment close met_unconfirmed"; ok "segment close accepts met_unconfirmed"
{ python3 "$S3/bin/board.py" status | grep -q "status met_unconfirmed"; } || fail "status shows met_unconfirmed"; ok "state records met_unconfirmed, distinct from met"

echo "== write guard"
{ echo hi | b write --path lanes/static/scope/round-01.md >/dev/null; } || fail "write inside inv dir"; ok "write inside inv dir"
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
