#!/usr/bin/env python3
"""Build the `stockd` investigation target: a git repo with history + production logs.

    python3 examples/stockd/build_target.py --out targets/stockd

Creates (deterministically — fixed identities and dates, so commit hashes are stable):
  <out>/repo   git repo, 18 commits. A lost-update race is introduced by the
               "perf: fast path for single-unit reservations" commit; a later
               "raise default workers 4 -> 16" commit makes it more frequent.
  <out>/logs   30 daily production logs (stockd-2026-08-DD.log): deploys, requests,
               noisy slow-request warnings, nightly reconciliation results.
  <out>/.stockd-target   marker (this script only ever replaces directories it created)

This file is the answer key: don't point investigation agents at it.
"""
import argparse
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- source by stage

def inventory_src(stage: int) -> str:
    fast_path = stage >= 11
    audit = stage >= 11
    restock = stage >= 10
    lines = [
        '"""In-memory inventory with reservations."""',
        "import threading",
        "import time" if audit else "",
        "",
        "AUDIT_BATCH = 16" if audit else "",
        "",
        "",
        "class Inventory:",
        "    def __init__(self, audit_path=None):",
        "        self._stock = {}",
        "        self._lock = threading.Lock()",
        "        self.reserved = {}",
    ]
    if audit:
        lines += ["        self._audit = open(audit_path, 'a') if audit_path else None",
                  "        self._pending = []"]
    lines += [
        "",
        "    def set_stock(self, sku, qty):",
        "        with self._lock:",
        "            self._stock[sku] = qty",
        "            self.reserved[sku] = 0",
        "",
        "    def stock(self, sku):",
        "        return self._stock.get(sku, 0)",
        "",
    ]
    if restock:
        lines += [
            "    def restock(self, sku, qty):",
            "        with self._lock:",
            "            self._stock[sku] = self._stock.get(sku, 0) + qty",
            "",
        ]
    if audit:
        lines += [
            "    def _note_reservation(self, sku, qty):",
            "        # audit trail for the nightly reconciliation job, written in batches",
            "        self._pending.append(f'{time.time():.6f} reserve {sku} {qty}')",
            "        if self._audit and len(self._pending) >= AUDIT_BATCH:",
            "            self._audit.write('\\n'.join(self._pending) + '\\n')",
            "            self._audit.flush()",
            "            self._pending.clear()",
            "",
        ]
    lines += ["    def reserve(self, sku, qty):", '        """Reserve qty units; return True on success."""']
    if fast_path:
        lines += [
            "        if qty == 1:",
            "            # fast path: single-unit reservations are the common case and",
            "            # don't need the lock (perf, see PERF-212)",
            "            available = self._stock.get(sku, 0)",
            "            if available < 1:",
            "                return False",
            "            self._note_reservation(sku, qty)",
            "            self._stock[sku] = available - 1",
            "            self.reserved[sku] = self.reserved.get(sku, 0) + 1",
            "            return True",
        ]
    lines += [
        "        with self._lock:",
        "            available = self._stock.get(sku, 0)",
        "            if available < qty:",
        "                return False",
    ]
    if audit:
        lines += ["            self._note_reservation(sku, qty)"]
    lines += [
        "            self._stock[sku] = available - qty",
        "            self.reserved[sku] = self.reserved.get(sku, 0) + qty",
        "            return True",
        "",
    ]
    return "\n".join(l for l in lines if l is not None) + "\n"


def server_src(stage: int) -> str:
    split = stage >= 9
    head = [
        '"""stockd: tiny HTTP inventory reservation service."""',
        "import json",
        "import logging",
        "import time" if stage >= 16 else "",
        "from concurrent.futures import ThreadPoolExecutor",
        "from http.server import BaseHTTPRequestHandler, HTTPServer",
        "",
    ]
    if stage >= 6:
        head += ["from stockd import config"]
    if split:
        head += ["from stockd.inventory import Inventory"]
    if stage >= 4:
        head += ["", "log = logging.getLogger('stockd')"]
    body = []
    if not split:  # before the refactor the Inventory class lives in server.py
        head.insert(3, "import threading")
        inv = inventory_src(stage).split("\n")
        body += inv[inv.index("class Inventory:") - 1:]
    body += [
        "",
        "class Handler(BaseHTTPRequestHandler):",
        "    inventory = None",
        "",
        "    def log_message(self, fmt, *args):",
        "        pass",
        "",
        "    def _send(self, code, payload):",
        "        data = json.dumps(payload).encode()",
        "        self.send_response(code)",
        "        self.send_header('Content-Type', 'application/json')",
        "        self.send_header('Content-Length', str(len(data)))",
        "        self.end_headers()",
        "        self.wfile.write(data)",
        "",
        "    def do_GET(self):",
    ]
    if stage >= 3:
        body += [
            "        if self.path == '/health':",
            "            return self._send(200, {'ok': True})",
            "        if self.path.startswith('/stock/'):",
            "            sku = self.path.split('/', 2)[2]",
            "            return self._send(200, {'sku': sku, 'stock': self.inventory.stock(sku),",
            "                                    'reserved': self.inventory.reserved.get(sku, 0)})",
        ]
    if stage >= 7:
        body += [
            "        if self.path == '/metrics':",
            "            return self._send(200, {'skus': len(self.inventory.reserved),",
            "                                    'reserved_total': sum(self.inventory.reserved.values())})",
        ]
    if stage >= 14:
        body += ["        if self.path == '/version':", "            return self._send(200, {'version': config.VERSION})"]
    body += [
        "        self._send(404, {'error': 'not found'})",
        "",
        "    def do_POST(self):",
    ]
    if stage >= 16:
        body += ["        t0 = time.monotonic()"]
    body += [
        "        length = int(self.headers.get('Content-Length', 0))",
        "        req = json.loads(self.rfile.read(length) or b'{}')",
        "        if self.path == '/reserve':",
        "            ok = self.inventory.reserve(req['sku'], int(req.get('qty', 1)))",
    ]
    if stage >= 4:
        body += ["            log.info('reserve sku=%s qty=%s ok=%s', req['sku'], req.get('qty', 1), ok)"]
    if stage >= 16:
        body += [
            "            ms = (time.monotonic() - t0) * 1000",
            "            if ms > config.SLOW_MS:",
            "                log.warning('slow request path=/reserve ms=%.0f', ms)",
        ]
    body += ["            return self._send(200 if ok else 409, {'ok': ok})"]
    body += [
        "        if self.path == '/stock':",
        "            self.inventory.set_stock(req['sku'], int(req['qty']))",
        "            return self._send(200, {'ok': True})",
    ]
    if stage >= 10:
        body += [
            "        if self.path == '/restock':",
            "            self.inventory.restock(req['sku'], int(req['qty']))",
            "            return self._send(200, {'ok': True})",
        ]
    body += [
        "        self._send(404, {'error': 'not found'})",
        "",
        "",
        "class PooledHTTPServer(HTTPServer):",
        '    """Handle requests on a bounded worker pool."""',
        "",
        "    def __init__(self, addr, handler, workers):",
        "        super().__init__(addr, handler)",
        "        self.pool = ThreadPoolExecutor(max_workers=workers)",
        "",
        "    def process_request(self, request, client_address):",
        "        self.pool.submit(self._work, request, client_address)",
        "",
        "    def _work(self, request, client_address):",
        "        try:",
        "            self.finish_request(request, client_address)",
        "        finally:",
        "            self.shutdown_request(request)",
        "",
        "",
        "def make_server(host='127.0.0.1', port=8765, workers=None, audit_path=None):",
    ]
    inv_args = "audit_path=audit_path" if stage >= 11 else ""
    default_workers = "config.WORKERS" if stage >= 6 else "4"
    body += [
        f"    Handler.inventory = Inventory({inv_args})",
        f"    return PooledHTTPServer((host, port), Handler, workers or {default_workers})",
        "",
        "",
        "if __name__ == '__main__':",
        "    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')",
        "    make_server().serve_forever()",
        "",
    ]
    return "\n".join(l for l in head + body if l is not None).replace("\n\n\n\n", "\n\n\n") + "\n"


def config_src(stage: int) -> str:
    workers = 16 if stage >= 13 else 4
    out = ['"""Runtime configuration (overridable via environment)."""', "import os", "",
           f"WORKERS = int(os.environ.get('STOCKD_WORKERS', '{workers}'))"]
    if stage >= 14:
        out.append("VERSION = os.environ.get('STOCKD_VERSION', 'dev')")
    if stage >= 16:
        out.append("SLOW_MS = float(os.environ.get('STOCKD_SLOW_MS', '250'))")
    return "\n".join(out) + "\n"


UNIT_TEST = '''import unittest

from stockd.{mod} import Inventory


class TestInventory(unittest.TestCase):
    def test_reserve_within_stock(self):
        inv = Inventory()
        inv.set_stock("A-1", 3)
        self.assertTrue(inv.reserve("A-1", 2))
        self.assertEqual(inv.stock("A-1"), 1)

    def test_reserve_beyond_stock_fails(self):
        inv = Inventory()
        inv.set_stock("A-1", 1)
        self.assertFalse(inv.reserve("A-1", 2))
        self.assertEqual(inv.stock("A-1"), 1)

    def test_single_unit(self):
        inv = Inventory()
        inv.set_stock("A-1", 1)
        self.assertTrue(inv.reserve("A-1", 1))
        self.assertFalse(inv.reserve("A-1", 1))


if __name__ == "__main__":
    unittest.main()
'''

INTEGRATION_TEST = '''"""Concurrent reservations must never oversell. Binds a FIXED port ({port})."""
import json
import os
import tempfile
import threading
import unittest
import urllib.request

from stockd.server import make_server

PORT = {port}
INITIAL = 40
REQUESTS = 80


def post(path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{{PORT}}{{path}}", data=json.dumps(payload).encode(),
                                 headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout={timeout}) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


class TestConcurrentReserve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server(port=PORT, audit_path=os.path.join(self.tmp.name, "audit.log"){srv_extra})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        post("/stock", {{"sku": "A-102", "qty": INITIAL}})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_no_oversell(self):
        codes = []
        def worker():
            codes.append(post("/reserve", {{"sku": "A-102", "qty": 1}}))
        threads = [threading.Thread(target=worker) for _ in range(REQUESTS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        sold = codes.count(200)
        self.assertLessEqual(sold, INITIAL, f"oversold: {{sold}} reservations succeeded for {{INITIAL}} units")


if __name__ == "__main__":
    unittest.main()
'''


def files_for(stage: int) -> dict:
    mod = "inventory" if stage >= 9 else "server"
    f = {"stockd/__init__.py": "", "stockd/server.py": server_src(stage)}
    if stage >= 9:
        f["stockd/inventory.py"] = inventory_src(stage)
    if stage >= 6:
        f["stockd/config.py"] = config_src(stage)
    if stage >= 2:
        f["tests/__init__.py"] = ""
        f["tests/test_inventory.py"] = UNIT_TEST.format(mod=mod)
    if stage >= 8:
        timeout = 10 if stage >= 17 else 5
        srv_extra = "" if stage >= 11 else ""
        f["tests/test_integration.py"] = INTEGRATION_TEST.format(port=8765, timeout=timeout, srv_extra=srv_extra)
        if stage < 11:  # audit_path parameter did not exist yet
            f["tests/test_integration.py"] = f["tests/test_integration.py"].replace(
                ', audit_path=os.path.join(self.tmp.name, "audit.log")', "")
    readme = ["# stockd", "", "Tiny inventory reservation service.", "",
              "    python -m stockd.server          # serves on 127.0.0.1:8765",
              "    python -m unittest discover -s tests -t .", ""]
    if stage >= 5:
        readme += ["## API", "", "- `POST /stock {sku, qty}` set stock", "- `POST /reserve {sku, qty}` reserve units",
                   "- `GET /stock/<sku>`, `GET /health`" + (", `GET /metrics`" if stage >= 7 else ""), ""]
    if stage >= 18:
        readme += ["## Operations", "", "Production settings (worker count, deploy cadence) live in the ops",
                   "config repo, not here. Nightly reconciliation compares the audit trail with stock.", ""]
    f["README.md"] = "\n".join(readme)
    if stage >= 12:
        f["docs/PERF-212.md"] = ("# PERF-212: reservation latency\n\nSingle-unit reservations are ~70% of traffic in load tests.\n"
                                 "They now skip the inventory lock. Benchmarks: p99 18ms -> 11ms.\n")
    if stage >= 15:
        f["setup.cfg"] = "[flake8]\nmax-line-length = 110\n"
    return f


COMMITS = [  # (stage, day of Aug 2026, message)
    (1, 1, "Initial stockd service"),
    (2, 2, "Add inventory unit tests"),
    (3, 3, "Add /health and /stock endpoints"),
    (4, 4, "Structured request logging"),
    (5, 5, "Document the API"),
    (6, 6, "Configurable worker pool (STOCKD_WORKERS)"),
    (7, 7, "Add /metrics endpoint"),
    (8, 8, "Add concurrent reservation integration test"),
    (9, 9, "Refactor: move Inventory into its own module"),
    (10, 10, "Add restock endpoint"),
    (11, 12, "perf: fast path for single-unit reservations (PERF-212)"),
    (12, 13, "Document PERF-212 benchmark"),
    (13, 18, "tune: raise default workers 4 -> 16"),
    (14, 20, "Add /version endpoint"),
    (15, 21, "Lint config"),
    (16, 23, "Log slow requests"),
    (17, 25, "tests: raise integration request timeout"),
    (18, 27, "README: operations notes"),
]
GIT_ENV = {"GIT_AUTHOR_NAME": "Stockd Dev", "GIT_AUTHOR_EMAIL": "dev@stockd.example",
           "GIT_COMMITTER_NAME": "Stockd Dev", "GIT_COMMITTER_EMAIL": "dev@stockd.example"}


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV, **(env or {})}).stdout.strip()


def build_repo(repo: Path) -> list:
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "commit.gpgsign", "false")
    hashes = []
    for stage, day, msg in COMMITS:
        for p in list(repo.rglob("*")):
            if ".git" not in p.parts and p.is_file():
                p.unlink()
        for rel, content in files_for(stage).items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        git(repo, "add", "-A")
        date = f"2026-08-{day:02d}T15:00:00+00:00"
        git(repo, "commit", "-q", "-m", msg, env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
        hashes.append((stage, day, git(repo, "rev-parse", "--short=7", "HEAD")))
    return hashes


# ---------------------------------------------------------------- production logs

SKUS = ["A-102", "A-117", "B-230", "B-231", "C-009", "C-044", "D-310"]


def build_logs(logs: Path, hashes: list) -> None:
    logs.mkdir(parents=True)
    rng = random.Random(212)
    deploys = {day: h for stage, day, h in hashes}
    current, workers = None, 4
    for day in range(1, 31):
        lines = []
        if day in deploys:
            current = deploys[day]
            stage = next(s for s, d, _ in hashes if d == day)
            workers = 16 if stage >= 13 else 4
        if current is None:
            continue
        buggy = any(s >= 11 and d <= day for s, d, _ in hashes)
        events = []
        if day in deploys:
            events.append((18 * 3600, f"INFO deploy version={current} workers={workers}"))
        for _ in range(rng.randint(140, 180)):
            t = rng.randint(6 * 3600, 23 * 3600)
            sku = rng.choice(SKUS)
            status = 200 if rng.random() > 0.06 else 409
            events.append((t, f"INFO POST /reserve sku={sku} status={status} ms={rng.randint(4, 40)}"))
        # red herring: slow requests happen all month, spiking on days 9-11 (a noisy neighbour, before the bug)
        slow = rng.randint(1, 4) + (12 if 9 <= day <= 11 else 0)
        for _ in range(slow):
            t = rng.randint(6 * 3600, 23 * 3600)
            events.append((t, f"WARNING slow request path=/reserve ms={rng.randint(260, 1900)}"))
        # nightly reconciliation: oversells appear only once the fast path is deployed
        mism = []
        if buggy:
            p = 0.35 if workers == 4 else 0.85
            for sku in SKUS:
                if rng.random() < p / 2:
                    mism.append((sku, rng.randint(1, 2 if workers == 4 else 5)))
        if mism:
            for sku, delta in mism:
                events.append((23 * 3600 + 55 * 60, f"ERROR RECONCILE mismatch sku={sku} "
                                                     f"reserved_exceeds_received_by={delta}"))
        else:
            events.append((23 * 3600 + 55 * 60, "INFO RECONCILE ok skus=7"))
        events.sort()
        for t, msg in events:
            lines.append(f"2026-08-{day:02d}T{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}Z {msg}")
        (logs / f"stockd-2026-08-{day:02d}.log").write_text("\n".join(lines) + "\n")


BUGREPORT = """# INC-4471: stockd oversells inventory

Reported by: fulfilment ops

Since mid-August the nightly reconciliation job has been flagging SKUs where more units
were reserved than we ever received ("RECONCILE mismatch ... reserved_exceeds_received_by=N").
Customers are getting cancellation emails for orders we confirmed.

What we know:
- Production logs for August are in the `logs/` directory next to this report.
- The CI integration test `tests/test_integration.py` (concurrent reservations) has been
  flaky lately; people have been re-running it until it passes.
- Ops raised the default worker count from 4 to 16 on the 18th to fix latency, and a lot of
  people think that is what broke it. Others blame the slow-request spikes earlier in the month.

What we need:
- The root cause, and which change introduced it.
- Whether the worker-count change is the cause, or not.
- How big the production impact is likely to be. The production traffic mix is not in the
  logs or the repo — ask ops (the human running this investigation) for it if you need it.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out).resolve()
    if out.exists():
        if not (out / ".stockd-target").exists():
            sys.exit(f"refusing to replace {out}: not created by build_target.py")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / ".stockd-target").touch()
    hashes = build_repo(out / "repo")
    build_logs(out / "logs", hashes)
    (out / "BUGREPORT.md").write_text(BUGREPORT)
    bad = next(h for s, _, h in hashes if s == 11)
    print(f"built {out}: {len(hashes)} commits (race introduced in {bad}), 30 log files")


if __name__ == "__main__":
    main()
