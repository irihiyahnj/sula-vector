#!/usr/bin/env python3
"""Append one fragment to a Sula vector.

The whole point of this tool is that identity is never hand-written: id and
time come from the clock and the filename, and every `--refs` / `--closes` /
`--supersedes` target is checked against the vector before the
file is written. A malformed or dangling fragment cannot be produced this way.

    python3 note.py . --kind decision "选定 A 供应商，因为交付周期短一半"
    python3 note.py . --kind artifact --pointer docs/proposal.pdf "客户提案 v2"
    python3 note.py . --kind decision --supersedes <id> "改回月度节奏"
    python3 note.py . --kind correction --broken-ref <id>,<id> "这些 id 从未存在"
    echo "长正文" | python3 note.py . --kind assessment --title "季度复盘"
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from append import append_fragment, fragment_text
from render import LANE_BY_KIND, LANES, is_symbolic_ref, load_fragments

SLUG_KEEP = re.compile(r"[^a-z0-9]+")

RESERVED_FIELD_KEYS = {
    "id",
    "time",
    "kind",
    "lane",
    "refs",
    "tags",
    "closes",
    "supersedes",
    "broken_ref",
    "done_when",
    "verifier_ref",
    "pointer",
    "author",
    "summary",
}


def lane_of_kind(kind: str, fields: dict) -> str:
    declared = str(fields.get("lane", "")).strip()
    return declared if declared in LANES else LANE_BY_KIND.get(kind, "evidence")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def slugify(text: str, kind: str, fallback_seed: str, hints: list[str] | None = None) -> str:
    for candidate in [text, *(hints or [])]:
        ascii_only = SLUG_KEEP.sub("-", candidate.lower()).strip("-")
        words = [w for w in ascii_only.split("-") if w]
        slug = "-".join(words)[:60].strip("-")
        if slug:
            return f"{kind}-{slug}" if not slug.startswith(kind) else slug
    digest = hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:8]
    return f"{kind}-{digest}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Append one fragment to a Sula vector (id and time are derived)."
    )
    p.add_argument("project_root", help="project root containing fragments/")
    p.add_argument("body", nargs="?", default="", help="fragment body; omit to read stdin")
    p.add_argument("--kind", default="decision")
    p.add_argument("--title", default="", help="one-line summary; also used for the slug")
    p.add_argument("--lane", choices=LANES, help="override the lane derived from --kind")
    # Repeatable single-value flags, comma-splittable. `nargs="*"` would swallow
    # the positional body.
    p.add_argument("--refs", action="append", default=[])
    p.add_argument("--tags", action="append", default=[])
    p.add_argument("--closes", action="append", default=[], help="ids of directions this closes")
    p.add_argument(
        "--supersedes", action="append", default=[], help="ids of judgments this replaces"
    )
    # Deliberately outside the existence check below: these ids are broken
    # precisely because nothing carries them. Validating them would make the
    # repair path for a dangling reference impossible to use.
    p.add_argument(
        "--broken-ref",
        action="append",
        default=[],
        help="ids that do not exist and cannot be recovered; acknowledges the "
        "dangling references pointing at them (the fragments holding them can "
        "never be edited — B1)",
    )
    p.add_argument("--pointer", default="", help="path or URL of the artifact")
    p.add_argument("--author", default="")
    p.add_argument("--done-when", default="", help="goal success condition")
    p.add_argument("--verifier", default="", help="e.g. 'shell: python3 -m unittest ...'")
    p.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--dry-run", action="store_true")
    args, extra = p.parse_known_args(argv)

    # Python <= 3.12's argparse cannot match a trailing optional positional that
    # appears AFTER optionals, so `note.py . --kind decision "body"` loses the
    # body there while it parses fine on 3.13+. Recover it from the leftovers.
    # Strictness is preserved: anything that still looks like a flag is an error,
    # because a mistyped option must never silently become body text.
    if extra:
        flagged = [x for x in extra if x.startswith("-")]
        if flagged:
            p.error("unrecognized arguments: " + " ".join(flagged))
        if args.body:
            p.error("body given more than once: " + " ".join([args.body, *extra]))
        args.body = " ".join(extra)

    root = Path(args.project_root).resolve()
    fragments_dir = root / "fragments"
    if not fragments_dir.is_dir():
        print(f"no fragments/ in {root}", file=sys.stderr)
        return 2

    def items(values: list[str]) -> list[str]:
        return [v.strip() for raw in values for v in raw.split(",") if v.strip()]

    args.refs = items(args.refs)
    args.tags = items(args.tags)
    args.closes = items(args.closes)
    args.supersedes = items(args.supersedes)
    args.broken_ref = items(args.broken_ref)

    body = args.body.strip()
    if not body and not sys.stdin.isatty():
        body = sys.stdin.read().strip()
    if not body and not args.title:
        print("nothing to record: give a body or --title", file=sys.stderr)
        return 2

    frags = load_fragments(fragments_dir)
    existing = {f.id for f in frags}
    unknown = [
        target
        for target in (
            list(args.refs)
            + list(args.closes)
            + list(args.supersedes)
        )
        if target not in existing and not is_symbolic_ref(target)
    ]
    if unknown:
        print("unknown fragment id(s):", file=sys.stderr)
        for target in unknown:
            print(f"  {target}", file=sys.stderr)
        return 2

    if args.kind == "goal" and not args.verifier:
        print("a goal needs --verifier (B9: no goal without a verifier)", file=sys.stderr)
        return 2
    if args.kind == "rules":
        print("the rule sheet is written with rules.py, which validates it", file=sys.stderr)
        return 2
    if args.kind == "transcript":
        print("transcripts are written with turn.py, which redacts them and keeps them out of git",
              file=sys.stderr)
        return 2

    now = now_utc()
    stamp = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
    safe_stamp = stamp.replace(":", "-")
    seed = f"{stamp}{args.title}{body}"
    slug = slugify(
        args.title or body.split("\n", 1)[0],
        args.kind,
        seed,
        hints=list(args.tags),
    )

    extra: dict[str, object] = {}
    for raw in args.field:
        key, _, value = raw.partition("=")
        key = key.strip()
        if key in RESERVED_FIELD_KEYS:
            print(
                f"--field cannot set reserved key: {key} "
                "(use the dedicated flag or leave it to the tool)",
                file=sys.stderr,
            )
            return 2
        if key:
            extra[key] = value.strip()

    fields: dict[str, object] = {
        "time": stamp,
        "kind": args.kind,
    }
    if args.lane:
        fields["lane"] = args.lane
    fields["refs"] = list(args.refs)
    fields["tags"] = list(args.tags)
    fields["closes"] = list(args.closes)
    fields["supersedes"] = list(args.supersedes)
    fields["broken_ref"] = list(args.broken_ref)
    if args.title:
        fields["summary"] = args.title
    if args.pointer:
        fields["pointer"] = args.pointer
    if args.author:
        fields["author"] = args.author
    if args.done_when:
        fields["done_when"] = args.done_when
    if args.verifier:
        fields["verifier_ref"] = args.verifier
    fields.update(extra)

    try:
        if args.dry_run:
            sys.stdout.write(fragment_text(fields, body or args.title))
            return 0
        target = append_fragment(fragments_dir, slug, fields, body or args.title, stamp=stamp)
    except (OSError, ValueError) as exc:
        print(f"cannot append fragment: {exc}", file=sys.stderr)
        return 2

    print(f"[sula] + {args.kind} → {lane_of_kind(args.kind, fields)}  {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
