#!/usr/bin/env python3
"""Verification digest for a judge/refuter: facts computed from an investigation directory.

    enrich.py <investigation dir>

Prototype of what `board.py brief` could print for verdict roles (DESIGN_V2 §3.6): the review
status of the tasks behind each shared entry, and open lane-board hypotheses / questions /
contradictions that no shared entry refers to. Facts only — no judgment, no target knowledge.
"""
import glob
import json
import re
import sys
from pathlib import Path


def entries(path):
    out = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("op") == "amend":
            if r["target"] in out:
                out[r["target"]].update(r.get("set", {}))
        else:
            out[r["id"]] = r
    return out


def main(root: Path):
    shared = entries(root / "shared" / "board.jsonl")
    lanes = {}
    for p in glob.glob(str(root / "lanes" / "*" / "board.jsonl")):
        lanes.update(entries(p))
    produced = {}                       # board id -> (task id, last review)
    for res in glob.glob(str(root / "lanes" / "*" / "tasks" / "*" / "result.json")):
        r = json.load(open(res))
        reviews = sorted(glob.glob(str(Path(res).parent / "review-*.json")))
        last = json.load(open(reviews[-1])) if reviews else None
        for bid in r.get("board_ids", []):
            produced[bid] = (r["id"], r.get("status"), last)
    print("## Verification digest (computed from the files by tooling: facts, not judgments)\n")
    print("Review status of the work behind each shared entry:")
    mentioned = set()
    for sid, e in shared.items():
        cited = sorted(set(re.findall(r"B-[a-z_]+-\d{4}", " ".join(e.get("refs", [])) + " " + e.get("body", ""))) - {sid})
        mentioned.update(cited)
        if e.get("status") in ("refuted", "irrelevant"):
            print(f"- {sid} is marked {e['status']}.")
        for c in cited:
            if c in produced:
                tid, status, last = produced[c]
                rv = f"last review = {last['verdict']} (\"{last['summary'][:140]}\")" if last else "never reviewed"
                print(f"- {sid} cites {c}, produced by task {tid} (task status: {status}); {rv}")
    loose = [e for bid, e in lanes.items() if e.get("kind") in ("hypothesis", "question", "contradiction")
             and e.get("status", "open") == "open" and bid not in mentioned]
    print("\nOpen hypotheses, questions and contradictions on lane boards that no shared entry refers to:")
    for e in loose:
        print(f"- {e['id']} [{e['kind']}/{e.get('confidence', '-')}] {e['subject']}  (lane {e['lane']})")
    if not loose:
        print("- none")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
