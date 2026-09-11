---
name: debugger
summary: Inspect a running or crashing program with a debugger (gdb, lldb, pdb, delve) to capture its state.
use_when: [a crash or hang needs a backtrace, internal state at failure time is unknown, static reading is ambiguous]
resource_kinds: [local-repo, device, ssh, port]
verify_default: light
task_kinds: [debug]
---
# Lane: {{lane}}

## Mandate
{{mandate}}

## Resources
{{resources}}

## Method
1. Make the session reproducible: drive the debugger in batch mode with a command file
   (`gdb -batch -x cmds.gdb ...`, `lldb -s cmds.lldb ...`, `python -m pdb` with commands)
   and save both the command file and the output in your task directory.
2. Least-invasive first: backtraces of all threads, then breakpoints at suspect sites,
   then watchpoints. Record locals and the relevant structures at each stop.
3. Symbols must match the binary under test; record the build/commit you debugged.
4. For races, capture state at the moment of violation (conditional breakpoints or an
   assertion that dumps state) rather than stepping, which changes timing.
5. Detach and kill everything you started (`task started` / `task stopped`).

## Evidence standard
{{evidence_standard}}

## Pitfalls
- The debugger changes timing and can hide a race → say so when a failure stops
  reproducing under the debugger; pair with experiment-lane rates.
- Halting a target can trip watchdogs or time out clients → note side effects.
- Mismatched symbols → misleading line numbers; verify the binary's build id.
- Interactive sessions → not reproducible; always use command files.

## Typical tasks
- `debug` — Capture all-thread backtraces when the process hangs under load.
- `debug` — Break when the invariant is violated and dump the relevant state.
