---
name: bisect
summary: Find the change that introduced a behaviour by bisecting version-control history.
use_when: [a regression with a known-good past state, the question is "which change broke it", failures started at some point in time]
resource_kinds: [local-repo]
verify_default: adversarial
task_kinds: [experiment, trace]
---
# Lane: {{lane}}

## Mandate
{{mandate}}

## Resources
{{resources}}

## Method
1. Clone into your task directory: `git clone <repo> <task dir>/repo`. Never bisect or
   check out commits in a shared repository.
2. Pin the endpoints with evidence: a known-bad commit (fails) and a known-good commit
   (passes) — for a flaky test, N runs each (N ≥ 10); good means 0 failures.
3. `git bisect start <bad> <good>`; at each step run the test N times (N ≥ 5 for flaky
   tests; any failure ⇒ `git bisect bad`, all passes ⇒ `git bisect good`). Commits that
   can't be tested (build broken, test missing) ⇒ `git bisect skip`.
4. Save `git bisect log` and a per-step table (commit, runs, failures) as artifacts.
5. Confirm the culprit: culprit fails at least once in N runs, its parent passes N/N with
   N ≥ 10. Then read the culprit's diff and state which hunk plausibly causes the behaviour.

## Evidence standard
{{evidence_standard}}

## Pitfalls
- A flaky test marks a bad commit "good" → use repeated runs per step and report the
  chance of a false "good" (e.g. 50% failure rate, 5 runs ⇒ ~3%).
- Bisecting in the shared checkout → breaks every other lane; use a clone.
- The test itself changes across history → check it exists and means the same thing at
  both endpoints; otherwise copy the current test into each checkout.
- The first commit where failures *increase* is not the one where they *start* → bisect
  on "fails at all", not on "fails more".
- `git bisect reset` fails with "We are not bisecting" when no bisect is in progress, and
  in an `&&` chain that aborts everything after it → use `git bisect reset || true`.
- `git bisect good|bad|skip` take no flags (`-q` is read as a commit) → pass none, and put
  `-q` only on `git checkout`.

## Typical tasks
- `experiment` — Establish good/bad endpoints with 10 runs each.
- `experiment` — Bisect with 5 runs per step and confirm the culprit against its parent.
- `trace` — Explain the culprit commit's diff and how it produces the failure.
