# X3 — strategist or council: results

2026-09-21/22. Target `trisvc`, profile `bursty`. Norm model Sonnet 4.5; Opus 5 reference at k = 1
in stage a. Plain workflow agents. Strategy roles reach only the bug report and config (a target
view; reads of source and logs fail); lane advocates see only their lane and the shared board
(other lanes' boards are emptied in their copy).

States, all with round 1 (or 1–2) finished and the next round to plan:
- **S1** red-herring board, end of round 1: eviction leads, deploy second; the timeline already shows
  drift before both; the true lead is an un-promoted low-confidence note on the static lane board.
- **S2** red-herring board, end of round 2, stalled: "0 of 171 evicted keys ever reserved again"
  reported as inconclusive; timing attribution failed; synthesis still leads with eviction; judge: no progress.
- **S0** true-lead board, end of round 1: the per-attempt-key explanation leads at med, static-only.

A position = hypotheses with status + a directive of ≤ 4 experiments. Scored by regex (true lead
live / leading / demoted; red herring demoted; directive contains a discriminating experiment)
and read by hand for the claims below.

## Pilot (k = 1) — fixture fixed twice

Every arm found the true lead: the static note was printed in the brief and 11 of 16 agents read
the 150-line source (`gateway.py`) — investigator work a strategist cannot do on a real codebase.
Lane advocates queried the other lanes' boards despite the instruction. Both were then enforced
physically (target view; board partition). Scorer regexes tightened.

## Stage a — Sonnet 4.5, k = 3 (Opus k = 1)

| Arm | S1: true lead live | S2: true lead live | S1: herring demoted | S2: herring demoted | Directive has the key trace | Tool calls |
|---|---|---|---|---|---|---|
| C0 v1 judge gaps | 0/3 | 0/3 | 0/3 | 0/3 | 2/6 | 8–15 |
| C1 single strategist | 2/3 | 3/3 | 1/3 | 3/3 | 5/6 | 4–5 |
| C2 persona council (union of 3) | 3/3 sets | 3/3 | 2/3 | 3/3 | 6/6 | 19–27 per set |
| C3 lane advocates (union of 3, partitioned) | 1/3 sets | 2/3 | 1/3 | 2/3 | 6/6 | 12–21 per set |

- **C0 → C1.** The strategist is worth its one cheap agent: 5/6 vs 0/6 on keeping the true lead live.
- **S1 is the hard state**; S2 (the negative result on the board) is handled by the strategist alone.
- **C2 members disagree**: ≥ 2 distinct leading choices in 6/6 Sonnet sets. The **sceptic** seat
  alone kept the true lead live 6/6 — better than the plain strategist (5/6) — and was the
  cheapest seat at S1.
- **C3 is out.** The static advocate — the one member whose own board holds the true-lead note —
  kept eviction leading 6/6 and once explicitly deprioritised the retry-key idea. Its lane
  authored the eviction hypothesis; the advocate defended it. Partition removed the cross-lane
  view strategy needs; the union of three advocates trails one strategist.
- **Opus** found the true lead in nearly every cell; organisation matters less on a strong model.
- Validity: 3 Opus trials (`C0-S1`, `C1-S1`, `C2-S1-breadth`) bypassed the view by searching the
  repo for the target; Sonnet never did. 2 Opus advocates lost to a 500-char schema cap (raised).

## Stage b — Sonnet 4.5, k = 3, concurrent baselines

b1 added **S0** (true-lead board: does anyone demote a correct lead?) and **C1s**, a single
strategist with the sceptic seat's framing ("assume the leading hypothesis is wrong; what on the
boards contradicts it; what did it predict that was not observed"). b2 ran a **chair** over each
Sonnet council set (choose, don't blend; check cited ids; fund the strongest dissent).

| Arm | S0: true lead leading | S0: true lead demoted | S1: true lead leading | S1: herring demoted | S2: true lead leading | Agents / round | Tool calls / round |
|---|---|---|---|---|---|---|---|
| C0 v1 judge gaps | 0/3 (3/3 mentioned) | 0/3 | 0/3 (stage a) | 0/3 | 0/3 (stage a) | 0 extra | 7 |
| C1 single strategist | 3/3 | 0/3 | **1/3** (stage a: 1/3; 2/6 overall) | 0/3 (1/6 overall) | 3/3 | 1 | 6–10 |
| C1s sceptic strategist | 3/3 | 0/3 | **3/3** | 3/3 | 3/3 | 1 | 7–11 |
| C2 members (union) | 3/3 sets | 0/9 | 3/3 sets (stage a) | 2/3 | 3/3 | 3 | 24–34 |
| C2c council + chair | 3/3 | 0/3 | **3/3** | 0/3 (kept live, not leading) | 3/3 | 4 | 30–40 |

- **No false demotion anywhere** (0 of 27 positions on S0). The sceptic framing does not turn
  into contrarianism: on the true board its positions read "leading: per-attempt keys; live:
  eviction", with "the leading hypothesis is wrong" listed as a live alternative in one trial.
- **S1 is the state that separates arms**, and the plain strategist fails it (2/6 leading over
  both runs). Its directives usually still contain the key trace, so a following round would
  probably have found the answer one round later, after an eviction hunt.
- **The chair chooses by evidence, not by count.** On S1 set 2, both focus and breadth led with
  eviction and the sceptic led with nothing; the chair chose the sceptic's position and made the
  retry-key mechanism leading. 9 of 9 chairs funded or checked dissent as instructed.
- **C1s equals the council + chair on every state at a quarter of the cost** (one agent, ~7 tool
  calls, ~6k output tokens vs four agents, ~35 tool calls, ~21k).
- Validity: Sonnet never reached target content in stage b (checked per tool result).

## Decision

1. **Adopt a single strategist, sceptic-framed (C1s)** — DESIGN_V2 §3.1. One agent per round,
   no target access, working from the boards, synthesis, verdicts and plans; it must list every
   explanation in play including lane notes and open questions, treat negative results as
   evidence, keep ≥ 2 hypotheses live, and return statuses plus ≤ 4 discriminating experiments.
2. **No council.** The persona council's members do disagree (6/6 sets on the herring boards,
   1/3 on the true board — the right shape) and its chair picks well, but it never beats the
   sceptic strategist and costs four agents. Escalation-to-council (C4) has no state here where it
   would have helped; it stays unbuilt until a stall that C1s cannot break is observed.
3. **Lane-advocate council rejected**: advocates defend their lane's prior work; the member
   holding the true-lead note kept the red herring leading 6/6.
4. The v1 judge's gaps are not direction (0/9 true lead leading across all states): the judge
   measures criteria, as designed, and something else has to choose the next experiment.

## Caveats

- One target, two planted red herrings, k = 3 per cell; Sonnet-only in stage b (Opus at k = 1 in
  stage a found the lead in almost every arm, so the organisation question is a small-model question).
- Positions were scored as text; nothing here measures what the *planners* then do with a
  directive. That coupling (strategist → plan → task) is E2's territory.
- The sceptic framing was chosen after seeing stage a; b1 was a fresh concurrent run, but the
  hypothesis came from the same fixture. A second target would settle whether it generalises.
