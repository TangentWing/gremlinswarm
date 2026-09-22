#!/usr/bin/env python3
"""Summarize one investigation run: models used, agent health, protocol friction.

    tests/run_report.py <transcript dir> [<investigation dir>]

Reports what matters when comparing runs across models: which model actually ran,
agents that produced no structured output, guard interventions, board.py errors,
tool calls vs each role's turn cap, and the judge/refuter outcome.
"""
import collections, glob, json, os, re, sys

CAPS = {"scope": 15, "plan": 12, "investigator": 45, "challenger": 35, "salvage": 25,
        "synthesizer": 25, "judge": 25, "refuter": 40, "strategist": 20, "checkpoint": 20}


def main(tdir, inv=None):
    models, errs, guard, rows = collections.Counter(), collections.Counter(), [], []
    for f in sorted(glob.glob(os.path.join(tdir, "agent-*.jsonl"))):
        meta_path = f[:-len(".jsonl")] + ".meta.json"
        meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        label = meta.get("description", "?")
        role = (meta.get("agentType") or "?").split(":")[-1]
        tools = structured = 0
        for line in open(f):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            if msg.get("model"):
                models[msg["model"]] += 1
            if not isinstance(msg.get("content"), list):
                continue
            for c in msg["content"]:
                if c.get("type") == "tool_use":
                    tools += 1
                    structured += c.get("name") == "StructuredOutput"
                elif c.get("type") == "tool_result":
                    t = json.dumps(c.get("content"))
                    if "investigate guard:" in t:
                        guard.append((label, t[t.find("investigate guard:"):][:130]))
                    for m in re.finditer(r"error: ([^\"\\]{10,110})", t):
                        errs[re.sub(r"\d{2,}|B-\w+-\d+|[A-Za-z0-9_/.-]{25,}", "…", m.group(1)).strip()] += 1
        rows.append((label, role, tools, CAPS.get(role), structured))

    print(f"# {os.path.basename(tdir)}")
    print(f"models: {dict(models) or '(none)'}")
    print(f"agents: {len(rows)}   no structured output: {sum(1 for r in rows if not r[4])}")
    near = [r for r in rows if r[3] and r[2] >= r[3] - 3]
    print(f"at/near turn cap: {len(near)}" + ("".join(f"\n    {r[0]} ({r[1]}) {r[2]}/{r[3]}" for r in near) if near else ""))
    print(f"guard interventions: {len(guard)}" + "".join(f"\n    {l}: {t}" for l, t in guard[:6]))
    print("board.py errors:" + ("".join(f"\n    x{c} {e}" for e, c in errs.most_common(8)) if errs else " none"))
    busiest = sorted(rows, key=lambda r: -r[2])[:5]
    print("busiest agents:" + "".join(f"\n    {r[0]:32} {r[1]:13} {r[2]} calls" for r in busiest))

    if inv:
        for n in sorted(glob.glob(os.path.join(inv, "judge", "round-*.json"))):
            v = json.load(open(n))
            print(f"judge {os.path.basename(n)}: met={v['met']} progress={v['progress']} "
                  f"gaps={len(v.get('gaps', []))}" + (f" REFUTED by {v['refuted']['by']}" if "refuted" in v else ""))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
