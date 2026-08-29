"""Measure the Daytona sandbox path before committing the demo to it.

Answers three questions the plan flags as its largest open risk:

  1. How long is the COLD path (create + clone + install)? This is what a
     judge sees if the prewarmed session dies. If it is minutes, prewarm is
     mandatory rather than merely preferred.
  2. How long is the LIVE path (bump + test + patch + test)? This is what
     runs on stage. Anything over ~30s total makes the demo drag.
  3. Does the sandbox survive an idle gap as long as the wait before our
     slot? auto_stop / auto_archive can kill a "kept alive" session.

Run:  DAYTONA_API_KEY=... python3 sandbox/timing_probe.py
      DAYTONA_API_KEY=... python3 sandbox/timing_probe.py --idle-minutes 20

Nothing on the demo path imports this. It is a measurement tool.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field

import yaml
from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Image


@dataclass
class Step:
    name: str
    seconds: float
    exit_code: int
    tail: str = ""


@dataclass
class Timings:
    steps: list[Step] = field(default_factory=list)

    def add(self, name: str, seconds: float, exit_code: int, tail: str = "") -> None:
        self.steps.append(Step(name, seconds, exit_code, tail))
        mark = "ok " if exit_code == 0 else f"exit {exit_code}"
        print(f"  {seconds:7.2f}s  {name:<34} {mark}")

    def total(self, *names: str) -> float:
        wanted = set(names)
        return sum(s.seconds for s in self.steps if s.name in wanted)


def load_demo() -> dict:
    with open("configs/demo.yaml") as fh:
        return yaml.safe_load(fh)["demo"]


def run(sandbox, timings: Timings, name: str, cmd: str, *, cwd: str | None = None,
        expect_zero: bool = True, timeout: int = 600) -> Step:
    started = time.monotonic()
    result = sandbox.process.exec(cmd, cwd=cwd, timeout=timeout)
    elapsed = time.monotonic() - started
    tail = (result.result or "")[-1500:]
    timings.add(name, elapsed, result.exit_code, tail)
    if expect_zero and result.exit_code != 0:
        print(f"\n--- {name} failed ---\n{tail}\n")
    return timings.steps[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle-minutes", type=float, default=0.0,
                    help="Sleep this long mid-run, then prove the sandbox still works.")
    ap.add_argument("--keep", action="store_true", help="Do not delete the sandbox at the end.")
    args = ap.parse_args()

    api_key = os.getenv("DAYTONA_API_KEY")
    if not api_key:
        print("DAYTONA_API_KEY is not set.", file=sys.stderr)
        return 2

    demo = load_demo()
    repo, commit = demo["repo_url"], demo["commit"]
    before, after = demo["install_spec_before"], demo["install_spec_after"]
    workdir = "/home/daytona/repo"

    timings = Timings()
    daytona = Daytona(DaytonaConfig(api_key=api_key))

    print("\nCOLD PATH — what a judge sees if the prewarmed session died\n")
    t0 = time.monotonic()
    sandbox = daytona.create(
        CreateSandboxFromImageParams(image=Image.debian_slim("3.12")),
        timeout=300,
    )
    timings.add("create sandbox", time.monotonic() - t0, 0)

    try:
        run(sandbox, timings, "clone at pinned commit",
            f"git clone --filter=blob:none {repo} {workdir} "
            f"&& cd {workdir} && git checkout -q {commit}")
        run(sandbox, timings, "install baseline deps",
            f'pip install -q -e ".[dev]" "{before}"', cwd=workdir)
        baseline = run(sandbox, timings, "baseline tests (expect GREEN)",
                       "python -m pytest -q", cwd=workdir)

        if baseline.exit_code != 0:
            print("\nBaseline is not green in the sandbox. Stop and fix this "
                  "before anything else — the whole product rests on it.")
            return 1

        if args.idle_minutes:
            mins = args.idle_minutes
            print(f"\nIDLE — sleeping {mins:g} min to test auto_stop / auto_archive\n")
            time.sleep(mins * 60)
            revive = run(sandbox, timings, f"after {mins:g} min idle", "true",
                         expect_zero=False)
            if revive.exit_code != 0:
                print("\nThe sandbox did NOT survive the idle gap. Prewarming is "
                      "not enough on its own — set auto_stop/auto_archive "
                      "explicitly, or keep a heartbeat running.")
                return 1
            print("  sandbox survived the gap")

        print("\nLIVE PATH — what runs on stage\n")
        run(sandbox, timings, "bump to breaking version",
            f'pip install -q "{after}"', cwd=workdir)
        red = run(sandbox, timings, "tests (expect RED)", "python -m pytest -q",
                  cwd=workdir, expect_zero=False)
        if red.exit_code == 0:
            print("\nTests passed under the new version. The break did not "
                  "reproduce in the sandbox — investigate before trusting it.")
            return 1

        run(sandbox, timings, "apply patch",
            "grep -rl 'from mcp.server.fastmcp import FastMCP' src/ | xargs sed -i "
            "'s/from mcp.server.fastmcp import FastMCP/"
            "from mcp.server.mcpserver import MCPServer as FastMCP/'",
            cwd=workdir)
        green = run(sandbox, timings, "tests (expect GREEN)", "python -m pytest -q",
                    cwd=workdir)

        print("\n" + "=" * 62)
        cold = timings.total("create sandbox", "clone at pinned commit",
                             "install baseline deps", "baseline tests (expect GREEN)")
        live = timings.total("bump to breaking version", "tests (expect RED)",
                             "apply patch", "tests (expect GREEN)")
        print(f"  COLD (prewarm, off-stage)   {cold:6.1f}s")
        print(f"  LIVE (on stage)             {live:6.1f}s")
        print("=" * 62)
        if live > 30:
            print("  LIVE is over 30s. Trim it or the demo drags.")
        if green.exit_code != 0:
            print("  Patch did not restore green. This is the demo. Fix it.")
            return 1
        print("  red -> green proven in a real Daytona sandbox.")
        return 0
    finally:
        if args.keep:
            print(f"\n  sandbox kept: {sandbox.id}")
        else:
            sandbox.delete()


if __name__ == "__main__":
    sys.exit(main())
