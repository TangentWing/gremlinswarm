#!/usr/bin/env python3
"""Build the trisvc target (bursty profile) for an end-to-end run: a shim over the experiments' generator.

    build_target.py --out DIR      (called by tests/make_smoke.sh trisvc-e6)

The generator and answer key live in experiments/targets/trisvc/. The key for this build is written
next to the output directory (<out>.answer_key.json); never point agents at it.
"""
import runpy
import sys
from pathlib import Path

gen = Path(__file__).resolve().parents[2] / "experiments" / "targets" / "trisvc" / "build_target.py"
out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else str(Path(__file__).resolve().parents[2] / "targets" / "trisvc-e6")
sys.argv = [str(gen), "--profile", "bursty", "--seed", "3", "--out", out, "--check"]
runpy.run_path(str(gen), run_name="__main__")
