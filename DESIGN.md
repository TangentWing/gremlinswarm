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
                  sweep: item agents (parallel, or serial on an exclusive claim) → reducer → verify
                  investigator died → salvage agent
    round ends when all short tasks done (long ones may continue)
    synthesize ── dedupe / contradictions / irrelevance / promote to shared
    judge      ── criteria vs shared board → met / progress / gaps
    met?       ── refuter tries to overturn it; refuted → objections become gaps, continue
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
| API / rate / session limit | max(3, lanes) consecutive agents return `null` | Stop dispatching, skip synthesis/judge, stop reason `error`; the round is not counted, so a relaunch resumes it. |

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
  files), so one allow rule (`Bash(<inv>/bin/board.py:*)`) pre-approves agent bookkeeping.
- The board CLI is handed to agents as a single executable path (shebang), not
  `python3 <path>`: smoke test 1 showed 11/12 agents storing the two-word form in a shell
  variable, which zsh does not word-split.
- Every agent's first action is `board.py brief --role R [--lane L] [--task T] [--round N]`,
  which prints protocol + role prompt + lane.md + manifest essentials + the state that role
  needs in one call (smoke test 1: agents spent 2–5 opening calls reading these).
- Plan saves merge: resubmitted ids keep history (attempt increments when requeued from
  failed/partial/blocked/needs_redo/orphaned), queued tasks left out are marked `dropped`,
  terminal tasks are carried over, and in-flight ids are refused.
- Supersession is computed across all boards (a shared entry usually supersedes lane entries).
- The synthesizer maintains `shared/synthesis.md`; the checkpoint writes `report.md` and
  `reports/after-round-NN.md`.

## 10. Roles, enforcement and templates

**Role agents** (`investigate/agents/*.md`, one per role). Each workflow `agent()` call passes
`agentType: investigate:<role>` (via manifest `agent_types`), which gives per-role
`disallowedTools` and `maxTurns` and a shared system prompt per role (prompt-cache friendly).
The agent body is deliberately short — "run `brief` first, return structured output" —
because it *replaces* the system prompt; real instructions stay in the per-investigation
prompt pack so they remain pinned and editable per investigation. Plugin agents cannot carry
hooks (Claude Code ignores `hooks`/`mcpServers`/`permissionMode` in plugin agents).

**Guard hook** (`investigate/hooks/`, plugin-level, so it also runs inside subagents). It
acts only on agents whose own transcript begins with an investigation prompt:
- `PreToolUse`: Edit/Write only inside the investigation directory or `writable`; Bash
  commands matching the manifest's `safety_deny` regexes are blocked (exit 2 + reason).
- `SubagentStop`: an investigator cannot stop before `task finish` (or `task item` for a
  sweep item); a judge cannot stop before `judge save`. `stop_hook_active` prevents loops.
It fails open and is a seatbelt, not a sandbox (shell redirection can still write).

**Lane archetypes** (`kit/archetypes/*.md`): frontmatter (summary, use_when, resource
kinds, verify default, task kinds) + a `lane.md` template. Setup picks archetypes; `scaffold`
renders each lane's `lane.md`. Authoring guide and template: `kit/archetypes/README.md`.

**Resource probes**: `resources[].check` commands; `board.py probe` runs them; the scope
agent's brief includes its lane's probe results every round.

**Confirm met**: a `met` verdict stops everything, so a fresh refuter must fail to
overturn it (`board.py judge refute` turns objections into gaps and reopens).

**Sweeps**: `kind: sweep` + `items[]` (≤ `max_sweep_items`) → one agent per item, then a
reducer; replaces "one investigator with two children" for many-unit work.

## 11. What the smoke runs measured

| Run | Target | Agents | Result |
|---|---|---|---|
| toy 1 | toy-ringbuf | 12 | Correct root cause. 10/12 agents hit a shell word-splitting error; 20 calls spent re-reading prompt files. |
| toy 2 | toy-ringbuf | 12 | Same answer, 73 tool calls vs 133, 3.6M vs 6.6M cache reads, 0 shell errors (single-path CLI + `brief`). |
| stockd before | stockd | 46 | 3/5 criteria. One **long** bisect task held the exclusive port for a whole round, so both repro tasks were deferred — the two open criteria needed them. |
| stockd after | stockd | 60 (interrupted) | Round 1 alone produced root cause, reproducer, introducing commit and log timeline. The bisect lane split into two **short** tasks and planned a no-port task next round; repro finished 4 tasks. 0 guard interventions, no turn cap reached. |
| stockd-onset | stockd | 20 | 3/3 criteria in one round. The refuter re-derived all 30 table rows and upheld the verdict (confirm-met proven live). The planner chose one grep task over a 30-item sweep — correctly. |
| toy on Haiku 4.5 | toy-ringbuf | 14 | Correct answer with all 9 roles on Haiku 4.5, at ~2× Opus's tool calls (150 vs 73). **The refuter hit its 15-turn cap and returned no verdict, so `met` was accepted unconfirmed** — the safety check silently didn't run. |
| toy on Sonnet 4.5 | toy-ringbuf | 13 | Correct answer with all 9 roles on Sonnet 4.5 (after the refuter fix), 123 tool calls. Refuter returned a real verdict in 12 of 30 turns; no retry, no structured-output misses, no guard hits. Sonnet 4 itself is retired and fails fast (0 tokens) via the failure guard. |

Repairs those runs drove: exclusive claims shown to planners (and "never make a task long
while it holds a shared exclusive resource"), the `brief` command, the single-path board
CLI, the glued-argument repair, `mail show`, the bisect archetype's git pitfalls, sharper
sweep guidance, and — from the Haiku run — a refuter retry that stops as `met_unconfirmed`
rather than reporting an unchecked `met`, a refuter turn cap of 30, and a rule to return a
partial verdict (unchecked criteria as objections) before running out of turns.

## 11a. What the component experiments changed (v1.1, 2026-09-21)

Component experiments on a small generated target (`experiments/`, results in
`experiments/x0-verifier-canaries/results.md`) planted faults in front of the verifier roles
on Sonnet 4.5. Gross faults were caught (challenger 6/6); what the roles missed was whatever
was *absent* from their view. Changes, each measured with concurrent baselines under the
plugin's role agents:

- `board.py digest`, printed in the judge's and refuter's brief: the last review behind each
  shared entry, and open lane hypotheses no shared entry cites; the role prompts say what each
  means for the verdict. Unpromoted rival: caught 0/6 → 5/5. Evidence promoted from a task its
  challenger rejected: 1/6 → 4/4 (nobody ever looked at review files unprompted). No false
  alarms on clean states (0/8).
- Challenger coverage rule (check every row, `checked N of N`, look for counterexamples outside
  the sample): one counterexample to an "all 15" claim, noticed 0/3 → 2/3.
- Turn caps: judge 15 → 25, challenger 25 → 35, refuter 30 → 40, plus a "return the verdict you
  can support before you run out" rule for judge and challenger. At 15 turns the baseline judge
  returned **no verdict** in 3 of 3 trials on a state that invited re-verification — in a real
  run that is "judge lost, no progress", silently.
- **Guard hook fix.** The workflow harness indents the script's prompt and may relay the user's
  request as a separate first turn; `guard.py` matched neither, so it never recognised a real
  workflow agent and none of its checks ran. It now reads the opening user turns together and
  ignores indentation (`tests/test_guard.py` has a harness-shaped transcript).
- Not adopted: a "consistency check" step for the judge (3/3 without the plugin, 0/3 under it).
  The refuter catches that case (5 of 6), which is what it is for.

Worth knowing: the harness relays the launching user message verbatim to **every** workflow
agent as "the only user voice". Steering typed after `/investigate:run` therefore reaches all
agents of that segment, unfiltered by lane.

## 11b. The v2 slice (2026-09-22): strategist, pushed context, kb pages, two mechanical rules

What x1–x3 decided (DESIGN_SPACE.md §5), built as the smallest set of changes that carries
each result. Untested end to end; E6 on stockd is the confirmation (`DESIGN_SPACE.md`).

- **Strategist** (`prompts/strategist.md`, `agents/strategist.md`, 15 turns). One agent after
  the judge, sceptic-framed ("assume the leading hypothesis is wrong…"), boards only: the guard
  blocks any Bash that is not the board CLI and any Read/Glob/Grep outside the investigation
  directory (x3: a strategist that can read the target does the investigators' work instead).
  It saves a position with `strategy save`: every explanation in play with a status
  (`leading|live|deprioritised|refuted`), the observations whose outcome differs between the
  live ones, and what is not pursued. `board.py` refuses fewer than two live hypotheses (unless
  the rest are refuted) and refuses a status change that cites no new evidence (hysteresis).
  **Wake rule** in `investigate.js`, from signals it already has: no strategy yet, judge lost,
  `met` refuted, no progress, or the synthesizer changed the shared board; otherwise the round
  is quiet and the strategist is skipped. Setup seeds strategy v1 from the user's hypotheses.
- **Intent, not orders** (x2). `shared/strategy.md` is rendered from the position and printed in
  every scope and plan brief; the scope brief drops the raw judge verdict when a strategy exists
  (3/3 v1 planners queued the wasted task because a gap said so). Planners design the
  experiments.
- **Pushed context** (x1). Tasks carry `context: [board ids, kb slugs]`, validated at
  `plan save`; `task start` prints the entries in full — except open hypotheses, shown by id and
  subject only, marked UNDER TEST — plus every kb page whose `match` token appears in the spec.
  Workers get facts, never the synthesis or the strategy.
- **KB pages** (`kb save|list|show|search`, `kb/<slug>.md`): one mechanism with file:line per
  claim, written by an `explainer` task (new task kind). Not evidence. `write` refuses `kb/`.
- **`judge save` refuses `met=true`** while an open hypothesis or contradiction on a lane board
  is cited by no live shared entry; the error names them and the ways out (a shared entry that
  cites it; `amend --set status=irrelevant --note`, recorded under the judge's name). x0: with
  the digest alone 4 of 6 judges still said met.
- **Proportionate `light` verdict**: `task review --verdict accept --correction "..."` records a
  detail that was wrong with its right value; the challenger puts the same note on the entry.
  The digest shows "accept (with corrections)".
- **Cap deaths leave a record**: the guard's SubagentStop gate now also holds a challenger until
  the Nth review of this round is on file (confirm1: 5 of 6 cap deaths recorded nothing). A
  lost judge is named in the next judge's prompt.

## 12. Known v1 limits

- No per-agent timeout; a hung agent is stopped by hand in `/workflows` (→ salvage).
- Workflow resume is same-session only; cross-session continuity comes from the
  files (`/investigate:run` always resumes from `state.json`).
- Nested children spawned by investigators are bounded by prompt + the platform's
  subagent depth limit, not counted by the scheduler.
