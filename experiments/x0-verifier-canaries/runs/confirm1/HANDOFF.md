# HANDOFF — run `x0-verifier-canaries / confirm1` under the investigate plugin

You are a Claude Code session started for one job: launch one prepared workflow, score it, and
report. Everything is already built. **Do not edit any file, do not rebuild anything, do not
re-run `prepare.py`** (it would wipe the prepared trial directories).

Repo root (your working directory): `<repo>`

## Why this run exists

Earlier runs in another session tested the investigation kit's verifier roles (challenger,
judge, refuter) against planted faults on a small target. Three cheap prompt/brief overlays
recovered most of what Sonnet 4.5 missed (`../../results.md`). But those runs used plain
workflow agents: the plugin was not loaded, so the role **turn caps were not in force**
(challenger 25, judge 15, refuter 30), nor the role system prompts, tool limits or guard hook.
Some overlay trials used more tool calls than the cap allows. This run repeats the comparison
**with the plugin's role agents and with concurrent baselines**, to learn:

1. Do the overlays still work under the real role agents?
2. How often does a trial hit its turn cap and return no verdict?
3. Are the baselines from the earlier run reproducible?

## Preconditions — check before launching, stop if one fails

1. The session was started from the repo root with the plugin loaded:
   `claude --plugin-dir ./investigate`
2. Your available agent types include `investigate:challenger`, `investigate:judge` and
   `investigate:refuter`. If they are not listed, **stop and tell the user** — running without
   them would silently repeat the earlier, cap-less conditions.
3. The Workflow tool is available (Dynamic workflows enabled in `/config`).
4. `ls investigations/_exp/x0-verifier-canaries/confirm1/sonnet45 | wc -l` prints `72`.

Permissions: `.claude/settings.local.json` already allows `Workflow`, anything under
`investigations/_exp/`, and `grep`, `sed -n`, `wc`, `python3 -c`. Do not change settings.

## Step 1 — launch (the user's request to run this file is the opt-in for the Workflow tool)

Call the **Workflow** tool with:

- `scriptPath`: `<repo>/experiments/x0-verifier-canaries/runs/confirm1/run_trials.frozen.js`
- `args`: the JSON object in `experiments/x0-verifier-canaries/runs/confirm1/args.json` — read
  the file and pass its content **as an object, not a string**. Do not alter it.

It runs 72 independent single-agent trials (24 cells × 3), all on `claude-sonnet-4-5`, each in
its own prepared investigation directory. Expect roughly 45–70 minutes and ~3M subagent tokens.
Note the **Transcript dir** printed at launch. Tell the user it is running and wait for the
completion notification. If a permission prompt appears for an agent, tell the user what it
asked for; do not add allow rules yourself.

## Step 2 — score

```bash
python3 experiments/harness/score.py x0-verifier-canaries --run confirm1 --transcripts "<Transcript dir>"
```

This writes `runs/confirm1/returns.json` and `scores.json` and prints three tables:
per-role rates, per-cell outcomes, and per-cell tool calls against the role cap with the count
of trials that returned nothing.

## Step 3 — report to the user (and save the same text)

Save the full scorer output, followed by your notes, to
`experiments/x0-verifier-canaries/runs/confirm1/REPORT.md` (the one file you may create), and
show it to the user. In the notes, state:

- whether the plugin agent types were really used: `python3 -c "import json,glob,collections;print(collections.Counter(json.load(open(f)).get('agentType') for f in glob.glob('<Transcript dir>/agent-*.meta.json')))"`
- how many trials returned no structured output, per cell, and whether those cells also show
  tool calls at the cap;
- any guard-hook interventions or permission denials you saw;
- nothing else — no interpretation is needed; the originating session will read the numbers.

## What the run contains

Baseline = the kit's v1 prompts. Each overlay is already applied inside the trial directories
(`prompts/*.md` of that trial); you do not apply anything.

| Cells | Role | Planted fault | Compared |
|---|---|---|---|
| `ch-C-logs` | challenger | none (clean control) | baseline vs `@exhaustive` |
| `ch-S2` | challenger | row 5 of 6 in a trace table cites real log lines that belong to other requests | baseline vs `@exhaustive` |
| `ch-S3` | challenger | "all 15 requests" claim with one counterexample outside the sample | baseline vs `@exhaustive` |
| `ju-J0`, `re-J0` | judge, refuter | none (clean control) | baseline vs `@crosscheck`, `@digest`, `@digest-rule` |
| `ju-J3`, `re-J3` | judge, refuter | shared root-cause entry asserts a mechanism another shared entry rules out | baseline vs `@crosscheck` |
| `ju-J4`, `re-J4` | judge, refuter | a rival explanation raised on a lane board, absent from the shared board | baseline vs `@digest-rule` |
| `ju-J5`, `re-J5` | judge, refuter | shared evidence promoted from a task its challenger rejected (`redo`) | baseline vs `@digest` |

Overlays: `exhaustive` = "check every row, write `checked N of N`, look for counterexamples
outside the sample" (challenger). `crosscheck` = one consistency step (judge, refuter).
`digest` = tool-computed facts appended to the role prompt: review status of the task behind
each shared entry, and open lane hypotheses no shared entry cites. `digest-rule` = the digest
plus one sentence saying what an open rival means for the criteria.

## Never

- Read or mention `experiments/targets/` or `answer_key.json` in any agent prompt (the scorer
  invalidates contaminated trials).
- Edit `investigate/`, `experiments/harness/`, the spec, or the prepared trial directories.
- Re-run with different models, k or cells. If the run fails part-way (rate limits, many null
  agents), report what happened; the same `scriptPath` and `args` with `resumeFromRunId` replays
  completed agents from cache **in the same session**.
