# E6 — the v2 slice end to end: results (run 1)

2026-09-22. Two investigations run to completion from a plugin session (`claude --plugin-dir
./investigate`), all ten roles on Sonnet 4.5, no steering, "continue" at every checkpoint. Raw
collection in `run1/REPORT-*.md` (written by the running session, no interpretation); scoring
against the answer keys here.

| Run | Target | Rounds | Stop | Agents | Fresh tokens | Cached tokens | Criteria |
|---|---|---|---|---|---|---|---|
| `trisvc-e6` | the experiments' target, bursty profile | 4 (2 segments) | `stall` | 64 (39/40 + 25/40) | 5.8M | 53.3M | 2 of 3 met; the third **answered on the board but unverified** |
| `stockd-v2` | stockd, held out | 4 (2 segments) | `stall` | 60 (39/60 + 21/60) | 5.2M | 44.7M | **4 of 5** met; the fifth needs human data and the run asked for it |

For comparison (`DESIGN.md §11`): stockd-before, v1, 46 agents → 3 of 5; stockd "after", 60 agents,
interrupted. The relayed launch message was the bare `/investigate:run` command in every agent (0 of
124 transcripts mention the hand-off).

## Correctness against the answer keys

**trisvc-e6** — everything the key holds is on the shared board, verified except the traces:
- Root cause: `services/gateway.py:22-24`, per-attempt idempotency key (key: line 24) — B-shared-0001/0002; the
  uncancelled callee (common.py) and orders' dedupe-after-reserve as co-mechanism — B-shared-0003/0009/0017/0018.
- Eviction ruled out (B-shared-0005, 0013), deploy ruled out by drift onset 10:10 preceding it (B-shared-0013),
  r-0023 double-reserved pre-deploy (B-shared-0004) — all three match the key's discriminators.
- Traces: five end-to-end traces exist (r-0023 + r-0061, r-0074, r-0088, r-0103 in B-shared-0014; all in the
  key's affected set). Quantification 235 reserves / 191 confirms / +44 matches the key.
- The judge counted one trace because B-shared-0014 rests on `logs-r02-01`, which was never reviewed.

**stockd-v2** — the four technical criteria match the generator: the introducing commit (fast path for
single-unit reservations) and the check-then-act race at `inventory.py:38-47`; the 4→16 worker change as
amplifier, not cause; a 65–70% reproducer against a passing baseline; onset 5h55m after the deploy. Criterion 5
(production impact) needs the request mix "only the human can supply": the run compiled a partial estimate and
filed three `ask` questions (B-shared-0007..0009). With no steering, that is the ceiling.

## Did the slice work?

| Mechanism | trisvc | stockd | Verdict |
|---|---|---|---|
| Strategist, boards only | ran each round; guard blocked 3 target reads; 1 rejection (`keep at least two`) | ran each round; guard blocked 3 reads; **r2 strategist died at 20/20 with no position** | works; cap raised to 30, "save early" rule added |
| Intent in scope/plan briefs | v1–v3 saved; planners cited its entries | v1, v2 | works |
| Task `context` | 8 of 13 tasks (all post-round-1) | 3 of 11 (2 entries rejected as not board ids) | used once a strategy exists; round-1 tasks carry none |
| `Context pushed to this task` | 14 investigator transcripts | 11 | fires |
| kb pages / `explainer` tasks | 0 / 0 | 0 / 0 | **unused** — planners put the mechanism into task instructions instead; pages need a trigger (a consult), not planner initiative |
| Plan lint | refused 1 over-cap plan | warned once (3 tasks on the port) | fires; nothing to refuse |
| `judge save` refuses `met` | never tried | never tried | unexercised; no run reached a `met` attempt |
| Refuter | did not run | did not run | unexercised |
| `--correction` | 2 accepts with corrections | 0 | works |
| Challenger stop-gate | **0 gate messages in 124 transcripts** | 0 | see below |

## What went wrong, and the fixes

1. **Verification debt stalled trisvc with the answer on the board.** Three tasks finished without a review:
   two skipped at the agent cap (segment 1 used 39 of 40; a 40-agent cap on four lanes was my fixture's mistake),
   and one — plus stockd's `static-r01-01` — reviewed by a challenger that **returned `accept` as structured
   output and never ran `task review`**. The judge, following the digest rule, counted that work as unverified;
   no planner can queue "review an old task"; two rounds of no progress → `stall`.
   Fix (this commit): `board.py debt` / `wf-args.verification_debt` (finished tasks whose lane verifies with no
   review on file, computed from files), and a "Verify debt" step at segment start in `investigate.js` that runs
   the overdue reviews first. The challenger prompt now says the returned verdict is discarded unless the review
   is on file. `reference.md` sizes `max_agents_per_segment` with the strategist and warns that reviews are the
   first casualty of a cap.
2. **The SubagentStop gate never fires for workflow agents.** Across 124 transcripts: 0 stop-gate messages,
   6 PreToolUse blocks. So the investigator/judge/challenger gates (v1 and the slice) are inert in workflows; the
   files-based fallbacks (orphan detection, placeholder verdicts, the digest's "never reviewed") are what hold.
   Fix: `touch investigate/hooks/DEBUG` makes the guard log every hook call's payload keys to
   `hooks/guard.log`; the next plugin run says whether SubagentStop arrives at all, and with what.
3. **Strategist turn cap.** 20 was enough for the 4-lane trisvc (≤ 11 tool calls in x3) but not for stockd's
   five lanes and 60+ entries: the round-2 strategist spent turns on blocked target reads and re-orienting, and
   saved nothing. Cap 30; the prompt now says to save a supportable position early.
4. **kb pages never happened.** The x1 result (an explainer page halves worker cost and resists a wrong board)
   did not materialise because nothing asks for a page. `context` carried the facts instead. The consult
   mechanism (DESIGN_V2 §3.3) is the trigger; until it exists, the strategist's "settle" list could name a page.

## What this decides

- The slice runs end to end under the plugin with correct answers on both targets, including the held-out one,
  at 60–64 agents and ~5.5M fresh tokens per run. That is the E6 confirmation DESIGN_SPACE asked for, with the
  verification-debt hole fixed mechanically.
- Next run (`run2`): both targets again with the debt step, cap 30, `hooks/DEBUG` on, and `trisvc-e6`'s cap
  raised to 60. Expected: trisvc reaches a `met` attempt (exercising the judge rule and the refuter for the
  first time), stockd stalls at 4 of 5 unless the checkpoint questions are answered.
