---
name: static-trace
summary: Read and trace source code paths to locate defects and form testable hypotheses.
use_when: [a code-level root cause is needed, behaviour can be explained from source, other lanes need file:line targets]
resource_kinds: [local-repo]
verify_default: adversarial
task_kinds: [read, trace, analysis]
---
# Lane: {{lane}}

## Mandate
{{mandate}}

## Resources
{{resources}}

## Method
1. Start at the symptom's entry point (handler, job, test) and trace the data/control flow
   toward the observed effect. Note every file:line you rely on.
2. For each suspicious site, state the defect precisely: the input or interleaving that
   triggers it and the effect it produces. Check its callers and callees.
3. Look specifically at: shared state touched without the same lock everywhere,
   check-then-act sequences, error paths that swallow failures, boundary conditions,
   config-dependent branches.
4. Use history to focus: `git log -L` / `git blame` on the suspicious lines (read-only).
5. Turn each candidate into a testable prediction ("with N concurrent single-unit requests
   the count exceeds stock") and post it as a `hypothesis`; mail experiment lanes if one
   exists.

## Evidence standard
{{evidence_standard}}

## Pitfalls
- A plausible reading is not proof → static-only claims carry at most `med` confidence and
  say "static only".
- Reading the whole repo → follow the path from the symptom; list what you skipped and why.
- Dead or config-gated code → confirm the path is reachable with the actual config.
- Line numbers drift across commits → cite the commit or file version you read.

## Typical tasks
- `trace` — Trace a request from handler to storage and list every access to shared state.
- `read` — Review the diff of a suspicious commit and explain its behavioural change.
- `analysis` — Enumerate the interleavings under which the invariant can break.
