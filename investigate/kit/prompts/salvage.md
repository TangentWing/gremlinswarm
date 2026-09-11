# Salvage (skunkworks)

An investigator died or was stopped mid-task. Recover as much as possible, leave nothing
running, and make sure the planner knows what happened.

## Steps

1. Your brief already printed `task show` (spec, `notes.md`, partial artifacts, earlier
   result/reviews) and `leftovers` for the lane (side effects recorded but never stopped).
2. **Clean up** this task's leftovers: run each recorded `stop` command if it is safe under
   the manifest's safety rules, then `task stopped --id T --ref S#`. If a process may be
   hung, check it first (`ps`, `ssh host pgrep ...`); escalate from polite to forceful
   (`kill`, wait a few seconds, then `kill -9`). If you cannot clean something, say so.
3. **Decide:**
   - The notes/artifacts show the work is essentially complete, or it can be finished
     cheaply within the original mandate → finish it, post what it found, and
     `task finish` with the honest status.
   - Otherwise → `task finish --id T --status failed --summary "agent lost; recovered: ...; needs retask"`
     and `mail send --to <lane> --type failure --subject "Task T lost: needs retask" --body "<what was recovered, where it is, suggested next step>"`.

Return `{status, summary, board_ids, artifacts}`.
