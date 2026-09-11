---
name: setup
description: Set up a structured multi-agent investigation of a codebase or environment (bug hunt, root-cause analysis, audit, "why does X happen"). Interviews the user for goal, scope, resources, evaluation criteria, lanes and budget, then scaffolds a self-contained investigation directory that /investigate:run executes.
argument-hint: "[goal or problem description]"
---

# Investigation setup

You are setting up an investigation with the user. Nothing runs autonomously yet: your
output is a validated investigation directory and a clear next step. Be a good
interviewer — scout first, then **propose** concrete defaults the user can accept or edit;
don't ask what you can infer.

Kit location (copied into every investigation): `${CLAUDE_SKILL_DIR}/../../kit`
Manifest reference: [reference.md](reference.md) (read it before writing the manifest).
Example manifest: `${CLAUDE_SKILL_DIR}/../../kit/templates/manifest.example.json`

User's opening description: $ARGUMENTS

## 1. Check for existing investigations

`ls investigations/*/manifest.json 2>/dev/null`. If the user is describing one that
already exists, say so and point them to `/investigate:run <dir>` instead of creating a
duplicate.

## 2. Scout (≤ ~6 quick tool calls)

Enough to make good proposals, not to start investigating: repo layout, build and test
system, where logs live, CI config, remote hosts mentioned (`~/.ssh/config` host names
only), relevant tooling on PATH (`gdb`, `lldb`, `gh`, docker, cross-compilers).

## 3. Interview — batch questions with AskUserQuestion, propose defaults

Cover, in two or three rounds:

1. **Goal & question**: the one question the investigation answers.
2. **Evaluation criteria**: what "done" means (`criteria.success`, each checkable), the
   evidence standard, and `stop_if` conditions ("can't reproduce after two dedicated
   attempts → ask me").
3. **Scope**: in / out (including "investigation only — no fixes" if that's the intent).
4. **Resources**: for each — kind, how to access it, whether it is `exclusive` (only one
   task at a time: a port, a single device, a shared DB), and safety notes. **Verify
   access now, non-destructively** (path exists, `ssh -o BatchMode=yes -o ConnectTimeout=5 host true`,
   `gh auth status`) and report what works.
5. **Safety rules**: hard constraints for every agent (no writes to tracked files, no
   sudo, never touch prod, ...).
6. **Lanes**: propose 2–4 semantic lanes plus `skunkworks` (always included: generalist,
   unroutable mail, salvage). Each: `name` (lowercase, `[a-z0-9_]`), mandate, resources,
   `verify_default`, evidence standard. Typical axes: static source analysis, logs,
   experiments on the target, debugger, endpoints. Fewer lanes is better; one real lane
   plus skunkworks is valid.
7. **Budget** — propose from [reference.md](reference.md) and show the cost estimate:
   agents per round ≈ 2×lanes + tasks×(1 + reviews) + 2; per segment ≈ that ×
   `rounds_per_checkpoint` + 1. Keep `max_concurrent` ≤ CPUs − 2 (the workflow runtime's
   own cap; check with `sysctl -n hw.ncpu` or `nproc`). Mention optional per-role `models`
   / `effort` (e.g. `scope: low`), and that a `+500k`-style token target on the run
   message is enforced as a hard ceiling.

## 4. Confirm, then create

1. Show a compact summary of the manifest (goal, criteria, lanes with resources, budget,
   cost estimate) and get an explicit OK.
2. Directory: default `investigations/<slug>` under the current working directory. It
   **must** be readable by the session (the workflow script is launched from it); if the
   user wants it elsewhere, tell them to `/add-dir` it.
3. Create it:
   ```bash
   mkdir -p investigations/<slug> && cp -R "${CLAUDE_SKILL_DIR}/../../kit/bin" "${CLAUDE_SKILL_DIR}/../../kit/prompts" investigations/<slug>/
   ```
4. Write `investigations/<slug>/manifest.json` (Write tool), then:
   ```bash
   python3 investigations/<slug>/bin/board.py validate && python3 investigations/<slug>/bin/board.py scaffold
   ```
   Fix anything `validate` reports.
5. **Enrich each `lanes/<lane>/lane.md`** (scaffold wrote a stub) with what you learned:
   exact access commands, where to work, focus areas and files, known pitfalls, evidence
   standard, anything lane-specific the agents should know. Keep each under ~60 lines.
6. Optionally tailor `investigations/<slug>/prompts/*.md` for this investigation (e.g. an
   extra rule for the investigator). The kit copy is pinned to this investigation.

## 5. Permissions

Workflow agents use this session's permission rules; every unapproved tool call becomes a
prompt that stalls the run. Propose an allowlist for `.claude/settings.local.json`, e.g.:

```json
{"permissions": {"allow": [
  "Workflow",
  "Bash(python3 investigations/<slug>/bin/board.py:*)",
  "Bash(python3 <absolute path>/investigations/<slug>/bin/board.py:*)",
  "Edit(investigations/<slug>/**)",
  "Bash(ssh armbox:*)", "Bash(gh run view:*)"
]}}
```

Include only what the lanes need, show it, and apply it **only with the user's consent**
(merge with any existing file — never overwrite it).

## 6. Hand off

Tell the user: the directory, lanes, budget, and the next step —
`/investigate:run investigations/<slug>` (optionally with steering text or `--rounds N`).
Do not start the run yourself unless they ask.
