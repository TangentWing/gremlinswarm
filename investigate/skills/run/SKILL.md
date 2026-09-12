---
name: run
description: Use when the user wants to start, continue, resume, or steer an investigation that already has an investigation directory (created by /investigate:setup), or when an investigation workflow segment has just finished and its checkpoint needs presenting.
argument-hint: "[investigation dir] [--rounds N] [steering text]"
---

# Run an investigation segment

Arguments: $ARGUMENTS

Each launch runs **one segment** (a few rounds) as a workflow, then stops at a checkpoint
for the user. All state lives in the investigation directory, so a segment can always be
launched again from files — even in a new session. Invoking this skill is the user's
opt-in to running the investigation workflow.

## 1. Resolve

- A directory argument with a `manifest.json`, else `ls investigations/*/manifest.json`
  (one → use it; several → ask; none → suggest `/investigate:setup`).
- `BOARD=<absolute dir>/bin/board.py` (an executable). `--rounds N` overrides the segment
  length once; any remaining argument text is steering.

## 2. Pre-flight

1. `$BOARD status` — summarise in two lines. `status: met` → show the bottom line and
   continue only if the user wants to push further. `status: met_unconfirmed` → say the
   refuter never checked the verdict and offer to relaunch. Round beyond `max_rounds` → offer to
   raise it in `manifest.json`.
2. **Questions for the human** (`$BOARD questions`) — ask the user (AskUserQuestion for
   choices). Record each reply with `$BOARD answer --id <id> --body "<reply>"`:

   | The user… | Record |
   |---|---|
   | answers | their answer |
   | doesn't know, declines, or says skip | their words, e.g. "Human doesn't know — proceed without it" |
   | says "later" / "not now" | nothing; it stays open |

3. **Steering**: record steering text with `$BOARD steer add --body "<text>"` (`--lane L` if
   it is clearly for one lane). If `report.md` exists and you have not shown it to the
   user in this conversation, show its bottom line and ask whether to steer (default:
   continue as planned). Otherwise don't ask.
4. Mention orphaned tasks or leftovers from `status` for visibility only; the agents handle
   them. Never edit plans or state by hand.

## 3. Launch

1. `$BOARD wf-args [--rounds N]` → a JSON object. If its `agent_types` name `investigate:*`
   agents that are not among your available agent types (the plugin isn't loaded in this
   session), re-run with `--no-agent-types` and tell the user this run uses plain workflow
   agents: no per-role tool restrictions or turn caps.
2. **Workflow** tool: `scriptPath` = `<absolute dir>/bin/investigate.js`, `args` = that JSON
   **as an object**, not a string. No `resumeFromRunId` (see Recovery).
3. Tell the user: rounds, lanes, agent cap, and that `/workflows` shows progress (a stuck
   agent can be stopped there with `x`; its task is salvaged). Then wait for completion.

No Workflow tool → workflows are disabled; tell the user to enable "Dynamic workflows" in `/config`.

## 4. Checkpoint (workflow finished)

1. Read `report.md` (fallback: the workflow's `summary` and `$BOARD status`).
2. Present: stop reason (`checkpoint | met | met_unconfirmed | stall | agent_cap | token_budget | max_rounds`),
   bottom line, confirmed findings with board ids, **questions** (record replies as in 2.2),
   "Needs your attention", suggested steering.
   Stop reason `error` means agents were failing repeatedly (API, rate or session limit):
   there is no report and the round was not counted — relaunch (step 3) once it clears.
   Stop reason `met_unconfirmed` means the judge said met but the refuter returned no verdict
   (twice): say the verdict is unchecked; relaunching re-judges and re-runs the refuter.
3. Ask: continue / steer (`steer add`) / change budget (edit `manifest.json` → `validate`) /
   stop. On continue, go straight to step 3 in this turn.

## Recovery

- **Stopped mid-segment in this same session**: relaunch with the same `scriptPath` and
  `args` plus `resumeFromRunId` from the original tool result (stop the old run first).
- **Otherwise** (new session, crash, no run id): launch normally (step 3). Orphaned
  `running` tasks are re-planned and leftovers cleaned by the agents.
- **Inspecting state**: `$BOARD status`, `plan show --lane L`, `worklog --lane L`,
  `query --lane all --format full --limit 30`; plan history in `lanes/<lane>/archive/`.
