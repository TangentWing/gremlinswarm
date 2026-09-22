# Experiments

Small, component-level experiments that decide the open organisational questions in
[../DESIGN_SPACE.md](../DESIGN_SPACE.md). One role, on a frozen investigation state, many
trials per arm, scored mechanically. Full investigations are only used to confirm winners.

Norm model: **Sonnet 4.5** (`claude-sonnet-4-5`). Reference: Opus 5 (`claude-opus-5`), to tell
"the model can't" from "the prompt doesn't". Record the model that actually ran — ids get remapped.

## Layout

```
targets/trisvc/          build_target.py (seeded generator = answer key), services/ (the real source)
states/build_state.py    scripted board states on trisvc, written through board.py
harness/prepare.py       spec -> trial dirs (investigations/_exp/...) + workflow args
harness/run_trials.js    workflow: one agent per trial; prompt builders copied from investigate.js
harness/score.py         mechanical scoring (verifier roles), transcript metrics, contamination check
harness/score_work.py    mechanical scoring for investigator trials (trace.json vs the answer key, route, cost)
harness/enrich.py        prototype of a computed verification digest for judge / refuter briefs (now board.py digest)
harness/lint.py          cross-lane plan lint, validated on the real stockd plan histories (→ board.py lint)
harness/score_strategy.py, score_plan.py   scorers for strategy positions (x3) and plans (x2)
xN-<name>/spec.json      question, cells/arms, metrics and the decision rule — written before running
xN-<name>/runs/<run>/    trials.json, returns.json, scores.json
xN-<name>/results.md     what we learned and what it decides
```

Generated material is git-ignored: the target in `targets/trisvc/`, trial directories in
`investigations/_exp/` (already covered by an allow rule in `.claude/settings.local.json`).

## The `trisvc` target

Gateway, orders and inventory (~50 lines each) plus one merged log (~900 lines) produced by
running that source under a seeded simulation. Symptom: inventory holds more reserved stock
than orders has confirmed. Gateway lines carry `rid` but no key; inventory lines carry `key`
but no rid; joining them needs the key derivation in `gateway.py` — the "merged log you cannot
read without the source" case. Two profiles: `base` (x0; a timing heuristic can still attribute
every reserve) and `bursty` (x1; same-SKU bursts and network jitter make the source necessary —
`build_target.py --profile bursty`, output in `targets/trisvc-bursty/`). Two red herrings (cache eviction, a coincident deploy). Cause,
line numbers, affected requests and the discriminating experiments are in `answer_key.json`.

**Never point an agent at `experiments/`.** `score.py` invalidates any trial whose agent touched it.

## Running one

```bash
python3 experiments/targets/trisvc/build_target.py --check      # once, or after changing services/
python3 experiments/harness/prepare.py x0-verifier-canaries --run pilot
# Workflow: scriptPath = experiments/harness/run_trials.js, args = the content of runs/pilot/args.json
# score.py reads the returns from the workflow journal in the transcript dir:
python3 experiments/harness/score.py x0-verifier-canaries --run pilot --transcripts <transcript dir>
```

## Conventions

- Spec first: metrics and the decision rule are fixed before the run.
- Pilot (k = 1) before every full run: shakes out the harness, measures cost per trial, and
  calibrates difficulty. If the norm model is at 0% or 100% on the baseline arm, fix the
  fixture — an arm that cannot fail or cannot succeed measures nothing.
- Arms are prompt/brief variants laid over each trial's own kit copy; `investigate/` is not
  touched until an arm wins.
- Fidelity caveat: unless the session was started with `claude --plugin-dir ./investigate`,
  trials run as plain workflow agents — no role agent definition (system prompt, turn cap,
  tool limits) and no guard hook. This is v1's supported `--no-agent-types` mode. Note which
  mode a run used in its results.

- Launch message hygiene: a workflow launched in the same turn as a user message gets that message relayed,
  verbatim, to every trial agent as "the user request". Launched from a turn triggered by a task notification,
  nothing is relayed. In `confirm1` the relayed text named the hand-off file and 7 of 72 agents opened it; in the
  x2 pilot it carried the experimenter's hypothesis and a planner commented on it. Launch scored runs from
  notification-triggered turns (or with a neutral message such as "go"), then check the first agent transcript.

## Experiments

| # | Question | Status |
|---|---|---|
| x0 | Do the v1 verifiers catch planted faults and leave clean work alone? | done — [results](x0-verifier-canaries/results.md): gross faults caught; absences missed on Sonnet 4.5; digest + coverage rule + higher turn caps adopted into the kit after a plugin-mode confirmation; guard-hook bug found and fixed |
| x1 | Does pushed context (and an explainer KB page) help an investigator on the merged log, and does a wrong lead anchor it? | done — [results](x1-context-push/results.md): Sonnet 4.5 does not pull; push facts and KB pages, never the narrative; the explainer page is the robust win |
| x2 | Which plan review earns its cost, and how should the strategist's position reach a planner? | done — [results](x2-plan-review/results.md): no-agent lint (validated on stockd's real failures); intent equals orders; the v1 planner carries no board facts to workers by itself |
| e6 | Does the v2 slice work end to end, under the plugin, on trisvc and on the held-out stockd? | prepared — `e6-end-to-end/HANDOFF.md`; needs a `--plugin-dir` session |
| x3 | Single strategist or council (members first, chairs only if they disagree)? | done — [results](x3-strategy-council/results.md): a single sceptic-framed strategist, no target access; councils match it at 4× the cost; lane advocates defend their lane's work |
