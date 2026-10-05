#!/usr/bin/env python3
"""Migrate a legacy Sula-adopted project into a Sula vector.

Idempotent. Reads source files only; writes fragments and (optionally) drops in
the AGENTS template. Does not touch the
old `.sula/` directory or any legacy markdown sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from append import publish

AGENTS_TEMPLATE_DEFAULT = Path(__file__).parent / "AGENTS.md"
PROTOCOL_HEADING = "# AGENTS.md — Sula Vector"

# One list, because two lists drift silently: the update skill compared hashes
# over its own copy that had lost note.py and skills/witness.py, so a release
# touching only those would report a project already up to date.
TOOLING_FILES = (
    "migrate.py",
    "render.py",
    "append.py",
    "capture.py",
    "note.py",
    "rules.py",
    "update-from-canonical.sh",
    "AGENTS.md",
    "README.md",
    "RELEASE-NOTES.md",
    "skills/README.md",
    "skills/witness.py",
    "skills/verifier-shell.py",
)

# Tooling earlier releases shipped. An update removes them, because a stale
# copy keeps running from hooks and tells agents about a protocol that is gone.
RETIRED_FILES = (
    "skills/finish.py",
    "skills/scheduler.py",
    "skills/llm-dispatcher.py",
    "skills/auto-update-from-canonical.py",
    "hooks/install.py",
    "principles/README.md",
)

# Triggers the v1.1–v1.3 installer wrote. Each is removed only when it is
# recognisably ours; anything else is reported and left alone.
GIT_HOOK_MARKER = "# sula-vector witness"

DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$")
SLUG_RE = re.compile(r"[^a-zA-Z0-9-]+")
NOISE_EVENT_TYPES = {
    "sync.applied",
    "query.rebuild",
    "digest.refreshed",
    "check.passed",
    "doctor.passed",
    "session.start",
    "session.end",
}


def slugify(value: str) -> str:
    value = value.strip().lower().replace(" ", "-")
    value = SLUG_RE.sub("-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def parse_date_prefix(name: str) -> tuple[str, str] | None:
    m = DATE_PREFIX_RE.match(name)
    if not m:
        return None
    y, mo, d, rest = m.group(1, 2, 3, 4)
    return (f"{y}-{mo}-{d}T00:00:00Z", rest)


def file_mtime_iso(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_fragment(
    out_dir: Path,
    *,
    time_iso: str,
    slug: str,
    kind: str,
    body: str,
    refs: list[str] | None = None,
    tags: list[str] | None = None,
    extra: dict[str, str] | None = None,
) -> Path | None:
    safe_time = time_iso.replace(":", "-")
    fragment_id = f"{safe_time}--{slug}"
    target = out_dir / f"{fragment_id}.md"
    if target.exists():
        return None
    fm: list[str] = ["---", f"id: {fragment_id}", f"time: {time_iso}", f"kind: {kind}"]
    if refs:
        fm.append(f"refs: [{', '.join(refs)}]")
    if tags:
        fm.append(f"tags: [{', '.join(tags)}]")
    if extra:
        for key, value in extra.items():
            fm.append(f"{key}: {value}")
    fm.append("---")
    return target if publish(target, "\n".join(fm) + "\n" + body.strip() + "\n") else None


def migrate_change_records(root: Path, out: Path) -> int:
    src = root / "docs" / "change-records"
    if not src.is_dir():
        return 0
    count = 0
    for f in sorted(src.glob("*.md")):
        if f.name in {"_template.md", "README.md"}:
            continue
        parsed = parse_date_prefix(f.name)
        if parsed is None:
            continue
        time_iso, rest = parsed
        slug = f"decision-{slugify(rest)[:80]}"
        body = f.read_text(encoding="utf-8")
        if emit_fragment(
            out,
            time_iso=time_iso,
            slug=slug,
            kind="decision",
            body=body,
            tags=["migrated-from-sula", "change-record"],
            extra={"source_path": str(f.relative_to(root))},
        ):
            count += 1
    return count


def migrate_releases(root: Path, out: Path) -> int:
    src = root / "docs" / "releases"
    if not src.is_dir():
        return 0
    count = 0
    for f in sorted(src.glob("*.md")):
        if f.name in {"_template.md", "README.md"}:
            continue
        parsed = parse_date_prefix(f.name)
        if parsed is None:
            continue
        time_iso, rest = parsed
        slug = f"release-{slugify(rest)[:80]}"
        body = f.read_text(encoding="utf-8")
        if emit_fragment(
            out,
            time_iso=time_iso,
            slug=slug,
            kind="release",
            body=body,
            tags=["migrated-from-sula", "release"],
            extra={"source_path": str(f.relative_to(root))},
        ):
            count += 1
    return count


def migrate_incidents(root: Path, out: Path) -> int:
    src = root / "docs" / "incidents"
    if not src.is_dir():
        return 0
    count = 0
    for f in sorted(src.glob("*.md")):
        if f.name in {"_template.md", "README.md"}:
            continue
        parsed = parse_date_prefix(f.name)
        if parsed is None:
            time_iso = file_mtime_iso(f)
            rest = f.stem
        else:
            time_iso, rest = parsed
        slug = f"incident-{slugify(rest)[:80]}"
        body = f.read_text(encoding="utf-8")
        if emit_fragment(
            out,
            time_iso=time_iso,
            slug=slug,
            kind="incident-fact",
            body=body,
            tags=["migrated-from-sula", "incident"],
            extra={"source_path": str(f.relative_to(root))},
        ):
            count += 1
    return count


def migrate_status(root: Path, out: Path) -> int:
    src = root / "STATUS.md"
    if not src.is_file():
        return 0
    body = src.read_text(encoding="utf-8")
    time_iso = file_mtime_iso(src)
    slug = "snapshot-legacy-status"
    if emit_fragment(
        out,
        time_iso=time_iso,
        slug=slug,
        kind="snapshot",
        body=body,
        tags=["migrated-from-sula", "status-snapshot"],
        extra={"source_path": "STATUS.md"},
    ):
        return 1
    return 0


def migrate_project_manifest(root: Path, out: Path) -> int:
    src = root / ".sula" / "project.toml"
    if not src.is_file():
        return 0
    raw = src.read_text(encoding="utf-8")
    body = "Project manifest captured at migration time:\n\n```toml\n" + raw + "\n```"
    time_iso = file_mtime_iso(src)
    slug = "decision-project-manifest"
    if emit_fragment(
        out,
        time_iso=time_iso,
        slug=slug,
        kind="decision",
        body=body,
        tags=["migrated-from-sula", "manifest"],
        extra={"source_path": ".sula/project.toml"},
    ):
        return 1
    return 0


def migrate_artifacts(root: Path, out: Path) -> int:
    src = root / ".sula" / "artifacts" / "catalog.json"
    if not src.is_file():
        return 0
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    items = data.get("artifacts") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return 0
    count = 0
    fallback_time = file_mtime_iso(src)
    for art in items:
        if not isinstance(art, dict):
            continue
        ident = (
            art.get("id")
            or art.get("identity_key")
            or art.get("project_relative_path")
        )
        if not ident:
            continue
        time_iso = (
            art.get("created_at")
            or art.get("registered_at")
            or art.get("last_refreshed_at")
            or fallback_time
        )
        body_lines = [f"Migrated artifact entry: {art.get('title', ident)}"]
        for key in [
            "kind",
            "project_relative_path",
            "provider_item_id",
            "provider_item_url",
            "source_of_truth",
            "collaboration_mode",
            "family_key",
            "artifact_role",
        ]:
            value = art.get(key)
            if value:
                body_lines.append(f"- {key}: {value}")
        slug = f"artifact-{slugify(str(ident))[:80]}"
        extra: dict[str, str] = {"source_path": ".sula/artifacts/catalog.json"}
        for key in ("family_key", "artifact_role"):
            if art.get(key):
                extra[key] = str(art[key])
        if art.get("project_relative_path"):
            extra["pointer"] = str(art["project_relative_path"])
        if emit_fragment(
            out,
            time_iso=time_iso,
            slug=slug,
            kind="artifact",
            body="\n".join(body_lines),
            tags=["migrated-from-sula", "artifact"],
            extra=extra,
        ):
            count += 1
    return count


def migrate_events(root: Path, out: Path, include_noise: bool) -> int:
    src = root / ".sula" / "events" / "log.jsonl"
    if not src.is_file():
        return 0
    count = 0
    seen: set[str] = set()
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        et = ev.get("event_type") or "event"
        if not include_noise and et in NOISE_EVENT_TYPES:
            continue
        ts = ev.get("timestamp")
        if not ts:
            continue
        summary = (ev.get("summary") or et).strip()
        dedup_key = f"{ts}|{et}|{summary}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        suffix = hashlib.sha1(dedup_key.encode("utf-8")).hexdigest()[:8]
        slug = f"event-{slugify(et)[:60]}-{suffix}"
        if emit_fragment(
            out,
            time_iso=ts,
            slug=slug,
            kind="event",
            body=summary,
            tags=["migrated-from-sula", "legacy-event"],
            extra={"event_type": et},
        ):
            count += 1
    return count


def install_tooling(root: Path, canonical_tools: Path) -> dict[str, int]:
    """Copy the runtime tooling into <root>/tools/sula_vector/ so the project is
    self-contained. Skip when target == canonical (the Sula source repo itself).
    """
    target = root / "tools" / "sula_vector"
    if target.resolve() == canonical_tools.resolve():
        return {"copied": 0, "skipped_self": 1}
    files = TOOLING_FILES
    target.mkdir(parents=True, exist_ok=True)
    (target / "skills").mkdir(exist_ok=True)
    copied = 0
    for rel in files:
        src = canonical_tools / rel
        if not src.exists():
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    retired = 0
    for rel in RETIRED_FILES:
        path = target / rel
        if path.is_file():
            path.unlink()
            retired += 1
    for path in sorted((target / "principles").glob("2026-05-23T04-50-00Z--principle-tier-*.md")):
        path.unlink()
        retired += 1
    for folder in ("hooks", "principles"):
        path = target / folder
        if path.is_dir() and not any(p for p in path.iterdir() if p.name != "__pycache__"):
            shutil.rmtree(path)
    return {"copied": copied, "skipped_self": 0, "retired": retired}


def retire_capture_triggers(root: Path) -> list[str]:
    """Remove the capture triggers older releases installed, when they are ours."""
    notes = []
    hook = root / ".git" / "hooks" / "post-commit"
    if hook.is_file():
        text = hook.read_text(encoding="utf-8", errors="replace")
        if GIT_HOOK_MARKER in text:
            head, _, tail = text.partition(GIT_HOOK_MARKER)
            rest = "\n".join(line for line in tail.splitlines()[1:]
                             if "tools/sula_vector/skills/witness.py" not in line
                             and not line.strip().startswith("--project-root"))
            remaining = (head + rest).strip()
            if remaining in {"", "#!/bin/sh"}:
                hook.unlink()
            else:
                hook.write_text(remaining + "\n", encoding="utf-8")
            notes.append("removed sula witness from .git/hooks/post-commit")
    for rel in (".kiro/hooks/sula-witness.kiro.hook", ".kiro/agents/sula.json"):
        path = root / rel
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if "sula_vector" in text:
                path.unlink()
                notes.append(f"removed {rel}")
            else:
                notes.append(f"left {rel}: not recognisably written by Sula")
    return notes


def install_agents_template(root: Path, template: Path) -> str:
    target = root / "AGENTS.md"
    sentinel = "<!-- sula-vector -->"
    priority = "<!-- sula-vector-priority -->"
    rel_tools = "tools/sula_vector"
    # The notice must not quote the sentinel literally: the idempotence checks
    # below test for the sentinel's presence in the file.
    priority_notice = (
        f"{priority}\n"
        "> **Active host protocol:** the \"Sula Vector — Host Operating Protocol\"\n"
        "> section at the end of this file is authoritative for any LLM operating\n"
        "> in this project. Any rules above it that conflict with it are legacy\n"
        "> from prior project conventions and are superseded.\n\n"
    )
    template_body = template.read_text(encoding="utf-8").replace(
        "path/to/", f"{rel_tools}/"
    )
    protocol = template_body.split(sentinel, 1)[-1].lstrip("\n")
    suffix = f"\n\n---\n\n{sentinel}\n{protocol}"

    if not target.exists():
        body = template_body
        if sentinel not in body:
            body = sentinel + "\n" + body
        if priority not in body:
            body = priority_notice + body
        target.write_text(body, encoding="utf-8")
        return "installed"
    existing = target.read_text(encoding="utf-8")
    changed = False
    status = "unchanged"
    if priority not in existing:
        existing = priority_notice + existing
        changed = True
        status = "priority-prepended"
    if sentinel not in existing:
        existing = existing.rstrip() + suffix
        changed = True
        status = "appended"
    else:
        # The region from the sentinel on is tooling-owned, and stale protocol
        # text is worse than none: an agent reads instructions the tools no
        # longer implement and boots on a contract that has moved. Everything
        # the project wrote above the sentinel is preserved. Rewriting stops if
        # that region does not look like a protocol this tool wrote, because
        # silently deleting a project's own text is the worse failure.
        head, _, current = existing.partition(sentinel)
        if PROTOCOL_HEADING not in current:
            status = "protocol-foreign-left-alone"
        elif current.lstrip("\n") != protocol:
            existing = head + sentinel + "\n" + protocol
            changed = True
            status = "protocol-refreshed"
    if changed:
        target.write_text(existing, encoding="utf-8")
    return status


HOST_POINTER_TARGETS = {
    "CLAUDE.md": "CLAUDE.md",
    "CODEX.md": "CODEX.md",
    "GEMINI.md": "GEMINI.md",
    ".github/copilot-instructions.md": "GitHub Copilot Instructions",
    ".cursor/rules/project.mdc": "Cursor — project rules",
}

CURSOR_FRONTMATTER = (
    "---\ndescription: Sula Vector project rules\nglobs:\nalwaysApply: true\n---\n\n"
)


def host_pointer_text(title: str) -> str:
    return (
        f"# {title}\n\n"
        "This project runs on the Sula Vector convention. **[AGENTS.md](AGENTS.md) is\n"
        "the authoritative protocol** — read it first and follow it exactly.\n\n"
        "Boot (two steps): note the current UTC time as your session start, then run\n\n"
        "```bash\n"
        "python3 tools/sula_vector/render.py . --for-agent\n"
        "```\n\n"
        "Follow the **Rules** section of that output. Record decisions with\n"
        "`tools/sula_vector/note.py`; change a rule with `tools/sula_vector/rules.py`.\n\n"
        "Nothing in this file overrides AGENTS.md. Legacy Sula 0.18.x instructions\n"
        "(`scripts/sula.py`, `.sula/`, `STATUS.md`) are historical reference only.\n"
    )


# The pointer v1.1–v1.3 generated. A file still holding it was written by this
# tool, not by the project, so an update may replace it.
def _v13_pointer_text(title: str) -> str:
    return (
        f"# {title}\n\n"
        "This project runs on the Sula Vector convention. **[AGENTS.md](AGENTS.md) is\n"
        "the authoritative protocol** — read it first and follow it exactly.\n\n"
        "Boot (two steps): note the current UTC time as your session start, then run\n\n"
        "```bash\n"
        "python3 tools/sula_vector/render.py . --for-agent\n"
        "```\n\n"
        "Record judgments with `tools/sula_vector/note.py`. Mechanical evidence (files\n"
        "produced, commits made) is captured by `tools/sula_vector/skills/witness.py`;\n"
        "do not narrate it by hand.\n\n"
        "Nothing in this file overrides AGENTS.md. Legacy Sula 0.18.x instructions\n"
        "(`scripts/sula.py`, `.sula/`, `STATUS.md`) are historical reference only.\n"
    )


def install_host_pointers(root: Path) -> tuple[int, int]:
    """Every host entrypoint must boot into the same protocol, or continuity is
    a claim rather than a property.

    Returns (written, skipped). A non-empty existing file that is not exactly
    the generated pointer is project-authored content; overwriting it would
    silently delete rules the project wrote, so it is left untouched and
    reported instead. The operator resolves the conflict the same way the
    AGENTS.md updater reports a foreign protocol region.
    """
    written = 0
    skipped = 0
    for rel, title in HOST_POINTER_TARGETS.items():
        text = host_pointer_text(title)
        if rel.endswith(".mdc"):
            text = CURSOR_FRONTMATTER + text
        target = root / rel
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing == text:
                continue
            previous = _v13_pointer_text(title)
            if rel.endswith(".mdc"):
                previous = CURSOR_FRONTMATTER + previous
            if existing.strip() and existing != previous:
                skipped += 1
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written += 1
    return written, skipped


def doctor_report(out: Path) -> dict:
    """Whether the vector this update just produced is actually usable.

    A fleet update that reports only what it copied hides the thing the operator
    needs: several projects carry hand-written v1.0-era fragments whose dangling
    refs and header disagreements keep the gate shut regardless of tooling.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from render import load_report, view_doctor  # type: ignore

    frags, problems = load_report(out)
    return view_doctor(frags, problems)


def emit_migration_decision(out: Path, total: int) -> None:
    for _ in out.glob("*--decision-migrated-to-sula-vector.md"):
        return
    body = (
        f"Migrated this project from legacy Sula to the Sula Vector convention.\n\n"
        f"Generated {total} migrated fragments. Legacy `.sula/` directory left "
        f"intact for reference and rollback. Old `docs/change-records/`, "
        f"`docs/releases/`, `docs/incidents/`, and `STATUS.md` are also left in "
        f"place; they may be archived once the new vector is verified."
    )
    emit_fragment(
        out,
        time_iso=now_iso(),
        slug="decision-migrated-to-sula-vector",
        kind="decision",
        body=body,
        tags=["migration-event"],
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Migrate a legacy Sula-adopted project into a Sula vector."
    )
    p.add_argument("--project-root", required=True)
    p.add_argument(
        "--output-dir",
        help="Where to write fragments. Defaults to <project-root>/fragments.",
    )
    p.add_argument("--include-event-noise", action="store_true")
    p.add_argument("--agents-template", default=str(AGENTS_TEMPLATE_DEFAULT))
    p.add_argument("--no-agents", action="store_true")
    p.add_argument(
        "--no-host-pointers",
        action="store_true",
        help="Do not project CLAUDE.md / CODEX.md / GEMINI.md / Cursor / Copilot pointers.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Write to a temporary directory and report counts; do not modify the project.",
    )
    args = p.parse_args(argv)

    root = Path(args.project_root).resolve()
    if not root.is_dir():
        print(f"project-root not found: {root}", file=sys.stderr)
        return 2
    if args.dry_run:
        import tempfile

        out = Path(tempfile.mkdtemp(prefix="sula-migrate-")).resolve()
        print(f"DRY RUN: writing to {out}")
    else:
        out = (
            Path(args.output_dir).resolve()
            if args.output_dir
            else root / "fragments"
        )
        out.mkdir(parents=True, exist_ok=True)

    counts = {
        "change_records": migrate_change_records(root, out),
        "releases": migrate_releases(root, out),
        "incidents": migrate_incidents(root, out),
        "status": migrate_status(root, out),
        "manifest": migrate_project_manifest(root, out),
        "artifacts": migrate_artifacts(root, out),
        "events": migrate_events(root, out, args.include_event_noise),
    }
    total = sum(counts.values())

    if not args.dry_run:
        canonical_tools = Path(args.agents_template).resolve().parent
        tooling = install_tooling(root, canonical_tools)
        counts["tooling_files_copied"] = tooling["copied"]
        counts["tooling_files_retired"] = tooling.get("retired", 0)
        for note in retire_capture_triggers(root):
            print(f"  trigger          : {note}")
        if tooling["skipped_self"]:
            counts["tooling_skipped_self"] = 1
    if not args.no_agents and not args.dry_run:
        counts["agents_template"] = install_agents_template(
            root, Path(args.agents_template).resolve()
        )
    elif args.dry_run:
        counts["agents_template"] = "skipped (dry-run)"
    if not args.no_host_pointers and not args.dry_run:
        host_written, host_skipped = install_host_pointers(root)
        counts["host_pointers"] = host_written
        if host_skipped:
            counts["host_pointers_skipped_custom"] = host_skipped

    emit_migration_decision(out, total)


    print(f"  output dir       : {out}")
    for k, v in counts.items():
        print(f"  {k:18}: {v}")
    print(f"  total written    : {sum(v for v in counts.values() if isinstance(v, int))}")

    report = doctor_report(out)
    if report["ok"]:
        print(f"\n  doctor           : OK ({report['fragments']} fragments)")
    else:
        print(f"\n  doctor           : {len(report['problems'])} problem(s)")
        for code, count in report["by_code"].items():
            print(f"    {count:6d}  {code}")
    print(
        "\nNext: python3 tools/sula_vector/render.py "
        f"{out.parent} --for-agent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
