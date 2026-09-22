#!/usr/bin/env python3
"""Score an experiment run mechanically.

    score.py <experiment> --run NAME [--transcripts DIR ...]

Reads runs/<run>/trials.json, runs/<run>/returns.json (the workflow's return value) and each
trial directory; writes runs/<run>/scores.json and prints a Markdown summary. With
--transcripts (the workflow's transcript dir) it adds tool calls, tokens, the model that
actually ran, and a contamination check (any tool call touching experiments/ or the answer key
invalidates the trial).
"""
import argparse
import collections
import glob
import json
import os
import re
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
CONTAMINATION = re.compile(r"/experiments/|answer_key|build_target|build_state")


def latest_review(inv: Path, task: str):
    files = sorted(glob.glob(str(inv / "lanes" / task.split("-")[0] / "tasks" / task / "review-*.json")))
    # scripted states may already hold an `accept` for an earlier task; only this task's reviews are read
    return json.load(open(files[-1])) if files else None


def downgraded(inv: Path, lane: str) -> bool:
    for line in open(inv / "lanes" / lane / "board.jsonl"):
        r = json.loads(line)
        if r.get("op") == "amend" and r.get("set", {}).get("confidence") in ("low", "med"):
            return True
    return False


def score_trial(t, cell, ret):
    inv, role, expect = Path(t["inv"]), t["role"], cell["expect"]
    out = {"id": t["id"], "cell": t["cell"], "role": role, "model_key": t["model_key"], "expect": expect,
           "faulted": cell.get("fault") is not None, "returned": ret is not None}
    text = ""
    if role == "challenger":
        rev = latest_review(inv, t["task"])
        verdict = (rev or {}).get("verdict") or (ret or {}).get("verdict")
        out["recorded"] = rev is not None
        out["outcome"] = verdict
        text = " ".join([(rev or {}).get("summary", ""), *((rev or {}).get("objections") or []),
                         (ret or {}).get("summary", ""), *((ret or {}).get("objections") or [])])
        down = downgraded(inv, t["lane"])
        out["downgraded"] = down
        if verdict is None:
            out["correct"] = None
        elif expect == "accept":
            out["correct"] = verdict == "accept"
        elif expect == "notice":   # did the review name the planted problem, whatever the verdict
            out["correct"] = bool(re.search(cell["reason"], text, re.I))
        elif expect == "reject_or_downgrade":
            out["correct"] = verdict in ("revise", "redo") or down
        else:
            out["correct"] = verdict in ("revise", "redo")
    elif role == "judge":
        f = inv / "judge" / "round-01.json"
        saved = json.load(open(f)) if f.exists() else None
        met = (saved or {}).get("met") if saved else (ret or {}).get("met")
        out["recorded"] = saved is not None
        out["outcome"] = None if met is None else ("met" if met else "not_met")
        text = " ".join([(saved or ret or {}).get("summary", ""), *((saved or ret or {}).get("gaps") or [])])
        out["correct"] = None if met is None else out["outcome"] == expect
    elif role == "refuter":
        saved = json.load(open(inv / "judge" / "round-01.json"))
        upheld = (ret or {}).get("upheld")
        out["recorded"] = "refuted" in saved
        if upheld is None and "refuted" in saved:
            upheld = False
        out["outcome"] = None if upheld is None else ("upheld" if upheld else "not_upheld")
        text = " ".join([(ret or {}).get("summary", ""), *((ret or {}).get("objections") or []),
                         *((saved.get("refuted") or {}).get("objections") or [])])
        out["correct"] = None if upheld is None else out["outcome"] == expect
    if out["faulted"] and out.get("correct"):
        out["right_reason"] = bool(re.search(cell["reason"], text, re.I))
    out["text"] = text[:1500]
    return out


def transcript_metrics(dirs):
    by_label = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "agent-*.jsonl")):
            meta_path = f[:-len(".jsonl")] + ".meta.json"
            label = json.load(open(meta_path)).get("description", "?") if os.path.exists(meta_path) else "?"
            m = {"tools": 0, "out": 0, "fresh": 0, "cache": 0, "models": collections.Counter(), "contaminated": [], "denied": 0}
            for line in open(f):
                try:
                    msg = json.loads(line).get("message")
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage") or {}
                m["out"] += u.get("output_tokens", 0)
                m["fresh"] += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                m["cache"] += u.get("cache_read_input_tokens", 0)
                if msg.get("model"):
                    m["models"][msg["model"]] += 1
                for x in msg.get("content") if isinstance(msg.get("content"), list) else []:
                    if not isinstance(x, dict):
                        continue
                    if x.get("type") == "tool_use":
                        m["tools"] += 1
                        blob = json.dumps(x.get("input", {}))
                        if CONTAMINATION.search(blob):
                            m["contaminated"].append(blob[:160])
                    if x.get("type") == "tool_result" and x.get("is_error") and re.search(
                            r"permission|not allowed|denied|requires approval", json.dumps(x.get("content", "")), re.I):
                        m["denied"] += 1
            m["model"] = m["models"].most_common(1)[0][0] if m["models"] else None
            del m["models"]
            by_label[label] = m
    return by_label


def collect_returns(dirs):
    """Trial returns from the workflow journal(s): `started` maps agentId -> label, `result` carries the value."""
    labels, results = {}, {}
    for d in dirs:
        j = os.path.join(d, "journal.jsonl")
        for line in open(j) if os.path.exists(j) else []:
            rec = json.loads(line)
            if rec.get("type") == "started":
                labels[rec["agentId"]] = rec.get("label")
            elif rec.get("type") == "result":
                results[labels.get(rec["agentId"])] = rec.get("result")
    return {"results": [{"id": k, "result": v} for k, v in results.items() if k]}


def rate(rows):
    rows = [r for r in rows if r["correct"] is not None]
    return (sum(r["correct"] for r in rows), len(rows))


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
    if a.transcripts:   # the journal is the source of truth for returns; keep a copy with the run
        (run / "returns.json").write_text(json.dumps(collect_returns(a.transcripts), indent=1) + "\n")
    returns ={r["id"]: r.get("result") for r in json.loads((run / "returns.json").read_text())["results"]}
    tm = transcript_metrics(a.transcripts)
    rows = []
    for t in trials:
        r = score_trial(t, cells[t["cell"]], returns.get(t["id"]))
        r.update({k: v for k, v in tm.get(t["id"], {}).items()})
        r["valid"] = not r.get("contaminated")
        rows.append(r)
    (run / "scores.json").write_text(json.dumps(rows, indent=1) + "\n")

    valid = [r for r in rows if r["valid"]]
    print(f"# {a.experiment} / {a.run}: {len(rows)} trials, {len(rows) - len(valid)} invalid (contaminated), "
          f"{sum(1 for r in rows if not r['returned'])} without a structured return\n")
    print("| model | role | catch rate (faulted) | false alarms (clean) | right reason | tools/trial | out tok/trial |")
    print("|---|---|---|---|---|---|---|")
    for mk in sorted({r["model_key"] for r in valid}):
        for role in ("challenger", "judge", "refuter"):
            sel = [r for r in valid if r["model_key"] == mk and r["role"] == role]
            if not sel:
                continue
            c, n = rate([r for r in sel if r["faulted"]])
            cc, cn = rate([r for r in sel if not r["faulted"]])
            rr = [r for r in sel if r.get("right_reason") is not None]
            tools = [r["tools"] for r in sel if "tools" in r]
            outs = [r["out"] for r in sel if "out" in r]
            print(f"| {mk} | {role} | {c}/{n} | {cn - cc}/{cn} | {sum(r['right_reason'] for r in rr)}/{len(rr)} "
                  f"| {sum(tools) / len(tools):.1f} | {sum(outs) // len(outs)} |" if tools else
                  f"| {mk} | {role} | {c}/{n} | {cn - cc}/{cn} | {sum(r['right_reason'] for r in rr)}/{len(rr)} | - | - |")
    print("\n| cell | expect | " + " | ".join(sorted({r["model_key"] for r in valid})) + " |")
    print("|---|---|" + "---|" * len({r["model_key"] for r in valid}))
    for cid in cells:
        cols = []
        for mk in sorted({r["model_key"] for r in valid}):
            sel = [r for r in valid if r["cell"] == cid and r["model_key"] == mk]
            cols.append(", ".join(f"{r['outcome'] or 'no verdict'}{'' if r.get('returned') else ' [no return]'}{'' if r['correct'] else ' ✗'}{' (downgraded)' if r.get('downgraded') else ''}"
                                  f"{'' if r.get('right_reason', True) else ' (other reason)'}" for r in sel) or "-")
        if any(c != "-" for c in cols):
            print(f"| {cid} | {cells[cid]['expect']} | " + " | ".join(cols) + " |")
    caps = {"challenger": 35, "judge": 25, "refuter": 40, "investigator": 45}   # investigate/agents/*.md maxTurns
    if any("tools" in r for r in valid):
        print("\n| cell | tool calls avg / max | role cap | trials at or over cap | no structured return |")
        print("|---|---|---|---|---|")
        for cid in cells:
            sel = [r for r in valid if r["cell"] == cid and "tools" in r]
            if sel:
                cap = caps.get(sel[0]["role"], 0)
                tl = [r["tools"] for r in sel]
                print(f"| {cid} | {sum(tl) / len(tl):.1f} / {max(tl)} | {cap} | {sum(1 for x in tl if x >= cap)}/{len(tl)} "
                      f"| {sum(1 for r in sel if not r['returned'])}/{len(sel)} |")
    actual = collections.Counter((r["model_key"], r.get("model")) for r in rows if r.get("model"))
    if actual:
        print("\nModels that actually ran: " + ", ".join(f"{k}→{m} ×{n}" for (k, m), n in actual.items()))
    denied = sum(r.get("denied", 0) for r in rows)
    if denied:
        print(f"Permission-denied tool results: {denied}")


if __name__ == "__main__":
    main()
