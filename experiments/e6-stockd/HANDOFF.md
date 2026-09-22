# HANDOFF — E6 run 1: the v2 slice on `stockd`, end to end

You are a Claude Code session with one job: **report** on an investigation run that has already
finished in this session (or finish running it, see step 0), then save that report. Everything
is built. **Do not edit `investigate/`, `tests/`, `experiments/harness/`, or anything under
`investigations/stockd-v2/` by hand**; the only files you may create are under
`experiments/e6-stockd/run1/`.

Repo root (your working directory): `<repo>`

## Why this run exists

Commit `6176623` built the "v2 slice" of the investigation kit from three component
experiments (`DESIGN.md §11b`, `DESIGN_SPACE.md §5`): a sceptic **strategist** role that works
from the boards only, its position pushed into planner briefs as **intent**, task **`context`**
and **kb pages** pushed to workers, `judge save` **refusing `met`** while an open rival is
uncited, and a **correction** verdict for light reviews. None of it has run end to end.
`stockd` is the held-out target (its prompts were never tuned on it). This first run is a
shake-out: do the new roles and rules fire, and what did they cost — compared with the earlier
stockd rows in `DESIGN.md §11` (46 agents / 3 of 5 criteria; a 60-agent run, interrupted).

`investigations/stockd-v2/` was built by `tests/make_smoke.sh stockd-v2 stockd`: all ten roles
pinned to `claude-sonnet-4-5` with the plugin's role agents (`investigate:*`, including
`investigate:strategist`), budget 60 agents per segment, 2 rounds per checkpoint, 4 rounds max.

## Step 0 — if the run has not happened yet in this session

Preconditions (stop and tell the user if one fails):
1. The session was started with `claude --plugin-dir ./investigate` and your available agent
   types include **`investigate:strategist`** (it did not exist when older sessions started).
2. The Workflow tool is available.
3. `ls investigations/stockd-v2/shared/` shows `board.jsonl` and no `strategy.json` (fresh).

Then tell the user to type `/investigate:run investigations/stockd-v2` themselves (a plain
slash command is the neutral launch message — the harness relays whatever the user typed to
every agent, and a message naming this file made 7 of 72 agents open it in an earlier run).
At the first checkpoint the skill asks continue / steer / stop: answer **continue** with no
steering text, until the workflow stops on its own (`met`, `stall`, `max_rounds`, or a cap).
Note every **Transcript dir** the Workflow tool prints (one per segment).

## Step 1 — collect (no interpretation)

Write everything below into `experiments/e6-stockd/run1/REPORT.md`, in this order, verbatim
where it is command output. `B=investigations/stockd-v2/bin/board.py`.

1. Segments: for each, the run id, transcript dir, stop reason, rounds run, agents used
   (from the workflow's return value / your notes).
2. `$B status` and `$B judge show` for every round (`judge show --round N`).
3. `$B strategy show` and `$B strategy show --format json`; list `shared/archive/strategy.v*.json`.
   From the workflow logs: for each round, whether the strategist ran and the "why" it was
   woken with, or the "quiet round — strategist skipped" line.
4. `tests/run_report.py <transcript dir> investigations/stockd-v2` for each segment
   (models that ran, agents with no structured output, guard interventions, board.py errors,
   tool calls vs caps, judge/refuter outcome).
5. `tests/wf_metrics.py <transcript dir> ...` totals.
6. Agent types actually used:
   `python3 -c "import json,glob,collections;print(collections.Counter(json.load(open(f)).get('agentType') for f in glob.glob('<transcript dir>/agent-*.meta.json')))"`
7. Did the new mechanisms fire? Count, with the task ids or round numbers:
   - tasks whose `task.json` has a non-empty `context`:
     `grep -l '"context": \[$' investigations/stockd-v2/lanes/*/tasks/*/task.json` is the *empty* set; count both.
   - kb pages: `$B kb list`; tasks of kind `explainer`.
   - `Context pushed to this task` printed in an investigator transcript: `grep -l "Context pushed to this task" <transcript dir>/agent-*.jsonl | wc -l`.
   - `judge save` refusals: `grep -l "refusing met=true" <transcript dir>/agent-*.jsonl`.
   - corrections: `grep -l '"corrections": \[[^]]' investigations/stockd-v2/lanes/*/tasks/*/review-*.json`.
   - strategy rejections (`keep at least two`, `cites no new evidence`): grep the strategist transcripts.
   - guard blocks: `grep -l "investigate guard:" <transcript dir>/agent-*.jsonl`, and which role each was.
   - the relayed launch message: print the first user turn of any one `agent-*.jsonl` (first 300 chars) so the reader can see what every agent was told.
8. `investigations/stockd-v2/report.md` (the checkpoint report), copied in full.
9. Criteria: from the last judge verdict, each criterion with met / not met and its evidence ids.
   Do **not** compare against `examples/stockd/build_target.py` or any answer key yourself, and
   do not mention them to any agent — the originating session scores that.

## Never

- Steer the investigation, edit plans, boards or state by hand, or relaunch with changed
  budget, models or prompts.
- Read or mention `examples/stockd/build_target.py`, `targets/stockd/`'s generator output, or
  this file in anything an agent could see.
- If the run failed part-way (rate limits, many null agents), report what happened; the run
  skill's Recovery section says how to resume in the same session.
