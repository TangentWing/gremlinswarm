# X2 — how a strategist's position reaches the planner: results

2026-09-22. Target `trisvc`, profile `bursty`. Planner role, plain workflow agents (the plan
agent's 12-turn cap not in force; the highest trial used 12 tool calls, most 3–5). 48 trials in
two runs (`pilot` k = 1, `full` k = 3), Sonnet 4.5 only. `full` was launched from a
notification-triggered turn: no user message was relayed, no trial touched `experiments/`,
every trial returned structured output and saved a plan.

States (from x3): **S1** red-herring board, end of round 1, eviction leading, true lead an
un-promoted note on the static lane board; **S0** true-lead board, per-attempt keys leading at
med, static-only. The strategist's position for each state is the x3 C1s output, scripted.
Lanes: `logs` (S0, S1) and `static` (S1). Planner writes ≤ 2 tasks for round 2.

| Arm | What the planner gets |
|---|---|
| P0 | v1: scope brief + judge gaps |
| P1 | detailed orders: the strategist's directive items for this lane verbatim (experiment, what it separates, predictions); may decline with a reason |
| P2 | intent only: hypotheses with statuses and reasons, what the round must settle, not-pursuing — no experiments, no lane assignment |
| P3 | P2 + a sceptic step in the planner ("assume the leading hypothesis is wrong; write what contradicts it and what it predicted that was not observed; queue one task that would show it wrong") |

`key_trace` = a queued task attributes inventory lines to requests through the key derivation
(the step that unblocks the criteria). `method` = how that task tells its worker to do it:
exact (sha1(rid:attempt) / B-static-0002 named), pointer (read `gateway.py`), none (guess by
sku/timestamp — x1 showed the guess fails on this log). `eviction hunt` = a task looks for
evicted keys being reserved again (the wasted task of x3's S2 state).

## Results — Sonnet 4.5, k = 3

| arm | lane | state | trace task | method exact | method pointer | timing guess | eviction hunt | follows note | cites ids (avg) | adversarial | lint | sceptic note | tools |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P0 | logs | S0 | 2/3 | 1/3 | 0/3 | 0/3 | 0/3 | 1/3 | 0.0 | 3 | 0 | — | 3.0 |
| P0 | logs | S1 | 2/3 | **0/3** | 1/3 | 1/3 | **3/3** | 3/3 | 0.3 | 2 | 0 | — | 4.0 |
| P0 | static | S1 | 2/3 | 2/3 | 1/3 | 0/3 | 0/3 | 3/3 | 1.0 | 3 | 0 | — | 4.3 |
| P1 | logs | S0 | 3/3 | 3/3 | 0/3 | 0/3 | 1/3 | 3/3 | 0.0 | 1 | 0 | — | 3.7 |
| P1 | logs | S1 | 2/3 | 3/3 | 0/3 | 0/3 | 1/3 | 3/3 | 1.0 | 1 | 0 | — | 4.7 |
| P1 | static | S1 | 2/3 | 3/3 | 0/3 | 0/3 | 0/3 | 3/3 | 0.3 | 4 | 0 | — | 3.0 |
| **P2** | logs | S0 | 3/3 | 3/3 | 0/3 | 0/3 | 1/3 | 3/3 | 1.3 | 2 | 0 | — | 4.0 |
| **P2** | logs | S1 | **3/3** | **3/3** | 0/3 | 0/3 | **0/3** | 3/3 | 1.0 | 1 | 0 | — | 3.7 |
| **P2** | static | S1 | 2/3 | 3/3 | 0/3 | 0/3 | 0/3 | 3/3 | 0.7 | 4 | 0 | — | 7.0 |
| P3 | logs | S0 | 2/3 | 2/3 | 0/3 | 1/3 | 2/3 | 2/3 | 0.3 | 1 | 0 | 2/3 | 5.7 |
| P3 | logs | S1 | 2/3 | 3/3 | 0/3 | 0/3 | 0/3 | 3/3 | 0.7 | 3 | 0 | 2/3 | 3.7 |
| P3 | static | S1 | 3/3 | 3/3 | 0/3 | 0/3 | 0/3 | 3/3 | 0.7 | 4 | 0 | 3/3 | 8.0 |

(`lint` = findings of `harness/lint.py` on the saved plan; `adversarial` = count of tasks at that verify level across the cell; `tools` = tool calls per trial.)

## What it shows

1. **The v1 planner runs the eviction hunt on the red-herring board, and cannot tell its worker
   how to attribute.** P0 logs S1: 3/3 queued an "evicted keys reserved again" task; the trace
   task's method was `none` or `pointer` in every trial (one queued a timing guess — the method
   x1 showed fails on this log). This is the round x3's S2 state was frozen after.
2. **Any strategist position removes the hunt and fixes the method.** P1 and P2 on S1: method
   exact 3/3 in every cell; eviction hunts 0/3 (P2) and 1/3 (P1). The position, not its form,
   carries the value — the planner reads "not pursuing: eviction" and the mechanism statement
   and turns them into a task that names `sha1(rid:attempt)` / B-static-0002.
3. **Intent matches or beats orders.** P2 ≥ P1 on every scored column on S1 (logs: trace 3/3 vs
   2/3, hunts 0/3 vs 1/3) and equal on S0. Given intent, the planner converts it into the right
   experiment on this model. Orders bought nothing, and P1 planners cited fewer board ids.
4. **The planner-side sceptic step does not pay.** P3 vs P2: no gain on S1 (logs trace 2/3 vs
   3/3; static 3/3 vs 2/3 — one trial each way), and on the *true-lead* board S0 it produced
   2/3 eviction hunts (vs 1/3), one timing-guess task and one trial with no key trace at all.
   The written notes are reasonable ("171 evictions vs 33 timeouts — drift may exceed the
   retry mechanism") but the doubt lands on the correct lead and spends a task on the rival.
   The x3 result holds one level down: scepticism belongs in the strategist, once per round,
   not in every planner. The step was also followed only 7/9 times, and cost 1.5–2× the tool calls.
5. **Lint found nothing** in 36 two-task plans on this fixture. It has real catches on stockd
   (spec `lint.validated_on`); nothing here contradicts B0 (lint only), and nothing here
   tests B1/B2 (a plan reviewer) either — with ≤ 2 tasks per lane on an unshared target there
   is no conflict to catch.
6. On S0 the eviction task is not obviously waste: the criteria demand the rival ruled out, and
   P1/P2 queued it 1/3 alongside a correct trace. The metric is about S1, where the hunt
   replaces the trace.

## Decision (spec rule)

**Adopt P2 — intent.** The strategist's position reaches the planner as hypotheses with statuses
and reasons, what the round must settle, and not-pursuing; the strategist names no experiments
per lane and assigns nothing. This is the cheaper coupling for DESIGN_V2 §3.1 (the strategist
keeps ≤ 4 discriminating observations in its own position, for the record and the judge, but the
lane planner is not handed orders). The judge's raw gap list leaves the scope brief; the
position carries it. **P3 not adopted.** Plan review (axis B): stay at B0 (lint) until an
end-to-end run on stockd shows a conflict lint misses.

## Caveats

- One target, two states, k = 3; the positions were scripted from x3's C1s output rather than
  produced live, so this measures the channel, not strategist variance.
- Plain agents; the 12-turn plan cap was not in force. P3 static S1 averaged 8 tool calls and
  one trial hit 12 — under the plugin the sceptic step would risk the cap. P2 sits at 4–7.
- `method`, `eviction hunt` and `key_trace` are regex over task text, spot-read on the cells
  that decide (P0-logs-S1, P2-logs-S1, P3-logs-S0).
- Nothing here measures what the *worker* then does with an `exact` task; x1 covers that.
