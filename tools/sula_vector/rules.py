#!/usr/bin/env python3
"""Maintain the project's rule sheet: the rules every agent reads at boot.

The sheet is one `kind: rules` fragment. A change appends a complete new
version that supersedes the previous one, so every version stays on disk and
the current one is a pure function of the fragments. Changes go one line at a
time and must name their reason; replacing the whole sheet is reserved for
writing the first version and for merging a fork.

    python3 rules.py . show
    python3 rules.py . add  --section "部署" --why "<why>" "<rule> [<source>]"
    python3 rules.py . edit --match "<unique text>" --why "<why>" "<new rule>"
    python3 rules.py . remove --match "<unique text>" --why "<why>"
    python3 rules.py . set  --from sheet.md --why "<why>"
    python3 rules.py . log
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from append import append_fragment
from render import is_symbolic_ref, load_fragments, rules_heads, sheet_problems, sheet_rules


def as_rule(text: str) -> str:
    text = " ".join(text.split())
    return text if text.startswith("- ") else f"- {text}"


def unique_rule(lines: list[str], match: str) -> int:
    hits = [i for i, line in enumerate(lines) if line.startswith("- ") and match in line]
    if len(hits) != 1:
        raise ValueError(f"--match must select exactly one rule; {len(hits)} contain {match!r}")
    return hits[0]


def add_rule(lines: list[str], section: str, rule: str) -> list[str]:
    heading = f"## {section.strip()}"
    if heading not in lines:
        while lines and not lines[-1].strip():
            lines.pop()
        return lines + ["", heading, rule]
    end = lines.index(heading) + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    return lines[:end] + [rule] + lines[end:]


def print_diff(before: str, after: str) -> None:
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        print(f"  {line}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Maintain the rule sheet (one line per change).")
    p.add_argument("project_root")
    p.add_argument("op", choices=["show", "add", "edit", "remove", "set", "log"])
    p.add_argument("text", nargs="?", default="", help="rule line for add/edit")
    p.add_argument("--section", default="", help="heading for add; created if absent")
    p.add_argument("--match", default="", help="text that occurs in exactly one rule (edit/remove)")
    p.add_argument("--from", dest="source", default="", help="sheet file for set")
    p.add_argument("--why", default="", help="reason for the change; required for every write")
    p.add_argument("--refs", action="append", default=[], help="fragment ids behind this change")
    args, extra = p.parse_known_args(argv)
    # Python <= 3.12 cannot match a trailing optional positional after options,
    # so `add --section X --why Y "<rule>"` leaves the rule unparsed there.
    if extra:
        flagged = [x for x in extra if x.startswith("-") and not x.startswith("- ")]
        if flagged or args.text:
            p.error("unrecognized arguments: " + " ".join(extra))
        args.text = " ".join(extra)

    root = Path(args.project_root).resolve()
    fragments_dir = root / "fragments"
    if not fragments_dir.is_dir():
        print(f"no fragments/ in {root}", file=sys.stderr)
        return 2
    frags = load_fragments(fragments_dir)
    heads = rules_heads(frags)

    if args.op == "show":
        if not heads:
            print("no rule sheet yet")
        for head in heads:
            print(f"# version {head.id}\n{head.body.strip()}\n")
        return 0
    if args.op == "log":
        sheets = [f for f in frags if f.kind == "rules"]
        previous = ""
        for f in sheets:
            before, after = set(sheet_rules(previous)), set(sheet_rules(f.body))
            print(f"[{f.time}] {f.id}  +{len(after - before)} -{len(before - after)}  {f.get('summary', '')}")
            previous = f.body
        return 0

    if not args.why.strip():
        print("--why is required: a rule change without its reason cannot be reviewed later", file=sys.stderr)
        return 2
    refs = [r.strip() for raw in args.refs for r in raw.split(",") if r.strip()]
    known = {f.id for f in frags}
    unknown = [r for r in refs if r not in known and not is_symbolic_ref(r)]
    if unknown:
        print("unknown fragment id(s): " + ", ".join(unknown), file=sys.stderr)
        return 2

    if args.op == "set":
        if not args.source:
            print("set needs --from <file>", file=sys.stderr)
            return 2
        current = heads[0].body if len(heads) == 1 else ""
        new = Path(args.source).read_text(encoding="utf-8")
    else:
        if not heads:
            print("no rule sheet yet: write the first version with `set --from <file>`", file=sys.stderr)
            return 2
        if len(heads) > 1:
            print(f"the rule sheet has forked into {len(heads)} versions; merge them with `set --from <file>`",
                  file=sys.stderr)
            return 2
        current = heads[0].body
        lines = current.splitlines()
        try:
            if args.op == "add":
                if not args.section.strip() or not args.text.strip():
                    raise ValueError("add needs --section and the rule text")
                lines = add_rule(lines, args.section, as_rule(args.text))
            elif args.op == "edit":
                if not args.match or not args.text.strip():
                    raise ValueError("edit needs --match and the new rule text")
                lines[unique_rule(lines, args.match)] = as_rule(args.text)
            else:
                if not args.match:
                    raise ValueError("remove needs --match")
                del lines[unique_rule(lines, args.match)]
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        new = "\n".join(lines)

    new = new.strip() + "\n"
    issues = sheet_problems(new)
    if issues:
        print("the resulting sheet is not valid:\n  " + "\n  ".join(issues), file=sys.stderr)
        return 2
    if new.strip() == current.strip() and len(heads) <= 1:
        print("[sula] rule sheet unchanged")
        return 0

    try:
        target = append_fragment(fragments_dir, "rules", {
            "kind": "rules",
            "summary": " ".join(args.why.split()),
            "refs": refs,
            "supersedes": [h.id for h in heads],
        }, new)
    except (OSError, ValueError) as exc:
        print(f"cannot append the rule sheet: {exc}", file=sys.stderr)
        return 2
    print(f"[sula] + rules  {target.name}")
    print_diff(current, new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
