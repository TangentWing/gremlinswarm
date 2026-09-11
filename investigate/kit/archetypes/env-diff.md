---
name: env-diff
summary: Compare environments (CI vs local, prod vs staging, old vs new) to find differences that could explain behaviour.
use_when: [it works here but not there, a failure appeared after an environment change, CI and local disagree]
resource_kinds: [local-repo, ssh, service, other]
verify_default: light
task_kinds: [analysis, read]
---
# Lane: {{lane}}

## Mandate
{{mandate}}

## Resources
{{resources}}

## Method
1. Collect the same facts from each environment: runtime and dependency versions
   (lockfiles), OS/kernel, CPU count, config files, environment variables (names and
   non-secret values), feature flags, resource limits.
2. Save each snapshot as an artifact and produce a side-by-side diff.
3. Rank differences by plausibility against the symptom, with a one-line reason each.
4. Turn the top differences into experiments ("run locally with X set to the CI value") and
   hand them to the experiment lane by mail or as `hypothesis` entries.

## Evidence standard
{{evidence_standard}}

## Pitfalls
- A difference is not a cause → only an experiment that toggles it can show that.
- Secrets in environment dumps → record names, redact values.
- Comparing at different times → versions drift; timestamp every snapshot.

## Typical tasks
- `analysis` — Snapshot versions/config/env in CI and locally and diff them.
- `read` — Compare the config at two deploys and list behavioural settings that changed.
