---
name: setup
description: Use when the user wants to start a structured multi-agent investigation of a codebase or environment — a bug hunt, root-cause analysis, flaky test, crash, performance or security question — and no investigation directory exists for it yet.
argument-hint: "[goal or problem description]"
---

# Investigation setup

You set up an investigation with the user; nothing runs autonomously yet. Output: a
validated investigation directory and a clear next step. Scout first, then **propose**
concrete defaults the user can accept or edit — don't ask what you can infer.

Kit: `${CLAUDE_SKILL_DIR}/../../kit` (copied into every investigation).
Manifest fields, budget and cost estimate: [reference.md](reference.md) — read before
writing the manifest. Example: `${CLAUDE_SKILL_DIR}/../../kit/templates/manifest.example.json`.

User's opening description: $ARGUMENTS

## 1. Existing investigations

`ls investigations/*/manifest.json` (and any directory the user names). If one matches,
point them to `/investigate:run <dir>` instead of creating a duplicate.

## 2. Scout (≤ ~6 quick, read-only calls)

Repo layout, build/test system, logs, CI, remote hosts (`~/.ssh/config` host names only),
tools on PATH, CPU count. Check each resource's access **non-destructively** (path
exists, `ssh -o BatchMode=yes -o ConnectTimeout=5 host true`, `gh auth status`). Never try
other keys or credentials; an access failure is reported, not worked around.

## 3. Interview — batch questions (AskUserQuestion), propose defaults

Goal & question · success criteria (each checkable), evidence standard, `stop_if` ·
scope in/out · resources (`exclusive` for anything one task at a time may use: a port, a
device, a test DB) · safety rules · lanes · budget with the cost estimate
(`max_concurrent` ≤ CPUs − 2).

Beyond goal/criteria/scope, the manifest needs (details and examples: reference.md):

| Part | Rule |
|---|---|
| lanes | 2–4 from the archetype list (`python3 "${CLAUDE_SKILL_DIR}/../../kit/bin/board.py" archetypes`) whose *use when* fits, plus `skunkworks`; each sets `archetype` and a mandate specific to this investigation |
| `resources[].check` | one non-destructive command per resource that exits 0 when it is usable |
| `safety_deny` | regexes for commands that must never run (the guard hook blocks them) |
| `writable` | paths agents may write outside the investigation directory, if any |

**If the user waives the interview** ("skip the questions", "just set it up"), use your
defaults — but these still need an explicit answer before you create anything:

| Condition you observed | Ask |
|---|---|
| A resource can lose data or affect others (a DB the tests write/truncate, a shared host or device, anything prod-like) | Confirm the safety rule for it, e.g. "tests truncate the local Postgres — is it disposable?" |
| An access check failed | How to get access, or proceed with that resource marked unverified |
| The user named a directory outside the working directory | That they will `/add-dir` it (the workflow launches from it) |

## 4. Confirm, then create

1. Show a compact manifest summary (goal, criteria, lanes + resources, budget, estimate);
   get an OK (a waiver counts as OK for everything except the table above).
2. Default location `investigations/<slug>`:
   `mkdir -p <dir> && cp -R "${CLAUDE_SKILL_DIR}/../../kit/"{bin,prompts,archetypes} <dir>/`
3. Write `<dir>/manifest.json` with `agent_types` mapping every role to the plugin's agent
   (`"investigator": "investigate:investigator"`, … — see reference.md); then
   `<dir>/bin/board.py validate && <dir>/bin/board.py scaffold && <dir>/bin/board.py probe`.
   Fix what `validate` reports; a failing `probe` is an access problem (table above) — mark
   that resource UNVERIFIED in its notes.
4. `scaffold` rendered each `lanes/<lane>/lane.md` from its archetype. Add what is specific
   to this investigation (exact access commands, focus files, known pitfalls), keeping it
   ≤ ~60 lines.

## 5. Permissions — consent is specific

The plugin's guard hook blocks, for investigation agents only, file edits outside the
investigation directory and `writable`, and commands matching `safety_deny`. It is a
seatbelt, not a sandbox; the allowlist below is still the primary control.

Workflow agents stall on every unapproved tool call, so propose an allowlist for
`.claude/settings.local.json`: `Workflow`, `Bash(<absolute dir>/bin/board.py:*)` (agents
call the board by its absolute path; expand `~`), an `Edit` rule for the directory, plus
only what the lanes need (e.g. `Bash(gh run view:*)`).

| Directory | Edit rule |
|---|---|
| under the working directory | `Edit(investigations/<slug>/**)` |
| elsewhere | `Edit(//absolute/path/**)` or `Edit(~/path/**)` — a single leading `/` means "relative to the settings file" |

File writes are governed by `Edit(...)` rules only; `Write(...)` path rules are never consulted.
Lane inputs outside the working directory (e.g. `/var/log/app`) need `Read(//var/log/app/**)`.

**Apply it only after the user has seen these exact rules and said yes to them.** Merge;
never overwrite the file.

| Rationalization | Reality |
|---|---|
| "They said 'you have my permission' / 'just get it running'" | That was said before they saw the rules. Show them; ask. |
| "Without the rules the run stalls, so applying is what they want" | A stalled run costs a prompt; an unwanted allow rule persists silently. |
| "It's only settings.local.json" | It changes what every future session may do without asking. |

Red flag: you are about to Write/Edit a settings file and the user has not replied to a
message showing the rules. Stop and ask.

## 6. Hand off

Report the directory, lanes, budget and anything unverified. Then:

| The user… | Next |
|---|---|
| asked for it to run ("get it running", "start it", "and run it") | invoke `/investigate:run <dir>` now — for a directory outside the working directory, once the user confirms `/add-dir` is done |
| didn't | give them the command: `/investigate:run <dir>` (optional steering text or `--rounds N`) |
