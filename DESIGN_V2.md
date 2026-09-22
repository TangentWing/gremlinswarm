# Investigation Kit — v2 protocol design (draft)

Draft from the design discussion of 2026-09-19. Nothing here is implemented. v1 design:
[DESIGN.md](DESIGN.md). This is **one candidate (draft A)**: the organisational choices in
§3.1, §3.3, §3.5 and §3.11 are open and are decided by the experiments in
[DESIGN_SPACE.md](DESIGN_SPACE.md); the correctness and safety items (§3.6, §3.9, §3.10) are not. Decisions still open are collected in §9; platform facts that need
a test before we rely on them are in §10.

## 1. What the v1 runs show

Measured over 187 agent transcripts and the 7 investigation directories under `investigations/`.

| Observation | Number |
|---|---|
| Investigators that ever `query` the board | 27 of 41 (64%); round 1: 15 of 29 |
| Investigators that used `ask` | 0 |
| Mail of type `query`, all runs | 1 (≈80% of mail is one-way `notice`) |
| Board entries of kind `question` | 7; no role owns answering them |
| Entries ever marked `status: confirmed` | stockd 0 of 64, stockd-onset 0 of 14 (a run that ended `met`), others 2–3 |
| Entries self-graded `confidence: high` by their investigator | stockd 26 of 64 |
| Child agents spawned by investigators (allowed: 2 each) | 0, in any run |
| `task note` calls per investigator | median 2; 16 of 42 wrote 0–1 notes |
| Share of fresh+output tokens by role | investigator 34%, challenger 25%, plan 10%, scope 10%, synthesizer 7%, judge 5%, refuter 5%, checkpoint 4% |
| Challenger verdicts, all runs | 33 `accept`, 1 `revise`, 0 `redo` (for 25% of spend) |
| Task outcomes, all runs | 35 of 38 `done`, 0 re-attempts — execution is not where runs fail |
| The one run that failed (stockd-before, 3/5 criteria) | a **cross-lane plan** failure: a `long` task held the exclusive port, starving another lane |
| `--as` identity mismatches | 2 of 666 write calls |
| Edit/Write outside the agent's own task directory | 0 of 68 |

Caveat: 29 of 41 investigators ran in round 1, so later-round behaviour is thinly sampled.

## 2. Diagnosis

1. **Nobody reasons about the problem as a whole.** Scope is barred from hypotheses, the
   planner is "not an analyst", the investigator is narrow, the synthesizer "does not
   investigate", the judge measures criteria. Planner and scope briefs never include
   `shared/synthesis.md`; the only directed signal into planning is the judge's gap list.
   Choosing the next most informative experiment has no owner, so work follows whatever is
   immediately at hand.
2. **Asking is irrational under the protocol.** Replies arrive next round; an investigator
   lives one round. "Never wait", "do not chase it".
3. **The worker is the only role whose brief carries no state.** Every other role gets state
   pushed; the investigator must pull, and cannot grep for what it does not know exists.
4. **Verification never reaches the board.** A challenger `accept` does not touch the entries
   it reviewed; `status` is effectively unused; the judge decides on self-graded confidence.
   `unverified` (review skipped for budget) exists only in the workflow's return value.
5. **Nothing looks outside the union of the lanes**, and the map of the system is never built.

## 3. Roles and mechanisms

### 3.1 Strategist (every round) and framing critic (on stall)

- **Strategist**: one agent per round, after the judge. **Decided by x3** (experiments/x3-strategy-council/results.md):
  a single strategist, **sceptic-framed** — "assume the leading hypothesis is wrong: what on the boards
  contradicts it, what did it predict that was not observed" — with **no target access** (it works from the
  boards, synthesis, verdicts and plans; on Sonnet 4.5 a strategist that can read the code does the
  investigators' job instead). It must list every explanation in play, including lane notes and open
  questions, treat negative results as evidence, keep ≥ 2 hypotheses live, and return per-hypothesis
  statuses plus ≤ 4 discriminating experiments. On the round-1 red-herring board this kept the true lead
  leading 3/3 where the plain strategist managed 2/6; on the true-lead board it never demoted the correct
  lead (0/9). The v1 judge's gaps alone: 0/9. Councils (persona members + chair) matched it at four times the
  cost; lane-advocate councils were worse than one strategist (advocates defend their lane's prior work).
  Reads synthesis, the KB map, judge gaps, `unknowns`, open leads. Maintains `shared/strategy.md`: hypothesis
  tree, for each live pair the experiment that would discriminate them, which lane should run it, what is
  deliberately not being pursued. Stateless — works from files, so no orchestrator handoff problem. Its
  output is pushed into scope and plan briefs (facts and the directive; not to workers — §3.2).
- **A round-level role, not a lane.** A lane's output reaches other lanes by mail, a round
  late and advisory; strategy has to sit in the control path, pushed into every planner's brief
  before planning starts. Position: after the judge (= start of the next round).
- **Two outputs.** `shared/strategy.md` (slow: hypotheses, what is not pursued and why; changes
  need new evidence) and a **round directive** (fast: the discriminating experiments this round,
  which lane runs each, ordering of exclusive resources). The directive is deliberately
  non-exhaustive: of a lane's `max_tasks_per_lane_round`, at least one slot stays the lane's
  own choice. It must keep ≥ 2 live hypotheses or justify holding one, and give the strongest
  alternative at least one task per round — otherwise top-down direction converges every lane
  on the strategist's favourite.
- **Plan review — decided by x2** (experiments/x2-plan-review/results.md): **lint only, no agent.**
  `board.py lint` runs after all lane plans land: `long` task holding an exclusive resource another
  lane queued for (the stockd-before failure), > 2 tasks fanning in on one exclusive resource, shared
  working locations, dead deps, over-cap, directive items neither covered nor declined. Validated on
  the real stockd histories: fires on both known failures, silent on four clean rounds.
  No reviewer agent: under the intent form below, planners already wrote the needed fact into the
  task 3/3 and never queued the wasted task; a reviewer had nothing left to do.
- **The channel to planners is intent, not orders.** The strategist's position reaches each planner
  as: hypotheses with statuses and reasons, the observations whose outcome differs between the live
  hypotheses, what is not pursued. No experiments unless only one will do; the lane designs the
  task. Measured equal to detailed orders on method and wasted work (3/3 vs 3/3), slightly more
  context cited, at no extra cost. Planners see the position, **not the judge's raw gap list**: 3/3 v1
  planners queued the wasted eviction hunt because a gap said so. The v1 planner also carries no
  board facts to the worker on its own (0/3 on the herring board, 1/3 with the fact on the shared
  board): the fact must arrive in its brief — from the position — and it then copies it into the task.
- **When it runs**: no gate agent — a gate would have to read what the strategist reads, so it
  costs the same. The script skips the strategist only on signals it already has for free:
  synthesizer counters all zero, judge `progress: true`, no refutation, no new leads. Otherwise
  it runs, on a **delta** computed by `board.py` (what changed since the last strategy version).
  "No change" is a first-class output; any change must cite the new evidence ids that justify
  it (hysteresis — a strategy that moves every round makes planners drop queued work).
  The wake rule is event-based and mechanical, not the strategist predicting its own relevance.
- **Seeded at setup**: the interview records the human's initial hypotheses as strategy v0.
- **Separate from the judge**: whoever directs the work must not grade it. Judge gaps stay
  "what the criteria still lack"; the strategist turns gaps into direction.
- **Framing critic**: the challenger role in a second mode, not a new role. Runs when the
  judge reports `progress: false` (and every N rounds) against `shared/strategy.md`:
  unexplained observations, assumptions every lane shares, the question nobody asked, criteria
  that look malformed. Emits `question` entries, scout tasks and proposals (§3.5).

### 3.2 Push context to the worker

- Investigator brief gains state — **facts, not beliefs** (x1: a pushed narrative with a wrong lead cut success
  and made 2 of 8 workers report a false hypothesis as confirmed; facts + KB page gave 8/8 on both boards):
  established entries and open questions from the task's `context`, the KB pages matching it, and
  hypotheses by id only, marked "under test — do not assume". The synthesis narrative and the strategy
  go to planners and the strategist, not to workers.
- Task field `context: [board ids, kb pages]` set by the planner; `task start` prints them in full.
- `RESULT` schema gains `unknowns: [..]` — what was assumed without checking. `task finish`
  rejects items that name no entity or path. Consumed by strategist, challenger and scout triggers.
- Verifiers stay blind: challenger and refuter do **not** receive the strategy narrative.

### 3.3 Consults (yield and resume, through the scheduler)

Decided: not nested children. Investigators never spawned a child in any v1 run, Agent-tool
children run in the background (a workflow agent that ends its turn to wait has returned), and
nested agents bypass the pool, the caps and the failure guard.

`board.py consult --kind how|why-intent|web|oracle --about <entity|path> --question Q --decision "what depends on it"`

A consult is a **synthetic task**; the asking task depends on it. That reuses `pump()` as is:
ordering, accounting, de-duplication (two askers depend on one ticket), and claims — the asker
releases its exclusive resources while the consultant runs.

| Tier | When | Cost to the asker |
|---|---|---|
| 1. Planned | planner lists `consults: [{about, question}]` on the task; they run as deps before it starts | none |
| 2. KB hit | `consult` finds a page; prints it with age and verification state | one tool call |
| 3. Pre-flight yield | first turns, after reading the task and its context | almost nothing to lose |
| 4. Mid-task yield | a blocking question found late | the agent's working context |

The design goal is to make tier 4 rare. It needs:
- `task yield --id T --ticket C-.. --established "..." --next "..." --refs ..` — a structured
  handoff, required by the SubagentStop guard (notes are too thin to resume from: median 2 per
  task). The same handoff serves salvage and revisions.
- `consult` refuses to yield while the task has recorded side effects still running, after
  `max_yields_per_task` (then: state the assumption, list it in `unknowns`, continue), and for
  sweep items.
- `RESULT.status` gains `yielded` with `consults: [ticket ids]`; the script runs the consultant
  (`brief --role consultant --ticket C-..`) and re-queues the task with the dep added.
- The consultant saves a KB page with the ticket. The asking task records the pages it relied
  on, so its challenger can check them.

One `consultant` role and prompt; the agent type differs by kind because tool limits do.

| Kind | Agent type | Notes |
|---|---|---|
| `how` | `explainer` | read-only; follows a code chain, cites `file:line` at a pinned SHA |
| `why-intent` | `explainer` | git history, PRs, design docs |
| `web` | `web` | least-privileged (§3.9); URL + quote + version applicability |
| `oracle` | `oracle` | `models.oracle` — only worth it when stronger than the workers; output is hypotheses + "how to verify locally", never facts |

Why-causal questions are the investigation itself: they become hypotheses, not consults.
Non-urgent `question` entries are owned by the strategist, who routes them into plans.

### 3.4 Knowledge base (per investigation)

- `kb/<slug>.md`: topic pages (service, log format, function chain, glossary term) with
  `[[links]]` and board ids. `board.py kb save|show|search|backlinks|gaps`; backlinks and the
  index are computed on read. `query --cited-by ID` on the board.
- Pages carry source SHA, author role, ticket, verification state. First write gets a `light` review.
- **KB pages are not evidence.** The judge counts board entries only.
- `kb gaps` (no agent): entities cited by ≥ N entries with no page; pages cited by many newer
  entries (stale); pages whose cited files changed.

### 3.5 Scouting, leads, proposals

- Task kind `scout`: read-only, breadth-first, deliverable = map pages + `lead` entries.
  The round-0 orientation (system map, log formats, correlation ids, time bases, glossary) is
  simply the first scout task.
- `horizon` lane archetype owns cross-lane scouting; idle unless a trigger fires.
- Triggers: stall; `kb gaps`; consult misses; clustered `unknowns`; critic blind spots.
- `lead` board kind: what, why it may matter, cost to explore, candidate owner. Open leads are
  capped and ranked against judge gaps.
- **Proposals queue** (`board.py propose --kind access|criteria|lane|resource`): agents never
  change the manifest. Anything needing new access, a new lane or changed criteria is
  presented at the checkpoint for a one-step accept.

#### Scope is four things; only one of them is agent-expandable

| Scope | v1 home | Who may widen it |
|---|---|---|
| **Access** — what may be touched (paths, hosts, network, writes, safety rules) | `scope.in/out`, `resources`, `safety` | human only; guard-enforced |
| **Focus** — where we are looking, inside access | mixed into `scope.in` | the strategist, within the bounds below |
| **Goal** — question and success criteria | `criteria` | human; agents add sub-questions, never edit criteria; the judge stays pinned to the original |
| **Effort** — budget | `budget` | human; agents allocate within it |

Manifest change: `scope.focus` (start here) ⊂ `scope.envelope` (may follow a trail here,
read-only, without asking) ⊂ everything else (proposal + `ask`, non-blocking). Setup asks:
"if the trail leads outside the starting point, where may agents follow it without asking?"

#### Bounds on autonomous focus expansion

1. **Frontier only.** A lead must cite the entry or KB page it grows from (`--from`), and
   include a first observation. The KB is the map: an entity that is referenced but unmapped
   is a *stub*; exploration means turning stubs into pages. No jumps to unlinked territory.
2. **Hop limit.** Distance in the link graph from a criterion-linked entry; beyond N hops
   needs strategist sign-off in the directive.
3. **Exploration budget.** A fixed share of each round's task slots (default ~20%; the
   strategist raises it on stall, lowers it when converging). A floor as well as a cap:
   today the share is zero.
4. **Two stages.** A `scout` task is a cheap, read-only, turn-capped look that ends with
   "worth pursuing? why"; only an adopted lead becomes a full task.
5. **Decay.** Leads not tied to a hypothesis, gap or unknown expire after N rounds.
6. **Reviewed after the fact.** The checkpoint report lists every widening
   ("+service B handler, from B-logs-0012") and the human can retract it by steering.

Investigators stay narrow: they record a lead (with its first observation) rather than chase
it. Autonomy lives at the strategist/scout level, where it is budgeted and visible.

### 3.6 Provenance and mechanical verification

Rules move from prose into `board.py`, with error messages that teach.

- `source: observed|derived|web|model` is **derived from the caller's role**, immutable.
  `model` entries: kind `hypothesis` only, confidence `low`, hidden from judge and refuter
  until an `observed` entry cites them. `web`: capped at `med` until checked locally.
- `task review accept` stamps the task's board ids `verified_by: review-N`. Entries from
  unverified tasks (verify `none`, or review skipped) are capped at `med`; the script records
  `unverified` through `board.py`, not only in its return value.
- Ref validation at `post`: `path:line` must resolve inside a declared target; optional
  `--quote` must be found near that line. Entries are stamped with the target's HEAD SHA;
  setup pins target SHAs in the manifest.
- Taint propagation via backlinks: entries that cite a refuted or superseded entry are flagged
  for re-review.
- `judge save` refuses to re-declare a criterion met on the evidence set a refuter rejected.
- Judge and refuter briefs include lane-level contradictions and refuted entries, not only
  the synthesizer's shared digest.

### 3.7 Web research lane

Optional archetype `web-research` (proactive: known issues for library X at version Y), plus
the `web` consult. Manifest `network: none|allowed` with query-hygiene rules (no proprietary
identifiers or log lines in search queries). Non-web roles get `disallowedTools: WebSearch, WebFetch`.

### 3.8 MCP servers as resources

`resources[]: {kind: "mcp", server: "grafana", capacity: 2, check: ...}`. Tasks already declare
resources; the scheduler picks the agent type from them. Setup generates per-investigation
agent variants (`tools` allowlist including `mcp__<server>__*`); the base investigator has no
MCP tools. `capacity: N` generalises `exclusive` (= capacity 1) for rate-limited services.

### 3.9 Hardening (latent in v1 — becomes live with web, log and MCP input)

| Hole in v1 | Change |
|---|---|
| Guard allows Edit/Write anywhere under the investigation dir — including `manifest.json` (its own `safety_deny`), `bin/board.py`, `prompts/*.md` | Guard scopes writes by role: investigator → its task dir; nobody → protocol files |
| `board.py write` is a deny-list: can overwrite `judge/round-NN.json`, `review-N.json`, `prompts/`, `lane.md` | Per-role allow-list of paths |
| `amend` may set any field except `id/op/supersedes` (body, author, confidence, kind) | Field allow-list per role; `source`, `author`, `verified_by` immutable |
| Anyone may `--supersedes` any id (hides contradictions and refutations); ids unchecked | Synthesizer or the entry's author only; ids must exist; refuted status carries over |
| `--as` is a free string | Guard checks `--as` against the identity in the agent's first prompt |
| Board bodies, mail and web text are re-read by other agents and by the main session (`report.md`) | Render external/quoted content inside data delimiters; `task-request` mail from `web`/`oracle` roles cannot create tasks without strategist sign-off |
| `safety_deny` is a regex deny-list | `web`/`oracle` roles: guard Bash **allow**-list (board CLI only) |
| Child agents whose prompt repeats the parent's header are guarded as the parent (could `task finish` its task) | Children get their own role header; guard knows the new roles |

### 3.10 Liveness and bookkeeping

- Stall uses two signals: criteria progress and exploration (new mapped entities, adopted
  leads, refuted hypotheses). Exploration credit is limited to N consecutive rounds.
- `judge save` writes `met_pending`; only an upheld refutation check writes `met`
  (v1 leaves `met` on disk when refuter and checkpoint both die).
- Steering can be superseded or expired.
- Entry ids from max+1, and appends guarantee a trailing newline (a truncated line currently
  swallows the next record and can duplicate an id).
- Briefs scale: judge/refuter get entries cited per criterion plus changes since the last
  verdict, not the whole shared board; scope gets strategy-ranked entries, not the newest 15.
- `kit_version` in the manifest; `/investigate:run` pre-flight compares it with the plugin
  (agents and guard are unpinned, the kit is pinned) and offers `board.py migrate`.

### 3.11 Reorganisation that pays for the additions (proposed — test on stockd first)

- **Retire the per-lane scope agent** (41 agents, ~10% of spend, rewritten from scratch every
  round). Since `brief` and `probe` exist, lane state and resource checks are computed; idle
  detection can be too (no open items, gaps, mail, steering or strategy assignments → lane
  skipped with no agent). Search-space recon moves to scout tasks and persists in the KB.
  Planner brief = computed digest + strategy + KB pages. Keep `scope: true` as a per-lane
  option where recon is real work (remote hosts). Saves one agent per lane per round — about
  what the strategist, horizon lane and consults cost.
- **Spend challengers where claims are load-bearing** (challengers are 25% of spend). Mechanical
  checks (§3.6) replace `light` review of self-evidencing work; add a **promotion review** —
  an unverified entry gets reviewed when the judge cites it for a criterion or the strategy
  hinges on it — so verification follows importance instead of task order.
- Net roles: 9 − scope + strategist + consultant = 10; critic and scout are modes of
  challenger and investigator.

## 4. Lane, service role or task kind?

| Need | Form | Why |
|---|---|---|
| Explain code / intent | consult → `explainer` | demand-driven; the asker needs it now |
| Ask the model | consult → `oracle` | demand-driven; a lane would launder guesses |
| Web research | consult **and** optional lane | both reactive and proactive uses |
| Scouting | task kind + `horizon` lane | proactive, own method, own deliverable |
| Whole-problem reasoning | per-round role (strategist) | cross-lane by definition |

A lane costs a scope and a plan agent every round; it must earn that by being proactive.

## 5. Cost per round (v1 ≈ 22 agents for 3 lanes, 2 tasks each, `light`)

strategist +1 · critic +1 on stall · horizon +1 idle / +2 and its tasks when triggered ·
consults budgeted (`max_consults_per_task: 2`, `max_consults_per_segment: 12`), amortised by
KB hits. Expect +15–40%.

## 6. Risks of this design

- **Protocol tax**: every feature lengthens the brief; Haiku already needs 2× the tool calls.
  Mitigate with role-sliced protocol text, push over pull, and enforcement by error message.
- **Push amplifies errors**: one wrong KB page or strategy reaches every agent. Hence page
  review, taint propagation, blind verifiers, the critic.
- **Strategist as single point of failure / anchoring**: premature convergence. The critic,
  and a required "not pursuing, and why" section, are the counterweights.
- **Goodhart**: `unknowns` decays to boilerplate; consults get used to outsource the task.
  Both need a consumer that scores them (challenger checks specificity; consult requires
  `--about` and `--decision`).
- **Same-model verification** catches sloppiness, not shared misconceptions. Prefer mechanical
  checks; consider a different model for the refuter.

## 7. Build order

1. **Target + metrics**: merged multi-service log whose answer needs another service's source
   (and whose trail leaves the initial focus); `wf_metrics.py` gains query rate, consult rate,
   KB hits, verified-entry share. **Verifier canaries**: fixtures with seeded faults (a wrong
   `file:line`, a single-run "reproducible", an overstated confidence, a plan with a resource
   conflict) to measure whether challenger, judge, refuter and plan review catch them — 33 of
   34 `accept` cannot distinguish good work from a rubber stamp.
2. Push context, `context`, `unknowns`, persisted `unverified`, `verified_by` (no new agents).
3. Hardening §3.9 (before any web or MCP input exists).
4. Strategist + critic.
5. Consults + explainer + KB.
6. Provenance, ref validation, taint; oracle and web.
7. Scout kind, horizon lane, leads, proposals, stall change.
8. MCP resources and agent variants; `capacity`.

## 8. Not doing

Why/how as separate lanes · a graph database · agents editing the manifest · a standing
"ask the model" lane · a librarian agent (KB upkeep is computed, plus explainer and synthesizer).

## 9. Open decisions

- Plan review: decided (x2) — lint every round, no reviewer agent; strategist → planner as intent.
- Hop limit and exploration share: defaults (3 hops, 20%) are guesses until the target exists.
- May the strategist open a lane from an archetype inside the envelope, or is a new lane
  always a proposal? (Draft: always a proposal; `horizon` covers the interim.)
- Strategist: decided (x3) — single, sceptic-framed, no target access. Council: not adopted; escalation (C4) unbuilt until a stall C1s cannot break is seen.
- Retire scope agents (§3.11) — outright, or opt-in per lane?
- Promotion review: in addition to planner-chosen `verify`, or replacing `light`?
- Digest should also surface lane `note` entries that no shared entry cites (x3: the true lead was a note marked "not followed up").
- `horizon` as its own lane vs. duties folded into `skunkworks` (v1 deliberately de-overloaded it).
- Refuter on a different model by default?

## 10. Verify before relying on it

- Are plugin-shipped MCP servers visible session-wide or only to the plugin's agents?
- Do MCP tools work in background workflow agents under allow rules alone?
- Can a `PreToolUse` hook rewrite the command (inject `--as`) rather than only check it?
