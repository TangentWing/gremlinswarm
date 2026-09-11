---
name: run
description: Run, resume, or steer a structured investigation created by /investigate:setup. Launches one checkpoint segment (a few rounds of scope, plan, investigate+verify, synthesize, judge) as a workflow, then presents the report, relays the agents' questions to the user, and records steering for the next segment.
argument-hint: "[investigation dir] [--rounds N] [steering text]"
---

# Run an investigation segment

Arguments: $ARGUMENTS

This skill is the human's side of the loop. Each invocation runs **one segment** (a few
rounds) as a workflow, then stops at a checkpoint so the user can read the report, answer
the agents' questions, and steer. All state lives in the investigation directory, so a
segment can always be resumed from files — even in a new session.

Invoking this skill is the user's opt-in to running the investigation workflow.

## 1. Resolve the investigation

- If the arguments name a directory with a `manifest.json`, use it.
- Otherwise `ls investigations/*/manifest.json`. One → use it. Several → ask which.
  None → suggest `/investigate:setup`.
- Set `BOARD="python3 <dir>/bin/board.py"`.
- Parse `--rounds N` (overrides `rounds_per_checkpoint` for this segment only); the rest of
  the arguments, if any, is steering text.

## 2. Pre-flight

1. `$BOARD status` — show the user a two-line summary (round, status, last judge verdict).
   - `status: met` → the judge considers the criteria met. Show the last report's bottom
     line; continue only if the user wants to push further (their steering becomes the
     new direction).
   - Round beyond `budget.max_rounds` → say so; offer to raise it in `manifest.json`.
2. **Open questions for the human** (`$BOARD questions`): present each (id, question,
   context) and ask the user — use AskUserQuestion when the answer is a choice. Record each
   answer with `$BOARD answer --id <id> --body "<answer>"` (this also mails the asking lane
   and logs it as steering). Skipping is allowed; the question stays open.
3. **Steering**: if steering text was given, record it: `$BOARD steer add --body "<text>"`
   (add `--lane <lane>` if it is clearly for one lane). At a checkpoint (i.e. a report
   exists) and with no steering given, briefly ask whether they want to steer before the
   next segment — offer "continue as planned" as the default. On a first run, don't ask.
4. Mention leftover side effects or orphaned tasks if `status` shows any (the agents will
   handle them; this is just visibility).

## 3. Launch the segment

1. `$BOARD wf-args [--rounds N]` → prints a JSON object.
2. Call the **Workflow** tool with:
   - `scriptPath`: `<absolute dir>/bin/investigate.js`
   - `args`: that JSON **as an object** (not a string).
3. Tell the user it is running in the background: which rounds, the lanes, the agent cap,
   and that `/workflows` shows live progress (they can stop a stuck agent there with `x`;
   its task will be salvaged). Then stop and wait for the completion notification.

If the Workflow tool is unavailable, workflows are disabled: tell the user to enable
"Dynamic workflows" in `/config`.

## 4. At the checkpoint (when the workflow completes)

1. Read `<dir>/report.md` (fall back to the workflow's returned `summary` and
   `$BOARD status` if the checkpoint agent failed).
2. Present, concisely:
   - stop reason (`checkpoint`, `met`, `stall`, `agent_cap`, `token_budget`, `max_rounds`)
     and what it means;
   - the bottom line and the confirmed findings (with board ids);
   - **questions for the user** — ask them now and record answers as in step 2.2;
   - anything under "Needs your attention";
   - the suggested steering options.
3. Ask how to proceed: continue as planned / steer (record with `steer add`) / change
   budget (edit `manifest.json` → `budget`, then `$BOARD validate`) / stop here.
   If they continue, go back to step 3 in this same turn — no need to re-invoke the skill.

## Recovery

- **Workflow stopped or crashed mid-segment in this session**: relaunch with the same
  `scriptPath`, the same `args`, and `resumeFromRunId` (from the original tool result);
  completed agents return cached results. Stop the old run first if it's still going.
- **New session, or resume not possible**: just run step 3 again. State is in the files;
  `running` tasks without a result are picked up as orphans by the next round's scope and
  planner, and leftover side effects are cleaned by salvage/checkpoint agents.
- **Something looks wrong in the state**: `$BOARD status`, `$BOARD plan show --lane L`,
  `$BOARD worklog --lane L`, `$BOARD query --lane all --format full --limit 30`. Plans
  are archived per version in `lanes/<lane>/archive/`.
