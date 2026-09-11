# Investigation Kit — Design (v1)

Agreed design for the investigation skill set.
Implementation lives in `investigate/` (a Claude Code plugin).

## 1. Shape

| Piece | Kind | Why this kind |
|---|---|---|
| `/investigate:setup` | Skill (interactive) | Workflows can't take mid-run input; setup is a conversation. |
| `/investigate:run` | Skill (thin) | Pre-flight, steering intake, launches the workflow, presents checkpoints. |
| `investigate.js` | Dynamic workflow | The loop is deterministic; the judgment inside each step is not. Loop in code, judgment in agents. |
| `board.py` | Stdlib Python CLI | The only way agents touch shared state: locked appends, validation, archiving. |
| Prompt pack | Markdown files | Shared role prompts; agents get a short prompt that points at them. |

The **protocol** (directory layout + JSONL formats + prompt pack + `board.py`) is
host-agnostic. The workflow is the v1 *host*; an Agent SDK program can replace it
(v2) without touching the protocol.

Setup copies the kit (`bin/`, `prompts/`) into each investigation directory, so an
investigation is self-contained, pinned to the kit version it started with, and its
prompts can be tailored per investigation.

## 2. Key decisions (and what they replaced)

1. **Scheduler = script; orchestrators are stateless rounds.** No long-lived
   orchestrator agent exists, so there is no context-full handoff. Every agent is
   short-lived; the checkpoint *is* the lane directory.
2. **Lanes are a planning partition, not processes.** A lane = directory + `lane.md`
   (mandate, resources, evidence standard). All lane planners replan every round on
   the latest synthesized evidence; one global scheduler executes.
3. **Planning barrier, not execution barrier.** Rounds are replan points. Tasks
   marked `size: long` keep running across round boundaries; planners see them as
   in-flight. Only human checkpoints drain everything.
4. **Resource claims are enforced by the scheduler.** The manifest declares
   resources (`exclusive: true|false`); tasks declare claims; the scheduler never
   runs two tasks with overlapping exclusive claims concurrently.
5. **Dialectic + critique merged into one bounded verify step.** Worker →
   fresh adversarial challenger → `accept | revise | redo`. `revise` re-runs the
   worker with the objections (bounded by `verify_rounds`); `redo` flags the task
   for the planner. Level per task: `none | light | adversarial`.
6. **Explicit termination.** A judge checks the shared board against the
   manifest's criteria each round → `{met, progress, gaps}`. Stop on met, budget
   exhausted, or `stall_rounds` rounds without progress.
7. **Skunk-works de-overloaded.** Synthesis is a per-round cross-lane step;
   failure *detection* is free (runtime returns `null`); the `skunkworks` lane
   owns unroutable mail, cross-lane asks, and odd jobs. Salvage of dead agents is
   a salvage agent run in place of the dead one.
8. **Mail is async at round granularity.** No agent ever waits on another.
9. **Agents never hand-edit shared JSON.** Everything goes through `board.py`.
   Logs are append-only; changes are amendments; plans are archived per version.
10. **Human steering at checkpoints.** Each workflow run = one segment of N
    rounds. Between segments the user answers agent questions and steers.

## 3. The loop

```
/investigate:run ──► workflow segment (rounds R..R+N-1)
  for each round:
    per lane (pipelined, no barrier across lanes):
      scope  ── reads state, checks resources, writes brief ──► idle? skip lane
      plan   ── reads brief, saves plan.vNNN via board.py ──► dispatch list
    scheduler: tasks run as soon as their lane's plan lands, subject to
      global concurrency, exclusive claims, deps
      task chain: investigator → [challenger → (revise → challenger)*] 
                  investigator died → salvage agent
    round ends when all short tasks done (long ones may continue)
    synthesize ── dedupe / contradictions / irrelevance / promote to shared
    judge      ── criteria vs shared board → met / progress / gaps
  drain in-flight → checkpoint agent (cleanup leftovers, write report)
◄── report + open questions ── user steers ── /investigate:run again
```

## 4. Protocol

### Directory layout
```
investigations/<slug>/
  manifest.json            scope, resources, criteria, lanes, budget, models
  state.json               round counter, segment history
  steering.jsonl           human steering (append-only)
  report.md                latest checkpoint report
  bin/board.py  bin/investigate.js
  prompts/                 protocol.md + one file per role
  shared/board.jsonl       cross-lane findings, contradictions, human questions
  judge/round-NN.json      judge verdicts
  mail/<lane>.jsonl        per-lane inbox
  lanes/<lane>/
    lane.md                mandate, resources, evidence standard
    plan.json  archive/plan.vNNN.json
    worklog.jsonl  board.jsonl
    scope/round-NN.md      scope briefs
    tasks/<task-id>/
      task.json  notes.md  started.jsonl  result.json  review-N.json  (+ artifacts)
```

### Records (JSONL, one object per line)

Board entry (`shared/board.jsonl`, `lanes/<lane>/board.jsonl`):
```json
{"id":"B-static-0042","ts":"…","author":"static/static-r02-01","lane":"static",
 "kind":"finding|hypothesis|evidence|question|contradiction|note|question-for-human",
 "subject":"…","body":"…","tags":["ipc"],"refs":["B-logs-0007","src/ipc.c:212"],
 "confidence":"low|med|high","status":"open|confirmed|refuted|irrelevant|answered",
 "supersedes":[]}
```
Amendment (same file): `{"op":"amend","target":"B-static-0042","set":{"status":"confirmed"},"by":"…","ts":"…","note":"…"}`
An entry listed in any later entry's `supersedes` is hidden from default queries.

Mail (`mail/<to>.jsonl`):
```json
{"id":"M-static-0007","ts":"…","from":"logs","to":"static",
 "type":"query|task-request|reply|notice|failure|steering",
 "subject":"…","body":"…","re":null,"priority":"normal|high","status":"new"}
```
Status changes are amendments, like the board.

Task (in `plan.json` and `tasks/<id>/task.json`):
```json
{"id":"static-r02-01","title":"…","kind":"read|trace|experiment|endpoint|debug|analysis|other",
 "objective":"…","instructions":"…","deliverable":"…","resources":["repo"],
 "deps":[],"verify":"none|light|adversarial","size":"short|long","max_children":1,
 "status":"queued|running|done|partial|failed|blocked|needs_redo|dropped","attempt":1}
```

Agent → script returns are schema-enforced and small (`summary` ≤ ~600 chars);
everything else goes to files.

## 5. Scheduler rules (in `investigate.js`)

- Global pool: `budget.max_concurrent` agents (runtime cap is min(16, CPUs−2)).
- A task starts when: slot free, deps satisfied, no exclusive-claim conflict with
  a running task. Unknown deps (finished in earlier segments) count as satisfied
  once all planners have reported; dependency cycles are logged and skipped.
- Task chain holds its claims for its whole duration (worker + reviews + salvage).
- A dep that failed ⇒ dependents are not started this round; they stay `queued`
  and the next planner decides.
- Agent count per segment is capped (`max_agents_per_segment`); on reaching it the
  scheduler stops dispatching, finishes the round, and checkpoints — and logs it.
- Honors a `+500k`-style token target via the workflow `budget` global.

## 6. Failure handling

| Failure | Detection | Response |
|---|---|---|
| Agent dies / user stops it | `agent()` → `null` | Salvage agent reads `notes.md`/`started.jsonl`, kills leftovers, finishes or marks for retask (mail to lane). |
| Bad deliverable | Schema validation (runtime retries) | Runtime retry; then `null` → salvage. |
| Low-quality work | Challenger verdict | `revise` loop or `redo` flag for the planner. |
| Orphaned `running` tasks (host crash) | Scope agent sees `running` with no result | Planner re-queues with `attempt+1`. |
| Leaked side effects (servers, ports) | `started.jsonl` entries not stopped | Salvage + checkpoint agent run `board.py leftovers` and clean up. |
| Stalled investigation | Judge `progress:false` × `stall_rounds` | Stop and checkpoint. |

## 7. Budget knobs (manifest `budget`)

`max_concurrent`, `rounds_per_checkpoint`, `max_rounds`, `max_agents_per_segment`,
`max_tasks_per_lane_round`, `verify_rounds`, `max_children`, `stall_rounds`.
Per-role `models` / `effort` overrides (default: inherit session model).
Wall-clock budgets are not enforceable in a workflow script (`Date.now()` is
disabled for replay determinism) — v1 counts rounds and agents.

## 8. Agent SDK path (v2)

Same investigation directory, same prompts, same `board.py`. An SDK host replaces
`investigate.js` and gains: wall-clock/time budgets, per-agent timeouts and kills,
per-agent cost accounting ($ budgets), unattended/CI execution, board operations
as typed in-process tools instead of a CLI, and true turn-by-turn dialectic via
streaming input.

## 9. Implementation notes (decided while building)

- The workflow script can't read files, so `/investigate:run` passes `board.py wf-args`
  output as `args`; everything else flows through schema-checked agent returns.
- `agent()` has no turn cap; turn limits come from prompts (or a custom `agent_types` role
  whose definition sets `maxTurns`).
- The runtime caps concurrency at min(16, CPUs−2) — 6 on an 8-core machine — on top of
  `budget.max_concurrent`.
- All writes into the investigation directory go through `board.py` (`write` for free-form
  files), so one allow rule (`Bash(python3 …/board.py:*)`) pre-approves agent bookkeeping.
- Plan saves merge: resubmitted ids keep history (attempt increments when requeued from
  failed/partial/blocked/needs_redo/orphaned), queued tasks left out are marked `dropped`,
  terminal tasks are carried over, and in-flight ids are refused.
- Supersession is computed across all boards (a shared entry usually supersedes lane entries).
- The synthesizer maintains `shared/synthesis.md`; the checkpoint writes `report.md` and
  `reports/after-round-NN.md`.

## 10. Known v1 limits

- No per-agent timeout; a hung agent is stopped by hand in `/workflows` (→ salvage).
- Workflow resume is same-session only; cross-session continuity comes from the
  files (`/investigate:run` always resumes from `state.json`).
- Nested children spawned by investigators are bounded by prompt + the platform's
  subagent depth limit, not counted by the scheduler.
