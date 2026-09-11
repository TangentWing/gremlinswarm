---
name: perf-profile
summary: Measure and profile performance to explain latency, throughput or resource regressions.
use_when: [something got slower or heavier, latency spikes, CPU or memory growth, performance claims need numbers]
resource_kinds: [local-repo, service, port]
verify_default: light
task_kinds: [experiment, analysis]
---
# Lane: {{lane}}

## Mandate
{{mandate}}

## Resources
{{resources}}

## Method
1. Define the metric and the workload first (what is measured, how, for how long).
2. Baseline with repetitions: warm up, then ≥ 5 runs; report mean/median/p99 and spread.
3. Profile the slow case (cProfile/py-spy, perf, pprof, Instruments) and save the raw
   profile plus a top-N summary in your task directory.
4. Compare A/B (commit, config, input) under identical conditions; change one thing at a time.
5. Separate on-CPU from waiting (locks, I/O, GC); a profile of CPU time won't show lock waits.

## Evidence standard
{{evidence_standard}}

## Pitfalls
- Single measurements and noisy machines → repeat, report spread, note background load.
- Debug builds or profilers distorting results → note overhead; confirm with plain timing.
- Optimising the wrong thing → tie every hotspot back to the metric that regressed.

## Typical tasks
- `experiment` — Measure p50/p99 latency of X at commits A and B (10 runs each).
- `analysis` — Profile the slow path and attribute time to functions.
