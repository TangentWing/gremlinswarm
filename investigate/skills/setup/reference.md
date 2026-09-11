# manifest.json reference

`board.py validate` enforces the required parts. Example:
`kit/templates/manifest.example.json`.

| Field | Required | Meaning |
|---|---|---|
| `slug` | yes | Short id, used in paths (`investigations/<slug>`, `/tmp/inv-<slug>/...`). |
| `title` | | One-line human title (report heading). |
| `goal` | yes | What the investigation must produce. |
| `question` | | The single question it answers. |
| `scope.in` / `scope.out` / `scope.notes` | | What is and isn't in bounds. Agents treat `out` as forbidden. |
| `targets[]` | | `{name, path, notes}` — codebases / systems under investigation. |
| `resources[]` | yes | `{name, kind, access, exclusive, notes}`. `kind`: local-repo, ssh, port, logs, service, device, db, other. `exclusive: true` → the scheduler never runs two tasks claiming it at once. Tasks may only claim declared names. |
| `safety[]` | | Hard rules every agent follows. |
| `criteria.success[]` | yes | Checkable success criteria. The judge stops the run when all are met. |
| `criteria.evidence_standard` | | What counts as evidence, and confidence caps. |
| `criteria.stop_if[]` | | Conditions under which the judge halts and asks the human. |
| `lanes[]` | yes | `{name, mandate, resources[], verify_default, evidence_standard}`. Name: `[a-z][a-z0-9_]*`, not `shared`. Always include `skunkworks`. |
| `budget` | | See below; missing keys take defaults. |
| `models` | | Per-role model override (`scope`, `plan`, `investigator`, `challenger`, `salvage`, `synthesizer`, `judge`, `checkpoint`). Omit to inherit the session model. |
| `effort` | | Per-role effort: `low` … `max`. Good defaults: `scope: low`, `checkpoint: low`. |
| `agent_types` | | Per-role custom subagent type (advanced; e.g. a read-only reviewer agent for `challenger`). |

## Budget

| Key | Default | Meaning |
|---|---|---|
| `max_concurrent` | 4 | Agents running at once across all lanes (runtime cap is min(16, CPUs−2)). |
| `rounds_per_checkpoint` | 2 | Rounds per workflow run before the human checkpoint. `/investigate:run --rounds N` overrides once. |
| `max_rounds` | 8 | Hard cap on rounds over the whole investigation. |
| `max_agents_per_segment` | 60 | Agent cap per segment (3 are always reserved for synthesis, judge, checkpoint). |
| `max_tasks_per_lane_round` | 3 | Tasks a lane planner may queue per round. |
| `verify_rounds` | 2 | Max challenger reviews for `adversarial` tasks (revise loops = verify_rounds − 1). |
| `max_children` | 2 | Max child subagents an investigator may spawn. |
| `stall_rounds` | 2 | Stop after this many consecutive rounds the judge marks as no progress. |

## Cost estimate

Per round ≈ `2 × active lanes` (scope + plan) + `Σ tasks × (1 + reviews + revisions)` + 2
(synthesis + judge). Example: 3 lanes + skunkworks (usually idle), 2 tasks per lane,
`light` verify → 8 + 12 + 2 ≈ 22 agents per round; with `rounds_per_checkpoint: 2`
≈ 45 per segment. `adversarial` tasks cost up to `2 × verify_rounds` agents each.

## Lane design tips

- A lane earns its place by different **resources**, a different **evidence standard**, or
  a different **method** — not just a different topic.
- `verify_default`: `adversarial` for static analysis and root-cause claims, `light` for
  experiments whose output is self-evidencing, `none` rarely.
- Put shared, single-user things (a port, a device, a test DB) in their own resource with
  `exclusive: true` rather than marking a whole host exclusive.
