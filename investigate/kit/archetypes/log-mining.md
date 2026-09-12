---
name: log-mining
summary: Mine logs to build a timeline and correlate failures with deploys, load and conditions.
use_when: [production or CI logs exist, the question involves "since when" or "how often", failures are intermittent]
resource_kinds: [logs]
verify_default: light
task_kinds: [analysis, read]
---
# Lane: {{lane}}

## Mandate
{{mandate}}

## Resources
{{resources}}

## Method
1. Inventory first: which files, date range, format, timezone, gaps. Record it.
2. Build a timeline of *events*: deploys/versions, config changes, errors, warnings,
   restarts. Extract with `grep -c` / `grep -n` per file; keep per-day counts in an artifact
   (CSV or table) rather than pasting raw lines.
3. Establish the baseline before the incident, then the onset: the first occurrence of
   the failure signature and what changed just before it.
4. For each candidate cause, check temporal precedence (did it come first?), dose-response
   (more of it → more failures?) and whether it exists without the failure. Report all three.
5. Large sets (many files or shards) → first try one pass with `grep`/`awk` over all of
   them (cheapest, and usually enough for counts and timelines). Reach for a sweep only
   when each shard needs judgment or its own tooling, not just a pattern count.

## Evidence standard
{{evidence_standard}}

## Pitfalls
- Correlation read as causation → a change that *increases* failures may only amplify an
  earlier cause; find the onset, not the peak.
- Noisy warnings that are always present → compare against the baseline period.
- Timezones and rotation → normalise to UTC and check for missing days.
- Pasting secrets or personal data → redact before posting.

## Typical tasks
- `analysis` — Per-day counts of each error signature and deploy events for the whole period.
- `analysis` — First occurrence of signature X and the deploys in the preceding 48 hours.
- `read` — Extract the log lines surrounding each occurrence of X (±20 lines) into an artifact.
