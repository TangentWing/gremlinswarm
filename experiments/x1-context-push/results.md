# X1 — context push: results

2026-09-21. Target `trisvc`, profile `bursty` (seed 3). Investigator role, plain workflow agents
(45-turn cap not in force; the highest trial used 34 tool calls). 61 trials in four runs
(`pilot-base`, `pilot2`, `full`, `followup`), ~3.3M subagent tokens. Sonnet 4.5 k = 4 per cell,
Opus 5 k = 1 in `full`. No contaminated trials, every trial returned structured output.

Task: trace ≥ 5 timed-out requests end to end and deliver `trace.json`. The task text does not
say how an inventory `key=` relates to a request id; that fact lives in `gateway.py`. Success =
every row's reserve lines equal the answer key's, and at least 5 rows.

## Calibration

On the `base` profile the fixture measured nothing: 6 of 7 pilot trials succeeded, the
no-context arms included, by attributing reserves with sku, qty and timing (`timestamp − took`).
`build_target.py` now scores that heuristic itself: 100% of rows on `base`, 36% on `bursty`
(same-SKU bursts, jittered hops). All results below are on `bursty`.

## Results — Sonnet 4.5, k = 4

| Arm | What the worker gets | True lead on the board (T) | Red-herring lead (H) | Tool calls | Fresh input tokens |
|---|---|---|---|---|---|
| A0 | v1 brief (pull only) | 2/4 | 3/4 | 21 | 147k |
| A0d | + declared dep on the static task | 2/4 | — | 27 | 81k |
| A1 | + synthesis narrative and the planner's attached entries | **4/4** | **2/4**, 1/4 wrote that its evidence *confirmed* the false lead | 21 | 71k |
| A1L | A1 + "hypotheses are not established" label | — | **1/4**, 1/4 still credited eviction | 25 | 89k |
| A2 | A1 + explainer KB page | 4/4 | 4/4, 1/4 echoed the false lead as confirmed | 14 | 66k |
| **A3** | **established entries + open questions + KB page; hypotheses by id only, marked "under test"** | **4/4** | **4/4**, 0/4 endorsed the false lead (one mentioned eviction in passing) | 16 | 65k |

Endorsement of the false lead was read by hand; the scorer's regex is only a pointer.

Opus 5 (k = 1): 33/33 rows in six of seven cells — it traces every timed-out request with a
script. The exception is A1-H: handed the red-herring narrative it opened no source, wrote a
timing heuristic and got 14/33, while the *un*-pushed Opus in A0-H queried the board, read
`gateway.py` and got 33/33.

## What it shows

1. **Pull does not happen on Sonnet 4.5.** Unprompted board queries: 1 of 8 no-context trials
   (4 of 40 overall). Opus queried in 3 of 3 cells where nothing was pushed or declared. This is
   the capability gap behind "agents don't draw on each other".
2. **Pushed context is used, and it is cheap**: with the right lead pushed, 4/4 instead of 2/4 at
   a third of the input tokens (the pull-only worker burns tokens rediscovering).
3. **A declared dep is a weak channel.** All four A0d workers ran `task show` on the dep and saw
   the method; two attributed by timing anyway.
4. **Pushing a narrative crowds out pull and anchors.** With a wrong lead pushed, success fell
   (3/4 → 2/4; Opus 33/33 → 14/33) and 2 of 8 workers reported their evidence as confirming the
   false hypothesis, at high confidence, while their own traces showed per-attempt keys. A label
   ("not established") did not repair it (1/4).
5. **The explainer page is the robust win**: 8/8 with a narrative beside it, 8/8 without, lowest
   cost — it carries a mechanism fact with file:line, not a belief about the answer.
6. **Facts, not beliefs**: pushing established entries, open questions and KB pages, with
   hypotheses present only as ids marked "under test", gave 8/8 and no endorsement of the
   false lead.

## Decision (spec rule)

Narrative push (A1) is **not adopted**: it beats pull-only on the true board but raises anchoring
and lowers success on the red-herring board. Adopted for DESIGN_V2 §3.2: **A3** — the worker's
brief carries established entries and open questions chosen by the planner (`context`) and the KB
pages that match the task; hypotheses by id only; the synthesis narrative and strategy stay with
planners and the strategist. The explainer/KB mechanism (§3.3–3.4) is supported directly: the
page is what made workers robust to a wrong board.

## Caveats

- k = 4 per cell, one target, one task; fixtures written by the experimenter. Differences of one
  trial are noise; the claims above rest on 4/4 vs 2/4-or-worse and on hand-read transcripts.
- A2 and A3 both contain the KB page, so their success is mostly the page; A3's contribution is
  the absence of anchoring. "Facts without the page" was not run.
- The KB page was scripted. In a real run somebody has to write it first — that is the explainer
  consult, one agent, amortised over every later worker.
- Known target artifact: requests are simulated one after another, so a late-completing timed-out
  attempt is processed before its retry and `duplicate request ignored` can precede `confirmed`.
