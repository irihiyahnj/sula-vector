#!/usr/bin/env python3
"""verifier-shell skill: run shell commands as goal verifiers.

For every open goal whose verifier_ref starts with `shell:`, run the command in
the project root and append a `verification-fact` with passed true/false and
the command output. A goal is met when its latest verification passed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from append import append_fragment
from render import _is_satisfied, load_fragments

DEFAULT_TIMEOUT_SECONDS = 600
OUTPUT_TRUNCATE = 4000


def run_command(command: str, cwd: Path, timeout: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, shell=True, cwd=str(cwd),
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"verifier timed out after {timeout}s"
    output = (result.stdout + result.stderr).strip()
    if len(output) > OUTPUT_TRUNCATE:
        output = output[:OUTPUT_TRUNCATE] + "\n…(truncated)"
    return result.returncode == 0, output


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run shell-command verifiers for Sula vector goals.")
    p.add_argument("--project-root", required=True)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    p.add_argument("--dry-run", action="store_true", help="List goals without running commands.")
    args = p.parse_args(argv)

    root = Path(args.project_root).resolve()
    fragments_dir = root / "fragments"
    if not fragments_dir.is_dir():
        print(f"no fragments/ in {root}", file=sys.stderr)
        return 2
    frags = load_fragments(fragments_dir)
    candidates = [
        f for f in frags
        if f.kind == "goal"
        and str(f.get("verifier_ref", "")).startswith("shell:")
        and not _is_satisfied(f, frags)
    ]
    if not candidates:
        print("no shell-verified goals to evaluate")
        return 0

    failed = False
    for goal in candidates:
        command = str(goal.get("verifier_ref", ""))[len("shell:"):].strip()
        if not command:
            continue
        print(f"[verifier-shell] {goal.id}: {command}")
        if args.dry_run:
            continue
        passed, output = run_command(command, root, args.timeout)
        target = append_fragment(fragments_dir, f"verification-fact-shell-{goal.id[:60]}", {
            "kind": "verification-fact", "refs": [goal.id], "passed": passed,
            "tags": ["skill", "verifier-shell"], "verified_command": command,
        }, f"shell verifier: `{command}`\n\n```\n{output}\n```")
        failed |= not passed
        print(f"[verifier-shell] -> {'PASS' if passed else 'FAIL'}  {target.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
