# Lane archetypes

An archetype is a reusable lane design: a method of investigating (reading code, mining
logs, bisecting history, …) with its mandate, resources, evidence standard, verification
level, pitfalls and typical tasks. `/investigate:setup` picks archetypes for an
investigation, and `board.py scaffold` renders each lane's `lane.md` from its archetype.

```
kit/archetypes/
  README.md            this guide
  _template.md         copy this to add an archetype
  static-trace.md      one file per archetype
  ...
```

List them with `board.py archetypes`; show one with `board.py archetypes --show NAME`.

## File format

Each archetype is a Markdown file whose name is the archetype name (`[a-z][a-z0-9-]*`).

**Frontmatter** (between `---` lines, simple `key: value` pairs; lists as `[a, b]`):

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Same as the file name. |
| `summary` | yes | One line: the method. Shown by `board.py archetypes`. |
| `use_when` | yes | Symptoms/situations that call for this lane (a list). Setup matches on these. |
| `resource_kinds` | yes | Resource kinds the lane typically needs (`local-repo`, `logs`, `ssh`, `port`, `db`, `service`, `device`, `other`). |
| `verify_default` | yes | `none`, `light` or `adversarial` — the lane's default verification level. |
| `task_kinds` | yes | Task kinds its planner usually emits (`read`, `trace`, `experiment`, `endpoint`, `debug`, `analysis`, `cleanup`, `other`). |

**Body**: the `lane.md` template. Agents read it through `board.py brief`, so write it for
them: imperative, concrete, ≤ ~60 lines once rendered. Placeholders:

| Placeholder | Replaced with |
|---|---|
| `{{lane}}` | the lane name from the manifest |
| `{{mandate}}` | the lane's `mandate` from the manifest |
| `{{resources}}` | a bullet list of the lane's resources with access and notes |
| `{{evidence_standard}}` | the lane's `evidence_standard`, else the manifest's |
| `{{verify_default}}` | the lane's verify level |

Keep these body sections, in this order, so every lane reads the same way:
`Mandate`, `Resources`, `Method`, `Evidence standard`, `Pitfalls`, `Typical tasks`.

## Adding or changing an archetype

1. `cp _template.md <name>.md` and fill it in. Write **Method** as numbered steps an agent
   can follow without judgment calls it can't make; put hard-won failure modes in
   **Pitfalls** (each: the trap → what to do instead).
2. `board.py archetypes` must list it without errors (it validates frontmatter).
3. Add it to a smoke fixture (`tests/fixtures/*.manifest.json`, lane `"archetype": "<name>"`),
   build it with `tests/make_smoke.sh <fixture>`, and read the rendered `lane.md`.
4. Run a smoke investigation that exercises the lane and read the agents' transcripts
   (`tests/wf_metrics.py`) before and after the change — change archetypes in response to
   observed agent behaviour, not guesses.
5. Archetypes are copied into each investigation at setup; editing the plugin's copy does
   not change running investigations (edit `<investigation>/archetypes/` for that).

## Using one from a manifest

```json
{"name": "history", "archetype": "bisect",
 "mandate": "Find the commit that introduced the oversell, in a clone of the repo.",
 "resources": ["stockd_repo", "port_8765"]}
```

`verify_default` falls back to the archetype's. `board.py scaffold` writes `lane.md` only if
it does not exist yet, so setup can still enrich it afterwards.
