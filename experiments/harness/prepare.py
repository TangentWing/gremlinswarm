#!/usr/bin/env python3
"""Expand an experiment spec into trial directories and workflow args.

    prepare.py <experiment> --run NAME [--k N] [--models a,b] [--cells id,id]

Builds each (cell) state once with experiments/states/build_state.py, copies it per trial into
investigations/_exp/<experiment>/<run>/<model>/<cell>-<i>/ (git-ignored, and covered by the
existing `investigations/_exp/` allow rule), and writes experiments/<experiment>/runs/<run>/
trials.json (explicit, used by score.py) and args.json (compact — pass its content as `args` to
harness/run_trials.js).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
REPO = EXP.parent
BUILD = EXP / "states" / "build_state.py"


def render_position(pos, form, lane):
    """A strategist's position as it would reach a lane planner. `detailed`: the directive items for this lane
    verbatim (orders). `intent`: hypotheses, statuses, reasons, what would discriminate them and what is not
    pursued — no experiments, no lane assignments (mission orders: the lane designs the task)."""
    if not pos:
        return "\n## Strategist (nothing received this round)\n"
    hy = "\n".join(f"- [{h.get('status')}] {h.get('name')} — {h.get('reason', '')}" for h in pos.get("hypotheses", []))
    if form == "detailed":
        mine = [d for d in pos.get("directive", []) if d.get("lane") == lane]
        others = [d for d in pos.get("directive", []) if d.get("lane") != lane]
        return ("\n## Strategist's directive for this round (attached to your brief)\n\n### Hypotheses and their status\n" + hy
                + "\n\n### Your lane's items — plan tasks that carry them out, or decline one in the plan notes with a reason\n"
                + ("\n".join(f"- {d.get('experiment')}\n  - separates: {d.get('separates', '')}\n  - predictions: {d.get('predictions', '')}" for d in mine) or "- (none for this lane)")
                + "\n\n### Other lanes' items (for coordination only)\n" + ("\n".join(f"- [{d.get('lane')}] {d.get('experiment', '')[:160]}" for d in others) or "- (none)")
                + f"\n\n### Not pursuing\n{pos.get('not_pursuing', '')}\n")
    if form == "intent":
        disc = "\n".join(f"- {d.get('separates', '')}: {d.get('predictions', '')}" for d in pos.get("directive", []) if d.get("separates") or d.get("predictions"))
        return ("\n## Strategist's intent for this round (attached to your brief)\n\n### Hypotheses and their status\n" + hy
                + "\n\n### What this round must settle — observations whose outcome differs between the live hypotheses\n" + (disc or "- (none stated)")
                + f"\n\n### Not pursuing\n{pos.get('not_pursuing', '')}\n\nDesign your lane's tasks so their results settle the above; you choose the experiments.\n")
    raise SystemExit(f"unknown render form {form}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--run", required=True)
    ap.add_argument("--k", type=int)
    ap.add_argument("--models")
    ap.add_argument("--cells")
    ap.add_argument("--agent-types", metavar="PLUGIN", help="use the plugin's role agents, e.g. `investigate`")
    a = ap.parse_args()
    spec = json.loads((EXP / a.experiment / "spec.json").read_text())
    k = a.k or spec["k"].get(a.run, 1)
    models = a.models.split(",") if a.models else (list(k) if isinstance(k, dict) else list(spec["models"]))
    kby = {m: (k.get(m, 1) if isinstance(k, dict) else k) for m in models}     # k may differ per model
    cells = [c for c in spec["cells"] if not a.cells or c["id"] in a.cells.split(",")]
    base = REPO / "investigations" / "_exp" / a.experiment / a.run
    if base.exists():
        shutil.rmtree(base)
    templates = base / "_templates"
    trials, compact = [], []
    for c in cells:
        tpl = templates / c["id"]
        cmd = ([sys.executable, str(BUILD), c["state"], c["variant"], str(tpl)] + (["--judged"] if c.get("judged") else [])
               + c.get("state_args", []))
        env = {**os.environ, "TRISVC_PROFILE": spec.get("target_profile", "base")}
        info = json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True, env=env).stdout)
        for rel, src in spec.get("install", {}).items():           # experiment-local roles, briefs, tools
            (tpl / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(EXP / a.experiment / src, tpl / rel)
            if rel.startswith("bin/"):
                (tpl / rel).chmod(0o755)
        view = spec.get("target_view")
        if view and c["role"] in view["roles"]:
            # strategy roles work from the boards: the target they can reach holds only what `keep` lists
            real = Path(json.loads((tpl / "manifest.json").read_text())["targets"][0]["path"])
            tv = tpl / "_target"
            tv.mkdir()
            for sub in view["keep"]:
                src = real / sub
                (shutil.copytree if src.is_dir() else shutil.copy)(src, tv / sub)
            for f in [tpl / "manifest.json", *tpl.glob("lanes/*/lane.md")]:
                f.write_text(f.read_text().replace(str(real), str(tv)))
        if spec.get("partition_boards") and c["role"] in spec["partition_boards"] and (c.get("params") or {}).get("lane"):
            # an advocate sees its own lane and shared only: other lanes' material is removed from its copy
            own = c["params"]["lane"]
            for ld in tpl.glob("lanes/*"):
                if ld.name == own:
                    continue
                for name in ("board.jsonl", "worklog.jsonl"):
                    (ld / name).write_text("")
                shutil.rmtree(ld / "tasks", ignore_errors=True)
                (ld / "tasks").mkdir()
                plan = json.loads((ld / "plan.json").read_text())
                plan["tasks"], plan["notes"] = [], "(not visible to this advocate)"
                (ld / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
                shutil.rmtree(ld / "archive", ignore_errors=True)
        if c.get("arm") in spec.get("arms", {}):   # arms are overlays on the trial's own prompt pack
            armdef = spec["arms"][c["arm"]]
            overlay = dict(armdef.get("overlay", {}))
            if armdef.get("computed"):
                digest = subprocess.run([sys.executable, str(HERE / "enrich.py"), str(tpl)], check=True,
                                        capture_output=True, text=True).stdout
                overlay = {f"prompts/{r}.md": "\n" + digest + armdef.get("suffix", "") for r in ("judge", "refuter")}
            for rel, edits in armdef.get("edits", {}).items():               # regex edits on state files (path may use {lane}, {plan_round})
                f = tpl / rel.format(lane=(c.get("params") or {}).get("lane", ""), plan_round=f"{info.get('plan_round', 0):02d}")
                txt = f.read_text()
                for pat, repl in edits:
                    assert re.search(pat, txt, re.M), f"{c['id']}: edit pattern not found in {rel}: {pat}"
                    txt = re.sub(pat, repl, txt, flags=re.M)
                f.write_text(txt)
            for rel, sources in armdef.get("append_files", {}).items():       # arm material the state builder left in _arms/
                overlay[rel] = overlay.get(rel, "") + "".join((tpl / src).read_text() for src in sources)
            for rel, src in armdef.get("copy_files", {}).items():
                (tpl / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(tpl / src, tpl / rel)
            for rel, text in overlay.items():
                with open(tpl / rel, "a") as f:
                    f.write(text)
        shutil.rmtree(tpl / "_arms", ignore_errors=True)    # a trial never sees material meant for other arms
        compact.append({"id": c["id"], "role": c["role"],
                        **({k2: info[k2] for k2 in ("lane", "task", "title", "verify", "round") if k2 in info}
                           if c["role"] in ("challenger", "investigator") else {"round": info.get("plan_round" if c["role"] == "plan" else "round", 1)}),
                        **c.get("params", {}), **({"max_tasks": 2} if c["role"] == "plan" else {})})
        for m in models:
            for i in range(1, kby[m] + 1):
                d = base / m / f"{c['id']}-{i}"
                shutil.copytree(tpl, d)
                for rel, src in (c.get("inputs") or {}).items():
                    # per-trial input assembled from earlier runs' returns: {"from_run": R, "ids": ["<model>/<cell>-{i}", ...]}
                    exp_name, _, run_name = src["from_run"].rpartition(":")      # "x3:stage-b1" -> another experiment's run
                    exp_dir = next(EXP.glob(f"{exp_name}-*")) if exp_name else EXP / a.experiment
                    rets = {r["id"]: r.get("result") for r in json.loads(
                        (exp_dir / "runs" / run_name / "returns.json").read_text())["results"]}
                    parts = []
                    for tid in src["ids"]:
                        tid = tid.replace("{model}", m).replace("{i}", str(i))
                        pos = rets.get(tid)
                        seat = tid.split("/")[1].rsplit("-", 2)[-2] if pos else "?"
                        if src.get("render"):
                            parts.append(render_position(pos, src["render"], (c.get("params") or {}).get("lane")))
                        else:
                            parts.append(f"## Position from seat: {seat}\n\n" + (json.dumps(pos, indent=1) if pos else "(this member returned no position)"))
                    (d / rel).parent.mkdir(parents=True, exist_ok=True)
                    with open(d / rel, "a" if src.get("append") else "w") as f:
                        f.write("\n\n".join(parts) + "\n")
                t = {"id": f"{m}/{c['id']}-{i}", "cell": c["id"], "role": c["role"], "inv": str(d),
                     "model": spec["models"][m], "model_key": m, "round": 1}
                if c["role"] == "challenger":
                    # adversarial tasks get review 1 of verify_rounds (revise allowed); light tasks get a single review
                    t.update(lane=info["lane"], task=info["task"], title=info["title"], verify=info["verify"],
                             review=1, allowRevise=info["verify"] == "adversarial")
                if c["role"] == "investigator":
                    t.update(lane=info["lane"], task=info["task"], title=info["title"], round=info["round"])
                if c["role"] == "plan":
                    t.update(lane=c["params"]["lane"], round=info["plan_round"], max_tasks=2)
                t.update(c.get("params", {}))
                if "round" in info and c["role"] not in ("challenger", "investigator", "plan"):
                    t["round"] = info["round"]
                if c["role"] == "judge":
                    t.update(stall=0, stallRounds=2)
                trials.append(t)
    shutil.rmtree(templates)
    out = EXP / a.experiment / "runs" / a.run
    out.mkdir(parents=True, exist_ok=True)
    (out / "trials.json").write_text(json.dumps({"run": f"{a.experiment}/{a.run}", "target_profile": spec.get("target_profile", "base"),
                                                 "trials": trials}, indent=1) + "\n")
    args = {"run": f"{a.experiment}/{a.run}", "base": str(base), "k": kby,
            "models": {m: spec["models"][m] for m in models}, "cells": compact}
    if a.agent_types:
        args["agent_types"] = {r: f"{a.agent_types}:{r}" for r in sorted({c["role"] for c in cells})}
    (out / "args.json").write_text(json.dumps(args) + "\n")
    print(f"{len(trials)} trials ({len(cells)} cells x {len(models)} models x k={kby}) -> {out / 'trials.json'}")


if __name__ == "__main__":
    main()
