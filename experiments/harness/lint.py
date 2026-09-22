#!/usr/bin/env python3
"""Plan lint: cross-lane checks a script can make on the queued plans of a round, with no agent.

    lint.py <investigation dir> [--plans FILE ...] [--round N]   (default: every lane's current plan.json, queued tasks)

Prototype of a `board.py lint` step for DESIGN_V2 §3.1 (plan review, part 1). Reports:
  long-exclusive    a `long` task claims an exclusive resource another lane's queued task also
                    claims — the holder runs across round boundaries, so the other lane starves
                    (stockd-before, round 1: history-r01-01 held port_8765 all round; repro waited)
  exclusive-fanin   > 2 queued tasks across lanes claim the same exclusive resource this round
                    (they serialise; most of them will be deferred)
  same-dir          two tasks name the same working location (/tmp/..., another task's dir); read-only
                    inputs from the manifest (targets, resource access paths) are ignored
  dead-dep          a dep on a task that is not done/partial and not queued this round
  over-cap          more queued tasks than max_tasks_per_lane_round
  directive-unmet   (with --directive FILE) a directive item for this lane that no queued task
                    covers (keyword overlap) and no plan note declines
Exit code 0; findings are printed one per line as `<code> <lane>: <detail>` and returned as JSON with --json.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_BUDGET = {"max_tasks_per_lane_round": 3}
DIR_RE = re.compile(r"((?:/tmp|/var|/home|/Users|~)/[\w./-]+|lanes/\w+/tasks/[\w./-]+)")   # shared locations, not bare file names


def load(root: Path, plan_files):
    m = json.loads((root / "manifest.json").read_text())
    excl = {r["name"] for r in m.get("resources", []) if r.get("exclusive")}
    # read-only inputs: the targets and any absolute resource access path, plus their parent directories
    # (BUGREPORT.md sits next to the repo; a log glob is described in prose after the path)
    raw = [t.get("path") for t in m.get("targets", [])] + [r.get("access", "").split()[0] for r in m.get("resources", []) if r.get("access")]
    m["_inputs"] = sorted({str(Path(p).expanduser()) for p in raw if p.startswith(("/", "~"))}
                          | {str(Path(p).expanduser().parent) for p in raw if p.startswith(("/", "~"))})
    m["_shared_reads"] = re.compile(r"lanes/\w+/tasks/[\w-]+(/[\w.-]+)?$")   # reading an earlier task's artifacts is not a write conflict
    budget = {**DEFAULT_BUDGET, **m.get("budget", {})}
    plans = {}
    files = plan_files or sorted(root.glob("lanes/*/plan.json"))
    for f in files:
        p = json.loads(Path(f).read_text())
        plans[p["lane"]] = p
    return m, excl, budget, plans


def lint(root: Path, plan_files=None, directive=None, rnd=None):
    """rnd: replay a past round — the tasks planned in it, whatever their status now (plan.json is updated in place)."""
    m, excl, budget, plans = load(root, plan_files)
    out = []
    queued = {lane: [t for t in p["tasks"] if (t.get("planned_round") == rnd if rnd else t.get("status") == "queued")]
              for lane, p in plans.items()}
    status = {t["id"]: t.get("status") for p in plans.values() for t in p["tasks"]}
    # exclusive claims across lanes
    claims = {}
    for lane, ts in queued.items():
        for t in ts:
            for r in t.get("resources", []):
                if r in excl:
                    claims.setdefault(r, []).append((lane, t))
    for r, cs in claims.items():
        lanes = {l for l, _ in cs}
        for lane, t in cs:
            if t.get("size") == "long" and len(lanes) > 1:
                others = sorted({l for l, _ in cs if l != lane})
                out.append(("long-exclusive", lane, f"{t['id']} is long and holds exclusive '{r}' that {', '.join(others)} also queued for; "
                                                      f"split it so the resource is released between steps"))
        if len(cs) > 2:
            out.append(("exclusive-fanin", "all", f"{len(cs)} queued tasks claim exclusive '{r}': " + ", ".join(t["id"] for _, t in cs)))
    # shared working locations
    seen = {}
    for lane, ts in queued.items():
        for t in ts:
            for d in set(DIR_RE.findall(t.get("instructions", "") + " " + t.get("deliverable", ""))):
                if d.startswith(f"lanes/{lane}/tasks/{t['id']}") or any(d.startswith(i) for i in m["_inputs"]):
                    continue    # its own task dir, or a read-only input everyone names
                if m["_shared_reads"].match(d) and d.split("/")[3] not in {x["id"] for x in ts}:
                    continue    # an earlier task's artifacts, read by several tasks
                if d in seen and seen[d] != t["id"]:
                    out.append(("same-dir", lane, f"{t['id']} and {seen[d]} both name {d}"))
                seen.setdefault(d, t["id"])
    # deps
    for lane, ts in queued.items():
        qids = {t["id"] for t in ts}
        for t in ts:
            for d in t.get("deps", []):
                if d not in qids and status.get(d) not in ("done", "partial"):
                    out.append(("dead-dep", lane, f"{t['id']} depends on {d} which is {status.get(d, 'unknown')}"))
        if len(ts) > budget["max_tasks_per_lane_round"]:
            out.append(("over-cap", lane, f"{len(ts)} queued > max_tasks_per_lane_round={budget['max_tasks_per_lane_round']}"))
    # directive coverage
    if directive:
        words = lambda s: {w for w in re.findall(r"[a-z][a-z0-9_-]{3,}", s.lower())} - STOP
        for item in directive:
            lane = item.get("lane")
            if lane not in queued:
                continue
            want = words(item.get("experiment", ""))
            best = max((len(want & words(t.get("objective", "") + " " + t.get("instructions", ""))) / max(1, len(want)), t["id"])
                       for t in queued[lane]) if queued[lane] else (0, None)
            declined = bool(re.search(r"declin|defer", plans[lane].get("notes") or "", re.I))
            if best[0] < 0.25 and not declined:
                out.append(("directive-unmet", lane, f"no queued task covers: {item.get('experiment', '')[:100]}"))
    return out


STOP = {"with", "that", "this", "from", "each", "then", "than", "which", "where", "when", "what", "into", "have", "they",
        "them", "their", "these", "those", "using", "used", "show", "showing", "line", "lines", "number", "numbers", "least",
        "request", "requests", "merged", "logs", "log"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("inv")
    ap.add_argument("--plans", nargs="*")
    ap.add_argument("--directive", help="JSON file with a list of {lane, experiment}")
    ap.add_argument("--round", type=int, help="replay: lint the tasks planned in that round")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = json.loads(Path(a.directive).read_text()) if a.directive else None
    findings = lint(Path(a.inv).resolve(), a.plans, d, a.round)
    if a.json:
        print(json.dumps([{"code": c, "lane": l, "detail": t} for c, l, t in findings]))
    else:
        for c, l, t in findings:
            print(f"{c} {l}: {t}")
        if not findings:
            print("(no findings)")
