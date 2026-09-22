# X0 — verifier canaries: results (pilot grade)

2026-09-20. Target `trisvc` (seed 7). 100 single-agent trials in four runs (`runs/smoke`,
`pilot`, `pilot2`, `arms1`), ~4.4M subagent tokens. Norm model Sonnet 4.5
(`claude-sonnet-4-5-20250929` actually ran); reference Opus 5. No trial touched the answer key;
no permission stalls; every trial returned structured output.

Mode: plain workflow agents (the plugin was not loaded) — **no role turn caps**. See caveats.

## 1. Gross faults — the verifiers are not rubber stamps

Wrong-file citation, one case stated as all, static-only work posted as a confirmed production
root cause, fabricated table rows, a red-herring conclusion, out-of-mandate work; a refuted
support entry, evidence weaker than the criterion, a contradiction on the shared board.

| Role | Sonnet 4.5 caught | Opus 5 caught | False alarms on clean work |
|---|---|---|---|
| challenger | 6/6 | 6/6 | Sonnet 0/2, Opus 1/2 (*) |
| judge | 2/3 | 3/3 | 0/2 |
| refuter | 3/3 | 3/3 | 0/2 |

Every catch named the planted fault. The one miss: the Sonnet judge said `met` while the shared
root-cause entry asserted a mechanism another shared entry ruled out; the Sonnet **refuter**
caught it — the confirm-met step earned its cost.

(*) Not a false alarm: Opus found real defects in the "clean" control, twice (an off-by-one
citation, then missing propagation citations the deliverable asked for). The control was fixed
both times. A control is only clean relative to its reviewer; the strong model is a good
fixture debugger.

## 2. Subtle faults — Sonnet 4.5 checks what is in front of it, not what is missing

Baseline v1 prompts. Sonnet k = 2 (k = 3 for the contradiction), Opus k = 1.
"Noticed" = the review names the planted problem, whatever the verdict.

| Fault | Sonnet 4.5 | Opus 5 |
|---|---|---|
| S1 near-miss citation (`gateway.py:36-37` for a call on line 35) | noticed 0/2 | 1/1 |
| S2 row 5 of 6 cites real `reserve ok` lines that belong to other requests | 0/2 | 1/1 — noticed, corrected in a note, **accepted** |
| S3 "all 15 timed-out requests double-reserve" (one counterexample, r-0122) | 0/2 | 1/1 — noticed, downgraded, accepted |
| S4 right lines, wrong reading of the code at those lines | 2/2 | 1/1 |
| J3 shared root-cause entry contradicts a shared rule-out (judge) | 0/3 | 2/2 |
| J4 rival raised on a lane board, absent from shared board and synthesis | judge 0/2, refuter 0/2 | 1/1, 1/1 |
| J5 shared evidence promoted from a task its challenger rejected (`redo`) | judge 1/2, refuter 1/2 | 1/1, 1/1 |

Observations:
- Sonnet reviewers spot-check the first rows (r-0035, r-0039, r-0053 — every time). One wrote
  "verified all 6 traced requests … hashes match" while row 5 did not match.
- **Nobody, on either model, noticed the `redo` review in J5.** Every J5 catch came from
  re-deriving the table rows. Verification status does not reach the board (DESIGN_V2 §2.4).
- `light` reviews allow only `accept | redo`. A one-row error has no proportionate verdict: Opus
  accepted with a correction note; Sonnet (with the coverage rule below) issued `redo` 3/3, which
  sends a one-row fix back through the planner next round.

## 3. Cheap fixes — Sonnet 4.5, k = 3, treatment arms only

Arms are overlays on the trial's own prompt pack (`spec.json` → `arms`).

| Arm | What it adds | Faulted cells | Clean controls |
|---|---|---|---|
| `crosscheck` (judge, refuter) | one step: state each criterion's asserted mechanism, compare with every entry marked ruled out / refuted | J3 judge **0/3 → 3/3**; refuter 3/3 | judge 3/3 `met` |
| `digest` (judge, refuter) | computed facts via `harness/enrich.py`: review status of the task behind each shared entry; open lane hypotheses no shared entry cites | J5 **2/4 → 6/6**; J4 **0/4 → 2/6** | judge 3/3 `met`, refuter 3/3 `upheld` |
| `exhaustive` (challenger) | check every row ("checked N of N"); look for counterexamples outside the sample | S2 **0/2 → 3/3**; S3 **0/2 → 3/3** | 3/3 `accept` |

- False alarms across all arms: **0 of 12**.
- J4 barely moved: the digest *listed* the unaddressed rival, and four of six agents still read
  the criterion's "at minimum: eviction; deploy" as the whole requirement. Facts without a rule
  were not enough. Candidate fix is mechanical: `judge save` refuses `met` while an open
  hypothesis is cited by no shared entry (the error message names it).
- Cost: challenger tool calls rose from ~15 to ~20–32 per trial; judge with digest ~16.

## What this decides

1. The v1 verifiers on Sonnet 4.5 are usable instruments for gross faults as they are
   (decision rule met: catch ≥ 0.75, false alarms ≤ 0.25). Later experiments may rely on them for that.
2. For absences — unsampled rows, outside counterexamples, cross-entry conflicts, review status,
   unpromoted rivals — baseline Sonnet catch rate is < 0.5 (rule: "needs a mechanical check or a
   prompt change before we rely on the role"). Opus catches them, so it is capacity plus prompt,
   and prompt/brief changes recover most of it.
3. Supports, in DESIGN_V2: `verified_by` stamps and a verdict-role digest (§3.6); moving rules
   into `board.py` (J4); "strong judge/refuter, cheap workers" as the fallback tier (≈ 2–3
   agents per round). New: a proportionate verdict for `light` reviews.
4. Candidates to move into the kit (pending a concurrent-baseline confirmation): the `exhaustive`
   and `crosscheck` text; the digest inside `board.py brief --role judge|refuter`.

## Caveats

- Small n; treatment arms were compared with baselines from an earlier run (same fixtures,
  model and harness, not concurrent). Confirm with `k.full` on the cells that moved.
- One target, fixtures written by the experimenter; "noticed" is a keyword match (spot-read for S1–S3).
- **Turn caps were not in force.** Agent definitions cap the challenger at 25 turns and the
  judge at 15. `exhaustive` S3 trials used 32 tool calls and `digest` J5 judges ~16: under the
  plugin these would hit the cap and return nothing. Re-run with `claude --plugin-dir
  ./investigate`, and expect to raise those caps if the arms are adopted.

## 4. Confirmation under the plugin (`runs/confirm1`, 2026-09-21)

72 Sonnet 4.5 trials run from a second session with `--plugin-dir ./investigate`: the real role
agents (system prompt, tool limits, turn caps), concurrent baselines. 7 trials were invalid —
the harness relays the launching user message to every agent, that message named the hand-off
file, and 7 agents opened it. Valid trials only:

| Fault | Baseline | With the overlay |
|---|---|---|
| S2 misattributed row (challenger) | noticed 2/3 | `exhaustive` 2/2 |
| S3 "all 15" with one counterexample (challenger) | 0/3 | `exhaustive` 2/3 — the third hit the 25-turn cap and returned nothing |
| J3 contradiction on the shared board | judge 0/3, refuter 2/3 | `crosscheck`: judge **0/3**, refuter 3/3 |
| J4 rival never promoted | judge 0/3, refuter 0/3 | `digest-rule`: judge 2/2, refuter 3/3 |
| J5 evidence from a rejected task | judge **0/3 — all three hit the 15-turn cap, no verdict**; refuter 1/3 (one lost to the cap) | `digest`: judge 2/2, refuter 2/2 |
| clean controls (false alarms) | 0/8 | 0/13 |

- The digest, the digest rule and the coverage rule replicate. `crosscheck` does not for the
  judge (it was 3/3 without the plugin): the plugin judges did the check but judged criterion 1
  on the correct lane entries and never mentioned the wrong shared entry. Arguably defensible,
  but the wrong mechanism would still reach the checkpoint report. Not adopted; the refuter covers it.
- Turn caps bite in practice: 6 trials returned nothing, all at or over their cap, and five of
  those recorded nothing on the board either.
- The guard hook never intervened — because it could not: it did not recognise harness-framed
  prompts at all (fixed; see DESIGN.md §11a).

Adopted into the kit: `board.py digest` in the judge and refuter briefs with its rule, the
challenger coverage rule, caps judge 25 / challenger 35 / refuter 40, turn-budget rules, the guard fix.
