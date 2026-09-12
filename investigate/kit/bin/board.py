#!/usr/bin/env python3
"""board.py — the investigation protocol CLI.

Every agent reads and writes shared investigation state through this tool:
blackboards, mailboxes, plans, tasks, steering, judge verdicts. It gives
locked appends, validation, append-only history and plan archiving.

The investigation root is the parent of this file's directory (bin/..), or
--inv PATH, or $INV_DIR. Stdlib only.

Quick reference (all commands accept --as AUTHOR and --inv PATH):
  status [--json]                     overview: round, lanes, mail, questions, leftovers
  post --lane L|shared --kind K --subject S --body B [--tags a,b] [--refs x,y]
       [--confidence low|med|high] [--supersedes id,id]
  amend --id ID --set key=value [--set ...] [--note N]
  query [--lane L|shared|all] [--id ID,..] [--kind K] [--tag T] [--status S] [--author A]
        [--grep TEXT] [--round N] [--include-superseded] [--format brief|full|json] [--limit N]
  mail send --to L --subject S --body B [--type T] [--re ID] [--priority high]
  mail list --lane L [--all] [--format brief|full|json]     mail show --id ID
  mail set --id ID --status accepted|declined|done [--note N]
  mail reply --id ID --body B [--status done|declined|accepted]
  ask --question Q [--context C] [--lane L]
  questions [--all]
  answer --id ID --body B
  steer add --body B [--lane L]      steer list [--since-round N]
  plan show --lane L [--format brief|json]
  plan save --lane L [--file F]      (JSON on stdin: {"tasks":[...], "drop":[ids], "notes":"..."})
  task start --id ID                  task show --id ID
  task note --id ID --text T
  task started --id ID --what W --stop CMD      task stopped --id ID --ref S1
  task finish --id ID --status done|partial|failed|blocked --summary S
              [--board-ids ...] [--artifacts ...] [--details-file F]
  task review --id ID --verdict accept|revise|redo --summary S [--objection O ...]
  worklog --lane L [--tail N]
  leftovers [--lane L]
  write --path REL [--append]         (stdin → file inside the investigation dir)
  judge save --round N [--file F]     judge show [--round N]     judge refute --round N --objection O ...
  task item --id ID --n K --status S --summary S [--board-ids ...]   (one sweep item's result)
  segment close --start N --end M --reason R
  validate | scaffold | wf-args [--rounds N]
  archetypes [--show NAME]            lane archetypes available to this investigation
  probe [--lane L] [--resource R]     run resources' non-destructive `check` commands
  brief --role R [--lane L] [--task T] [--round N]   everything an agent needs, in one call
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LANE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TASK_ID_RE = re.compile(r"^(?P<lane>[a-z][a-z0-9_]*)-r\d{2,}-\d{2,}$")
ENTRY_ID_RE = re.compile(r"^(?P<prefix>[BM])-(?P<lane>[a-z][a-z0-9_]*)-(?P<n>\d+)$")

BOARD_KINDS = {"finding", "hypothesis", "evidence", "question", "contradiction", "note",
               "question-for-human"}
BOARD_STATUSES = {"open", "confirmed", "refuted", "irrelevant", "answered"}
CONFIDENCE = {"low", "med", "high"}
MAIL_TYPES = {"query", "task-request", "reply", "notice", "failure", "steering"}
MAIL_STATUSES = {"new", "accepted", "declined", "done"}
TASK_KINDS = {"read", "trace", "experiment", "endpoint", "debug", "analysis", "cleanup", "sweep", "other"}
TASK_STATUSES = {"queued", "running", "done", "partial", "failed", "blocked", "needs_redo", "dropped"}
TERMINAL = {"done", "partial", "failed", "blocked", "needs_redo", "dropped"}
REQUEUE_FROM = {"failed", "partial", "blocked", "needs_redo", "running"}
FINISH_STATUSES = {"done", "partial", "failed", "blocked"}
VERIFY = {"none", "light", "adversarial"}
SIZES = {"short", "long"}
VERDICTS = {"accept", "revise", "redo"}
ROLES = ["scope", "plan", "investigator", "challenger", "salvage", "synthesizer", "judge", "refuter", "checkpoint"]

DEFAULT_BUDGET = {
    "max_concurrent": 4,
    "rounds_per_checkpoint": 2,
    "max_rounds": 8,
    "max_agents_per_segment": 60,
    "max_tasks_per_lane_round": 3,
    "verify_rounds": 2,
    "max_children": 2,
    "stall_rounds": 2,
    "max_sweep_items": 12,
}


class BoardError(Exception):
    pass


# ---------------------------------------------------------------- basics

def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg: str, code: int = 2):
    raise BoardError(msg)


def inv_root(args) -> Path:
    p = getattr(args, "inv", None) or os.environ.get("INV_DIR")
    root = Path(p).expanduser().resolve() if p else Path(__file__).resolve().parent.parent
    if not (root / "manifest.json").exists():
        die(f"no manifest.json in {root} (pass --inv PATH or set INV_DIR)")
    return root


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.parent / f".{path.name}.lock"
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"warning: {path}:{i} is not valid JSON; skipped", file=sys.stderr)
    return out


def append_jsonl(path: Path, rec: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def csv(s: str | None) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


def manifest(root: Path) -> dict:
    return load_json(root / "manifest.json")


def state(root: Path) -> dict:
    return load_json(root / "state.json", {"round": 1, "status": "active", "segments": []})


def current_round(root: Path) -> int:
    return int(state(root).get("round", 1))


def lane_names(root: Path) -> list[str]:
    return [l["name"] for l in manifest(root).get("lanes", [])]


def check_lane(root: Path, lane: str, allow_shared=False) -> str:
    if allow_shared and lane == "shared":
        return lane
    if lane not in lane_names(root):
        die(f"unknown lane '{lane}' (lanes: {', '.join(lane_names(root))})")
    return lane


def author(args) -> str:
    return getattr(args, "author", None) or os.environ.get("BOARD_AUTHOR") or "unknown"


def board_path(root: Path, lane: str) -> Path:
    return root / "shared" / "board.jsonl" if lane == "shared" else root / "lanes" / lane / "board.jsonl"


def mail_path(root: Path, lane: str) -> Path:
    return root / "mail" / f"{lane}.jsonl"


def lane_of_task(task_id: str) -> str:
    m = TASK_ID_RE.match(task_id)
    if not m:
        die(f"bad task id '{task_id}' (expected <lane>-rNN-NN)")
    return m.group("lane")


def lane_of_entry(entry_id: str) -> tuple[str, str]:
    m = ENTRY_ID_RE.match(entry_id)
    if not m:
        die(f"bad id '{entry_id}' (expected B-<lane>-NNNN or M-<lane>-NNNN)")
    return m.group("prefix"), m.group("lane")


def worklog(root: Path, lane: str, event: str, who: str, **fields) -> None:
    path = root / "lanes" / lane / "worklog.jsonl"
    with locked(path):
        append_jsonl(path, {"ts": now(), "round": current_round(root), "author": who,
                            "event": event, **fields})


# ---------------------------------------------------------------- append-only logs

def materialize(records: list[dict]) -> tuple[dict, set]:
    """Apply amendments; return (entries by id in order, superseded ids)."""
    entries: dict[str, dict] = {}
    superseded: set[str] = set()
    for r in records:
        if r.get("op") == "amend":
            t = entries.get(r.get("target"))
            if t is not None:
                t.update(r.get("set", {}))
                t.setdefault("amendments", []).append(
                    {k: r[k] for k in ("ts", "by", "note", "set") if k in r})
            continue
        entries[r["id"]] = dict(r)
        superseded.update(r.get("supersedes") or [])
    return entries, superseded


def next_id(records: list[dict], prefix: str, lane: str) -> str:
    n = sum(1 for r in records if r.get("op") != "amend") + 1
    return f"{prefix}-{lane}-{n:04d}"


def append_entry(path: Path, prefix: str, lane: str, rec: dict) -> str:
    with locked(path):
        records = read_jsonl(path)
        rec = {"id": next_id(records, prefix, lane), **rec}
        append_jsonl(path, rec)
    return rec["id"]


def amend(path: Path, target: str, sets: dict, who: str, note: str | None = None) -> None:
    with locked(path):
        entries, _ = materialize(read_jsonl(path))
        if target not in entries:
            die(f"{target} not found in {path}")
        rec = {"op": "amend", "target": target, "set": sets, "by": who, "ts": now()}
        if note:
            rec["note"] = note
        append_jsonl(path, rec)


def fmt_entry(e: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(e, ensure_ascii=False)
    meta = "/".join(x for x in (e.get("kind") or e.get("type"), e.get("confidence") or e.get("priority"),
                                  e.get("status")) if x)
    head = f"{e['id']} [{meta}] {e.get('subject', '')}"
    extra = []
    if e.get("from"):
        extra.append(f"from {e['from']}")
    if e.get("tags"):
        extra.append("#" + " #".join(e["tags"]))
    if e.get("refs"):
        extra.append("refs " + ",".join(e["refs"]))
    if e.get("re"):
        extra.append(f"re {e['re']}")
    extra.append(e.get("author") or "")
    if fmt == "brief":
        body = (e.get("body") or "").replace("\n", " ")
        if len(body) > 160:
            body = body[:157] + "..."
        return f"{head}  ({'; '.join(x for x in extra if x)})\n    {body}"
    lines = [head, f"  {'; '.join(x for x in extra if x)}  r{e.get('round', '?')} {e.get('ts', '')}"]
    lines += ["  " + l for l in (e.get("body") or "").splitlines()]
    if e.get("supersedes"):
        lines.append(f"  supersedes: {', '.join(e['supersedes'])}")
    for a in e.get("amendments", []):
        lines.append(f"  amended {a.get('ts', '')} by {a.get('by', '')}: {a.get('set')} {a.get('note', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------- manifest

def validate_manifest(m: dict, root: Path | None = None) -> list[str]:
    errs = []
    archetypes = archetype_files(root) if root else {}
    for l in m.get("lanes", []):
        a = l.get("archetype")
        if a and root and a not in archetypes:
            errs.append(f"lane '{l.get('name')}' uses unknown archetype '{a}' (have: {', '.join(archetypes) or 'none'})")
        elif a and root:
            errs += archetype_errors(archetypes[a])
    for r in m.get("resources", []):
        if "check" in r and not isinstance(r["check"], str):
            errs.append(f"resource '{r.get('name')}': check must be a shell command string")
    if not isinstance(m.get("writable", []), list) or not all(isinstance(p, str) for p in m.get("writable", [])):
        errs.append("writable must be a list of paths")
    for pat in m.get("safety_deny", []):
        try:
            re.compile(pat)
        except (re.error, TypeError) as e:
            errs.append(f"safety_deny pattern {pat!r} is not a valid regex: {e}")
    for k in ("slug", "goal", "criteria", "lanes", "resources"):
        if k not in m:
            errs.append(f"missing '{k}'")
    res_names = set()
    for r in m.get("resources", []):
        if "name" not in r:
            errs.append(f"resource without name: {r}")
            continue
        if r["name"] in res_names:
            errs.append(f"duplicate resource '{r['name']}'")
        res_names.add(r["name"])
    seen = set()
    for l in m.get("lanes", []):
        n = l.get("name", "")
        if not LANE_RE.match(n) or n == "shared":
            errs.append(f"bad lane name '{n}' (lowercase [a-z0-9_], not 'shared')")
        if n in seen:
            errs.append(f"duplicate lane '{n}'")
        seen.add(n)
        if not l.get("mandate"):
            errs.append(f"lane '{n}' has no mandate")
        for r in l.get("resources", []):
            if r not in res_names:
                errs.append(f"lane '{n}' references unknown resource '{r}'")
        if l.get("verify_default") and l["verify_default"] not in VERIFY:
            errs.append(f"lane '{n}' verify_default must be one of {sorted(VERIFY)}")
    if not m.get("criteria", {}).get("success"):
        errs.append("criteria.success must list at least one success criterion")
    b = {**DEFAULT_BUDGET, **m.get("budget", {})}
    for k, v in b.items():
        if not isinstance(v, int) or v < 0:
            errs.append(f"budget.{k} must be a non-negative integer")
    if b["max_concurrent"] < 1:
        errs.append("budget.max_concurrent must be >= 1")
    for sect in ("models", "effort", "agent_types"):
        for role in m.get(sect, {}) or {}:
            if role not in ROLES:
                errs.append(f"{sect}.{role}: unknown role (roles: {', '.join(ROLES)})")
    return errs


# ---------------------------------------------------------------- archetypes

ARCH_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
ARCH_REQUIRED = ("name", "summary", "use_when", "resource_kinds", "verify_default", "task_kinds")


def parse_archetype(path: Path) -> tuple[dict, str]:
    """Split an archetype file into (frontmatter dict, body). Frontmatter is `key: value`
    lines; `[a, b]` values become lists."""
    text = path.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise BoardError(f"{path.name}: missing '---' frontmatter block")
    fm_text, body = text[4:].split("\n---\n", 1)
    fm = {}
    for line in fm_text.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise BoardError(f"{path.name}: bad frontmatter line '{line}'")
        k, v = (s.strip() for s in line.split(":", 1))
        fm[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()] if v.startswith("[") and v.endswith("]") else v
    return fm, body


def archetype_errors(path: Path) -> list[str]:
    try:
        fm, body = parse_archetype(path)
    except BoardError as e:
        return [str(e)]
    errs = [f"{path.name}: missing '{k}'" for k in ARCH_REQUIRED if not fm.get(k)]
    if fm.get("name") and fm["name"] != path.stem:
        errs.append(f"{path.name}: name '{fm['name']}' must match the file name")
    if not ARCH_NAME_RE.match(path.stem):
        errs.append(f"{path.name}: file name must match [a-z][a-z0-9-]*")
    if fm.get("verify_default") and fm["verify_default"] not in VERIFY:
        errs.append(f"{path.name}: verify_default must be one of {sorted(VERIFY)}")
    for k in ("task_kinds",):
        bad = [x for x in fm.get(k, []) if x not in TASK_KINDS]
        if bad:
            errs.append(f"{path.name}: unknown {k} {bad}")
    if "{{mandate}}" not in body:
        errs.append(f"{path.name}: body should contain {{{{mandate}}}}")
    return errs


def archetype_files(root: Path) -> dict[str, Path]:
    d = root / "archetypes"
    return {p.stem: p for p in sorted(d.glob("*.md")) if not p.name.startswith(("_", "README"))} if d.exists() else {}


def lane_verify_default(root: Path | None, lane: dict) -> str:
    if lane.get("verify_default"):
        return lane["verify_default"]
    if root and lane.get("archetype") in archetype_files(root):
        return parse_archetype(archetype_files(root)[lane["archetype"]])[0].get("verify_default", "light")
    return "light"


def render_lane_md(root: Path, m: dict, lane: dict) -> str:
    res_by_name = {r["name"]: r for r in m.get("resources", [])}
    res_lines = []
    for name in lane.get("resources", []):
        r = res_by_name.get(name, {})
        res_lines.append(f"- `{name}` [{r.get('kind', '?')}{', EXCLUSIVE — only via a task claim' if r.get('exclusive') else ''}]"
                         f" access: {r.get('access', '')}{' — ' + r['notes'] if r.get('notes') else ''}")
    subs = {"lane": lane["name"], "mandate": lane["mandate"],
            "resources": "\n".join(res_lines) or "(none)",
            "evidence_standard": lane.get("evidence_standard") or m.get("criteria", {}).get("evidence_standard", "See manifest criteria."),
            "verify_default": lane_verify_default(root, lane)}
    if lane.get("archetype"):
        _, body = parse_archetype(archetype_files(root)[lane["archetype"]])
        for k, v in subs.items():
            body = body.replace("{{" + k + "}}", v)
        return body.lstrip("\n")
    return (f"# Lane: {subs['lane']}\n\n## Mandate\n{subs['mandate']}\n\n## Resources\n{subs['resources']}\n\n"
            f"## Evidence standard\n{subs['evidence_standard']}\n\n## Default verify level\n{subs['verify_default']}\n")


def cmd_archetypes(args):
    try:
        root = inv_root(args)
    except BoardError:  # browsing the kit itself (e.g. during setup), no investigation yet
        root = Path(__file__).resolve().parent.parent
    files = archetype_files(root)
    if not files:
        die(f"no archetypes in {root / 'archetypes'}")
    if args.show:
        if args.show not in files:
            die(f"unknown archetype '{args.show}' (have: {', '.join(files)})")
        print(files[args.show].read_text())
        return
    errs = [e for p in files.values() for e in archetype_errors(p)]
    for name, p in files.items():
        if archetype_errors(p):
            continue
        fm, _ = parse_archetype(p)
        print(f"{name:18} {fm['summary']}\n{'':18} use when: {'; '.join(fm['use_when'])}\n"
              f"{'':18} resources: {', '.join(fm['resource_kinds'])} · verify: {fm['verify_default']}")
    if errs:
        print("INVALID archetypes:\n  " + "\n  ".join(errs))
        sys.exit(1)


# ---------------------------------------------------------------- resource probes

def cmd_probe(args):
    """Run each resource's `check` command (non-destructive access check)."""
    import subprocess
    root = inv_root(args)
    m = manifest(root)
    names = [r["name"] for r in m.get("resources", [])]
    if args.lane:
        lane = next((l for l in m["lanes"] if l["name"] == check_lane(root, args.lane)), None)
        names = lane.get("resources", [])
    if args.resource:
        names = [args.resource]
    failed = 0
    for r in (r for r in m.get("resources", []) if r["name"] in names):
        chk = r.get("check")
        if not chk:
            print(f"?    {r['name']}: no check defined")
            continue
        try:
            p = subprocess.run(chk, shell=True, capture_output=True, text=True, timeout=args.timeout)
            out = (p.stdout + p.stderr).strip().splitlines()
            ok = p.returncode == 0
            print(f"{'ok  ' if ok else 'FAIL'} {r['name']}: exit {p.returncode}" + (f" — {out[-1][:160]}" if out else ""))
        except subprocess.TimeoutExpired:
            ok = False
            print(f"FAIL {r['name']}: timed out after {args.timeout}s")
        failed += not ok
    if failed:
        sys.exit(1)


def cmd_validate(args):
    root = inv_root(args)
    errs = validate_manifest(manifest(root), root)
    if errs:
        print("manifest INVALID:\n  " + "\n  ".join(errs))
        sys.exit(1)
    print("manifest OK")


def cmd_scaffold(args):
    root = inv_root(args)
    m = manifest(root)
    errs = validate_manifest(m, root)
    if errs:
        die("manifest invalid, fix first:\n  " + "\n  ".join(errs))
    for d in ("shared", "judge", "mail", "lanes"):
        (root / d).mkdir(exist_ok=True)
    (root / "shared" / "board.jsonl").touch()
    (root / "steering.jsonl").touch()
    for l in m["lanes"]:
        ld = root / "lanes" / l["name"]
        for sub in ("archive", "scope", "tasks"):
            (ld / sub).mkdir(parents=True, exist_ok=True)
        for f in ("board.jsonl", "worklog.jsonl"):
            (ld / f).touch()
        (root / "mail" / f"{l['name']}.jsonl").touch()
        if not (ld / "plan.json").exists():
            write_json(ld / "plan.json", {"lane": l["name"], "version": 0, "round": 0, "tasks": [], "notes": ""})
        if not (ld / "lane.md").exists():
            (ld / "lane.md").write_text(render_lane_md(root, m, l))
    if not (root / "state.json").exists():
        write_json(root / "state.json", {"round": 1, "status": "active", "segments": []})
    print(f"scaffolded {root} with lanes: {', '.join(lane_names(root))}")


# ---------------------------------------------------------------- board

def cmd_post(args):
    root = inv_root(args)
    lane = check_lane(root, args.lane, allow_shared=True)
    if args.kind not in BOARD_KINDS:
        die(f"--kind must be one of {sorted(BOARD_KINDS)}")
    if args.confidence and args.confidence not in CONFIDENCE:
        die(f"--confidence must be one of {sorted(CONFIDENCE)}")
    status = args.status or "open"
    if status not in BOARD_STATUSES:
        die(f"--status must be one of {sorted(BOARD_STATUSES)}")
    rec = {"ts": now(), "round": current_round(root), "author": author(args), "lane": lane,
           "kind": args.kind, "subject": args.subject, "body": read_body(args),
           "tags": csv(args.tags), "refs": csv(args.refs), "status": status}
    if args.confidence:
        rec["confidence"] = args.confidence
    if args.supersedes:
        rec["supersedes"] = csv(args.supersedes)
    print(append_entry(board_path(root, lane), "B", lane, rec))


def read_body(args) -> str:
    if getattr(args, "body", None) == "-":
        return sys.stdin.read().strip()
    return args.body or ""


def parse_sets(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            die(f"--set expects key=value, got '{p}'")
        k, v = p.split("=", 1)
        if k in ("id", "op", "supersedes"):
            die(f"cannot amend '{k}'")
        if k == "status" and v not in BOARD_STATUSES | MAIL_STATUSES:
            die(f"bad status '{v}'")
        out[k] = v
    return out


def cmd_amend(args):
    root = inv_root(args)
    prefix, lane = lane_of_entry(args.id)
    path = board_path(root, lane) if prefix == "B" else mail_path(root, lane)
    sets = parse_sets(args.set)
    if not sets:
        die("nothing to amend (use --set key=value)")
    amend(path, args.id, sets, author(args), args.note)
    print(f"amended {args.id}: {sets}")


def select_entries(root: Path, lanes: list[str], args) -> list[dict]:
    # supersession crosses files (a shared entry typically supersedes lane entries),
    # so collect it from every board before filtering the requested ones
    boards = {l: materialize(read_jsonl(board_path(root, l))) for l in ["shared"] + lane_names(root)}
    sup = set().union(*(s for _, s in boards.values()))
    out = []
    for lane in lanes:
        entries, _ = boards[lane]
        for e in entries.values():
            if e["id"] in sup and not args.include_superseded:
                continue
            if args.id and e["id"] not in csv(args.id):
                continue
            if args.kind and e.get("kind") != args.kind:
                continue
            if args.tag and args.tag not in e.get("tags", []):
                continue
            if args.status and e.get("status") != args.status:
                continue
            if args.by_author and not (e.get("author") or "").startswith(args.by_author):
                continue
            if args.round is not None and e.get("round") != args.round:
                continue
            if args.grep and args.grep.lower() not in json.dumps(e, ensure_ascii=False).lower():
                continue
            out.append(e)
    out.sort(key=lambda e: e.get("ts", ""))
    return out


def cmd_query(args):
    root = inv_root(args)
    lane = args.lane or "all"
    lanes = ["shared"] + lane_names(root) if lane == "all" else [check_lane(root, lane, allow_shared=True)]
    rows = select_entries(root, lanes, args)
    if args.limit:
        rows = rows[-args.limit:]
    if not rows:
        print("(no entries)")
        return
    print("\n".join(fmt_entry(e, args.format) for e in rows))


# ---------------------------------------------------------------- mail

def cmd_mail(args):
    root = inv_root(args)
    if args.mail_cmd == "send":
        to = args.to if args.to in lane_names(root) else "skunkworks" if "skunkworks" in lane_names(root) else None
        if to is None:
            die(f"unknown lane '{args.to}' and no skunkworks lane to route to")
        typ = args.type or "query"
        if typ not in MAIL_TYPES:
            die(f"--type must be one of {sorted(MAIL_TYPES)}")
        rec = {"ts": now(), "round": current_round(root), "author": author(args),
               "from": args.sender or author(args).split("/")[0], "to": to, "type": typ,
               "subject": args.subject, "body": read_body(args), "re": args.re,
               "priority": args.priority or "normal", "status": "new"}
        if to != args.to:
            rec["body"] = f"[rerouted: addressed to unknown lane '{args.to}']\n" + rec["body"]
        print(append_entry(mail_path(root, to), "M", to, rec))
    elif args.mail_cmd == "list":
        lane = check_lane(root, args.lane)
        entries, _ = materialize(read_jsonl(mail_path(root, lane)))
        rows = [e for e in entries.values() if args.all or e.get("status") in ("new", "accepted")]
        print("\n".join(fmt_entry(e, args.format) for e in rows) if rows else "(no mail)")
    elif args.mail_cmd == "show":
        _, lane = lane_of_entry(args.id)
        entries, _ = materialize(read_jsonl(mail_path(root, lane)))
        e = entries.get(args.id) or die(f"{args.id} not found in {lane}'s mailbox")
        print(fmt_entry(e, "full"))
    elif args.mail_cmd == "set":
        if args.status not in MAIL_STATUSES:
            die(f"--status must be one of {sorted(MAIL_STATUSES)}")
        _, lane = lane_of_entry(args.id)
        amend(mail_path(root, lane), args.id, {"status": args.status}, author(args), args.note)
        print(f"{args.id} -> {args.status}")
    elif args.mail_cmd == "reply":
        _, lane = lane_of_entry(args.id)
        entries, _ = materialize(read_jsonl(mail_path(root, lane)))
        orig = entries.get(args.id) or die(f"{args.id} not found")
        status = args.status or "done"
        if status not in MAIL_STATUSES:
            die(f"--status must be one of {sorted(MAIL_STATUSES)}")
        amend(mail_path(root, lane), args.id, {"status": status}, author(args), "replied")
        back = orig.get("from")
        if back in lane_names(root):
            rec = {"ts": now(), "round": current_round(root), "author": author(args), "from": lane,
                   "to": back, "type": "reply", "subject": "Re: " + orig.get("subject", ""),
                   "body": read_body(args), "re": args.id, "priority": "normal", "status": "new"}
            print(append_entry(mail_path(root, back), "M", back, rec))
        else:
            print(f"{args.id} -> {status} (sender '{back}' has no mailbox; reply recorded as status only)")


# ---------------------------------------------------------------- human questions & steering

def cmd_ask(args):
    root = inv_root(args)
    lane = args.lane or author(args).split("/")[0]
    rec = {"ts": now(), "round": current_round(root), "author": author(args), "lane": "shared",
           "kind": "question-for-human", "subject": args.question, "body": args.context or "",
           "tags": [lane] if lane in lane_names(root) else [], "refs": [], "status": "open",
           "asked_by_lane": lane}
    print(append_entry(board_path(root, "shared"), "B", "shared", rec))


def open_questions(root: Path, include_all=False) -> list[dict]:
    entries, sup = materialize(read_jsonl(board_path(root, "shared")))
    return [e for e in entries.values() if e.get("kind") == "question-for-human" and e["id"] not in sup
            and (include_all or e.get("status") == "open")]


def cmd_questions(args):
    root = inv_root(args)
    qs = open_questions(root, args.all)
    if not qs:
        print("(no open questions for the human)")
        return
    for q in qs:
        print(f"{q['id']} [{q.get('status')}] from {q.get('author')} (r{q.get('round')})\n  Q: {q['subject']}")
        if q.get("body"):
            print("  context: " + q["body"].replace("\n", "\n           "))
        if q.get("answer"):
            print(f"  A: {q['answer']}")


def cmd_answer(args):
    root = inv_root(args)
    body = read_body(args)
    path = board_path(root, "shared")
    entries, _ = materialize(read_jsonl(path))
    q = entries.get(args.id) or die(f"{args.id} not found")
    amend(path, args.id, {"status": "answered", "answer": body},
          "human" if author(args) == "unknown" else author(args))
    add_steering(root, f"Answer to {args.id} ({q['subject']}): {body}", q.get("asked_by_lane"), "human")
    lane = q.get("asked_by_lane")
    if lane in lane_names(root):
        rec = {"ts": now(), "round": current_round(root), "author": "human", "from": "human", "to": lane,
               "type": "reply", "subject": "Human answered: " + q["subject"], "body": body,
               "re": args.id, "priority": "high", "status": "new"}
        append_entry(mail_path(root, lane), "M", lane, rec)
    print(f"answered {args.id}")


def add_steering(root: Path, body: str, lane: str | None, who: str) -> None:
    path = root / "steering.jsonl"
    with locked(path):
        n = len(read_jsonl(path)) + 1
        append_jsonl(path, {"id": f"S-{n:04d}", "ts": now(), "round": current_round(root),
                            "author": who, "lane": lane or "all", "body": body})


def cmd_steer(args):
    root = inv_root(args)
    if args.steer_cmd == "add":
        if args.lane:
            check_lane(root, args.lane)
        add_steering(root, read_body(args), args.lane, author(args) if author(args) != "unknown" else "human")
        print("steering recorded")
    else:
        rows = [s for s in read_jsonl(root / "steering.jsonl")
                if args.since_round is None or s.get("round", 0) >= args.since_round]
        if args.lane:
            rows = [s for s in rows if s.get("lane") in ("all", args.lane)]
        if not rows:
            print("(no steering)")
        for s in rows:
            print(f"{s['id']} r{s.get('round')} [{s.get('lane')}] {s['body']}")


# ---------------------------------------------------------------- plans

def all_task_ids(root: Path) -> dict[str, str]:
    out = {}
    for lane in lane_names(root):
        for t in load_json(root / "lanes" / lane / "plan.json", {"tasks": []})["tasks"]:
            out[t["id"]] = t.get("status", "queued")
    return out


def normalize_task(t: dict, lane: str, m: dict, budget: dict, root: Path | None = None) -> dict:
    res_names = {r["name"] for r in m.get("resources", [])}
    lane_cfg = next(l for l in m["lanes"] if l["name"] == lane)
    for k in ("id", "title", "objective", "deliverable"):
        if not t.get(k):
            die(f"task {t.get('id', '?')}: missing '{k}'")
    if lane_of_task(t["id"]) != lane:
        die(f"task {t['id']}: id must start with '{lane}-r' (format {lane}-rNN-NN)")
    t = {"kind": "other", "instructions": "", "resources": [], "deps": [],
         "verify": lane_verify_default(root, lane_cfg), "size": "short",
         "max_children": budget["max_children"], **t}
    if t["kind"] not in TASK_KINDS:
        die(f"task {t['id']}: kind must be one of {sorted(TASK_KINDS)}")
    if t["verify"] not in VERIFY:
        die(f"task {t['id']}: verify must be one of {sorted(VERIFY)}")
    if t["size"] not in SIZES:
        die(f"task {t['id']}: size must be one of {sorted(SIZES)}")
    if t["kind"] == "sweep":
        items = t.get("items")
        if not isinstance(items, list) or not items or not all(isinstance(i, str) and i for i in items):
            die(f"task {t['id']}: a sweep needs 'items': a non-empty list of strings (one per unit of work)")
        if len(items) > budget["max_sweep_items"]:
            die(f"task {t['id']}: {len(items)} sweep items exceeds max_sweep_items={budget['max_sweep_items']}; "
                f"split into several sweeps or group items")
    elif "items" in t:
        die(f"task {t['id']}: 'items' is only for kind 'sweep'")
    for r in t["resources"]:
        if r not in res_names:
            die(f"task {t['id']}: unknown resource '{r}' (declared: {', '.join(sorted(res_names))})")
    if not isinstance(t["max_children"], int) or t["max_children"] > budget["max_children"]:
        t["max_children"] = budget["max_children"]
    return t


def cmd_plan(args):
    root = inv_root(args)
    lane = check_lane(root, args.lane)
    ppath = root / "lanes" / lane / "plan.json"
    if args.plan_cmd == "show":
        plan = load_json(ppath)
        if args.format == "json":
            print(json.dumps(plan, indent=2))
            return
        print(f"plan {lane} v{plan['version']} (round {plan['round']}): {len(plan['tasks'])} tasks")
        for t in plan["tasks"]:
            print(f"  {t['id']} [{t.get('status')}/{t.get('verify')}/{t.get('size')}"
                  f"{'/att' + str(t['attempt']) if t.get('attempt', 1) > 1 else ''}] {t['title']}"
                  f"{'  deps=' + ','.join(t['deps']) if t.get('deps') else ''}"
                  f"{'  res=' + ','.join(t['resources']) if t.get('resources') else ''}")
        if plan.get("notes"):
            print(f"  notes: {plan['notes']}")
        return

    # save
    raw = open(args.file).read() if args.file else sys.stdin.read()
    try:
        incoming = json.loads(raw)
    except json.JSONDecodeError as e:
        die(f"plan JSON invalid: {e}")
    if isinstance(incoming, list):
        incoming = {"tasks": incoming}
    m = manifest(root)
    budget = {**DEFAULT_BUDGET, **m.get("budget", {})}
    rnd = args.round or current_round(root)
    with locked(ppath):
        old = load_json(ppath, {"lane": lane, "version": 0, "round": 0, "tasks": [], "notes": ""})
        old_by_id = {t["id"]: t for t in old["tasks"]}
        drop = set(incoming.get("drop", []))
        inflight = set(csv(args.inflight))
        new_tasks, seen = [], set()
        for t in incoming.get("tasks", []):
            t = normalize_task(t, lane, m, budget, root)
            if t["id"] in seen:
                die(f"duplicate task id {t['id']}")
            seen.add(t["id"])
            prev = old_by_id.get(t["id"])
            if prev:
                prev_status = prev.get("status", "queued")
                if prev_status == "done":
                    die(f"task {t['id']} is already done; use a new id for follow-up work")
                if t["id"] in inflight:
                    die(f"task {t['id']} is still in flight; leave it out of the plan (it keeps running)")
                t["attempt"] = prev.get("attempt", 1) + (1 if prev_status in REQUEUE_FROM else 0)
            else:
                t["attempt"] = 1
            t["status"] = "queued"
            t["planned_round"] = rnd
            new_tasks.append(t)
        # carry over everything not re-submitted: terminal tasks keep status; queued ones not resubmitted are dropped
        carried = []
        for tid, t in old_by_id.items():
            if tid in seen:
                continue
            t = dict(t)
            if tid in drop or t.get("status") == "queued":
                if t.get("status") != "done":
                    t["status"] = "dropped"
            carried.append(t)
        queued = [t for t in new_tasks if t["status"] == "queued"]
        if len(queued) > budget["max_tasks_per_lane_round"]:
            die(f"{len(queued)} queued tasks exceeds max_tasks_per_lane_round="
                f"{budget['max_tasks_per_lane_round']}; defer the rest (leave them out) or merge tasks")
        known = set(all_task_ids(root)) | seen
        for t in new_tasks:
            for d in t["deps"]:
                if d not in known:
                    die(f"task {t['id']}: unknown dependency '{d}'")
        if old["version"] > 0:
            write_json(root / "lanes" / lane / "archive" / f"plan.v{old['version']:03d}.json", old)
        plan = {"lane": lane, "version": old["version"] + 1, "round": rnd, "ts": now(),
                "author": author(args), "notes": incoming.get("notes", ""), "tasks": carried + new_tasks}
        write_json(ppath, plan)
    worklog(root, lane, "plan-save", author(args), version=plan["version"],
            summary=f"{len(queued)} queued, {len(drop)} dropped")
    dispatch = [{k: t[k] for k in ("id", "title", "kind", "resources", "deps", "verify", "size", "items") if k in t}
                for t in queued]
    print(json.dumps({"version": plan["version"], "dispatch": dispatch}, indent=1))


# ---------------------------------------------------------------- tasks

def task_dir(root: Path, tid: str) -> Path:
    return root / "lanes" / lane_of_task(tid) / "tasks" / tid


def set_plan_status(root: Path, tid: str, **fields) -> dict:
    lane = lane_of_task(tid)
    ppath = root / "lanes" / lane / "plan.json"
    with locked(ppath):
        plan = load_json(ppath)
        for t in plan["tasks"]:
            if t["id"] == tid:
                t.update(fields)
                write_json(ppath, plan)
                return t
    die(f"task {tid} not in {lane} plan")


def cmd_task(args):
    root = inv_root(args)
    tid = args.id
    lane = lane_of_task(tid)
    check_lane(root, lane)
    td = task_dir(root, tid)
    who = author(args)
    c = args.task_cmd

    if c == "start":
        t = set_plan_status(root, tid, status="running", started_round=current_round(root))
        td.mkdir(parents=True, exist_ok=True)
        write_json(td / "task.json", t)
        (td / "notes.md").touch()
        worklog(root, lane, "task-start", who, task=tid, attempt=t.get("attempt", 1))
        print(json.dumps(t, indent=1))
        prev = sorted(td.glob("review-*.json"))
        if (td / "result.json").exists() or prev:
            print(f"\nNOTE: earlier attempt exists in {td} — read result.json, review-*.json, notes.md first.")
    elif c == "show":
        print(f"# {td}")
        for name in ("task.json", "result.json"):
            if (td / name).exists():
                print(f"## {name}\n{(td / name).read_text()}")
        item_files = sorted((td / "items").glob("*.json")) if (td / "items").exists() else []
        if item_files or (td / "task.json").exists() and load_json(td / "task.json").get("kind") == "sweep":
            spec = load_json(td / "task.json") or {}
            done = {load_json(f)["n"]: load_json(f) for f in item_files}
            print(f"## sweep items ({len(done)}/{len(spec.get('items', []))} reported)")
            for n, item in enumerate(spec.get("items", []), 1):
                r = done.get(n)
                print(f"  {n:3d}. {item}: " + (f"[{r['status']}] {r['summary']}" + (f"  ({', '.join(r['board_ids'])})" if r['board_ids'] else "") if r else "(no result)"))
        for r in sorted(td.glob("review-*.json")):
            print(f"## {r.name}\n{r.read_text()}")
        notes = (td / "notes.md").read_text().splitlines() if (td / "notes.md").exists() else []
        if notes:
            print("## notes.md (last 30 lines)\n" + "\n".join(notes[-30:]))
        others = [p.name for p in td.iterdir() if p.name not in
                  {"task.json", "result.json", "notes.md", "started.jsonl"} and not p.name.startswith("review-")
                  and not p.name.endswith(".lock")] if td.exists() else []
        if others:
            print("## other files\n  " + "\n  ".join(sorted(others)))
    elif c == "note":
        td.mkdir(parents=True, exist_ok=True)
        with locked(td / "notes.md"):
            with open(td / "notes.md", "a") as f:
                f.write(f"- [{now()}] ({who}) {args.text}\n")
        print("noted")
    elif c == "started":
        path = td / "started.jsonl"
        with locked(path):
            n = sum(1 for r in read_jsonl(path) if r.get("op") != "stopped") + 1
            append_jsonl(path, {"ref": f"S{n}", "ts": now(), "by": who, "what": args.what, "stop": args.stop})
        print(f"S{n}")
    elif c == "stopped":
        path = td / "started.jsonl"
        with locked(path):
            append_jsonl(path, {"op": "stopped", "ref": args.ref, "ts": now(), "by": who, "note": args.note or ""})
        print(f"{args.ref} marked stopped")
    elif c == "finish":
        if args.status not in FINISH_STATUSES:
            die(f"--status must be one of {sorted(FINISH_STATUSES)}")
        t = load_json(td / "task.json") or die(f"task {tid} was never started")
        details = open(args.details_file).read() if args.details_file else ""
        res = {"id": tid, "attempt": t.get("attempt", 1), "status": args.status, "summary": args.summary,
               "board_ids": csv(args.board_ids), "artifacts": csv(args.artifacts), "details": details,
               "by": who, "ts": now(), "round": current_round(root)}
        if (td / "result.json").exists():
            old = load_json(td / "result.json")
            write_json(td / f"result.attempt{old.get('attempt', 1)}.{old.get('ts', 'x').replace(':', '')}.json", old)
        write_json(td / "result.json", res)
        set_plan_status(root, tid, status=args.status)
        live = leftovers_for(td)
        worklog(root, lane, "task-finish", who, task=tid, status=args.status, summary=args.summary)
        print(f"{tid} -> {args.status}")
        if live:
            print(f"WARNING: {len(live)} recorded side effect(s) not stopped: "
                  + "; ".join(f"{s['ref']}: {s['what']}" for s in live))
    elif c == "item":
        if args.status not in FINISH_STATUSES:
            die(f"--status must be one of {sorted(FINISH_STATUSES)}")
        if not (td / "task.json").exists():  # first item of a sweep starts the task
            t = set_plan_status(root, tid, status="running", started_round=current_round(root))
            td.mkdir(parents=True, exist_ok=True)
            write_json(td / "task.json", t)
            (td / "notes.md").touch()
            worklog(root, lane, "task-start", who, task=tid, attempt=t.get("attempt", 1))
        items = load_json(td / "task.json").get("items") or []
        if not 1 <= args.n <= max(len(items), 1):
            die(f"--n must be between 1 and {len(items)} for this sweep")
        write_json(td / "items" / f"{args.n:03d}.json",
                   {"n": args.n, "item": items[args.n - 1] if items else None, "status": args.status,
                    "summary": args.summary, "board_ids": csv(args.board_ids), "by": who, "ts": now()})
        print(f"{tid} item {args.n} -> {args.status}")
    elif c == "review":
        if args.verdict not in VERDICTS:
            die(f"--verdict must be one of {sorted(VERDICTS)}")
        n = len(list(td.glob("review-*.json"))) + 1
        rev = {"id": tid, "n": n, "verdict": args.verdict, "summary": args.summary,
               "objections": args.objection or [], "by": who, "ts": now(), "round": current_round(root)}
        write_json(td / f"review-{n}.json", rev)
        if args.verdict == "redo":
            set_plan_status(root, tid, status="needs_redo")
        worklog(root, lane, "task-review", who, task=tid, verdict=args.verdict, summary=args.summary)
        print(f"review-{n} {args.verdict}")


def leftovers_for(td: Path) -> list[dict]:
    recs = read_jsonl(td / "started.jsonl")
    stopped = {r["ref"] for r in recs if r.get("op") == "stopped"}
    return [r for r in recs if r.get("op") != "stopped" and r["ref"] not in stopped]


def cmd_leftovers(args):
    root = inv_root(args)
    lanes = [check_lane(root, args.lane)] if args.lane else lane_names(root)
    found = False
    for lane in lanes:
        for td in sorted((root / "lanes" / lane / "tasks").glob("*")):
            for s in leftovers_for(td):
                found = True
                print(f"{td.name} {s['ref']}: {s['what']}\n    stop: {s['stop']}")
    if not found:
        print("(no leftovers)")


def cmd_worklog(args):
    root = inv_root(args)
    lane = check_lane(root, args.lane)
    rows = read_jsonl(root / "lanes" / lane / "worklog.jsonl")[-args.tail:]
    for r in rows:
        extra = {k: v for k, v in r.items() if k not in ("ts", "round", "author", "event")}
        print(f"{r['ts']} r{r['round']} {r['event']} {r['author']} {json.dumps(extra, ensure_ascii=False)}")
    if not rows:
        print("(empty worklog)")


# ---------------------------------------------------------------- files, judge, segments

PROTECTED = {"manifest.json", "state.json", "steering.jsonl", "plan.json", "board.jsonl", "worklog.jsonl",
             "task.json", "result.json", "started.jsonl"}


def cmd_write(args):
    root = inv_root(args)
    target = (root / args.path).resolve()
    if root not in target.parents:
        die("path must be inside the investigation directory")
    if target.name in PROTECTED or target.suffix == ".jsonl" or "bin" in target.relative_to(root).parts[:1]:
        die(f"'{args.path}' is protocol-managed; use the matching board.py command")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = sys.stdin.read()
    with open(target, "a" if args.append else "w") as f:
        f.write(data)
    print(f"wrote {target.relative_to(root)} ({len(data)} bytes)")


def cmd_judge(args):
    root = inv_root(args)
    if args.judge_cmd == "save":
        raw = open(args.file).read() if args.file else sys.stdin.read()
        try:
            verdict = json.loads(raw)
        except json.JSONDecodeError as e:
            die(f"judge JSON invalid: {e}")
        for k in ("met", "progress", "gaps", "summary"):
            if k not in verdict:
                die(f"judge verdict missing '{k}'")
        verdict.update({"round": args.round, "ts": now(), "by": author(args)})
        write_json(root / "judge" / f"round-{args.round:02d}.json", verdict)
        spath = root / "state.json"
        with locked(spath):
            st = state(root)
            st["round"] = max(st.get("round", 1), args.round + 1)
            if verdict["met"]:
                st["status"] = "met"
            elif st.get("status") == "met":
                st["status"] = "active"
            write_json(spath, st)
        print(f"judge round {args.round} saved; next round {args.round + 1}")
    elif args.judge_cmd == "refute":
        path = root / "judge" / f"round-{args.round:02d}.json"
        verdict = load_json(path) or die(f"no judge verdict for round {args.round}")
        if not args.objection:
            die("refute needs at least one --objection")
        verdict["met_before_refute"] = verdict.get("met")
        verdict["met"] = False
        verdict["refuted"] = {"by": author(args), "ts": now(), "objections": args.objection}
        verdict["gaps"] = [f"[refuter] {o}" for o in args.objection] + list(verdict.get("gaps", []))
        write_json(path, verdict)
        spath = root / "state.json"
        with locked(spath):
            st = state(root)
            if st.get("status") == "met":
                st["status"] = "active"
            write_json(spath, st)
        print(f"judge round {args.round}: met verdict refuted ({len(args.objection)} objection(s))")
    else:
        files = sorted((root / "judge").glob("round-*.json"))
        if args.round:
            files = [f for f in files if f.name == f"round-{args.round:02d}.json"]
        if not files:
            print("(no judge verdicts yet)")
            return
        print(files[-1].read_text())


# ---------------------------------------------------------------- brief

# State each role needs up front; saves agents several opening tool calls.
BRIEF_STATE = {
    "scope": lambda a: [["probe", "--lane", a.lane], ["plan", "show", "--lane", a.lane], ["worklog", "--lane", a.lane, "--tail", "15"],
                        ["mail", "list", "--lane", a.lane], ["steer", "list", "--lane", a.lane], ["judge", "show"],
                        ["query", "--lane", a.lane, "--limit", "15"], ["query", "--lane", "shared", "--limit", "15"]],
    "plan": lambda a: [["plan", "show", "--lane", a.lane], ["mail", "list", "--lane", a.lane],
                       ["steer", "list", "--lane", a.lane]],
    "challenger": lambda a: [["task", "show", "--id", a.task]] if a.task else [],
    "salvage": lambda a: ([["task", "show", "--id", a.task], ["leftovers", "--lane", lane_of_task(a.task)]]
                          if a.task else []),
    "synthesizer": lambda a: [["query", "--lane", "all"] + (["--round", str(a.round)] if a.round else [])],
    "judge": lambda a: [["judge", "show"], ["steer", "list"], ["query", "--lane", "shared", "--format", "full"]],
    "refuter": lambda a: [["judge", "show"], ["query", "--lane", "shared", "--format", "full"]],
    "checkpoint": lambda a: [["status"], ["questions"], ["leftovers"]],
}


def manifest_essentials(m: dict) -> str:
    out = [f"goal: {m.get('goal', '')}"]
    if m.get("question"):
        out.append(f"question: {m['question']}")
    sc = m.get("scope", {})
    if sc:
        out.append(f"scope in: {'; '.join(sc.get('in', []))}\nscope out: {'; '.join(sc.get('out', []))}")
        if sc.get("notes"):
            out.append(f"scope notes: {sc['notes']}")
    out.append("safety (hard rules):\n" + "\n".join(f"  - {s}" for s in m.get("safety", [])))
    if m.get("safety_deny"):
        out.append("commands blocked by the guard (regex): " + "  ".join(m["safety_deny"]))
    out.append("writable outside the investigation directory: " + (", ".join(m.get("writable", [])) or "nothing"))
    c = m.get("criteria", {})
    out.append("success criteria:\n" + "\n".join(f"  - {s}" for s in c.get("success", [])))
    if c.get("evidence_standard"):
        out.append(f"evidence standard: {c['evidence_standard']}")
    if c.get("stop_if"):
        out.append("stop if:\n" + "\n".join(f"  - {s}" for s in c["stop_if"]))
    out.append("resources:\n" + "\n".join(
        f"  - {r['name']} [{r.get('kind', '?')}{', EXCLUSIVE' if r.get('exclusive') else ''}] "
        f"access: {r.get('access', '')}{'  — ' + r['notes'] if r.get('notes') else ''}" for r in m.get("resources", [])))
    out.append("lanes:\n" + "\n".join(f"  - {l['name']}: {l['mandate']}" for l in m.get("lanes", [])))
    return "\n".join(out)


def cmd_brief(args):
    root = inv_root(args)
    role = args.role
    if role not in ROLES:
        die(f"--role must be one of {', '.join(ROLES)}")
    if args.lane:
        check_lane(root, args.lane)
    sections = [("Protocol", (root / "prompts" / "protocol.md").read_text()),
                (f"Your role: {role}", (root / "prompts" / f"{role}.md").read_text())]
    if args.lane:
        sections.append((f"Your lane: {args.lane}", (root / "lanes" / args.lane / "lane.md").read_text()))
    sections.append(("Manifest essentials", manifest_essentials(manifest(root))))
    if role == "plan" and args.lane and args.round:
        brief = root / "lanes" / args.lane / "scope" / f"round-{args.round:02d}.md"
        sections.append((f"Scope brief (round {args.round})",
                         brief.read_text() if brief.exists() else "(no scope brief for this round)"))
    for s in sections:
        print(f"\n{'=' * 8} {s[0]} {'=' * 8}\n{s[1].strip()}\n")
    calls = BRIEF_STATE.get(role, lambda a: [])(args)
    if role in ("scope", "plan") and not args.lane:
        calls = []
    for argv in calls:
        print(f"\n{'=' * 8} state: board.py {' '.join(argv)} {'=' * 8}")
        sub = build_parser().parse_args(argv + ["--inv", str(root)])
        sub.author = author(args)
        try:
            sub.fn(sub)
        except BoardError as e:
            print(f"(error: {e})")
    print(f"\n{'=' * 8} end of brief {'=' * 8}")


def cmd_segment(args):
    root = inv_root(args)
    spath = root / "state.json"
    with locked(spath):
        st = state(root)
        st.setdefault("segments", []).append({"n": len(st.get("segments", [])) + 1, "start_round": args.start,
                                              "end_round": args.end, "reason": args.reason, "ts": now()})
        if args.reason in ("met", "met_unconfirmed", "stall", "max_rounds"):
            st["status"] = {"met": "met", "met_unconfirmed": "met_unconfirmed",
                            "stall": "stalled", "max_rounds": "exhausted"}[args.reason]
        write_json(spath, st)
    print(f"segment closed: rounds {args.start}-{args.end} ({args.reason})")


# ---------------------------------------------------------------- status & workflow args

def cmd_status(args):
    root = inv_root(args)
    m, st = manifest(root), state(root)
    lanes = {}
    for lane in lane_names(root):
        plan = load_json(root / "lanes" / lane / "plan.json", {"tasks": [], "version": 0})
        counts: dict[str, int] = {}
        for t in plan["tasks"]:
            counts[t.get("status", "queued")] = counts.get(t.get("status", "queued"), 0) + 1
        mail, _ = materialize(read_jsonl(mail_path(root, lane)))
        orphans = [t["id"] for t in plan["tasks"] if t.get("status") == "running"]
        lanes[lane] = {"plan_version": plan["version"], "tasks": counts,
                       "open_mail": sum(1 for e in mail.values() if e.get("status") in ("new", "accepted")),
                       "running_or_orphaned": orphans,
                       "leftovers": sum(len(leftovers_for(td)) for td in (root / "lanes" / lane / "tasks").glob("*"))}
    judge_files = sorted((root / "judge").glob("round-*.json"))
    last = load_json(judge_files[-1]) if judge_files else None
    out = {"investigation": m.get("slug"), "title": m.get("title", ""), "dir": str(root),
           "round": st.get("round", 1), "status": st.get("status", "active"),
           "segments": len(st.get("segments", [])), "lanes": lanes,
           "open_questions": [{"id": q["id"], "q": q["subject"]} for q in open_questions(root)],
           "last_judge": {k: last.get(k) for k in ("round", "met", "progress", "summary", "gaps")} if last else None}
    if args.json:
        print(json.dumps(out, indent=1))
        return
    print(f"{out['investigation']} — {out['title']}\n  dir: {root}\n  round {out['round']}  status {out['status']}"
          f"  segments {out['segments']}")
    for lane, info in lanes.items():
        tasks = ", ".join(f"{k}:{v}" for k, v in sorted(info["tasks"].items())) or "no tasks"
        flags = []
        if info["open_mail"]:
            flags.append(f"{info['open_mail']} open mail")
        if info["running_or_orphaned"]:
            flags.append(f"running/orphaned: {', '.join(info['running_or_orphaned'])}")
        if info["leftovers"]:
            flags.append(f"{info['leftovers']} leftover side effects")
        print(f"  [{lane}] plan v{info['plan_version']}: {tasks}{'  | ' + '; '.join(flags) if flags else ''}")
    if out["last_judge"]:
        j = out["last_judge"]
        print(f"  last judge (r{j['round']}): met={j['met']} progress={j['progress']} — {j['summary']}")
    for q in out["open_questions"]:
        print(f"  ? {q['id']}: {q['q']}")


def cmd_wf_args(args):
    root = inv_root(args)
    m, st = manifest(root), state(root)
    errs = validate_manifest(m, root)
    if errs:
        die("manifest invalid:\n  " + "\n  ".join(errs))
    budget = {**DEFAULT_BUDGET, **m.get("budget", {})}
    if args.rounds:
        budget["rounds_per_checkpoint"] = args.rounds
    board = root / "bin" / "board.py"
    board.chmod(board.stat().st_mode | 0o111)  # invoked directly via its shebang
    out = {
        "inv": str(root),
        "board": str(board),  # one token, so agents can keep it in a shell variable under any shell
        "start_round": st.get("round", 1),
        "lanes": [l["name"] for l in m["lanes"]],
        "exclusive": sorted(r["name"] for r in m["resources"] if r.get("exclusive")),
        "budget": budget,
        "models": {k: v for k, v in (m.get("models") or {}).items() if v},
        "effort": {k: v for k, v in (m.get("effort") or {}).items() if v},
        "agent_types": {} if args.no_agent_types else {k: v for k, v in (m.get("agent_types") or {}).items() if v},
    }
    print(json.dumps(out, indent=1))


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--as", dest="author", help="who is acting, e.g. static/static-r02-01")
    common.add_argument("--inv", help="investigation directory (default: bin/..)")

    p = argparse.ArgumentParser(prog="board.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def sp(name, fn, group=False, **kw):
        # group commands (mail, plan, task, ...) take the common flags on their leaves only;
        # argparse lets leaf defaults overwrite values parsed at the group level.
        s = sub.add_parser(name, parents=[] if group else [common], **kw)
        s.set_defaults(fn=fn)
        return s

    sp("validate", cmd_validate)
    sp("scaffold", cmd_scaffold)
    s = sp("archetypes", cmd_archetypes)
    s.add_argument("--show", metavar="NAME")
    s = sp("probe", cmd_probe)
    s.add_argument("--lane")
    s.add_argument("--resource")
    s.add_argument("--timeout", type=int, default=15)
    s = sp("brief", cmd_brief)
    s.add_argument("--role", required=True, choices=ROLES)
    s.add_argument("--lane")
    s.add_argument("--task")
    s.add_argument("--round", type=int)
    s = sp("status", cmd_status)
    s.add_argument("--json", action="store_true")
    s = sp("wf-args", cmd_wf_args)
    s.add_argument("--rounds", type=int)
    s.add_argument("--no-agent-types", action="store_true",
                   help="omit agent_types (run on default workflow subagents, e.g. when the plugin's agents aren't loaded)")

    s = sp("post", cmd_post)
    s.add_argument("--lane", required=True)
    s.add_argument("--kind", required=True)
    s.add_argument("--subject", required=True)
    s.add_argument("--body", default="", help="text, or '-' to read stdin")
    s.add_argument("--tags")
    s.add_argument("--refs")
    s.add_argument("--confidence")
    s.add_argument("--status")
    s.add_argument("--supersedes")

    s = sp("amend", cmd_amend)
    s.add_argument("--id", required=True)
    s.add_argument("--set", action="append")
    s.add_argument("--note")

    s = sp("query", cmd_query)
    s.add_argument("--lane")
    s.add_argument("--id", help="entry id(s), comma-separated")
    s.add_argument("--kind")
    s.add_argument("--tag")
    s.add_argument("--status")
    s.add_argument("--author", dest="by_author", help="filter: entries whose author starts with this")
    s.add_argument("--grep")
    s.add_argument("--round", type=int)
    s.add_argument("--include-superseded", action="store_true")
    s.add_argument("--format", choices=["brief", "full", "json"], default="brief")
    s.add_argument("--limit", type=int)

    s = sp("mail", cmd_mail, group=True)
    ms = s.add_subparsers(dest="mail_cmd", required=True)
    x = ms.add_parser("send", parents=[common])
    x.add_argument("--to", required=True)
    x.add_argument("--from", dest="sender")
    x.add_argument("--subject", required=True)
    x.add_argument("--body", default="", help="text, or '-' to read stdin")
    x.add_argument("--type")
    x.add_argument("--re")
    x.add_argument("--priority", choices=["normal", "high"])
    x = ms.add_parser("list", parents=[common])
    x.add_argument("--lane", required=True)
    x.add_argument("--all", action="store_true")
    x.add_argument("--format", choices=["brief", "full", "json"], default="brief")
    x = ms.add_parser("show", parents=[common])
    x.add_argument("--id", required=True)
    x = ms.add_parser("set", parents=[common])
    x.add_argument("--id", required=True)
    x.add_argument("--status", required=True)
    x.add_argument("--note")
    x = ms.add_parser("reply", parents=[common])
    x.add_argument("--id", required=True)
    x.add_argument("--body", default="", help="text, or '-' to read stdin")
    x.add_argument("--status")

    s = sp("ask", cmd_ask)
    s.add_argument("--question", required=True)
    s.add_argument("--context")
    s.add_argument("--lane")
    s = sp("questions", cmd_questions)
    s.add_argument("--all", action="store_true")
    s = sp("answer", cmd_answer)
    s.add_argument("--id", required=True)
    s.add_argument("--body", required=True, help="text, or '-' to read stdin")

    s = sp("steer", cmd_steer, group=True)
    ss = s.add_subparsers(dest="steer_cmd", required=True)
    x = ss.add_parser("add", parents=[common])
    x.add_argument("--body", required=True, help="text, or '-' to read stdin")
    x.add_argument("--lane")
    x = ss.add_parser("list", parents=[common])
    x.add_argument("--since-round", type=int)
    x.add_argument("--lane")

    s = sp("plan", cmd_plan, group=True)
    ps = s.add_subparsers(dest="plan_cmd", required=True)
    x = ps.add_parser("show", parents=[common])
    x.add_argument("--lane", required=True)
    x.add_argument("--format", choices=["brief", "json"], default="brief")
    x = ps.add_parser("save", parents=[common])
    x.add_argument("--lane", required=True)
    x.add_argument("--round", type=int)
    x.add_argument("--file")
    x.add_argument("--inflight", help="comma-separated task ids still running from earlier rounds")

    s = sp("task", cmd_task, group=True)
    ts = s.add_subparsers(dest="task_cmd", required=True)
    for name in ("start", "show"):
        x = ts.add_parser(name, parents=[common])
        x.add_argument("--id", required=True)
    x = ts.add_parser("note", parents=[common])
    x.add_argument("--id", required=True)
    x.add_argument("--text", required=True)
    x = ts.add_parser("started", parents=[common])
    x.add_argument("--id", required=True)
    x.add_argument("--what", required=True)
    x.add_argument("--stop", required=True, help="exact command that undoes it")
    x = ts.add_parser("stopped", parents=[common])
    x.add_argument("--id", required=True)
    x.add_argument("--ref", required=True)
    x.add_argument("--note")
    x = ts.add_parser("finish", parents=[common])
    x.add_argument("--id", required=True)
    x.add_argument("--status", required=True)
    x.add_argument("--summary", required=True)
    x.add_argument("--board-ids")
    x.add_argument("--artifacts")
    x.add_argument("--details-file")
    x = ts.add_parser("item", parents=[common])
    x.add_argument("--id", required=True)
    x.add_argument("--n", type=int, required=True)
    x.add_argument("--status", required=True)
    x.add_argument("--summary", required=True)
    x.add_argument("--board-ids")
    x = ts.add_parser("review", parents=[common])
    x.add_argument("--id", required=True)
    x.add_argument("--verdict", required=True)
    x.add_argument("--summary", required=True)
    x.add_argument("--objection", action="append")

    s = sp("worklog", cmd_worklog)
    s.add_argument("--lane", required=True)
    s.add_argument("--tail", type=int, default=30)
    s = sp("leftovers", cmd_leftovers)
    s.add_argument("--lane")
    s = sp("write", cmd_write)
    s.add_argument("--path", required=True)
    s.add_argument("--append", action="store_true")

    s = sp("judge", cmd_judge, group=True)
    js = s.add_subparsers(dest="judge_cmd", required=True)
    x = js.add_parser("save", parents=[common])
    x.add_argument("--round", type=int, required=True)
    x.add_argument("--file")
    x = js.add_parser("show", parents=[common])
    x.add_argument("--round", type=int)
    x = js.add_parser("refute", parents=[common])
    x.add_argument("--round", type=int, required=True)
    x.add_argument("--objection", action="append")

    s = sp("segment", cmd_segment, group=True)
    gs = s.add_subparsers(dest="seg_cmd", required=True)
    x = gs.add_parser("close", parents=[common])
    x.add_argument("--start", type=int, required=True)
    x.add_argument("--end", type=int, required=True)
    x.add_argument("--reason", required=True,
                   choices=["checkpoint", "met", "met_unconfirmed", "stall", "max_rounds", "agent_cap", "token_budget", "error"])
    return p


GLUED_RE = re.compile(r"^(--[A-Za-z][\w-]*)\s+(.*)$", re.S)


def parse_argv(argv: list[str]):
    """Parse argv, repairing arguments glued by a shell that doesn't word-split.

    zsh (the default here) does NOT split an unquoted variable, so
    `A="--as lane/task"; board.py post ... $A` arrives as the single argument
    "--as lane/task". Only arguments argparse rejects are split, so real values
    are never touched."""
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra:
        fixed, glued = [], []
        for a in argv:
            m = GLUED_RE.match(a) if a in extra else None
            if m:
                fixed += [m.group(1), m.group(2)]
                glued.append(a)
            else:
                fixed.append(a)
        if glued:
            args2, extra2 = parser.parse_known_args(fixed)
            if not extra2:
                print(f"note: split {len(glued)} argument(s) that arrived glued, e.g. {glued[0]!r}. "
                      f"Your shell does not word-split an unquoted variable holding \"--flag value\"; "
                      f"export BOARD_AUTHOR=<your id> once instead of passing --as through a variable.",
                      file=sys.stderr)
                return args2
    if extra:
        parser.error("unrecognized arguments: " + " ".join(extra))
    return args


def main(argv=None):
    args = parse_argv(list(sys.argv[1:] if argv is None else argv))
    try:
        args.fn(args)
    except BoardError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
