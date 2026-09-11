# Checkpoint

End of a segment. Leave the investigation clean and brief the human, who will steer the
next segment from your report.

## Steps

1. **Leftovers** (your brief already printed `status`, `questions` and `leftovers`). For
   each, run the recorded `stop` command if it is safe under the manifest's safety rules,
   then `task stopped --id T --ref S#`. Anything you cannot clean goes in the report under
   "Needs your attention".
2. **Judge gaps**: for each round in the segment, `judge show --round N`. If one is missing,
   save a placeholder: `judge save --round N` with
   `{"met":false,"progress":false,"gaps":[],"summary":"judge unavailable"}`.
3. **Close the segment** with the command in your prompt (if it gives one).
4. **Write the report** with `write --path report.md`, and the same text with
   `write --path reports/after-round-NN.md` (NN = last round, two digits):

   ```
   # <manifest title> — checkpoint after round N
   ## Bottom line          3 sentences: where we stand against each success criterion
   ## Confirmed findings   board id, one-line claim, confidence
   ## Live hypotheses & contradictions
   ## This segment         per lane: tasks → outcomes and verdicts; deferred / lost tasks;
                           long tasks that finished after the last synthesis
   ## Questions for you    every open question-for-human: id, question, context
   ## Needs your attention leftovers not cleaned, unreachable resources, safety concerns
   ## Suggested steering   2–5 concrete options (redirect a lane, drop a hypothesis,
                           add/remove a lane, change budget) with a one-line rationale each
   ## Budget               rounds run, agents used / cap, stop reason
   ```
   Use `status`, `questions`, `judge show`, `shared/synthesis.md` and the worklogs as
   sources. Cite board ids.

Return `{report_path, summary, open_questions, leftovers_cleaned}` — `summary` is the bottom
line plus how many questions await the human.
