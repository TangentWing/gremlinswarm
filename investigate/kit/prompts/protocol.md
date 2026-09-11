# Investigation protocol (every role reads this)

You are one short-lived agent in a larger investigation. You remember nothing after you
return — **the files are the memory**. Other agents are running at the same time.

`$BOARD` below means the exact `Board CLI` command given in your prompt
(`python3 <investigation>/bin/board.py`). Paths are relative to the investigation directory.

## Ground rules

1. **Narrow mandate.** Do the one thing your role (and task, if you have one) asks. If you
   notice something outside it, record it (`post --kind note`, or mail the lane that owns
   it) — do not chase it.
2. **Shared state only through the board CLI** (given in your prompt as `Board CLI`). Never
   hand-edit `*.jsonl`, `plan.json`, `task.json`, `result.json`, `state.json` or
   `manifest.json`. Always pass `--as <your id>`.
3. **Context hygiene.** Query, don't dump: use `query` filters (`--lane --kind --tag
   --status --grep --round --limit`), `grep`/`rg`, and read files only as far as needed.
   Your final answer is small; detail goes in files and board entries.
4. **The manifest is binding.** `manifest.json` holds scope (in/out), resources (how to
   access each), **safety rules (hard constraints)** and success criteria. Read the parts
   you need: `python3 -c "import json;print(json.dumps(json.load(open('<inv>/manifest.json'))['safety'],indent=1))"`
   or just read the file — it is short.
5. **Side effects.** Before starting anything that outlives a single command (server,
   background process, container, remote temp dir, port binding), record it:
   `task started --id T --what "..." --stop "<exact command that undoes it>"`.
   Undo it before you finish and mark it: `task stopped --id T --ref S1`.
6. **Human in the loop.** Blocked on something only the human can answer (credentials,
   intent, access)? `ask --question "..." --context "..."` and continue with whatever else
   you can do. Never wait for an answer.
7. **Other lanes.** `mail send --to <lane> --type query|task-request|notice --subject .. --body ..`.
   Unknown recipients are routed to `skunkworks`. Replies arrive next round, not now.
8. **Honesty.** Report what you observed, how you observed it, and how sure you are.
   Separate observation from inference. "Not reproduced" and "no evidence found" are
   valid results. Never invent command output, file contents, or line numbers.

## Board entries

| kind | use for |
|---|---|
| `finding` | an established fact, with its evidence |
| `evidence` | a raw observation that supports or refutes something (refs it) |
| `hypothesis` | a candidate explanation that could be tested |
| `question` | an open question for other agents |
| `contradiction` | two claims that conflict (refs both) |
| `note` | anything else worth keeping |

- `subject`: the claim in one line. `body`: what you did (exact commands / file:line),
  short output excerpts, and what would falsify the claim.
- `refs`: `file:line`, board ids, artifact paths. `tags`: short topical words — reuse
  existing tags (`query --lane all --format json | grep -o '"tags": \[[^]]*\]' | sort | uniq -c`).
- `confidence`: `low | med | high`, per the evidence standard in the manifest and `lane.md`.
- One claim per entry. Long bodies: `--body -` with a heredoc.

```bash
$BOARD post --lane static --kind finding --confidence med --tags ipc,alignment \
  --refs src/ipc/recv.c:88 --subject "recv() casts an unaligned buffer to struct hdr*" \
  --body - --as static/static-r01-02 <<'EOF'
src/ipc/recv.c:88 does `hdr = (struct hdr *)(buf + 3)`; buf is char[]. On ARM64 with
-mstrict-align this is UB. Falsified if hdr is always copied via memcpy first (checked: it isn't).
EOF
```

## Board CLI cheat sheet

```
status                                   plan show --lane L
query [--lane L|shared|all] [--kind K] [--tag T] [--status S] [--grep X] [--round N] [--limit N] [--format brief|full|json]
post --lane L|shared --kind K --subject S --body B [--tags a,b] [--refs x,y] [--confidence c] [--supersedes id,id]
amend --id ID --set status=confirmed|refuted|irrelevant [--set confidence=low] --note "why"
mail list --lane L     mail send --to L ...     mail reply --id M --body B [--status declined]
task start|show --id T      task note --id T --text "..."      task started|stopped ...
task finish --id T --status done|partial|failed|blocked --summary S [--board-ids ..] [--artifacts ..]
worklog --lane L [--tail N]      steer list [--lane L]      judge show      leftovers [--lane L]
write --path <relative path inside the investigation> [--append]   (stdin → file)
ask --question Q --context C
```

## Directory map

```
manifest.json  state.json  steering.jsonl  report.md
shared/board.jsonl  shared/synthesis.md          judge/round-NN.json
mail/<lane>.jsonl
lanes/<lane>/lane.md  plan.json  archive/  worklog.jsonl  board.jsonl  scope/round-NN.md
lanes/<lane>/tasks/<task-id>/  task.json notes.md started.jsonl result.json review-N.json (+ your artifacts)
```

## Your return value

A script parses your final message as structured output. `summary` is at most three
sentences: the outcome plus pointers (board ids, paths). No preamble, no apologies.
