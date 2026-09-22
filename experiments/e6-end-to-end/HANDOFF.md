# HANDOFF — E6: the v2 slice end to end, under the plugin

You are a Claude Code session with one job: run two prepared investigations to completion with
the kit's real role agents, then collect a report for each. Do not edit `investigate/`,
`tests/`, `experiments/harness/`, or anything under `investigations/`; the only files you may
create are `experiments/e6-end-to-end/run1/REPORT-<slug>.md`.

Repo root (your working directory): `<repo>` — the directory this file is in, two levels up.

## Why

Commits `6176623` and `82d7268` built the v2 slice from the component experiments
(`DESIGN.md §11b`): a sceptic strategist that works from the boards only, its position pushed
to planners as intent, task `context` and kb pages pushed to workers, `judge save` refusing
`met` while an open rival is uncited, a plan lint, a correction verdict. It has never run end to
end. Two shake-out runs, all ten roles on Sonnet 4.5:

| Investigation | Target | Why | Budget |
|---|---|---|---|
| `investigations/trisvc-e6` | the experiments' own target (bursty profile) | the states x1–x3 were built from; do the pieces fire together, and does the run find the cause | 40 agents/segment, 2 rounds/segment, 4 rounds |
| `investigations/stockd-v2` | stockd, the held-out target (never tuned on) | compare with `DESIGN.md §11`: 46 agents / 3 of 5 criteria (before), 60 (interrupted) | 60 agents/segment, 2 rounds/segment, 4 rounds |

Both directories are scaffolded from the current kit and their resource probes pass.

## Preconditions — stop and tell the user if one fails

1. Started from the repo root with `claude --plugin-dir ./investigate`, and the available agent
   types include **`investigate:strategist`** (the slice added it; older sessions lack it).
2. The Workflow tool is available.
3. `investigations/trisvc-e6/shared/` and `investigations/stockd-v2/shared/` each hold only
   `board.jsonl` — fresh, no `strategy.json`.
4. `.claude/settings.local.json` allows what the agents will call (the user was shown this list;
   do not add rules yourself — if a permission prompt appears, tell the user what it asked for):
   - `Bash(<repo>/investigations/trisvc-e6/bin/board.py:*)`, `Edit(investigations/trisvc-e6/**)`,
     `Bash(python3 <repo>/investigations/trisvc-e6/lanes/*)`
   - `Bash(<repo>/investigations/stockd-v2/bin/board.py:*)`, `Edit(investigations/stockd-v2/**)`,
     `Bash(python3 <repo>/investigations/stockd-v2/lanes/*)`, `Bash(git clone <repo>/targets/stockd/repo:*)`

## Run — trisvc-e6 first, then stockd-v2

Ask the user to type `/investigate:run investigations/trisvc-e6` themselves: the plain slash
command is the neutral launch message (the harness relays whatever the user typed to every
agent of the run). At each checkpoint the skill asks continue / steer / stop: **continue with no
steering text** until the workflow stops on its own (`met`, `stall`, `max_rounds`, or a cap).
Note every **Transcript dir** and run id the Workflow tool prints (one per segment). When it has
stopped, do the same for `investigations/stockd-v2`.

## Collect — one report per investigation, no interpretation

Write `experiments/e6-end-to-end/run1/REPORT-<slug>.md` with, in this order (verbatim where it
is command output; `B=investigations/<slug>/bin/board.py`):

1. Segments: run id, transcript dir, stop reason, rounds run, agents used.
2. `$B status`; `$B judge show --round N` for every round.
3. `$B strategy show`, `$B strategy show --format json`, `ls investigations/<slug>/shared/archive/`.
   From the workflow logs, per round: the strategist's wake reason, or the "quiet round" line.
4. `tests/run_report.py <transcript dir> investigations/<slug>` per segment.
5. `tests/wf_metrics.py <transcript dir> ...` totals.
6. Agent types used: `python3 -c "import json,glob,collections;print(collections.Counter(json.load(open(f)).get('agentType') for f in glob.glob('<transcript dir>/agent-*.meta.json')))"`.
7. Did the new mechanisms fire (counts, with ids or rounds):
   - tasks with a non-empty `context` in `task.json`; kb pages (`$B kb list`); `explainer` tasks;
   - `Context pushed to this task` in investigator transcripts: `grep -l "Context pushed to this task" <transcript dir>/agent-*.jsonl | wc -l`;
   - `judge save` refusals: `grep -l "refusing met=true" <transcript dir>/agent-*.jsonl`;
   - `plan refused` and `WARNING` lines from `plan save` in planner transcripts;
   - corrections: `grep -l '"corrections": \[[^]]' investigations/<slug>/lanes/*/tasks/*/review-*.json`;
   - strategy rejections (`keep at least two`, `names nothing new`) in strategist transcripts;
   - guard blocks: `grep -l "investigate guard:" <transcript dir>/agent-*.jsonl`, with the role of each;
   - the relayed launch message: the first 300 chars of the first user turn of any one `agent-*.jsonl`.
8. `investigations/<slug>/report.md` in full.
9. From the last judge verdict: each criterion, met or not, and its evidence ids.

The originating session scores correctness against the answer keys; you do not. Never read or
mention `experiments/targets/`, `targets/*.answer_key.json`, `examples/*/build_target.py` or
this file in anything an agent could see.

## Never

- Steer, edit plans, boards or state by hand, or relaunch with changed budget, models or prompts.
- If a run fails part-way (rate limits, many null agents), report what happened; the run
  skill's Recovery section says how to resume in the same session.
