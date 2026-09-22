# Investigation Kit v2 — design space and experiments

[DESIGN_V2.md](DESIGN_V2.md) is one candidate (call it draft A). This file records the
**alternatives still open**, what each predicts, and the small experiments that choose between
them. Nothing is implemented. Started 2026-09-20.

## 1. How decisions get made

| Kind of decision | How | Examples |
|---|---|---|
| Correctness and safety | by argument — just do it | hardening (V2 §3.9), `met_pending`, persisted `unverified`, `verified_by` stamps, ref validation, id robustness, kit versioning |
| Organisation and behaviour | by experiment (below) | every axis in §2 |
| Defaults (numbers) | guess, then tune on the target | hop limit, exploration share, consult budget |

A full run costs 12–60 agents and millions of tokens, and single runs are anecdotes (DESIGN §11
is n = 1 per row). So organisation questions are tested **per component on frozen state**, many
trials per arm; end-to-end runs only confirm the winners.

## 2. Axes

Each axis lists its options (★ = draft A), the claim being tested, and what it interacts with.

### A. Context push — what the worker and planner see without asking
- A0 v1: no state in the investigator brief; planner sees scope brief only
- A1 ★ strategy summary + confirmed/refuted + KB index + task `context`
- A2 A1 but verifiers and a share of investigators stay blind to the leading hypothesis
- Claim: push raises use of other agents' results more than any "ask more" prompt.
  Counter-claim: push anchors every agent on the leading hypothesis and amplifies one wrong page.
- Interacts with: B, C (a planner or critic that already sees cross-lane context is less blind).

### B. Plan review
- B0 lint only (`board.py`: directive coverage, `long` + contested exclusive claim, write conflicts)
- B1 ★ one cross-lane reviewer per round (lint + enrich + ≤ 1 revise); needs a planning barrier
- B2 per-lane critic, pipelined (no barrier), reading pushed cross-lane context
- B3 no reviewer; the planner enriches its own tasks (`context`, planned consults)
- Note: under A1 the case for B1 weakens. Conflicts between plans written *at the same time*
  cannot be seen through pushed context (it is last round's state) — but those are exactly what
  lint catches. What is left for an agent is enrichment, which is lane-local. B1's own context
  also grows with lanes × tasks. So B0+B3 and B2 are live contenders. **Pinned for E2.**

### C. Strategy
- C0 v1: judge gaps are the only direction
- C1 ★ single stateless strategist (strategy + round directive), critic on stall
- C2 persona council: k = 3 members with different mandates (exploit / explore / sceptic),
  independent positions, then a chair
- C3 **lane-representative council**: one advocate per lane writes a position (what the lane
  learned, its leading hypothesis, what it wants from other lanes, its proposal); a chair
  synthesises the directive. Members differ in *information*, not just in sampling. Replaces the
  v1 scope agent one-for-one, so it is budget-neutral against v1.
- C4 escalation: C1 by default; convene a council only on stall, live contradiction, refuted
  `met`, or a proposed strategy change
- C5 model-diverse council (members on different models)
- Council protocol, if any: positions are written **independently** (no cross-talk — avoids
  conformity to the first or most confident voice); the chair must *choose*, not blend;
  **dissent is preserved** by funding the top minority position from the exploration share;
  the hysteresis rule (V2 §3.1) binds the chair.

### D. Consults
- D0 none (v1)   D1 ★ yield and resume, four tiers   D2 planned consults + KB hits only (no yield)
- Claim: most of the value is in tiers 1–2; mid-task yield may never pay for its context loss.

### E. Scope agent
- E0 keep (v1)   E1 ★ retire, computed digest   E2 opt-in per lane   E3 repurpose as lane advocate (C3)

### F. Verification spend
- F0 v1: planner-chosen per task   F1 ★ mechanical checks + promotion review   F2 F0 + mechanical checks

### G. Focus expansion
- G0 none (v1)   G1 ★ frontier-only leads, hop limit, exploration floor/cap, scout then adopt
- G2 G1 without the hop limit (budget is the only bound)

## 3. Adversarial notes on the council (C2–C5)

1. **Same model + same input = correlated votes.** Agreement is not evidence. If members agree
   in > 90% of trials the council is an expensive single strategist. Measure disagreement first.
2. **It is not decentralisation.** A council is one central decision with redundancy. v1's
   decentralisation is lanes planning independently; C3 is the variant that actually draws on it.
3. **The chair is the single point of failure again.** The council is the chair's judgment with
   richer input. Majority bias drops the (possibly correct) minority — hence funded dissent.
4. **Committee mush.** Blended directives ("look further into A and B") discriminate nothing.
   Directive items must be concrete experiments naming the hypotheses they separate.
5. **Assigned personas manufacture their role.** A designated sceptic always objects, so its
   objections carry little information. Information-diverse members (C3) dissent authentically.
6. **Churn.** A different majority each round. Hysteresis applies to the chair's output.
7. **Cost and latency.** k + 1 agents and two sequential steps at the round boundary, on top of
   any plan-review barrier. Shared prompt prefixes make members cheap in cache reads, not in latency.
8. **Most rounds do not need deliberation.** Execution rounds need none; stalls and
   contradictions do. That is the argument for C4.

## 4. Method

**Snapshot replay.** An investigation directory is the whole state, so a copy is a checkpoint.
A component experiment copies a frozen directory, runs only the role under test (k trials per
arm, in a small workflow script), and scores the output. Add `board.py snapshot` (called from
`judge save`) so future runs leave a snapshot per round.

Existing fixtures: `stockd-before` (after round 2, 3/5 criteria, the cross-lane port
starvation), `stockd` (after round 1, interrupted), `stockd-onset`, the toy runs. Answer key:
`examples/stockd/build_target.py`. To build: the merged multi-service-log target whose trail
leaves the initial focus (needed for D, G and any end-to-end confirmation).

**Seeded faults (canaries).** Copies of a snapshot with one planted defect each: wrong
`file:line`; "reproducible" from one run; overstated confidence; a finding contradicted by an
existing entry; a plan with a resource conflict; a plan that ignores the directive; a task whose
worker will obviously lack a fact. Score = caught / planted, plus false alarms on the clean copy.

**Rules.**
- Metrics and the decision rule are written down before the run.
- Mechanical scoring against the answer key wherever possible; a rubric grader only where not,
  and then the grader is itself checked on a few hand-scored cases.
- k ≥ 5 trials per arm; report the spread, not the best run.
- Two model arms where it matters (a strong model and Haiku 4.5): the target user is small-model.
- Snapshots from both strong-model and small-model runs — small-model boards are messier.
- A token budget per experiment; stop when the decision rule is met.
- At least two targets before generalising (stockd has one planted cause and known red herrings).

## 5. Experiments

Ordered by dependency: A shapes B and C, so it goes first.

| # | Question | Arms | Fixture | Metric | Cost / trial |
|---|---|---|---|---|---|
| E0 | Do the verifiers catch anything? | challenger, judge, refuter as in v1 | canaries | caught / planted; false alarms | 1 agent |
| E1 | Does pushed context get used, and does it anchor? | A0 / A1 / A2 investigators on the same task | `stockd` r1 snapshot, plus one where the leading hypothesis is the red herring | cites prior entries; repeats known work; follows the wrong lead | 1 agent |
| E2 | Which plan review earns its cost under A1? | B0 / B1 / B2 / B3 | `stockd-before` r1 plans + plan canaries | conflicts caught; useful `context` attached (vs. what the worker later needed); agents and barrier time | 1–5 agents |
| E3 | Single strategist or council? | C0 / C1 / C2 / C3 (C5 if C2 shows low disagreement) | `stockd-before` r2, `stockd` r1, a stalled snapshot | directive contains the discriminating experiment; true cause kept alive; red herring deprioritised; inter-member disagreement; round-to-round churn on replays | 1–6 agents |
| E4 | Does yield-and-resume pay? | D1 tier 3 vs tier 4 vs "assume and continue" | task snapshots cut at turn 3 and turn 20 | resumed task reaches the same result; extra turns; handoff completeness | 2–3 agents |
| E5 | Does retiring scope hurt plans? | E0 / E1 (/ E3 with C3) | `stockd` r2 state | plan quality rubric; planner context size; agents | 1–2 agents |
| E6 | End-to-end confirmation | v1 vs. the winners | merged-log target, then stockd | criteria met; agents; tokens; ≥ 3 runs per arm | 40–60 agents |

Decision rules (examples): adopt a council only if it beats C1 on the directive score by more
than the spread across C1 trials **and** disagreement is > 10%; otherwise C4 or C1. Adopt B1
over B0+B3 only if it catches conflicts lint misses or attaches context B3 does not.

Status 2026-09-21 (the experiments use their own small `trisvc` target, not stockd snapshots; E-numbers map to x-numbers in `experiments/`):
- **E0 done** — experiments/x0-verifier-canaries/results.md. Verifiers catch gross faults, miss what is absent from their view; digest, coverage rule and higher turn caps adopted into the kit (DESIGN.md §11a).
- **E1 done** — experiments/x1-context-push/results.md. Axis A decided: **A3, a new option** — push established entries, open questions and KB pages; hypotheses by id only; no narrative to workers (A1 anchors: 2 of 8 workers 'confirmed' a false lead). Axis D: KB hits (tier 2) are strongly supported; yield-and-resume untested.
- **E3 done** — experiments/x3-strategy-council/results.md. Axis C decided: **C1 with the sceptic framing** (a new option, C1s). C2 members disagree (6/6 sets on wrong boards) and the chair picks by evidence, but the council never beats C1s and costs 4×. C3 (lane advocates) is worse than one strategist: advocates defend their lane's prior work. C4 stays unbuilt. Also: strategy roles must be denied target access, and lane partition must be enforced by board.py, not by prompt.
- **E2 done** — experiments/x2-plan-review/results.md. Axis B: **B0 (lint) adopted; no reviewer agent.** Also decided: the strategist reaches planners as *intent* (hypotheses + what to settle), equal to detailed orders at no cost; planners must not see the judge's raw gaps; a sceptic step at the planner adds nothing. The v1 planner carries no board facts to workers by itself (0–1/3) — the position is the channel.
- **E6 run 1 done** — experiments/e6-end-to-end/results.md. The slice works end to end under the plugin: stockd (held out) 4 of 5 with the generator's answers, trisvc everything on the board. Found and fixed: verification debt (cap-skipped reviews and challengers that never recorded a verdict stalled a run with the answer on the board); the SubagentStop gate is inert for workflow agents. Run 2 next, with the debt step and the guard debug switch.
- Remaining: D (yield-and-resume), E (retire scope), F (promotion review), G (focus expansion).
- Plan from here (2026-09-22): (1) implement the decided slice in the kit — C1s strategist with target access denied physically, A3 push in the investigator brief, KB page at tier 2 only, `judge save` refusing `met` while an open hypothesis is cited by no shared entry, a proportionate verdict for `light` reviews, and a `no verdict` board record when a role dies at its cap; (2) E6 on stockd as the held-out target (no prompt tuning on it), v1 vs the slice, ≥ 3 runs per arm — this absorbs E5 and shows whether the components interact; (3) a Haiku 4.5 floor pass on the x0 verifier cells and x3 S1. D (yield mid-task) and C4 stay unbuilt until an E6 run shows a stall or stuck worker that needed them.

E0 runs first regardless: a 33-to-1 accept ratio cannot distinguish good work from a rubber
stamp, and every later experiment leans on these roles.

## 6. Threats to validity

- **Synthetic targets.** One planted cause, tidy logs. Real systems have several partial causes.
- **Snapshot bias.** Frozen boards came from strong-model runs; the component under test never
  sees the mess it would have produced upstream. Component wins must survive E6.
- **Interactions.** Axes are tested mostly one at a time with the others at draft-A values; the
  A×B and C×E couplings are covered, others are assumed weak.
- **Grader validity** where scoring is not mechanical.
- **Overfitting prompts to fixtures.** Hold one target out of prompt tuning.
