#!/usr/bin/env python3
"""Score investigator ("work") trials mechanically against the trisvc answer key.

    score_work.py <experiment> --run NAME [--transcripts DIR ...]

Per trial: is trace.json right row by row, how did the agent get the gateway-to-inventory join
(pushed / queried the board / `task show` on a dep / read gateway.py), did it present the
eviction red herring as the cause, and what did it cost.
"""
import argparse
import json
import re
from pathlib import Path

from score import EXP, collect_returns, transcript_metrics

TRUE = {}


def load_key(profile):
    key = json.loads((EXP / "targets" / "trisvc" / ("answer_key.json" if profile == "base" else f"answer_key.{profile}.json")).read_text())
    TRUE.update({a["rid"]: set(a["reserve_lines"]) for a in key["affected"]})
    for rid in key["facts"]["timed_out_rids"]:
        TRUE.setdefault(rid, set())           # timed out but reserved nothing: still a legitimate row

NOT_CAUSE = re.compile(r"rul(ed|es|ing) out|not (the|a) (root )?cause|refut|does not explain|cannot explain|contradict|"
                       r"no (key|replay)|never (re-?reserved|replayed|repeat)|predates|before the first evict|unrelated|red herring", re.I)


def load_trace(td: Path):
    for p in [td / "trace.json", *td.glob("*.json")]:
        if p.name in ("task.json", "result.json") or p.name.startswith(("review-", "result.")) or not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        rows = data if isinstance(data, list) else data.get("traces") or data.get("requests") or []
        rows = [r for r in rows if isinstance(r, dict) and r.get("rid")]
        if rows:
            return p.name, rows
    return None, []


def route(f):
    out = {"queried": 0, "task_show": 0, "read_gateway": 0, "read_kb": 0}
    for line in open(f):
        try:
            msg = json.loads(line).get("message")
        except json.JSONDecodeError:
            continue
        for x in (msg or {}).get("content") if isinstance((msg or {}).get("content"), list) else []:
            if isinstance(x, dict) and x.get("type") == "tool_use":
                blob = json.dumps(x.get("input", {}))
                out["queried"] += bool(re.search(r"board\.py[\"']?\s+query|\$B\w*\s+query", blob))
                out["task_show"] += bool(re.search(r"task show", blob))
                out["read_gateway"] += "gateway.py" in blob
                out["read_kb"] += "kb/" in blob
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--run", required=True)
    ap.add_argument("--transcripts", nargs="*", default=[])
    a = ap.parse_args()
    run = EXP / a.experiment / "runs" / a.run
    meta = json.loads((run / "trials.json").read_text())
    load_key(meta.get("target_profile") or json.loads((EXP / a.experiment / "spec.json").read_text()).get("target_profile", "base"))
    trials = json.loads((run / "trials.json").read_text())["trials"]
    if a.transcripts:
        (run / "returns.json").write_text(json.dumps(collect_returns(a.transcripts), indent=1) + "\n")
    returns = {r["id"]: r.get("result") for r in json.loads((run / "returns.json").read_text())["results"]}
    tm = transcript_metrics(a.transcripts)
    routes = {}
    for d in a.transcripts:
        for f in Path(d).glob("agent-*.jsonl"):
            meta = f.with_name(f.name[:-len(".jsonl")] + ".meta.json")
            if meta.exists():
                routes[json.loads(meta.read_text()).get("description")] = route(f)
    rows = []
    for t in trials:
        inv, ret = Path(t["inv"]), returns.get(t["id"])
        td = inv / "lanes" / t["lane"] / "tasks" / t["task"]
        fname, trace = load_trace(td)
        good = sum(1 for r in trace if r["rid"] in TRUE and set(map(int, r.get("reserve_lines") or [])) == TRUE[r["rid"]])
        who = f"{t['lane']}/{t['task']}"
        mine = [json.loads(l) for l in open(inv / "lanes" / t["lane"] / "board.jsonl")]
        mine += [json.loads(l) for l in open(inv / "shared" / "board.jsonl")]
        mine = [e for e in mine if e.get("author") == who and not e.get("op")]
        text = " ".join(f"{e.get('subject', '')} {e.get('body', '')}" for e in mine) + " " + (ret or {}).get("summary", "")
        claims = [s for s in re.split(r"(?<=[.!?\n])\s+", text) if re.search(r"evict", s, re.I)]
        asserts = any(re.search(r"caus|explain|responsible|because|due to|leads? to|result", s, re.I) and not NOT_CAUSE.search(s) for s in claims)
        result = json.loads((td / "result.json").read_text()) if (td / "result.json").exists() else None
        r = {"id": t["id"], "cell": t["cell"], "model_key": t["model_key"], "returned": ret is not None,
             "status": (result or ret or {}).get("status"), "finished": result is not None, "trace_file": fname,
             "rows": len(trace), "rows_correct": good, "success": good >= 5 and good == len(trace),
             "method_found": bool(re.search(r"sha-?1|idem_key|rid.{0,12}attempt|per[- ]attempt", text, re.I)),
             "asserts_eviction": asserts, "entries": len(mine),
             "cited_prior": bool(re.search(r"B-(static|shared)-000\d", json.dumps([e.get("refs") for e in mine]) + text)),
             **routes.get(t["id"], {}), **tm.get(t["id"], {}), "text": text[:1200]}
        r["valid"] = not r.get("contaminated")
        rows.append(r)
    (run / "scores.json").write_text(json.dumps(rows, indent=1) + "\n")
    print(f"# {a.experiment} / {a.run}: {len(rows)} trials, {sum(1 for r in rows if not r['valid'])} invalid, "
          f"{sum(1 for r in rows if not r['returned'])} without a structured return\n")
    print("| cell | model | n | success | rows right / given | method found | asserts eviction | queried board | task show | read gateway.py | cited prior entries | tools avg (max) | out tok avg |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    cells = list(dict.fromkeys(r["cell"] for r in rows))
    for cid in cells:
        for mk in sorted({r["model_key"] for r in rows}):
            sel = [r for r in rows if r["cell"] == cid and r["model_key"] == mk and r["valid"]]
            if not sel:
                continue
            n = len(sel)
            frac = lambda k: f"{sum(1 for r in sel if r.get(k))}/{n}"
            tl = [r.get("tools", 0) for r in sel]
            print(f"| {cid} | {mk} | {n} | {frac('success')} | {sum(r['rows_correct'] for r in sel)} / {sum(r['rows'] for r in sel)} | {frac('method_found')} "
                  f"| {frac('asserts_eviction')} | {frac('queried')} | {frac('task_show')} | {frac('read_gateway')} | {frac('cited_prior')} "
                  f"| {sum(tl) / n:.1f} ({max(tl)}) | {sum(r.get('out', 0) for r in sel) // n} |")


if __name__ == "__main__":
    main()
