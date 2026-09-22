#!/usr/bin/env python3
"""Hook guard for investigate workflow agents. Stdlib only.

    guard.py pretool   PreToolUse: Edit/Write only inside the investigation directory or the
                       manifest's `writable` paths; Bash commands checked against `safety_deny`.
    guard.py substop   SubagentStop: an investigator may not stop before recording its result
                       (task finish, or task item for a sweep item); a judge may not stop before
                       saving its verdict.

It acts only on agents whose own transcript starts with an investigation prompt
("Investigation directory: ..."), so it is a no-op for every other session and agent.
The workflow harness frames that prompt: it indents the script's text, and when a user request
triggered the run it relays that request as a separate user turn first. So the opening user
turns are read together, and the prompt's lines are matched with any indentation.
Blocking uses exit code 2 with the reason on stderr (fed back to the agent).
Fails open: if the context can't be resolved, the call is allowed.

This is a seatbelt, not a sandbox: shell redirection can still write files. Keep the
manifest's safety rules and permission allowlist as the primary controls.
"""
import glob
import json
import os
import re
import sys

ROLE_RE = re.compile(r"You are the (\w+) in a structured investigation")
PATTERNS = {
    "inv": re.compile(r"^[ \t]*Investigation directory: (.+)$", re.M),
    "task": re.compile(r"^[ \t]*Task: (\S+)", re.M),
    "item": re.compile(r"^[ \t]*SWEEP ITEM (\d+)/(\d+)", re.M),
    "round": re.compile(r"^[ \t]*Round: (\d+)", re.M),
    "review": re.compile(r"^[ \t]*Review task (\S+) .*review (\d+)\)", re.M),
}
TASK_ID_RE = re.compile(r"^(?P<lane>[a-z][a-z0-9_]*)-r\d{2,}-\d{2,}$")


def first_prompt(transcript: str) -> str:
    """Text of the user turns that open a JSONL transcript (everything before the agent's first reply)."""
    parts = []
    with open(transcript) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            if rec.get("type") != "user" and msg.get("role") != "user":
                if parts:
                    break
                continue
            content = msg.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts.append("\n".join(c.get("text", "") for c in content if isinstance(c, dict)))
    return "\n".join(parts)


def agent_transcript(data: dict) -> str | None:
    for key in ("agent_transcript_path", "transcript_path"):
        p = data.get(key)
        if p and os.path.basename(p).startswith("agent-") and os.path.exists(p):
            return p
    aid, tp = data.get("agent_id"), data.get("transcript_path")
    if aid and tp:
        hits = glob.glob(os.path.join(tp[:-len(".jsonl")] if tp.endswith(".jsonl") else tp,
                                      "subagents", "**", f"agent-{aid}.jsonl"), recursive=True)
        if hits:
            return hits[0]
    return None


def context(data: dict) -> dict | None:
    if not data.get("agent_id"):
        return None  # main conversation, not a subagent
    tp = agent_transcript(data)
    if not tp:
        return None
    text = first_prompt(tp)
    inv = PATTERNS["inv"].search(text)
    role = ROLE_RE.search(text)
    if not inv or not role:
        return None
    ctx = {"inv": inv.group(1).strip(), "role": role.group(1).lower()}
    for k in ("task", "round"):
        m = PATTERNS[k].search(text)
        ctx[k] = m.group(1) if m else None
    m = PATTERNS["item"].search(text)
    ctx["item"] = int(m.group(1)) if m else None
    m = PATTERNS["review"].search(text)
    ctx["review"] = int(m.group(2)) if m else None
    if m and not ctx["task"]:
        ctx["task"] = m.group(1)  # a challenger's prompt names its task on the review line
    ctx["manifest"] = load(os.path.join(ctx["inv"], "manifest.json")) or {}
    return ctx


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def under(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def block(reason: str):
    print(reason, file=sys.stderr)
    sys.exit(2)


def pretool(data: dict, ctx: dict):
    tool, ti = data.get("tool_name"), data.get("tool_input") or {}
    m = ctx["manifest"]
    if ctx["role"] == "strategist":
        # x3: a strategist that can read the target does the investigators' work instead of directing it.
        # Everything it needs is in the investigation directory, through the board CLI.
        board = os.path.join(ctx["inv"], "bin", "board.py")
        if tool == "Bash" and "board.py" not in (ti.get("command") or ""):
            block(f"investigate guard: the strategist works from the boards only. Run the board CLI ({board}); "
                  f"do not read source, logs or hosts — that is the investigators' job.")
        if tool in ("Read", "Glob", "Grep"):
            target = ti.get("file_path") or ti.get("path") or ""
            target = os.path.join(data.get("cwd") or os.getcwd(), os.path.expanduser(target)) if target else ctx["inv"]
            if not under(target, ctx["inv"]):
                block(f"investigate guard: the strategist reads nothing outside the investigation directory "
                      f"({ctx['inv']}). Use `query --id ... --format full` for board entries; targets are off limits.")
    if tool in ("Edit", "Write", "NotebookEdit"):
        target = ti.get("file_path") or ti.get("notebook_path") or ""
        if not target:
            return
        target = os.path.join(data.get("cwd") or os.getcwd(), os.path.expanduser(target))
        roots = [ctx["inv"]] + [os.path.expanduser(p) for p in m.get("writable", [])]
        if data.get("scratchpad_dir"):
            roots.append(data["scratchpad_dir"])  # the session's own temp space
        if not any(under(target, r) for r in roots):
            block(f"investigate guard: {tool} to {target} is outside this investigation. Write artifacts in your task "
                  f"directory under {ctx['inv']}/lanes/<lane>/tasks/<id>/"
                  + (f" or in the manifest's writable paths ({', '.join(m.get('writable', []))})" if m.get("writable") else "")
                  + "; never modify the targets under investigation.")
    elif tool == "Bash":
        cmd = ti.get("command") or ""
        for pat in m.get("safety_deny", []):
            try:
                hit = re.search(pat, cmd)
            except re.error:
                continue
            if hit:
                block(f"investigate guard: this command matches the investigation's safety rule /{pat}/ "
                      f"(matched '{hit.group(0)}'). Re-read the manifest's safety rules and choose a permitted approach; "
                      f"if the investigation truly needs this, `ask` the human.")


def substop(data: dict, ctx: dict):
    if data.get("stop_hook_active"):
        return  # already continued once because of us; never loop
    inv, role = ctx["inv"], ctx["role"]
    board = os.path.join(inv, "bin", "board.py")
    if role == "investigator" and ctx["task"]:
        m = TASK_ID_RE.match(ctx["task"])
        if not m:
            return
        td = os.path.join(inv, "lanes", m.group("lane"), "tasks", ctx["task"])
        if ctx["item"]:
            if not os.path.exists(os.path.join(td, "items", f"{ctx['item']:03d}.json")):
                block(f"investigate guard: record this sweep item before stopping: {board} task item --id {ctx['task']} "
                      f"--n {ctx['item']} --status done|partial|failed|blocked --summary \"...\" --as <you>")
            return
        plan = load(os.path.join(inv, "lanes", m.group("lane"), "plan.json")) or {}
        status = next((t.get("status") for t in plan.get("tasks", []) if t.get("id") == ctx["task"]), None)
        if status in (None, "queued", "running"):
            block(f"investigate guard: task {ctx['task']} is still '{status or 'not started'}'. Record your result before "
                  f"stopping: {board} task finish --id {ctx['task']} --status done|partial|failed|blocked --summary \"...\" "
                  f"--as <you> (use status failed or blocked if you could not complete it).")
    elif role == "judge" and ctx["round"]:
        if not os.path.exists(os.path.join(inv, "judge", f"round-{int(ctx['round']):02d}.json")):
            block(f"investigate guard: save your verdict before stopping: {board} judge save --round {ctx['round']} "
                  f"--as judge <<'EOF' {{\"met\":..,\"progress\":..,\"gaps\":[..],\"summary\":\"..\"}} EOF")
    elif role == "challenger" and ctx["task"] and ctx["review"]:
        # x0 confirm1: a challenger that dies at its cap leaves no review; the task then reads as never reviewed.
        m = TASK_ID_RE.match(ctx["task"])
        if not m:
            return
        td = os.path.join(inv, "lanes", m.group("lane"), "tasks", ctx["task"])
        # reviews are numbered across attempts; "review N" in the prompt is the Nth review this round
        this_round = [r for r in (load(p) or {} for p in glob.glob(os.path.join(td, "review-*.json")))
                      if str(r.get("round")) == str(ctx["round"])]
        if len(this_round) < ctx["review"]:
            block(f"investigate guard: record the verdict you can support now before stopping: {board} task review "
                  f"--id {ctx['task']} --verdict accept|revise|redo --summary \"...\" [--objection \"what you could not "
                  f"check\"] --as <you>. No review on file means the task counts as unverified.")


def debug_log(mode: str, data: dict, ctx) -> None:
    """When hooks/DEBUG exists next to this file, append one line per hook call: what the harness sent and what
    was resolved. E6: PreToolUse fired for workflow agents, SubagentStop never did — this is how to find out why."""
    here = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(os.path.join(here, "DEBUG")):
        return
    try:
        with open(os.path.join(here, "guard.log"), "a") as f:
            f.write(json.dumps({"mode": mode, "event": data.get("hook_event_name"), "keys": sorted(data.keys()),
                                "agent_id": data.get("agent_id"), "agent_type": data.get("agent_type"),
                                "transcript_path": data.get("transcript_path"), "agent_transcript_path": data.get("agent_transcript_path"),
                                "resolved": {k: ctx[k] for k in ("inv", "role", "task", "round")} if ctx else None}) + "\n")
    except OSError:
        pass


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    ctx = context(data)
    debug_log(mode, data, ctx)
    if not ctx:
        return
    if mode == "pretool":
        pretool(data, ctx)
    elif mode == "substop":
        substop(data, ctx)


if __name__ == "__main__":
    main()
