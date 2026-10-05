#!/usr/bin/env python3
"""Reproducible handoffs of copied projects: code, documents, media-sized files.

Not a user time-savings study. Each scenario builds a project with the copied
tooling, writes a rule sheet and a verified goal, copies the whole folder
elsewhere, and checks that the receiving side boots identically, still sees
the rules and the verification, can change a rule, and passes doctor.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
from append import append_fragment
from migrate import install_tooling


def run(root: Path, tool: str, *args: str, expected: int = 0) -> str:
    result = subprocess.run([sys.executable, str(root / "tools/sula_vector" / tool), *args],
                            cwd=root, capture_output=True, text=True)
    if result.returncode != expected:
        raise AssertionError(f"{tool}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def scenario(parent: Path, name: str, rel: str, size: int) -> dict:
    root = parent / name
    fragments = root / "fragments"
    fragments.mkdir(parents=True)
    install_tooling(root, TOOLS)
    asset = root / rel
    asset.parent.mkdir(parents=True, exist_ok=True)
    with asset.open("wb") as handle:
        handle.write(b"approved = True\n" if asset.suffix == ".py" else b"approved\n")
        if size:
            handle.truncate(size)

    reason = append_fragment(fragments, "decision", {"kind": "decision", "summary": "Release only after approval"},
                             "The client signs off each delivery before it ships.").stem
    sheet = parent / f"{name}-sheet.md"
    sheet.write_text(f"## Delivery\n- Ship {rel} only after the client approves it [{reason.split('--')[0]}]\n", encoding="utf-8")
    run(root, "rules.py", ".", "set", "--from", str(sheet), "--why", "first rule sheet", "--refs", reason)

    check = f"from pathlib import Path; assert Path({rel!r}).open('rb').read(8) == b'approved'"
    if asset.suffix == ".py":
        check = f"import runpy; assert runpy.run_path({rel!r})['approved'] is True"
    run(root, "note.py", ".", "--kind", "goal", "--title", "Delivery approved",
        "--done-when", "approved bytes match",
        "--verifier", "shell: " + shlex.quote(sys.executable) + " -c " + shlex.quote(check),
        "Validate the delivery version.")
    run(root, "skills/verifier-shell.py", "--project-root", str(root))
    full = run(root, "render.py", ".", "--for-agent")
    if f"Ship {rel} only after the client approves it" not in full:
        raise AssertionError(f"{name}: boot lost the rule")
    if "Delivery approved" in full.split("## Open goals", 1)[1].split("##", 1)[0]:
        raise AssertionError(f"{name}: a verified goal still shows as open")

    copy = parent / f"{name}-received"
    shutil.copytree(root, copy)
    if run(copy, "render.py", ".", "--for-agent") != full:
        raise AssertionError(f"{name}: handoff changed the boot context")
    run(copy, "migrate.py", "--help")
    run(copy, "rules.py", ".", "add", "--section", "Delivery", "--why", "receiving side adds a rule",
        "Keep the signed approval with the delivery")
    if "Keep the signed approval with the delivery" not in run(copy, "render.py", ".", "--for-agent"):
        raise AssertionError(f"{name}: rule change did not reach the boot")
    run(copy, "render.py", ".", "--view", "doctor")
    return {
        "scenario": name, "fixture": rel, "asset_bytes": asset.stat().st_size,
        "boot_bytes": len(full.encode()),
        "copied_project_boot_byte_stable": True, "rules_in_boot": True,
        "verified_goal_closed": True, "receiving_side_rule_change": True,
        "updater_starts_from_copy": True, "doctor_ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="sula-handoff-") as temp:
        root = Path(temp)
        rows = [scenario(root, *case) for case in [
            ("code-project", "src/rule.py", 0),
            ("document-project", "delivery/terms.txt", 0),
            ("media-sized-project", "delivery/master.bin", 50 * 1024 * 1024 + 1),
        ]]
    report = {"method": "controlled fixtures copied between local directories",
              "limitations": "No real-user timing, remote-device or sync-provider test.",
              "scenarios": rows, "passed": True}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
