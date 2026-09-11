#!/usr/bin/env python3
"""Offline tests for investigate/hooks/guard.py: fake transcripts + hook inputs on stdin.
Usage: python3 tests/test_guard.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "investigate", "hooks", "guard.py")
KIT = os.path.join(ROOT, "investigate", "kit")


def prompt(inv, role="INVESTIGATOR", lane="static", task="static-r01-01", item=None, rnd=1):
    lines = [f"You are the {role} in a structured investigation.", f"Investigation directory: {inv}",
             f"Board CLI: {inv}/bin/board.py   (an executable; pass --as x on every call)",
             f"Round: {rnd}   Lane: {lane}", "", f"Task: {task} — t"]
    if item:
        lines.append(f"SWEEP ITEM {item}/3: something")
    return "\n".join(lines)


class GuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.inv = os.path.join(cls.tmp, "inv")
        os.makedirs(cls.inv)
        for d in ("bin", "prompts", "archetypes"):
            shutil.copytree(os.path.join(KIT, d), os.path.join(cls.inv, d))
        m = json.load(open(os.path.join(KIT, "templates", "manifest.example.json")))
        m["writable"] = [os.path.join(cls.tmp, "scratch")]
        m["safety_deny"] = [r"\bgit\s+push\b", r"\bsudo\b"]
        json.dump(m, open(os.path.join(cls.inv, "manifest.json"), "w"))
        cls.board(["scaffold"])
        tasks = {"tasks": [{"id": "static-r01-01", "title": "t", "objective": "o", "deliverable": "d"},
                           {"id": "static-r01-02", "title": "s", "objective": "o", "deliverable": "d",
                            "kind": "sweep", "items": ["a", "b", "c"]}]}
        subprocess.run([os.path.join(cls.inv, "bin", "board.py"), "plan", "save", "--lane", "static"],
                       input=json.dumps(tasks), text=True, check=True, capture_output=True)
        cls.board(["task", "start", "--id", "static-r01-01"])
        # fake session: <proj>/<sess>.jsonl and <proj>/<sess>/subagents/workflows/wf_1/agent-<id>.jsonl
        cls.proj = os.path.join(cls.tmp, "proj")
        cls.sess = os.path.join(cls.proj, "sess1.jsonl")
        os.makedirs(os.path.join(cls.proj, "sess1", "subagents", "workflows", "wf_1"))
        with open(cls.sess, "w") as f:
            f.write("{}\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    @classmethod
    def board(cls, args):
        return subprocess.run([os.path.join(cls.inv, "bin", "board.py"), *args], check=True,
                              capture_output=True, text=True).stdout

    def agent(self, aid, text):
        p = os.path.join(self.proj, "sess1", "subagents", "workflows", "wf_1", f"agent-{aid}.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}) + "\n")
        return p

    def run_guard(self, mode, data):
        p = subprocess.run([sys.executable, GUARD, mode], input=json.dumps(data), text=True, capture_output=True)
        return p.returncode, p.stderr

    def pre(self, aid, tool, tool_input, **extra):
        return self.run_guard("pretool", {"hook_event_name": "PreToolUse", "agent_id": aid, "agent_type": "investigate:investigator",
                                          "transcript_path": self.sess, "cwd": self.tmp, "tool_name": tool,
                                          "tool_input": tool_input, **extra})

    # ------------------------------------------------------------ PreToolUse
    def test_main_session_is_untouched(self):
        code, _ = self.run_guard("pretool", {"transcript_path": self.sess, "tool_name": "Write",
                                             "tool_input": {"file_path": "/etc/x"}})
        self.assertEqual(code, 0)

    def test_foreign_subagent_is_untouched(self):
        self.agent("other", "You are a helpful reviewer. Review src/.")
        code, _ = self.pre("other", "Write", {"file_path": "/etc/x"})
        self.assertEqual(code, 0)

    def test_write_inside_investigation_allowed(self):
        self.agent("a1", prompt(self.inv))
        code, _ = self.pre("a1", "Write", {"file_path": os.path.join(self.inv, "lanes/static/tasks/static-r01-01/x.py")})
        self.assertEqual(code, 0)

    def test_write_outside_blocked_with_guidance(self):
        self.agent("a2", prompt(self.inv))
        code, err = self.pre("a2", "Edit", {"file_path": os.path.join(self.tmp, "target", "src.py")})
        self.assertEqual(code, 2)
        self.assertIn("outside this investigation", err)
        self.assertIn("task directory", err)

    def test_relative_path_resolved_against_cwd(self):
        self.agent("a3", prompt(self.inv))
        code, _ = self.pre("a3", "Write", {"file_path": "../../etc/passwd"})
        self.assertEqual(code, 2)

    def test_writable_path_allowed(self):
        self.agent("a4", prompt(self.inv))
        code, _ = self.pre("a4", "Write", {"file_path": os.path.join(self.tmp, "scratch", "t1", "f.txt")})
        self.assertEqual(code, 0)

    def test_session_scratchpad_allowed(self):
        self.agent("a8", prompt(self.inv))
        pad = os.path.join(self.tmp, "pad")
        code, _ = self.pre("a8", "Write", {"file_path": os.path.join(pad, "plan.json")}, scratchpad_dir=pad)
        self.assertEqual(code, 0)

    def test_safety_deny_blocks_bash(self):
        self.agent("a5", prompt(self.inv))
        code, err = self.pre("a5", "Bash", {"command": "cd repo && git push origin main"})
        self.assertEqual(code, 2)
        self.assertIn("safety rule", err)

    def test_allowed_bash_passes(self):
        self.agent("a6", prompt(self.inv))
        code, _ = self.pre("a6", "Bash", {"command": "git log --oneline -5"})
        self.assertEqual(code, 0)

    def test_transcript_found_via_agent_transcript_path(self):
        p = self.agent("a7", prompt(self.inv))
        code, _ = self.run_guard("pretool", {"agent_id": "a7", "agent_transcript_path": p, "tool_name": "Bash",
                                             "tool_input": {"command": "sudo ls"}, "cwd": self.tmp})
        self.assertEqual(code, 2)

    # ------------------------------------------------------------ SubagentStop
    def stop(self, aid, **extra):
        return self.run_guard("substop", {"hook_event_name": "SubagentStop", "agent_id": aid,
                                          "agent_type": "investigate:investigator", "transcript_path": self.sess, **extra})

    def test_investigator_cannot_stop_while_running(self):
        self.agent("s1", prompt(self.inv))
        code, err = self.stop("s1")
        self.assertEqual(code, 2)
        self.assertIn("task finish --id static-r01-01", err)

    def test_stop_hook_active_never_loops(self):
        self.agent("s2", prompt(self.inv))
        code, _ = self.stop("s2", stop_hook_active=True)
        self.assertEqual(code, 0)

    def test_sweep_item_gate(self):
        self.agent("s3", prompt(self.inv, task="static-r01-02", item=2))
        code, err = self.stop("s3")
        self.assertEqual(code, 2)
        self.assertIn("task item --id static-r01-02 --n 2", err)
        self.board(["task", "item", "--id", "static-r01-02", "--n", "2", "--status", "done", "--summary", "x"])
        code, _ = self.stop("s3")
        self.assertEqual(code, 0)

    def test_judge_must_save_verdict(self):
        self.agent("j1", prompt(self.inv, role="JUDGE", lane="", task="", rnd=3).replace("Task:  — t", ""))
        code, err = self.stop("j1")
        self.assertEqual(code, 2)
        self.assertIn("judge save --round 3", err)
        subprocess.run([os.path.join(self.inv, "bin", "board.py"), "judge", "save", "--round", "3"], check=True,
                       input='{"met":false,"progress":true,"gaps":[],"summary":"s"}', text=True, capture_output=True)
        code, _ = self.stop("j1")
        self.assertEqual(code, 0)

    def test_zz_finished_investigator_may_stop(self):  # runs last: finishes static-r01-01
        self.agent("s4", prompt(self.inv))
        self.board(["task", "finish", "--id", "static-r01-01", "--status", "done", "--summary", "ok"])
        code, _ = self.stop("s4")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
