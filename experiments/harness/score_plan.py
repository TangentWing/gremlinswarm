#!/usr/bin/env python3
"""Score planner trials (x2) from the plan each trial saved.

    score_plan.py <experiment> --run NAME [--transcripts DIR ...]

Reads lanes/<lane>/plan.json in each trial directory (tasks with planned_round == the plan round),
classifies tasks by regex, runs harness/lint.py on the plan (with the directive for detailed-orders
arms), and reports per cell. Regexes are pointers; read the plans before concluding.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from score import EXP, collect_returns, transcript_metrics

KEY_TRACE = re.compile(r"sha-?1|short_hash|idem_?key|B-static-0002|rid.{0,25}attempt.{0,40}key|key.{0,40}(rid|request).{0,25}attempt|"
                       r"(comput|deriv|calculat|reconstruct)\w* .{0,40}(idempotency )?keys?|keys? (for|per|of) (each )?(rid|request|attempt)|"
                       r"map\w* .{0,30}keys? .{0,20}(to|onto|back to) (rid|request)|attribut\w* .{0,60}(by|via|through|using) (the )?(idempotency )?key", re.I)
EVICT_HUNT = re.compile(r"evict\w*.{0,120}(reserved? again|re-?reserv|reused|re-?used|replay|subsequent(ly)? (reserv|used)|later (reserv|used)|same key)|"
                        r"(reserved? again|re-?reserv|replay|reus).{0,80}evict", re.I)
FOLLOW_NOTE = re.compile(r"B-static-0002|retry loop|idem_key|short_hash|rid.{0,20}attempt|attempt.{0,30}(key|hash)|post_order|gateway\.py:2[0-9]|gateway\.py:3[0-9]", re.I)
METHOD_EXACT = re.compile(r"sha-?1|short_hash|idem_?key|B-static-0002|rid:attempt|\{rid\}:\{attempt\}|attempt.{0,25}(key|hash)|(key|hash).{0,25}attempt", re.I)
METHOD_POINTER = re.compile(r"gateway\.py.{0,100}key|key.{0,80}gateway\.py|key[- ](generation|derivation|construction|building) (logic|code|function)|read (the )?(gateway|source).{0,60}key", re.I)
TIMING_ONLY = re.compile(r"(timestamp|timing|temporal|proximity|window).{0,60}(match|correlat|attribut)", re.I)


def tasks_of(inv: Path, lane: str, rnd: int):
    plan = json.loads((inv / "lanes" / lane / "plan.json").read_text())
    return [t for t in plan["tasks"] if t.get("planned_round") == rnd], plan


def text(t):
    return " ".join(str(t.get(k, "")) for k in ("title", "objective", "instructions", "deliverable"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--run", required=True)
    ap.add_argument("--transcripts", nargs="*", default=[])
    a = ap.parse_args()
    run = EXP / a.experiment / "runs" / a.run
    spec = json.loads((EXP / a.experiment / "spec.json").read_text())
    cells = {c["id"]: c for c in spec["cells"]}
    trials = json.loads((run / "trials.json").read_text())["trials"]
    if a.transcripts:
        (run / "returns.json").write_text(json.dumps(collect_returns(a.transcripts), indent=1) + "\n")
    returns = {r["id"]: r.get("result") for r in json.loads((run / "returns.json").read_text())["results"]}
    tm = transcript_metrics(a.transcripts)
    rows = []
    for t in trials:
        inv, cell = Path(t["inv"]), cells[t["cell"]]
        ts, plan = tasks_of(inv, t["lane"], t["round"])
        blob = " || ".join(text(x) for x in ts)
        notes = plan.get("notes") or ""
        directive = None
        src = (cell.get("inputs") or {}).get("prompts/plan.md")
        if src and src.get("render") == "detailed":
            i = int(t["id"].rsplit("-", 1)[1])
            exp_name, _, run_name = src["from_run"].rpartition(":")
            exp_dir = next(EXP.glob(f"{exp_name}-*")) if exp_name else EXP / a.experiment
            rets = {r["id"]: r.get("result") for r in json.loads((exp_dir / "runs" / run_name / "returns.json").read_text())["results"]}
            pos = rets.get(src["ids"][0].replace("{model}", t["model_key"]).replace("{i}", str(i))) or {}
            directive = [d for d in pos.get("directive", []) if d.get("lane") == t["lane"]]
        dpath = run / f".directive-{t['id'].replace('/', '_')}.json"
        if directive is not None:
            dpath.write_text(json.dumps(directive))
        lint = subprocess.run([sys.executable, str(EXP / "harness" / "lint.py"), str(inv), "--round", str(t["round"]), "--json"]
                              + (["--directive", str(dpath)] if directive is not None else []), capture_output=True, text=True).stdout
        findings = json.loads(lint or "[]")
        dpath.unlink(missing_ok=True)
        rows.append({"id": t["id"], "cell": t["cell"], "arm": cell["arm"], "state": cell["variant"], "lane": t["lane"], "model_key": t["model_key"],
                     "returned": returns.get(t["id"]) is not None, "saved": plan.get("version", 0) > 1, "n_tasks": len(ts),
                     "adversarial": sum(1 for x in ts if x.get("verify") == "adversarial"),
                     "key_trace": bool(KEY_TRACE.search(blob)), "eviction_hunt": bool(EVICT_HUNT.search(blob)),
                     "follows_note": bool(FOLLOW_NOTE.search(blob)),
                     "method": "exact" if METHOD_EXACT.search(blob) else "pointer" if METHOD_POINTER.search(blob) else "none",
                     "timing_only": bool(TIMING_ONLY.search(blob)) and not METHOD_EXACT.search(blob),
                     "cites_ids": len(set(re.findall(r"B-[a-z]+-\d{4}", blob))), "deps": sum(len(x.get("deps", [])) for x in ts),
                     "sceptic_note": bool(re.search(r"contradict|does not fit|not (been )?observed|predict", notes, re.I)),
                     "lint": [f["code"] for f in findings], "notes": notes[:300], "tasks": [x["title"] for x in ts],
                     **tm.get(t["id"], {})})
    for r in rows:
        r["valid"] = not r.get("contaminated")
    (run / "scores.json").write_text(json.dumps(rows, indent=1) + "\n")
    ok = [r for r in rows if r["valid"]]
    print(f"# {a.experiment} / {a.run}: {len(rows)} trials, {sum(1 for r in rows if not r['saved'])} saved no plan, "
          f"{sum(1 for r in rows if not r['returned'])} without a structured return\n")
    print("| arm | lane | state | n | trace task | method exact | method pointer | timing guess | eviction hunt | follows note | cites ids (avg) | tasks (avg) | adversarial | lint findings | sceptic note | tools |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    keyf = lambda r: (r["arm"], r["lane"], r["state"])
    for k in sorted({keyf(r) for r in ok}):
        sel = [r for r in ok if keyf(r) == k]
        n = len(sel)
        f = lambda name: f"{sum(1 for r in sel if r.get(name))}/{n}"
        m = lambda v: f"{sum(1 for r in sel if r['method'] == v)}/{n}"
        print(f"| {k[0]} | {k[1]} | {k[2]} | {n} | {f('key_trace')} | {m('exact')} | {m('pointer')} | {f('timing_only')} | {f('eviction_hunt')} | {f('follows_note')} "
              f"| {sum(r['cites_ids'] for r in sel) / n:.1f} | {sum(r['n_tasks'] for r in sel) / n:.1f} | {sum(r['adversarial'] for r in sel)} "
              f"| {sum(len(r['lint']) for r in sel)} | {f('sceptic_note')} | {sum(r.get('tools', 0) for r in sel) / n:.1f} |")


if __name__ == "__main__":
    main()
