#!/usr/bin/env python3
"""Per-agent metrics for one workflow run, from its transcript directory.

Usage: tests/wf_metrics.py <transcript dir> [<transcript dir> ...]
   (the "Transcript dir" printed when the workflow launched:
    ~/.claude/projects/<project>/<session>/subagents/workflows/wf_<id>)

Reports, per agent and in total: tool calls, calls spent reading the prompt pack,
shell word-splitting failures (exit 127 "no such file or directory: python3 ..."),
output tokens, fresh input tokens (uncached + cache writes) and cache reads.
"""
import glob
import json
import os
import re
import sys

SPLIT_FAIL = re.compile(r"no such file or directory: \S+ \S|command not found: \S+ \S")
PROMPT_READ = re.compile(r"/prompts/\w+\.md|/lanes/\w+/lane\.md")


def agent_rows(tdir):
    rows = []
    for f in sorted(glob.glob(os.path.join(tdir, "agent-*.jsonl"))):
        meta_path = f[:-len(".jsonl")] + ".meta.json"
        label = json.load(open(meta_path)).get("description", "?") if os.path.exists(meta_path) else "?"
        r = dict(label=label, tools=0, prompt_reads=0, split_fail=0, out=0, fresh=0, cache=0)
        for line in open(f):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            u = msg.get("usage") or {}
            r["out"] += u.get("output_tokens", 0)
            r["fresh"] += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            r["cache"] += u.get("cache_read_input_tokens", 0)
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if c.get("type") == "tool_use":
                    r["tools"] += 1
                    inp = c.get("input", {})
                    target = inp.get("file_path") or inp.get("command") or ""
                    if c.get("name") == "Read" and PROMPT_READ.search(target):
                        r["prompt_reads"] += 1
                    elif c.get("name") == "Bash" and "cat " in target and PROMPT_READ.search(target):
                        r["prompt_reads"] += 1
                elif c.get("type") == "tool_result" and SPLIT_FAIL.search(json.dumps(c.get("content"))):
                    r["split_fail"] += 1
        rows.append(r)
    return rows


def report(tdir):
    rows = agent_rows(tdir)
    rows.sort(key=lambda r: -r["cache"])
    print(f"\n# {tdir}\n{'agent':38} tools prmpt split    out    fresh    cache")
    for r in rows:
        print(f"{r['label'][:38]:38} {r['tools']:5} {r['prompt_reads']:5} {r['split_fail']:5} "
              f"{r['out']:6} {r['fresh']:8} {r['cache']:8}")
    tot = {k: sum(r[k] for r in rows) for k in ("tools", "prompt_reads", "split_fail", "out", "fresh", "cache")}
    hit = sum(1 for r in rows if r["split_fail"])
    print(f"{'TOTAL (' + str(len(rows)) + ' agents)':38} {tot['tools']:5} {tot['prompt_reads']:5} {tot['split_fail']:5} "
          f"{tot['out']:6} {tot['fresh']:8} {tot['cache']:8}")
    print(f"agents hitting word-splitting failures: {hit}/{len(rows)}")
    return tot


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for d in sys.argv[1:]:
        report(os.path.expanduser(d))
