#!/usr/bin/env python3
"""Brief for the experimental strategy roles (x3). Installed into a trial's bin/ next to board.py.

    xbrief.py --role strategist|member|advocate [--persona focus|breadth|sceptic] [--lane L] [--as WHO]

Same idea as `board.py brief`: everything the role needs in one call — protocol, role instructions,
manifest essentials, then state printed by the board CLI.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = str(ROOT / "bin" / "board.py")
SEATS = {
    "focus": "**Your seat: FOCUS.** Argue for the fastest route to settling the current leading hypothesis — confirming it or "
             "killing it — with the fewest tasks. Say what evidence would settle it and whether the boards already hold it.",
    "breadth": "**Your seat: BREADTH.** Look for what the investigation has not followed up: explanations, observations, notes and "
               "open questions on any board that nobody has acted on. Argue for the most promising one.",
    "sceptic": "**Your seat: SCEPTIC.** Assume the leading hypothesis is wrong. What on the boards contradicts it or fails to "
               "fit it? What did it predict that has not been observed? Argue for the experiment most likely to break it.",
}


def board(*args):
    p = subprocess.run([BOARD, *args], capture_output=True, text=True)
    return (p.stdout + p.stderr).strip()


def section(title, text):
    print(f"\n{'=' * 8} {title} {'=' * 8}\n{text.strip()}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, choices=["strategist", "member", "advocate", "chair"])
    ap.add_argument("--persona", choices=list(SEATS))
    ap.add_argument("--lane")
    ap.add_argument("--as", dest="author")
    a = ap.parse_args()
    role = (ROOT / "prompts" / f"{a.role}.md").read_text()
    role = role.replace("{{SEAT}}", SEATS.get(a.persona, "")).replace("{{LANE}}", a.lane or "")
    section("Protocol", (ROOT / "prompts" / "protocol.md").read_text())
    section(f"Your role: {a.role}", role)
    brief = board("brief", "--role", "checkpoint")          # reuse its manifest-essentials section only
    start = brief.find("======== Manifest essentials")
    end = brief.find("======== state:", start)
    print("\n" + brief[start:end].strip() + "\n")
    calls = [["status"], ["judge", "show"], ["steer", "list"]]
    if a.role == "chair":
        pos = ROOT / "council" / "positions.md"
        section("Council positions (written independently; you decide)", pos.read_text() if pos.exists() else "(missing)")
    if a.role == "advocate":
        section(f"Your lane: {a.lane}", (ROOT / "lanes" / a.lane / "lane.md").read_text())
        calls += [["plan", "show", "--lane", a.lane], ["worklog", "--lane", a.lane, "--tail", "12"],
                  ["query", "--lane", a.lane, "--format", "full"], ["query", "--lane", "shared", "--format", "full"]]
    else:
        calls += [["query", "--lane", "shared", "--format", "full"], ["query", "--lane", "all", "--format", "brief", "--limit", "60"], ["digest"]]
    for c in calls:
        section("state: board.py " + " ".join(c), board(*c))
    syn = ROOT / "shared" / "synthesis.md"
    section("state: shared/synthesis.md", syn.read_text() if syn.exists() else "(none)")
    print(f"{'=' * 8} end of brief {'=' * 8}")


if __name__ == "__main__":
    sys.exit(main())
