---
name: repro-experiment
summary: Reproduce the failure with controlled experiments and measure rates under varied conditions.
use_when: [the failure must be demonstrated, hypotheses need testing at runtime, the failure is flaky]
resource_kinds: [local-repo, port, service]
verify_default: light
task_kinds: [experiment]
---
# Lane: {{lane}}

## Mandate
{{mandate}}

## Resources
{{resources}}

## Method
1. Work in your task directory; if you need the code, clone it there
   (`git clone <repo> <task dir>/repo`) — never modify or check out commits in a shared repo.
2. Baseline: run the unmodified reproducer N times (N ≥ 10 for anything flaky) and record
   the pass/fail tally, not a single outcome.
3. Vary one factor at a time (concurrency, input, config, commit) and re-measure with the
   same N. Report rates with n: "7/20 fail at 16 workers vs 6/20 at 4".
4. Record exact commands, environment variables and versions so another agent can re-run
   them. Save scripts and raw output in the task directory.
5. Anything long-running (servers, background loops): `task started` before, stop it and
   `task stopped` after. Hold exclusive resources (ports, devices) only through your claim.

## Evidence standard
{{evidence_standard}}

## Pitfalls
- One run proves nothing for a flaky failure → always report tallies with n.
- Changing two factors at once → you can't attribute the effect.
- Leaving a server bound to a shared port → the next task fails for the wrong reason.
- Testing a patched copy and reporting it as the original → label every run with what it ran.

## Typical tasks
- `experiment` — Run the failing test 20× at the current commit and report the failure rate.
- `experiment` — Compare failure rates with setting X = a vs b (20 runs each).
- `experiment` — Write a minimal stand-alone reproducer and measure it.
