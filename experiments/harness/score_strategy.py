#!/usr/bin/env python3
"""Score strategy positions (x3) mechanically.

    score_strategy.py <experiment> --run NAME [--transcripts DIR ...]

A position is {hypotheses:[{name, based_on, status, reason}], directive:[{lane, experiment, separates, predictions}]}.
The v1 baseline arm (C0) is a judge: its gaps are scored as the directive. Regex classification is a pointer —
results.md must rest on hand-read positions as well.
"""
import argparse
import collections
import json
import re
from pathlib import Path

from score import EXP, collect_returns, transcript_metrics

EVICT = re.compile(r"evict|\bLRU\b|cache (size|turnover|forget|pressure|capacity)|forg[eo]ts? (a |the |idempotency )?keys?", re.I)
DEPLOY = re.compile(r"deploy|v1\.4\.2|release", re.I)
TRUE = re.compile(r"per[- ]attempt|idem_?key|attempt.{0,50}\bkeys?\b|\bkeys?\b.{0,70}(attempt|derived|derivation|built from|includes? the|"
                  r"differ|new key|changes? (per|on|with)|not reused|never reused)|new (idempotency )?key|retr(y|ies).{0,60}(new|different|fresh) key|"
                  r"(timeout|timed[- ]out|retr(y|ies|ied)).{0,80}(duplicate|multiple|double|separate|independent|extra|second|additional) (reserv|reservation)|"
                  r"(duplicate|multiple|double) reserv\w*.{0,60}(retr|timeout|attempt)|(without|independent of|no) eviction", re.I)
D = {
    "D1_same_key_twice": re.compile(r"(same|any|an?|evicted) key.{0,60}(twice|more than once|again|repeat|re-?reserv|second time)|uniq -d|duplicate keys?|"
                                    r"key.{0,30}appears? (twice|more than once)", re.I),
    "D2_key_trace": re.compile(r"sha-?1|short_hash|idem_?key|deriv|comput\w* (the )?(idempotency )?keys?|keys? (for|per|of) (each )?(rid|request|attempt)|"
                               r"(rid|request).{0,25}attempt.{0,40}key|map\w* .{0,30}keys? .{0,20}(to|onto) (rid|request)|attribut\w* .{0,60}(by|via|through|using) (the )?key", re.I),
    "D3_age_vs_gap": re.compile(r"\bage\b.{0,80}(retry|gap|interval|2\.?\d? ?s|seconds)|(retry|gap|interval).{0,80}\bage\b|how old|minutes old.{0,60}retr", re.I),
    "D4_onset_order": re.compile(r"(before|preced|predat|earlier than|prior to).{0,60}(deploy|evict|10:1[45])|(deploy|evict\w*).{0,60}(after|later than).{0,40}(drift|double|onset)|"
                                 r"10:0[5-9]|10:10.{0,80}(deploy|evict)", re.I),
}


def classify(h, note_id):
    text = f"{h.get('name', '')} {h.get('reason', '')}"
    name = h.get("name", "")
    if EVICT.search(name) and not TRUE.search(name):
        return "eviction"
    if DEPLOY.search(name) and not TRUE.search(name):
        return "deploy"
    if TRUE.search(name) or (note_id in (h.get("based_on") or []) and not EVICT.search(name)) or (TRUE.search(text) and not EVICT.search(name)):
        return "retry-key"
    return "eviction" if EVICT.search(text) else "deploy" if DEPLOY.search(text) else "other"


def score_position(pos, note_id):
    hyps = [(classify(h, note_id), h.get("status")) for h in pos.get("hypotheses") or []]
    status = lambda cls: next((s for c, s in hyps if c == cls), None)
    dtext = " || ".join(f"{d.get('experiment', '')} {d.get('separates', '')} {d.get('predictions', '')}" for d in pos.get("directive") or [])
    flags = {k: bool(r.search(dtext)) for k, r in D.items()}
    leading = [c for c, s in hyps if s == "leading"]
    return {"true_status": status("retry-key"), "true_live": status("retry-key") in ("leading", "live"), "true_leading": status("retry-key") == "leading",
            "true_demoted": status("retry-key") in ("deprioritised", "refuted"),
            "evict_status": status("eviction"), "herring_demoted": status("eviction") in ("deprioritised", "refuted"),
            "leading": leading[0] if leading else None, **flags, "discriminating": any(flags.values()),
            "n_hyp": len(hyps), "n_dir": len(pos.get("directive") or [])}


def score_judge(ret):
    text = " || ".join((ret or {}).get("gaps") or []) + " " + (ret or {}).get("summary", "")
    flags = {k: bool(r.search(text)) for k, r in D.items()}
    return {"true_status": None, "true_live": bool(TRUE.search(text)), "true_leading": False, "true_demoted": False, "evict_status": None,
            "herring_demoted": bool(re.search(r"evict\w*[^.|]{0,100}(rul(e|ed|es) out|refut|contradict|cannot (explain|be the cause|account)|does not explain|"
                                              r"not the cause|unlikely|predat|(drift|double)[^.|]{0,40}before)|(0 of \d+|no evicted key)[^.|]{0,80}(refut|rul|contradict|against|does not)", text, re.I)),
            "leading": None, **flags, "discriminating": any(flags.values()), "n_hyp": 0, "n_dir": len((ret or {}).get("gaps") or [])}


def routes(dirs):
    """Per trial label: did the agent read target source/log files, and which lanes did it query."""
    out = {}
    for d in dirs:
        for m in Path(d).glob("agent-*.meta.json"):
            lab = json.loads(m.read_text()).get("description")
            src, lanes = set(), set()
            for line in open(str(m)[:-len(".meta.json")] + ".jsonl"):
                try:
                    msg = json.loads(line).get("message")
                except json.JSONDecodeError:
                    continue
                for x in (msg or {}).get("content") if isinstance((msg or {}).get("content"), list) else []:
                    if isinstance(x, dict) and x.get("type") == "tool_use":
                        blob = json.dumps(x.get("input", {}))
                        src.update(re.findall(r"services/(\w+\.py)", blob))
                        if "merged.log" in blob:
                            src.add("merged.log")
                        lanes.update(re.findall(r"--lane (\w+)", blob))
            out[lab] = {"read_target": sorted(src), "lanes_queried": sorted(lanes)}
    return out


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
    rt = routes(a.transcripts)
    rows = []
    for t in trials:
        ret, cell = returns.get(t["id"]), cells[t["cell"]]
        sc = score_judge(ret) if t["role"] == "judge" else score_position(ret or {}, "B-static-0002")
        rows.append({"id": t["id"], "cell": t["cell"], "arm": cell["arm"], "state": cell["variant"], "model_key": t["model_key"], "role": t["role"],
                     "seat": (cell.get("params") or {}).get("persona") or (cell.get("params") or {}).get("lane"),
                     "index": int(t["id"].rsplit("-", 1)[1]), "returned": ret is not None, **sc, **tm.get(t["id"], {}), **rt.get(t["id"], {}),
                     "valid": not tm.get(t["id"], {}).get("contaminated")})
    (run / "scores.json").write_text(json.dumps(rows, indent=1) + "\n")
    ok = [r for r in rows if r["valid"] and r["returned"]]
    print(f"# {a.experiment} / {a.run}: {len(rows)} trials, {len(rows) - len(ok)} invalid or without a return\n")
    print("| arm | state | model | seat | n | true lead live | true lead leading | true lead demoted | herring demoted | D1 same key twice | D2 key trace | D3 age vs gap | D4 onset order | read target | tools | out tok |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    keyf = lambda r: (r["arm"], r["state"], r["model_key"], r["seat"] or "")
    for k in sorted({keyf(r) for r in ok}):
        sel = [r for r in ok if keyf(r) == k]
        n = len(sel)
        f = lambda name: f"{sum(1 for r in sel if r.get(name))}/{n}"
        print(f"| {k[0]} | {k[1]} | {k[2]} | {k[3] or '-'} | {n} | {f('true_live')} | {f('true_leading')} | {f('true_demoted')} | {f('herring_demoted')} | {f('D1_same_key_twice')} "
              f"| {f('D2_key_trace')} | {f('D3_age_vs_gap')} | {f('D4_onset_order')} | {sum(1 for r in sel if r.get('read_target'))}/{n} "
              f"| {sum(r.get('tools', 0) for r in sel) / n:.1f} | {sum(r.get('out', 0) for r in sel) // n} |")
    print("\n| council | state | model | set | leading choices | distinct | union: true live | union: D2 key trace | union: herring demoted | all agree on true lead live | tools (sum) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    sets = collections.defaultdict(list)
    for r in ok:
        if r["arm"] in ("C2", "C3") and r["role"] != "chair":
            sets[(r["arm"], r["state"], r["model_key"], r["index"])].append(r)
    for k in sorted(sets):
        m = sets[k]
        lead = [r["leading"] or "none" for r in m]
        print(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]} ({len(m)} of 3) | {', '.join(lead)} | {len(set(lead))} | {any(r['true_live'] for r in m)} "
              f"| {any(r['D2_key_trace'] for r in m)} | {any(r['herring_demoted'] for r in m)} | {all(r['true_live'] for r in m)} | {sum(r.get('tools', 0) for r in m)} |")


if __name__ == "__main__":
    main()
