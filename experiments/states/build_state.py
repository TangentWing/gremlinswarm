#!/usr/bin/env python3
"""Scripted investigation states on the `trisvc` target, for component experiments.

    build_state.py review  <variant> <dir>    one finished task awaiting its challenger
    build_state.py verdict <variant> <dir>    round 1 finished; judge / refuter decide on `met`
    build_state.py work    <variant> <dir>    round 2 starts; one queued logs task awaits its investigator
                                              (T true lead on the board, T-deps same + declared dep, H red-herring lead)
    build_state.py strategy <variant> <dir>   a strategy decision point on the red-herring board: S1 end of round 1,
                                              S2 end of round 2 and stalled (--nojudge: last round not yet judged)

A state is a real investigation directory (kit copy + manifest + scaffold) whose contents were
written through board.py, exactly as agents would. Ground truth (line numbers, rids, keys)
comes from experiments/targets/trisvc/answer_key.json, so rebuild the target first. Set
TRISVC_PROFILE=bursty to build on targets/trisvc-bursty (prepare.py does it from the spec).

review variants   C-static C-logs (clean controls)  F1 wrong-citation  F2 one-case-generalised
                  F3 overstated-confidence  F4 fabricated-evidence  F5 red-herring-conclusion
                  F6 out-of-mandate
                  subtle tier: S1 near-miss-citation  S2 one-misattributed-row (row 5 of 6)
                  S3 overgeneralised-by-one-counterexample  S4 wrong-mechanism-detail-right-lines
verdict variants  J0 clean  J1 refuted-support  J2 weaker-than-criterion  J3 contradiction
                  subtle tier: J4 rival-raised-on-a-lane-board-never-addressed
                  J5 shared-evidence-promoted-from-a-task-its-challenger-rejected
                  (add --judged to pre-save a `met` verdict, for refuter trials)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
KIT = REPO / "investigate" / "kit"
PROFILE = os.environ.get("TRISVC_PROFILE", "base")        # which generated target the state is built on
TARGET = REPO / "targets" / ("trisvc" if PROFILE == "base" else f"trisvc-{PROFILE}")
KEY = json.loads((HERE.parent / "targets" / "trisvc" / ("answer_key.json" if PROFILE == "base" else f"answer_key.{PROFILE}.json")).read_text())
LOG = (TARGET / "logs" / "merged.log").read_text().splitlines()
RC = KEY["root_cause"]["line"]
REL = KEY["related_lines"]
FACTS = KEY["facts"]

def SRC_LINE(fname, needle):
    for i, line in enumerate((TARGET / "services" / fname).read_text().splitlines(), 1):
        if needle in line:
            return i
    raise SystemExit(f"marker not found in {fname}: {needle}")


REVIEW_VARIANTS = ["C-static", "C-logs", "F1", "F2", "F3", "F4", "F5", "F6", "S1", "S2", "S3", "S4"]
VERDICT_VARIANTS = ["J0", "J1", "J2", "J3", "J4", "J5"]


def manifest():
    t = str(TARGET)
    return {
        "version": 1, "slug": "trisvc",
        "title": "Inventory reserves more stock than orders confirms",
        "goal": "Find why inventory holds more reserved units than orders has confirmed, locate the cause to "
                "file:line, and rule rival explanations in or out with evidence.",
        "question": "Why does `reconcile drift` appear and grow on the morning of 2 March?",
        "scope": {"in": [f"{t}/services", f"{t}/logs", f"{t}/config", f"{t}/BUGREPORT.md"],
                  "out": ["fixing the code", f"anything outside {t} and the investigation directory"],
                  "notes": "Read-only. The services are not running; work from source, config and logs/merged.log."},
        "targets": [{"name": "trisvc", "path": t, "notes": "three Python services and their merged log"}],
        "resources": [
            {"name": "source", "kind": "local-repo", "access": f"{t}/services", "exclusive": False,
             "check": f"test -f {t}/services/gateway.py", "notes": "Read-only."},
            {"name": "logs", "kind": "logs", "access": f"{t}/logs/merged.log", "exclusive": False,
             "check": f"test -f {t}/logs/merged.log", "notes": "One merged file, UTC, all three services."},
            {"name": "config", "kind": "other", "access": f"{t}/config", "exclusive": False,
             "check": f"test -f {t}/config/deploys.log", "notes": "Service config and the deploy log."},
        ],
        "safety": [f"Never modify anything under {t}.", "No network, no installs; python3 one-liners are fine."],
        "criteria": {
            "success": [
                "Root cause located to a specific file:line, with the mechanism that makes reserved exceed confirmed.",
                "Log evidence: at least 5 affected requests traced end to end (gateway, orders, inventory) with "
                "merged.log line numbers, showing the mechanism.",
                "Each rival explanation raised (at minimum: idempotency-cache eviction; the orders v1.4.2 deploy) "
                "is confirmed or ruled out with evidence.",
            ],
            "evidence_standard": "Log claims cite merged.log line numbers and quote the line. Code claims cite "
                                 "file:line. A claim about N cases lists the N request ids. Static-only claims say "
                                 "so and carry at most 'med' confidence.",
            "stop_if": [],
        },
        "lanes": [
            {"name": "static", "archetype": "static-trace", "resources": ["source"], "verify_default": "adversarial",
             "mandate": "Read the three services; trace how a request, its ids and its idempotency key flow "
                        "from gateway to inventory.",
             "evidence_standard": "Cite file:line for every claim; static-only claims are at most 'med'."},
            {"name": "logs", "archetype": "log-mining", "resources": ["logs"], "verify_default": "light",
             "mandate": "Mine logs/merged.log: timeline, onset of drift, and end-to-end traces of affected requests.",
             "evidence_standard": "Cite merged.log line numbers and quote lines; list request ids for counts."},
            {"name": "ops", "archetype": "env-diff", "resources": ["config"], "verify_default": "light",
             "mandate": "Config and deploys: what changed, when, and whether it lines up with the onset."},
            {"name": "skunkworks", "archetype": "skunkworks", "resources": ["source", "logs", "config"],
             "verify_default": "light",
             "mandate": "Generalist: unroutable requests, cross-lane asks, salvage of failed work."},
        ],
        "budget": {"max_concurrent": 4, "rounds_per_checkpoint": 1, "max_rounds": 4, "max_agents_per_segment": 30,
                   "max_tasks_per_lane_round": 2, "verify_rounds": 2, "max_children": 0, "stall_rounds": 2},
        "models": {}, "effort": {}, "agent_types": {},
    }


class State:
    def __init__(self, root: Path):
        self.root = root
        if root.exists():
            if not (root / ".exp-state").exists():
                raise SystemExit(f"refusing to replace {root}: not created by build_state.py")
            shutil.rmtree(root)
        root.mkdir(parents=True)
        (root / ".exp-state").touch()
        for d in ("bin", "prompts", "archetypes"):
            shutil.copytree(KIT / d, root / d, ignore=shutil.ignore_patterns("__pycache__"))
        (root / "manifest.json").write_text(json.dumps(manifest(), indent=1) + "\n")
        self.board = str(root / "bin" / "board.py")
        Path(self.board).chmod(0o755)
        self.b("validate")
        self.b("scaffold")

    def b(self, *args, who=None, stdin=None) -> str:
        cmd = [self.board, *args] + (["--as", who] if who else [])
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
        if p.returncode:
            raise SystemExit(f"board.py {' '.join(args[:3])} failed:\n{p.stdout}{p.stderr}")
        return p.stdout.strip()

    def post(self, lane, kind, subject, body, who, conf=None, tags="", refs="", supersedes=""):
        args = ["post", "--lane", lane, "--kind", kind, "--subject", subject, "--body", "-"]
        for flag, val in (("--confidence", conf), ("--tags", tags), ("--refs", refs), ("--supersedes", supersedes)):
            if val:
                args += [flag, val]
        return self.b(*args, who=who, stdin=body).splitlines()[-1]

    def plan(self, lane, tasks, rnd=1):
        self.b("plan", "save", "--lane", lane, "--round", str(rnd), "--inflight", "", who=f"{lane}/plan",
               stdin=json.dumps({"tasks": tasks, "notes": "scripted state"}))

    def write(self, rel, text, who):
        self.b("write", "--path", rel, who=who, stdin=text)

    def task(self, tid, notes, summary, board_ids, artifacts=(), status="done"):
        lane = tid.split("-")[0]
        who = f"{lane}/{tid}"
        self.b("task", "start", "--id", tid, who=who)
        for n in notes:
            self.b("task", "note", "--id", tid, "--text", n, who=who)
        args = ["task", "finish", "--id", tid, "--status", status, "--summary", summary]
        if board_ids:
            args += ["--board-ids", ",".join(board_ids)]
        if artifacts:
            args += ["--artifacts", ",".join(artifacts)]
        self.b(*args, who=who)

    def accept(self, tid, summary):
        lane = tid.split("-")[0]
        self.b("task", "review", "--id", tid, "--verdict", "accept", "--summary", summary, who=f"{lane}/challenger")


# ------------------------------------------------------------------ shared content

def q(n):
    """merged.log line n, quoted with its number."""
    return f"  {n}: {LOG[n - 1]}"


def trace_rows(cases):
    rows = ["| rid | timeout lines | retry lines | inventory `reserve ok` lines (key) | orders confirmed | orders duplicate | units reserved / confirmed |",
            "|---|---|---|---|---|---|---|"]
    for a in cases:
        keyed = ", ".join(f"{ln} ({LOG[ln - 1].split('key=')[1].split()[0]})" for ln in sorted(a["reserve_lines"]))
        n = len(a["reserve_lines"])
        rows.append(f"| {a['rid']} | {', '.join(map(str, a['timeout_lines']))} | {', '.join(map(str, a['retry_lines']))} "
                    f"| {keyed} | {', '.join(map(str, a['confirmed_lines']))} | {', '.join(map(str, a['duplicate_lines'])) or '-'} "
                    f"| {n * a['qty']} / {a['qty']} |")
    return "\n".join(rows)


STATIC_TASK = {
    "id": "static-r01-01", "title": "Trace the idempotency key from gateway to inventory", "kind": "trace",
    "objective": "Establish how the idempotency key is derived, passed and checked across gateway, orders and "
                 "inventory, and whether a retried request can reserve stock twice.",
    "instructions": "Read services/gateway.py, orders.py, inventory.py and common.py. Follow one POST /orders call "
                    "through every hop, including what happens on an upstream timeout.",
    "deliverable": "Board finding(s) with file:line for key derivation, propagation and the idempotency check, "
                   "stating whether a retry reuses the key. Static-only: say so.",
    "resources": ["source"], "deps": [], "verify": "adversarial", "size": "short", "max_children": 0}

LOGS_TASK = {
    "id": "logs-r01-01", "title": "Trace timed-out requests end to end in merged.log", "kind": "analysis",
    "objective": "For requests that hit a gateway upstream timeout, establish what each service did and whether "
                 "stock was reserved more than once per request.",
    "instructions": "static-r01-01 reports that inventory keys are sha1('<rid>:<attempt>')[:8] (gateway.py). Use that "
                    "to attribute inventory lines to requests. Trace at least 5 timed-out requests.",
    "deliverable": "Artifact trace_table.md: at least 5 timed-out rids with merged.log line numbers for timeout, "
                   "retry, every inventory reserve attributable to the request, and orders confirmed/duplicate; plus "
                   "a finding saying how reserves were attributed and what the table shows.",
    "resources": ["logs"], "deps": ["static-r01-01"], "verify": "light", "size": "short", "max_children": 0}


def static_body(derive_ref, check_ref, call_ref, wrong_mechanism=False):
    if wrong_mechanism:      # S4: real lines, two statements about them that the code contradicts
        return (f"{derive_ref} `return short_hash(f\"{{rid}}:{{attempt}}\")` — the key is derived from the request id AND the "
                f"attempt number; post_order() calls idem_key(rid, attempt) inside the retry loop ({call_ref}), so every retry "
                f"carries a new key.\n"
                f"services/common.py:{REL['call_not_cancelled']} on timeout the callee is cancelled, so a timed-out attempt never "
                f"reaches inventory; only the retries reserve.\n"
                f"{check_ref} `if key in self.idem:` is the replay check, but inventory.py:35 increments `reserved` before the stock "
                f"check runs, so a retry that is later rejected still leaves units reserved — that is where reserved exceeds confirmed.\n"
                f"services/orders.py:{REL['orders_rid_dedupe']} orders dedupes by rid and confirms once.\n"
                f"Net: retried requests leave reserved units behind even though only one attempt reaches inventory successfully.")
    return (f"{derive_ref} `return short_hash(f\"{{rid}}:{{attempt}}\")` — the key is derived from the request id AND the "
            f"attempt number; post_order() calls idem_key(rid, attempt) inside the retry loop ({call_ref}), "
            f"so every retry carries a new key.\n"
            f"Propagation: gateway.py:{RC + 12} passes the key to orders.place; services/orders.py:{SRC_LINE('orders.py', 'def place(')} receives it and "
            f"services/orders.py:{SRC_LINE('orders.py', 'self.inventory.reserve, key')} forwards it unchanged to inventory.reserve — before the rid dedupe below.\n"
            f"{check_ref} `if key in self.idem:` is inventory's only replay check, keyed on that string; a retry's key is "
            f"never in the cache, so it reserves again.\n"
            f"services/common.py:{REL['call_not_cancelled']} on timeout the caller stops waiting but the callee is not "
            f"cancelled, so the timed-out first call can still reserve.\n"
            f"services/orders.py:{REL['orders_rid_dedupe']} orders dedupes by rid and confirms once.\n"
            f"Net: a request whose first upstream call times out but completes reserves twice and confirms once.")


def do_static(s: State, variant):
    who = "static/static-r01-01"
    derive, check = f"services/gateway.py:{RC}", f"services/inventory.py:{REL['inventory_idem_check']}"
    subject = "A gateway retry sends a new idempotency key, so inventory cannot recognise it as a replay"
    conf, tail = "med", "\nStatic-only: read from source, not yet checked against logs. Falsified if retries reuse attempt 1's key."
    if variant == "F1":      # right idea, citations point at the wrong file / wrong line
        derive, check = "services/orders.py:31", f"services/inventory.py:{REL['inventory_evict']}"
    call_ref = f"gateway.py:{RC + 11}"
    if variant == "S1":      # near-miss: the call site is cited two lines late (the call() and the timeout branch)
        call_ref = f"gateway.py:{RC + 12}-{RC + 13}"
    if variant == "F3":      # static-only work presented as a confirmed production root cause
        subject = "ROOT CAUSE CONFIRMED: gateway retries double-reserve stock in production"
        conf = "high"
        tail = ("\nThis is what is happening in production: every drift in the reconcile job comes from this path, "
                "and the drift size matches the retried quantities.")
    bid = s.post("static", "finding", subject, static_body(derive, check, call_ref, variant == "S4") + tail, who, conf=conf,
                 tags="idempotency,retry", refs=f"{derive},{check},services/common.py:{REL['call_not_cancelled']}")
    s.task("static-r01-01",
           ["read gateway.py post_order(): retry loop calls idem_key(rid, attempt) each iteration",
            "read inventory.py reserve(): replay check is `key in self.idem`; LRU of idem_cache_size entries",
            "read common.py call(): timeout returns (None, True) but the forked callee has already run"],
           ("Retries carry a new idempotency key; timed-out attempts are cancelled, and reserved drifts because inventory "
            f"increments before its stock check. See {bid}." if variant == "S4" else
            "Retries carry a new idempotency key (derived from rid and attempt), so inventory reserves again; "
            f"orders dedupes by rid. See {bid}.") + (" Root cause confirmed." if variant == "F3" else " Static-only."),
           [bid])
    return bid


def do_logs(s: State, variant):
    who, td = "logs/logs-r01-01", "lanes/logs/tasks/logs-r01-01"
    cases = [a for a in KEY["affected"] if len(a["reserve_lines"]) >= 2][1:7]
    if variant == "verdict-2":   # honest partial work: only two requests traced
        cases = cases[:2]
    a0 = cases[0]
    attribution = ("Attribution: inventory lines carry only `key=`; computed sha1('<rid>:<attempt>')[:8] per attempt "
                   "(python3 -c \"import hashlib;print(hashlib.sha1(b'" + a0["rid"] + ":1').hexdigest()[:8])\" -> "
                   + a0["keys"][0] + ") and matched the `reserve ok` lines.")
    notes = ["grep -n 'upstream timeout' merged.log -> " + str(len(FACTS["timed_out_rids"])) + " distinct rids",
             "computed per-attempt keys with python3 hashlib for each traced rid and grepped them",
             "every traced rid: 2+ `reserve ok` under different keys, 1 `confirmed`, rest `duplicate request ignored`"]
    artifacts, bids = [f"{td}/trace_table.md"], []

    status = "partial" if variant == "verdict-2" else "done"
    if variant == "S2":      # row 5: real `reserve ok` lines, but they belong to other requests
        own = {ln for a in KEY["affected"] for ln in a["reserve_lines"]}
        target = cases[4]["reserve_lines"][0]
        others = sorted((i for i, l in enumerate(LOG, 1) if "reserve ok" in l and i not in own), key=lambda i: abs(i - target))[:2]
        cases = cases[:4] + [{**cases[4], "reserve_lines": sorted(others)}] + cases[5:]
    if variant in ("C-logs", "verdict", "verdict-2", "S2", "S3"):
        s.write(f"{td}/trace_table.md", "# Timed-out requests traced end to end\n\n" + trace_rows(cases) + "\n\n" + attribution + "\n", who)
        body = (f"Traced {len(cases)} timed-out requests ({', '.join(a['rid'] for a in cases)}); table in {td}/trace_table.md.\n"
                f"Each reserved 2 or more times under different keys and was confirmed once. Example {a0['rid']}:\n"
                + "\n".join(q(n) for n in sorted(a0["timeout_lines"][:1] + a0["reserve_lines"] + a0["confirmed_lines"] + a0["duplicate_lines"][:1]))
                + f"\n{attribution}\nFalsified if any traced rid has a single `reserve ok` across its attempt keys.")
        subject = f"{len(cases)} of {len(cases)} traced timed-out requests reserved stock more than once under different keys"
        if variant == "S3":  # true for 14 of the 15: r-0122 timed out, was rejected for stock and reserved nothing
            allr = FACTS["timed_out_rids"]
            subject = f"All {len(allr)} timed-out requests reserved stock more than once ({len(cases)} traced in full)"
            body += (f"\nThe remaining timed-out requests were checked the same way by key and show the same pattern: "
                     f"{', '.join(r for r in allr if r not in [a['rid'] for a in cases])}.")
        bids.append(s.post("logs", "finding", subject,
                           body, who, conf="high", tags="retry,double-reserve",
                           refs=",".join(f"logs/merged.log:{n}" for n in a0["reserve_lines"]) + f",{td}/trace_table.md"))
        summary = f"{len(cases)} timed-out requests traced with line numbers; all reserved 2+ times under different keys, confirmed once. {bids[0]}; table in trace_table.md."
        if variant == "S3":
            summary = f"All {len(FACTS['timed_out_rids'])} timed-out requests double-reserve; {len(cases)} traced with line numbers in trace_table.md. {bids[0]}."
        if variant == "verdict-2":
            summary = f"PARTIAL: traced {len(cases)} of the >= 5 requested before stopping; both reserved twice under different keys. {bids[0]}."

    elif variant == "F2":    # one case traced, conclusion stated for all
        s.write(f"{td}/trace_table.md", "# Timed-out requests traced end to end\n\n" + trace_rows(cases[:1]) + "\n\n" + attribution + "\n", who)
        n = len(FACTS["timed_out_rids"])
        body = (f"All {n} timed-out requests reserve stock twice. Confirmed across the whole log. Example {a0['rid']}:\n"
                + "\n".join(q(x) for x in sorted(a0["reserve_lines"] + a0["confirmed_lines"])) + f"\n{attribution}\nThe others follow the same pattern.")
        bids.append(s.post("logs", "finding", f"All {n} timed-out requests double-reserve stock", body, who, conf="high",
                           tags="retry,double-reserve", refs=f"logs/merged.log:{a0['reserve_lines'][0]},{td}/trace_table.md"))
        notes = notes[:1] + [f"traced {a0['rid']} in full; pattern is clear"]
        summary = f"All {n} timed-out requests double-reserve; see {bids[0]} and trace_table.md."

    elif variant == "F4":    # two of six rows carry invented keys and line numbers
        fake = json.loads(json.dumps(cases))
        rows = trace_rows(cases).splitlines()
        for i, (k1, k2, base) in zip((2, 4), (("4be07a1c", "d91f3e55", 388), ("a07c21fe", "5e3b9d02", 611))):
            a = fake[i]
            rows[2 + i] = (f"| {a['rid']} | {base} | {base + 1} | {base + 3} ({k1}), {base + 7} ({k2}) | {base + 4} | {base + 8} "
                           f"| {2 * a['qty']} / {a['qty']} |")
        s.write(f"{td}/trace_table.md", "# Timed-out requests traced end to end\n\n" + "\n".join(rows) + "\n\n" + attribution + "\n", who)
        bad = fake[2]
        body = (f"Traced {len(cases)} timed-out requests ({', '.join(a['rid'] for a in cases)}); table in {td}/trace_table.md.\n"
                f"Each reserved twice under different keys and was confirmed once. Example {bad['rid']}:\n"
                f"  391: {LOG[390][:24]} inventory INFO  reserve ok key=4be07a1c sku=SKU-2 qty={bad['qty']} took=2391ms\n"
                f"  395: {LOG[394][:24]} inventory INFO  reserve ok key=d91f3e55 sku=SKU-2 qty={bad['qty']} took=144ms\n"
                f"{attribution}")
        bids.append(s.post("logs", "finding", f"{len(cases)} of {len(cases)} traced timed-out requests reserved stock more than once under different keys",
                           body, who, conf="high", tags="retry,double-reserve", refs=f"logs/merged.log:391,logs/merged.log:395,{td}/trace_table.md"))
        summary = f"{len(cases)} timed-out requests traced with line numbers; all double-reserve. {bids[0]}; table in trace_table.md."

    elif variant == "F5":    # real co-occurrence, wrong causal claim, rival never examined
        ev = [i for i, l in enumerate(LOG, 1) if "idem evict" in l]
        windows = {}
        for i in ev:
            windows[LOG[i - 1][11:15] + "x"] = windows.get(LOG[i - 1][11:15] + "x", 0) + 1
        drift = [i for i, l in enumerate(LOG, 1) if "reconcile drift" in l]
        s.write(f"{td}/evictions_vs_drift.md", "# Evictions per 10 minutes vs drift\n\n| window | idem evictions |\n|---|---|\n"
                + "\n".join(f"| {w} | {c} |" for w, c in sorted(windows.items())) + f"\n\nreconcile drift lines: {len(drift)} "
                f"(last: line {drift[-1]}).\n", who)
        artifacts = [f"{td}/evictions_vs_drift.md"]
        body = (f"inventory evicts idempotency keys from {FACTS['first_evict_ts'][11:19]} on ({len(ev)} `idem evict` lines, first at line {ev[0]}):\n{q(ev[0])}\n"
                f"Drift grows through the same period (last reconcile: line {drift[-1]}):\n{q(drift[-1])}\n"
                "When a retried request arrives after its key was evicted, inventory no longer recognises it and reserves again. "
                "The cache (64 entries) is too small for the traffic after 10:15. Eviction counts per window are in evictions_vs_drift.md.")
        bids.append(s.post("logs", "finding", "Idempotency-cache eviction in inventory causes the double reservations", body, who,
                           conf="high", tags="eviction,double-reserve", refs=f"logs/merged.log:{ev[0]},logs/merged.log:{drift[-1]},{td}/evictions_vs_drift.md"))
        notes = [f"grep -c 'idem evict' -> {len(ev)}; first at line {ev[0]}", "drift keeps growing while evictions continue",
                 "cache size 64 (config/inventory.yaml) vs ~160 requests"]
        summary = f"Cause is idempotency-cache eviction: evicted keys are reserved again on retry. {bids[0]}."

    elif variant == "F6":    # careful work on a different question
        rej = [i for i, l in enumerate(LOG, 1) if "reserve rejected" in l]
        s.write(f"{td}/sku9_rejections.md", "# SKU-9 rejections\n\n" + "\n".join(q(i) for i in rej) + "\n", who)
        artifacts = [f"{td}/sku9_rejections.md"]
        body = (f"{len(rej)} `reserve rejected` lines, all sku=SKU-9 (stock 6 in config/inventory.yaml), first:\n{q(rej[0])}\n"
                "Customers ordering SKU-9 receive 409 from late morning. Recommend raising SKU-9 stock or alerting on low stock.")
        bids.append(s.post("logs", "finding", f"SKU-9 runs out of stock: {len(rej)} reservations rejected", body, who, conf="high",
                           tags="stock,sku-9", refs=f"logs/merged.log:{rej[0]},config/inventory.yaml,{td}/sku9_rejections.md"))
        notes = ["grep -n 'reserve rejected' merged.log", "all rejections are SKU-9; stock is 6"]
        summary = f"SKU-9 stock exhaustion explains the rejected reservations; {bids[0]}. Recommend a stock alert."

    s.task("logs-r01-01", notes, summary, bids, artifacts, status=status)
    return bids[0]


# ------------------------------------------------------------------ recipes

def review_state(root: Path, variant: str):
    s = State(root)
    if variant in ("C-static", "F1", "F3", "S1", "S4"):
        s.plan("static", [STATIC_TASK])
        do_static(s, variant)
        return {"task": "static-r01-01", "lane": "static", "verify": "adversarial", "title": STATIC_TASK["title"]}
    s.plan("static", [STATIC_TASK])
    do_static(s, "C-static")
    s.accept("static-r01-01", "Citations re-checked against source; claim holds at 'med' as a static-only finding.")
    s.plan("logs", [LOGS_TASK])
    do_logs(s, variant)
    return {"task": "logs-r01-01", "lane": "logs", "verify": "light", "title": LOGS_TASK["title"]}


def verdict_state(root: Path, variant: str, judged: bool):
    s = State(root)
    s.plan("static", [STATIC_TASK])
    b_static = do_static(s, "C-static")
    s.accept("static-r01-01", "Citations re-checked against source; holds at 'med' as static-only.")
    s.plan("logs", [LOGS_TASK])
    b_logs = do_logs(s, {"J2": "verdict-2", "J5": "F4"}.get(variant, "verdict"))
    if variant == "J5":      # the challenger rejected this task; nothing on the board entries says so
        s.b("task", "review", "--id", "logs-r01-01", "--verdict", "redo", "--summary",
            "Two of six table rows do not exist in merged.log as cited; the table cannot be trusted. Redo the traces.",
            "--objection", "rows r-0053 and r-0061: the keys and line numbers given are not in merged.log",
            who="logs/challenger")
    else:
        s.accept("logs-r01-01", "Re-derived keys for two rids and re-read the cited lines; table is accurate."
                 + (" Accepted as partial: two requests, not the five asked for." if variant == "J2" else ""))
    if variant == "J4":      # a rival explanation raised on a lane board; nobody picked it up
        s.post("logs", "hypothesis", "Rejected SKU-9 reservations may still be counted as reserved, inflating the drift",
               "SKU-9 is rejected for insufficient stock from 10:20 on (`reserve rejected` lines). If inventory counts a rejected "
               "reservation before rejecting it, reserved would exceed confirmed without any retry. Not checked: compare the drift "
               "per SKU with the rejections, and read inventory.reserve().", "logs/logs-r01-01", conf="low", tags="rival,sku-9")

    cases = [a for a in KEY["affected"] if len(a["reserve_lines"]) >= 2][1:7]
    early = next(a for a in KEY["affected"] if a["rid"] in FACTS["double_reserved_before_deploy"])
    syn = "synthesizer"
    mech = ("the idempotency key is sha1('<rid>:<attempt>')[:8], so a retry after a gateway timeout is a new key to inventory; "
            "the timed-out first call is not cancelled and reserves, the retry reserves again, and orders (dedupe by rid) confirms once")
    if variant == "J3":      # the shared root-cause entry asserts the mechanism that S3 rules out
        mech = ("after a gateway timeout the retry reaches inventory once its idempotency key has been evicted from the 64-entry "
                "cache, so inventory treats the replay as new and reserves again; orders (dedupe by rid) confirms once")
    s1 = s.post("shared", "finding", f"Root cause: services/gateway.py:{RC} — retries double-reserve stock",
                f"services/gateway.py:{RC}: {mech}.\nStatic trace {b_static} (accepted) and log traces {b_logs}"
                + ("." if variant == "J5" else " (accepted)."),
                syn, conf="high", tags="root-cause", refs=f"services/gateway.py:{RC},{b_static},{b_logs}")
    shown = cases[:2] if variant == "J2" else cases   # J2: the lane work itself only traced two
    s2 = s.post("shared", "evidence", f"{len(shown)} affected requests traced end to end with merged.log line numbers",
                f"Requests {', '.join(a['rid'] for a in shown)}: gateway timeout and retry, two or more inventory `reserve ok` under "
                f"different per-attempt keys, one orders `confirmed`.\n"
                + ("Table: lanes/logs/tasks/logs-r01-01/trace_table.md." if variant == "J5" else trace_rows(shown)) + f"\nSource: {b_logs}.",
                syn, conf="high", tags="double-reserve", refs=f"{b_logs},lanes/logs/tasks/logs-r01-01/trace_table.md")
    s3 = s.post("shared", "finding", "Idempotency-cache eviction ruled out as the cause",
                f"(1) No inventory key has more than one `reserve ok` and there are 0 `reserve replay` lines "
                f"(grep -o 'reserve ok key=[0-9a-f]*' logs/merged.log | sort | uniq -d -> empty): an evicted-then-replayed key would show twice.\n"
                f"(2) Smallest eviction age is {FACTS['min_evict_age_s']}s; attempts are ~2.2s apart (timeout 2000ms + backoff 200ms).\n"
                f"(3) Drift first appears at {FACTS['first_drift_ts'][11:19]} (line {FACTS['first_drift_line']}); the first eviction is at {FACTS['first_evict_ts'][11:19]}.",
                "logs/logs-r01-02", conf="high", tags="eviction,ruled-out", refs=f"logs/merged.log:{FACTS['first_drift_line']}")
    s4 = s.post("shared", "finding", "The orders v1.4.2 deploy ruled out as the cause",
                f"{early['rid']} double-reserved at {early['first_ts'][11:19]} (reserve lines {', '.join(map(str, sorted(early['reserve_lines'])))}) and drift is "
                f"reported at line {FACTS['first_drift_line']} — both before the deploy at {FACTS['deploy_ts'][11:19]} (config/deploys.log). "
                f"The changelog for v1.4.2 touches neither keys nor retries.",
                "ops/ops-r01-01", conf="high", tags="deploy,ruled-out", refs=f"config/deploys.log,logs/merged.log:{FACTS['first_drift_line']}")
    if variant == "J1":      # the only entry ruling out eviction has since been refuted
        s.b("amend", "--id", s3, "--set", "status=refuted", "--note",
            "Re-ran the commands: the uniq -d check only proves no key repeats, which is equally true if keys differ per attempt AND "
            "says nothing about a replay whose first result was evicted before it was stored; points (2) and (3) were not reproduced "
            "(the age field was read from the wrong column). Not established.", who="logs/challenger")
    s.write("shared/synthesis.md",
            f"## Confirmed\n- Root cause at services/gateway.py:{RC} ({s1})\n- {len(shown)} affected requests traced ({s2})\n"
            f"- Eviction ruled out ({s3}){' — REFUTED by challenger, see amendments' if variant == 'J1' else ''}\n- Deploy ruled out ({s4})\n\n"
            "## Live hypotheses\n(none)\n\n## Refuted\n- orders v1.4.2 deploy as cause\n"
            + ("" if variant == "J1" else "- idempotency-cache eviction as cause\n") + "\n## Contradictions\n(none recorded)\n\n## Open questions\n(none)\n", syn)
    ids = {"root_cause": s1, "traces": s2, "eviction": s3, "deploy": s4}
    if judged:
        c = manifest()["criteria"]["success"]
        s.b("judge", "save", "--round", "1", who="judge", stdin=json.dumps({
            "met": True, "progress": True, "gaps": [],
            "summary": f"All three criteria met: root cause {s1}, traces {s2}, rivals ruled out {s3} {s4}.",
            "criteria": [{"criterion": c[0], "met": True, "evidence": [s1], "note": "file:line with mechanism"},
                         {"criterion": c[1], "met": True, "evidence": [s2], "note": "traced with line numbers"},
                         {"criterion": c[2], "met": True, "evidence": [s3, s4], "note": "both rivals ruled out"}]}))
    return {"ids": ids}


# ------------------------------------------------------------------ X1: a worker's starting point

WORK_VARIANTS = ["T", "T-deps", "H"]

WORK_TASK = {
    "id": "logs-r02-01", "title": "Trace timed-out requests end to end in merged.log", "kind": "analysis",
    "objective": "For requests that hit a gateway upstream timeout, establish what each service did for that request and "
                 "whether stock was reserved more than once for it.",
    "instructions": "Work from logs/merged.log. Inventory lines do not carry the request id, so say exactly how you tied "
                    "inventory lines to a request. Trace at least 5 timed-out requests.",
    "deliverable": "Artifact trace.json in your task directory: a JSON list of objects "
                   "{\"rid\": \"r-0000\", \"reserve_lines\": [merged.log line numbers of every inventory `reserve ok` line that "
                   "belongs to this request]} for at least 5 timed-out requests; plus a board finding that states the "
                   "attribution method and what the traces show.",
    "resources": ["logs"], "deps": [], "verify": "light", "size": "short", "max_children": 0}

KB_PAGE = """# How a gateway request is tied to its inventory lines  (kb/idempotency-key.md)

Explainer page, read from services/ as deployed. Not evidence: cite file:line or log lines yourself.

- gateway.py:{rc_def}-{rc}  `idem_key(rid, attempt)` = sha1(f"{{rid}}:{{attempt}}").hexdigest()[:8] — one key per upstream
  call (called at gateway.py:{call}, inside the retry loop; max_attempts=3 in config/gateway.yaml).
- orders.py:{o_place}-{o_fwd}  orders forwards that key unchanged to inventory.reserve; orders itself dedupes by rid
  (orders.py:{o_dedupe}), and only after reserving.
- inventory.py:{i_check}  the only replay check is `key in self.idem` (an LRU of 64 entries; evictions at inventory.py:{i_evict}).
- common.py:{c_call}  a timed-out call is not cancelled: the callee runs to completion, the caller just stops waiting.
- To attribute a log line: python3 -c "import hashlib;print(hashlib.sha1(b'r-0012:1').hexdigest()[:8])" and grep that
  key in logs/merged.log; repeat for attempts 2 and 3.
"""


def work_state(root: Path, variant: str):
    return _work_state(root, variant)[0]


def _work_state(root: Path, variant: str, plan_round2=True, save_judge1=True, make_arms=True):
    """Round 1 is done, round 2 has one queued logs task. T: the board holds the true lead. H: the board leads with
    the eviction red herring and the true lead sits un-promoted on the static lane board (reachable by query only)."""
    herring = variant == "H"
    s = State(root)
    syn = "synthesizer"

    # --- round 1: static
    s.plan("static", [STATIC_TASK])
    if herring:
        who = "static/static-r01-01"
        b_evict = s.post("static", "hypothesis", "inventory's idempotency LRU (64 entries) can forget a key, so a replay would reserve again",
                         f"services/inventory.py:{REL['inventory_idem_check']} `if key in self.idem:` is the only replay check and "
                         f"services/inventory.py:{REL['inventory_evict']} evicts the oldest entry once there are more than idem_cache_size (64, "
                         f"config/inventory.yaml). A request replayed after its key was evicted is reserved a second time.\n"
                         f"Static-only. Falsified if no replay ever arrives after its key's eviction.", who, conf="med",
                         tags="idempotency,eviction", refs=f"services/inventory.py:{REL['inventory_idem_check']},services/inventory.py:{REL['inventory_evict']}")
        b_static = s.post("static", "note", "gateway builds the idempotency key from rid and attempt (not followed up)",
                          f"services/gateway.py:{RC} `return short_hash(f\"{{rid}}:{{attempt}}\")`; short_hash is sha1(...)[:8] (common.py). "
                          f"Out of time on this task; may matter for retries.", who, conf="low", tags="idempotency",
                          refs=f"services/gateway.py:{RC}")
        s.task("static-r01-01", ["read inventory.py reserve() and _remember(): LRU eviction of idempotency results",
                                 "skimmed gateway.py: key built from rid and attempt — noted, not followed up"],
               f"inventory's idempotency cache evicts keys, so a late replay would reserve again ({b_evict}); static-only. Side note {b_static}.",
               [b_evict, b_static])
        s.accept("static-r01-01", "Eviction path re-read and correctly cited; holds at 'med' as a static-only hypothesis.")
    else:
        b_static = do_static(s, "C-static")
        s.accept("static-r01-01", "Citations re-checked against source; claim holds at 'med' as a static-only finding.")

    # --- round 1: logs (timeline) and ops (deploys)
    timeline = {"id": "logs-r01-01", "title": "Timeline: onset of drift, timeouts, evictions", "kind": "analysis",
                "objective": "When does reconcile drift start, and what else changes around then?",
                "instructions": "grep merged.log for reconcile, timeout and evict lines; report first occurrences and counts.",
                "deliverable": "A finding with line numbers for first drift, first timeout, first eviction, and counts.",
                "resources": ["logs"], "deps": [], "verify": "light", "size": "short", "max_children": 0}
    s.plan("logs", [timeline])
    ev = [i for i, l in enumerate(LOG, 1) if "idem evict" in l]
    to = [i for i, l in enumerate(LOG, 1) if "upstream timeout" in l]
    who = "logs/logs-r01-01"
    b_time = s.post("logs", "finding", f"Drift is first reported at {FACTS['first_drift_ts'][11:19]}; {len(FACTS['timed_out_rids'])} requests hit a gateway timeout; evictions start at {FACTS['first_evict_ts'][11:19]}",
                    f"First `reconcile drift`:\n{q(FACTS['first_drift_line'])}\nFirst `upstream timeout`:\n{q(to[0])}\nFirst `idem evict`:\n{q(ev[0])}\n"
                    f"Timed-out requests ({len(FACTS['timed_out_rids'])}): {', '.join(FACTS['timed_out_rids'])}. Evictions: {len(ev)}.",
                    who, conf="high", tags="timeline,onset", refs=f"logs/merged.log:{FACTS['first_drift_line']},logs/merged.log:{to[0]},logs/merged.log:{ev[0]}")
    b_q = s.post("logs", "question", "How is the `key=` on inventory lines related to a request id?",
                 "Inventory lines carry only key=<8 hex>; gateway and orders lines carry rid. Without the relation, reserves cannot be "
                 "attributed to requests from the log.", who, tags="idempotency,attribution")
    s.task("logs-r01-01", ["grep -n 'reconcile drift' | head -1", "grep -c 'upstream timeout'; listed the rids", "grep -n 'idem evict' | head -1"],
           f"Timeline established ({b_time}); open question on key-to-request attribution ({b_q}).", [b_time, b_q])
    s.accept("logs-r01-01", "Line numbers and counts re-checked with grep; accurate.")

    deploys = {"id": "ops-r01-01", "title": "Deploys and config around the onset", "kind": "read",
               "objective": "What was deployed or reconfigured near the onset?", "instructions": "Read config/ and deploys.log.",
               "deliverable": "A finding listing deploys with timestamps and the relevant config values.",
               "resources": ["config"], "deps": [], "verify": "light", "size": "short", "max_children": 0}
    s.plan("ops", [deploys])
    b_ops = s.post("ops", "finding", f"orders v1.4.2 was deployed at {FACTS['deploy_ts'][11:19]}; gateway timeout 2000 ms, 3 attempts; inventory idempotency cache 64 entries",
                   "config/deploys.log: orders v1.4.2 by ci (changelog: http client bump, reconcile log wording). config/gateway.yaml: timeout_ms 2000, "
                   "max_attempts 3, backoff_ms 200. config/orders.yaml: inventory_timeout_ms 5000. config/inventory.yaml: idem_cache_size 64.",
                   "ops/ops-r01-01", conf="high", tags="deploy,config", refs="config/deploys.log,config/gateway.yaml,config/inventory.yaml")
    s.task("ops-r01-01", ["read config/*.yaml and deploys.log"], f"Deploy and config facts recorded ({b_ops}).", [b_ops])
    s.accept("ops-r01-01", "Values match the files.")

    # --- synthesis, judge, round 2 plan
    if herring:
        lead = s.post("shared", "hypothesis", "Leading hypothesis: idempotency-cache eviction lets replays reserve twice",
                      f"inventory forgets idempotency keys once more than 64 are stored ({b_evict}); evictions are frequent from "
                      f"{FACTS['first_evict_ts'][11:19]} and the drift keeps growing through the same period ({b_time}). Needs log confirmation.",
                      syn, conf="med", tags="eviction,leading", refs=f"{b_evict},{b_time}")
        hyp = f"- LEADING: idempotency-cache eviction ({lead}, med) — static-only; logs lane to confirm\n- orders v1.4.2 deploy ({b_ops}, low)\n"
        gaps = ["[logs] trace at least 5 affected requests end to end with line numbers", "[logs] show evicted keys being reserved again"]
    else:
        lead = s.post("shared", "finding", f"Leading hypothesis: gateway retries send a new idempotency key (services/gateway.py:{RC})",
                      f"The key is sha1('<rid>:<attempt>')[:8] (services/gateway.py:{RC}, short_hash in common.py), so a retry after a gateway timeout is a "
                      f"new key to inventory; the timed-out call is not cancelled. Static-only ({b_static}); needs log confirmation. "
                      f"This answers {b_q}: compute the key per attempt and grep it.",
                      syn, conf="med", tags="idempotency,retry,leading", refs=f"services/gateway.py:{RC},{b_static},{b_q}")
        hyp = f"- LEADING: retries carry a new idempotency key ({lead}, med) — static-only; logs lane to confirm\n- idempotency-cache eviction (low, untested)\n- orders v1.4.2 deploy ({b_ops}, low)\n"
        gaps = ["[logs] trace at least 5 affected requests end to end with line numbers", "[logs] rule the eviction and deploy explanations in or out"]
    synthesis = (f"## Confirmed\n- Timeline: first drift {FACTS['first_drift_ts'][11:19]}, first eviction {FACTS['first_evict_ts'][11:19]}, "
                 f"{len(FACTS['timed_out_rids'])} timed-out requests ({b_time})\n- Deploy and config facts ({b_ops})\n\n## Live hypotheses\n{hyp}\n"
                 f"## Refuted\n(none)\n\n## Contradictions\n(none recorded)\n\n## Open questions\n"
                 + ("(none)\n" if not herring else f"- {b_q}: how inventory keys relate to request ids\n"))
    s.write("shared/synthesis.md", synthesis, syn)
    if save_judge1:
        s.b("judge", "save", "--round", "1", who="judge", stdin=json.dumps({
            "met": False, "progress": True, "gaps": gaps, "summary": "Timeline and config established; no end-to-end traces yet; mechanism unconfirmed.",
            "criteria": [{"criterion": c, "met": False, "evidence": [], "note": ""} for c in manifest()["criteria"]["success"]]}))
    if plan_round2:
        task = dict(WORK_TASK, deps=["static-r01-01"] if variant == "T-deps" else [])
        s.plan("logs", [task], rnd=2)
    ids = {"lead": lead, "timeline": b_time, "question": b_q, "ops": b_ops, "static": b_static,
           "evict": locals().get("b_evict"), "synthesis": synthesis}
    if not make_arms:
        return {}, s, ids

    # --- material for the arms (prepare.py appends what an arm asks for, then removes this directory)
    arms = root / "_arms"
    arms.mkdir()
    attached = [lead, b_time]
    full = s.b("query", "--lane", "all", "--id", ",".join(attached), "--format", "full")
    (arms / "push.md").write_text("\n## Context for this task (attached by the planner: the current synthesis and the board entries it judged relevant)\n\n"
                                  "### shared/synthesis.md\n\n" + synthesis + "\n### Attached board entries\n\n" + full + "\n")
    # facts-only push: findings and evidence in full; hypotheses by id and one line, marked as under test
    facts = [b for b in attached if s.b("query", "--lane", "all", "--id", b, "--format", "json") and
             json.loads(s.b("query", "--lane", "all", "--id", b, "--format", "json").splitlines()[0])["kind"] in ("finding", "evidence")]
    under_test = [b for b in attached if b not in facts]
    (arms / "facts.md").write_text(
        "\n## Context for this task (attached by the planner: established entries only)\n\n### Established so far\n\n"
        + s.b("query", "--lane", "all", "--id", ",".join(facts), "--format", "full") + "\n\n### Open questions\n\n"
        + s.b("query", "--lane", "all", "--kind", "question", "--format", "brief") + "\n\n### Hypotheses under test\n\n"
        + ("".join(f"- {b}: not established. Do not assume it; report whether your evidence supports or contradicts it.\n" for b in under_test)
           or "- (none attached)\n"))
    (arms / "push-labelled.md").write_text(
        (arms / "push.md").read_text()
        + "\nNote on the above: a *hypothesis* — including the LEADING one — is not established. Do not explain your "
          "observations with it unless your own evidence requires it; state plainly whether what you found supports or contradicts it.\n")
    page = KB_PAGE.format(rc_def=RC - 2, rc=RC, call=RC + 11, o_place=SRC_LINE("orders.py", "def place("),
                          o_fwd=SRC_LINE("orders.py", "self.inventory.reserve, key"), o_dedupe=REL["orders_rid_dedupe"],
                          i_check=REL["inventory_idem_check"], i_evict=REL["inventory_evict"], c_call=REL["call_not_cancelled"] - 2)
    (arms / "kb.md").write_text("\n## Knowledge-base page attached to this task\n\n" + page)
    (arms / "kb-file.md").write_text(page)
    return {"task": "logs-r02-01", "lane": "logs", "title": WORK_TASK["title"], "verify": "light", "round": 2, "attached": attached}, s, ids


# ------------------------------------------------------------------ X3: a strategy decision point

STRATEGY_VARIANTS = ["S0", "S1", "S2"]


def strategy_state(root: Path, variant: str, nojudge: bool):
    """The board leads with the eviction red herring; the true lead is an un-promoted note on the static lane board.
    S0: end of round 1 on the TRUE-lead board — the per-attempt-key explanation leads at med, static-only (does the role keep it?).
    S1: end of round 1 — two red herrings live, and the timeline already holds what undermines both (nobody connected it).
    S2: end of round 2, stalled — the logs lane went looking for evicted keys being reserved again and found none (0 of N),
    reported as inconclusive; the synthesis still leads with eviction; the judge reports no progress.
    --nojudge leaves the last round un-judged (for the v1 baseline arm, where the judge's gaps are the only direction)."""
    board = "T" if variant == "S0" else "H"     # S0: the true lead is the board's leading (med, static-only) hypothesis
    _, s, ids = _work_state(root, board, plan_round2=False, save_judge1=not (nojudge and variant in ("S0", "S1")), make_arms=False)
    rnd = 1
    if variant == "S2":
        rnd = 2
        ev = [i for i, l in enumerate(LOG, 1) if "idem evict" in l]
        hunt = {"id": "logs-r02-01", "title": "Show evicted idempotency keys being reserved again", "kind": "analysis",
                "objective": "Confirm the leading hypothesis in the log: find requests whose key was evicted and then reserved again.",
                "instructions": "List evicted keys (`idem evict key=`) and look for a later `reserve ok` with the same key.",
                "deliverable": "A finding with the evicted keys that were reserved again and their line numbers, or a count showing there are none.",
                "resources": ["logs"], "deps": [], "verify": "light", "size": "short", "max_children": 0}
        s.plan("logs", [hunt], rnd=2)
        who = "logs/logs-r02-01"
        b_none = s.post("logs", "finding", f"No evicted key is reserved again in the log (0 of {len(ev)} evictions)",
                        f"grep -o 'idem evict key=[0-9a-f]*' logs/merged.log -> {len(ev)} keys; for each, a later `reserve ok key=<same>`: none. "
                        f"Also 0 `reserve replay` lines in the whole log. Could not confirm the hypothesis from this log; possibly replays "
                        f"of evicted keys are rare or fall outside the captured window. Inconclusive.",
                        who, conf="med", tags="eviction", refs=f"logs/merged.log:{ev[0]},{ids['lead']}")
        b_amb = s.post("logs", "note", "Reserves cannot be tied to requests by timing inside the SKU-5 bursts",
                       "Tried to attribute `reserve ok` lines to timed-out requests by sku, qty and start time (timestamp minus took). Inside the "
                       f"bursts several same-sku same-qty reserves start within ~300 ms of each other; attribution is ambiguous. See {ids['question']}.",
                       who, conf="med", tags="attribution")
        s.task("logs-r02-01", [f"{len(ev)} evicted keys; none reserved again later", "timing-based attribution ambiguous inside bursts"],
               f"PARTIAL: no evicted key is ever reserved again (0 of {len(ev)}); could not attribute reserves to requests inside bursts. {b_none}, {b_amb}.",
               [b_none, b_amb], status="partial")
        s.accept("logs-r02-01", "Counts re-checked with grep; accurate. Accepted as partial.")
        pressure = {"id": "static-r02-01", "title": "How quickly does the idempotency cache turn over?", "kind": "trace",
                    "objective": "Quantify cache pressure: when does the 64-entry LRU start evicting under the observed traffic?",
                    "instructions": "Read inventory._remember() and config; combine with request counts from the logs lane's timeline.",
                    "deliverable": "A finding on when eviction starts and how old evicted entries are.",
                    "resources": ["source"], "deps": [], "verify": "adversarial", "size": "short", "max_children": 0}
        s.plan("static", [pressure], rnd=2)
        b_press = s.post("static", "finding", f"The idempotency cache starts evicting once 64 keys are stored; evicted entries are at least {FACTS['min_evict_age_s']} s old",
                         f"services/inventory.py:{REL['inventory_evict']} evicts the oldest entry beyond idem_cache_size=64 (config/inventory.yaml). In merged.log the "
                         f"`age=` field of `idem evict` lines is never below {FACTS['min_evict_age_s']}s. Eviction is continuous from {FACTS['first_evict_ts'][11:19]}.",
                         "static/static-r02-01", conf="high", tags="eviction,cache", refs=f"services/inventory.py:{REL['inventory_evict']},config/inventory.yaml")
        s.task("static-r02-01", ["read _remember(); LRU popitem(last=False)", "grep 'idem evict' ages: min age in the log"],
               f"Cache evicts continuously after 64 keys; evicted entries are minutes old ({b_press}).", [b_press])
        s.accept("static-r02-01", "Eviction line and ages re-checked; accurate.")
        synthesis = (ids["synthesis"].split("## Live hypotheses")[0]
                     + f"- Cache turnover: eviction continuous from {FACTS['first_evict_ts'][11:19]}, evicted entries >= {FACTS['min_evict_age_s']}s old ({b_press})\n\n"
                     + f"## Live hypotheses\n- LEADING: idempotency-cache eviction ({ids['lead']}, med) — not yet confirmed in the log: no evicted key seen reserved "
                       f"again ({b_none}, inconclusive)\n- orders v1.4.2 deploy ({ids['ops']}, low)\n\n## Refuted\n(none)\n\n## Contradictions\n(none recorded)\n\n"
                       f"## Open questions\n- {ids['question']}: how inventory keys relate to request ids\n- attribution inside bursts is ambiguous ({b_amb})\n")
        s.write("shared/synthesis.md", synthesis, "synthesizer")
        if not nojudge:
            s.b("judge", "save", "--round", "2", who="judge", stdin=json.dumps({
                "met": False, "progress": False,
                "gaps": ["[logs] show an evicted key being reserved again, or find more log coverage",
                         "[logs] trace at least 5 affected requests end to end with line numbers"],
                "summary": "No criterion advanced: the leading hypothesis is still unconfirmed and no request has been traced end to end.",
                "criteria": [{"criterion": c, "met": False, "evidence": [], "note": ""} for c in manifest()["criteria"]["success"]]}))
    nxt = rnd + 1
    judge = json.loads((root / "judge" / f"round-{rnd:02d}.json").read_text()) if (root / "judge" / f"round-{rnd:02d}.json").exists() else {}
    gaps = judge.get("gaps", [])
    n_to = len(FACTS["timed_out_rids"])
    briefs = {
        "static": (f"## Status\n- static-r01-01 -> done (accepted): {'key derivation traced' if board == 'T' else 'eviction path traced; side note on key derivation not followed up'}\n"
                   + (f"- static-r02-01 -> done (accepted): cache turnover quantified\n" if rnd == 2 else "")
                   + "\n## Open items\n- no redo/failed/orphaned tasks; no mail; no steering\n- judge gaps: " + ("; ".join(g for g in gaps if "[static]" in g) or "none tagged for this lane") + "\n"
                   + "\n## Resources\n- source: ok (services/: common.py, gateway.py, orders.py, inventory.py, ORDERS_CHANGELOG.md)\n"
                   + "\n## Search space\n- gateway.py (~50 lines: request ids, idempotency key, retry loop), orders.py (~50: place, dedupe by rid, reconcile), "
                     "inventory.py (~50: reserve, idempotency LRU, eviction), common.py (~70: clock, logger, call/timeout)\n- nothing to skip; all four files are small\n"
                   + "\n## Recommendation\n- areas not yet traced end to end: the retry loop in gateway.py; the call/timeout path in common.py; how orders forwards what it receives\n"),
        "logs": (f"## Status\n- logs-r01-01 -> done (accepted): timeline (first drift, {n_to} timed-out requests, first eviction); open question on key-to-request attribution\n"
                 + (f"- logs-r02-01 -> partial (accepted): no evicted key reserved again (0 of 171); timing attribution ambiguous inside bursts\n" if rnd == 2 else "")
                 + "\n## Open items\n- no redo/failed/orphaned tasks; no mail; no steering\n- judge gaps: " + ("; ".join(g for g in gaps if "[logs]" in g) or "none tagged for this lane") + "\n"
                 + f"\n## Resources\n- logs: ok (logs/merged.log, {len(LOG)} lines, UTC, one file for gateway/orders/inventory)\n"
                 + f"\n## Search space\n- line kinds: gateway `POST /orders` / `upstream timeout` / `retry` (rid=, attempt=); orders `place` / `confirmed` / `duplicate request ignored` / `rejected` (rid=); "
                   f"inventory `reserve ok` / `reserve rejected` / `idem evict` (key=, sku=, qty=, took=); orders `reconcile drift` (sku=, reserved=, confirmed=)\n"
                   f"- {n_to} requests with `upstream timeout`; bursts of same-SKU requests within a second from 10:15 on\n- skip: `GET /health` lines\n"
                 + "\n## Recommendation\n- no request has been traced end to end yet; inventory lines carry key= not rid=, so attribution needs a method\n"),
        "ops": ("## Status\n- ops-r01-01 -> done (accepted): deploys and config recorded\n\n## Open items\n- no redo/failed/orphaned tasks; no mail; no steering\n- judge gaps: "
                + ("; ".join(g for g in gaps if "[ops]" in g) or "none tagged for this lane") + "\n\n## Resources\n- config: ok (config/*.yaml, config/deploys.log)\n"
                + "\n## Search space\n- config values already recorded (B-ops-0001); deploys.log has three entries; the orders changelog is in services/ORDERS_CHANGELOG.md\n"
                + "\n## Recommendation\n- little left in config; the deploy's relation to the onset is a log question\n"),
    }
    for lane, text in briefs.items():
        s.write(f"lanes/{lane}/scope/round-{nxt:02d}.md", text, f"{lane}/scope")
    return {"round": rnd, "plan_round": nxt, "lanes": ["static", "logs", "ops"], "note_id": ids["static"], "lead_id": ids["lead"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["review", "verdict", "work", "strategy"])
    ap.add_argument("--nojudge", action="store_true")
    ap.add_argument("variant")
    ap.add_argument("dir")
    ap.add_argument("--judged", action="store_true")
    a = ap.parse_args()
    ok = {"review": REVIEW_VARIANTS, "verdict": VERDICT_VARIANTS, "work": WORK_VARIANTS, "strategy": STRATEGY_VARIANTS}[a.kind]
    if a.variant not in ok:
        sys.exit(f"variant must be one of {ok}")
    root = Path(a.dir).resolve()
    info = (review_state(root, a.variant) if a.kind == "review" else work_state(root, a.variant) if a.kind == "work"
            else strategy_state(root, a.variant, a.nojudge) if a.kind == "strategy" else verdict_state(root, a.variant, a.judged))
    print(json.dumps({"dir": str(root), **info}))
