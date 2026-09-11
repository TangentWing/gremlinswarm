# orchestration_skills — Investigation kit

A Claude Code plugin for structured, multi-agent investigations of a codebase or
environment. Design rationale: [DESIGN.md](DESIGN.md).

```
/investigate:setup  "why does the client exit after one message on ARM64?"
      → interview → investigations/<slug>/ (manifest, lanes, prompt pack, board CLI)
/investigate:run    investigations/<slug>  [--rounds N] [steering text]
      → one workflow segment: per lane scope→plan, tasks with verify loops,
        synthesis, judge → checkpoint report → you answer questions / steer → repeat
```

## Layout

```
investigate/                     the plugin
  .claude-plugin/plugin.json
  skills/setup/SKILL.md          interactive setup (+ reference.md: manifest & budget)
  skills/run/SKILL.md            launches segments, runs checkpoints
  agents/*.md                    one agent definition per role (tool limits, turn caps)
  hooks/hooks.json, guard.py     guard: write scope, command deny-list, result recording
  kit/                           copied into every investigation directory
    bin/board.py                 protocol CLI (stdlib Python): boards, mail, plans, tasks, judge
    bin/investigate.js           the workflow: scheduler + round loop
    prompts/*.md                 protocol + one file per role
    archetypes/*.md              lane archetypes (README.md = how to add one; _template.md)
    templates/manifest.example.json
tests/
  test_board.sh                  end-to-end board.py checks
  mock_workflow.mjs              scheduler invariants against a fake agent()
  test_guard.py                  guard hook against fake transcripts
  wf_metrics.py                  per-agent tool/token metrics from a workflow transcript dir
  make_smoke.sh                  builds investigations/<name>/ from kit + tests/fixtures/<name>.manifest.json
  fixtures/                      smoke-test manifests
examples/toy-ringbuf/            tiny target with a planted bug (for a smoke test)
examples/stockd/                 harder target: generated repo history with a planted race,
                                 production logs, red herrings (build_target.py, verify_target.sh)
```

## Use it

Requires Claude Code with dynamic workflows enabled (`/config` → Dynamic workflows),
Python 3.9+, and — to run the tests — Node 18+.

```bash
claude --plugin-dir ./investigate          # load the plugin for a session
# or install it permanently as a skills-dir plugin:
#   cp -R investigate ~/.claude/skills/investigate
```

Then `/investigate:setup` in the repository you want to investigate.

To keep a run from stalling on permission prompts, allow the board CLI and the
investigation directory (setup proposes this for you), e.g. in `.claude/settings.local.json`:
`"Workflow"`, `"Bash(/absolute/path/investigations/<slug>/bin/board.py:*)"` (agents call the
board CLI by its absolute path), `"Edit(investigations/<slug>/**)"`.

## Test

```bash
bash tests/test_board.sh        # board.py protocol
python3 tests/test_guard.py     # guard hook
node tests/mock_workflow.mjs    # scheduler: concurrency, exclusive claims, deps, long tasks,
                                # salvage, revise loops, stall / agent-cap / max-rounds stops
```

## Smoke test (spends tokens: ~12–14 agents)

```bash
bash tests/make_smoke.sh toy-ringbuf     # fresh investigations/toy-ringbuf from kit + fixture
bash tests/make_smoke.sh stockd          # builds targets/stockd, then investigations/stockd
```

Then `/investigate:run investigations/toy-ringbuf`, or launch the workflow directly with
`scriptPath: investigations/toy-ringbuf/bin/investigate.js` and
`args: $(python3 investigations/toy-ringbuf/bin/board.py wf-args)`.
Fixture manifests live in `tests/fixtures/`; generated runs under `investigations/` are not
committed.
