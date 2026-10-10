#!/usr/bin/env python3
"""Sula vector renderer.

Pure function from a folder of typed text fragments to a project view.
Standard library only. See ../../docs/sula-vector-convention.md for the spec.

Identity is derived from the filename, never from hand-written frontmatter:
a fragment cannot carry a wrong id or a wrong timestamp, and no fragment is
ever silently dropped. Structural problems surface through `--view doctor`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

CONVENTION_VERSION = "1.4"

TIER_ORDER = ["highest", "invariant", "aesthetic", "discipline", "anti-pattern"]
PROJECT_TIER = "project"
PRINCIPLE_ORDER = TIER_ORDER + [PROJECT_TIER]
TIER_TITLES = {
    "highest": "Tier A — Highest rule",
    "invariant": "Tier B — Invariants",
    "aesthetic": "Tier C — Aesthetics",
    "discipline": "Tier D — Implementation discipline",
    "anti-pattern": "Tier E — Anti-patterns",
    PROJECT_TIER: "Project principles",
}

LANES = ("evidence", "judgment", "direction")
LANE_BY_KIND = {
    "rules": "judgment",
    "decision": "judgment",
    "correction": "judgment",
    "principle": "judgment",
    "assessment": "judgment",
    "annotation": "judgment",
    "preference": "judgment",
    "pitfall": "judgment",
    "chronicle": "judgment",
    "skill": "judgment",
    "intent": "direction",
    "goal": "direction",
}

RECENT_JUDGMENTS = 10
# Turn-by-turn dialogue written by turn.py. Kept for search and re-reading,
# never part of the boot, journal or turn mark.
TRANSCRIPT_KIND = "transcript"

FILENAME_TIME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2}(?:\.\d{1,6})?)Z(?:--(.*))?$"
)
FRONTMATTER_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


def time_key(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(timespec="microseconds")
    except ValueError:
        return value


@dataclass
class Fragment:
    id: str
    time: str
    kind: str
    refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    path: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        if key in {"id", "time", "kind", "refs", "tags", "body", "path"}:
            return getattr(self, key)
        return self.extra.get(key, default)

    def id_list(self, key: str) -> list[str]:
        raw = self.get(key)
        if raw is None or raw == "":
            return []
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        return [str(raw).strip()]


@dataclass
class Problem:
    code: str
    fragment: str
    path: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "fragment": self.fragment,
            "path": self.path,
            "detail": self.detail,
        }


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        if value.startswith('"'):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value[1:-1]
    low = value.lower()
    if low in {"true", "false"}:
        return low == "true"
    return value


def _parse_inline_list(value: str) -> list[Any]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    inner = value[1:-1].strip()
    if not inner:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return [_parse_scalar(item) for item in inner.split(",")]


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        tail = text.find("\n---", 4)
        if tail == -1 or text[tail:].strip() != "---":
            return {}, text
        end = tail
        body = ""
    else:
        body = text[end + 5 :]
    raw = text[4:end]

    out: dict[str, Any] = {}
    current_list_key: str | None = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_list_key is not None:
            out[current_list_key].append(_parse_scalar(line[4:]))
            continue
        if ":" not in line:
            current_list_key = None
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            out[key] = []
            current_list_key = key
        elif value.startswith("[") and value.endswith("]"):
            out[key] = _parse_inline_list(value)
            current_list_key = None
        else:
            out[key] = _parse_scalar(value)
            current_list_key = None
    return out, body.strip()


def derive_identity(path: Path) -> tuple[str, str | None]:
    """Fragment id and time as derived from the filename. Filename is truth."""
    stem = path.stem
    match = FILENAME_TIME_RE.match(stem)
    if not match:
        return stem, None
    day, hh, mm, ss, _slug = match.groups()
    timestamp = f"{day}T{hh}:{mm}:{ss}Z"
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return stem, None
    return stem, timestamp


def load_report(folder: Path) -> tuple[list[Fragment], list[Problem]]:
    """Load every fragment file. Nothing is ever skipped silently."""
    frags: list[Fragment] = []
    problems: list[Problem] = []
    for path in sorted(folder.rglob("*.md")):
        # Dot files are never fragments; macOS writes ._* AppleDouble companions on exFAT.
        if path.name in {"AGENTS.md", "README.md"} or path.name.startswith("."):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            problems.append(Problem("unreadable", path.stem, str(path), str(exc)))
            continue

        meta, body = _parse_frontmatter(text)
        fid, derived_time = derive_identity(path)

        # A writer that crashed mid-write leaves an empty, unclosed or
        # checksum-mismatched file; it is reported and excluded, never rendered.
        unclosed = text.startswith("---\n") and not meta
        digest = meta.pop("sha256", None)
        if not text.strip():
            torn = "empty file"
        elif unclosed:
            torn = "unclosed header"
        elif digest is not None and digest != hashlib.sha256(body.encode("utf-8")).hexdigest():
            torn = "body does not match sha256"
        else:
            torn = ""
        if torn:
            problems.append(Problem("incomplete-fragment", fid, str(path), torn))
            continue

        if not meta:
            problems.append(
                Problem("no-frontmatter", fid, str(path), "no `---` header block")
            )

        declared_time = str(meta.get("time", "")).strip()
        time = derived_time or declared_time
        if derived_time is None:
            problems.append(
                Problem(
                    "unparsable-filename",
                    fid,
                    str(path),
                    "filename must start with <YYYY-MM-DDTHH-MM-SSZ>--",
                )
            )
            if declared_time and not FRONTMATTER_TIME_RE.match(declared_time):
                problems.append(
                    Problem("unparsable-time", fid, str(path), declared_time)
                )
                time = ""
        elif declared_time and declared_time != derived_time:
            problems.append(
                Problem(
                    "header-disagreement",
                    fid,
                    str(path),
                    f"frontmatter time {declared_time} != filename time {derived_time}",
                )
            )

        declared_id = str(meta.get("id", "")).strip()
        if declared_id and declared_id != fid:
            problems.append(
                Problem(
                    "header-disagreement",
                    fid,
                    str(path),
                    f"frontmatter id {declared_id} != filename stem {fid}",
                )
            )

        kind = str(meta.get("kind", "")).strip()
        if not kind:
            problems.append(
                Problem("missing-kind", fid, str(path), "`kind` is required")
            )
            kind = "unknown"

        refs = meta.get("refs") or []
        tags = meta.get("tags") or []
        extra = {
            k: v
            for k, v in meta.items()
            if k not in {"id", "time", "kind", "refs", "tags"}
        }
        frags.append(
            Fragment(
                id=fid,
                time=time,
                kind=kind,
                refs=[str(x) for x in refs],
                tags=[str(x) for x in tags],
                extra=extra,
                body=body,
                path=str(path),
            )
        )

    frags.sort(key=lambda f: (time_key(f.time), f.id))
    return frags, problems


def load_fragments(folder: Path) -> list[Fragment]:
    return load_report(folder)[0]


def lane_of(f: Fragment) -> str:
    declared = str(f.get("lane", "")).strip()
    if declared in LANES:
        return declared
    return LANE_BY_KIND.get(f.kind, "evidence")


def _matches(
    f: Fragment,
    *,
    kind: str | None = None,
    since: str | None = None,
    until: str | None = None,
    tag: str | None = None,
    ref: str | None = None,
    lane: str | None = None,
) -> bool:
    if kind and f.kind != kind:
        return False
    if since and time_key(f.time) < time_key(since):
        return False
    if until and time_key(f.time) > time_key(until):
        return False
    if tag and tag not in f.tags:
        return False
    if ref and ref not in f.refs:
        return False
    if lane and lane_of(f) != lane:
        return False
    return True


def filter_fragments(frags: Iterable[Fragment], **q: Any) -> list[Fragment]:
    return [f for f in frags if _matches(f, **q)]


def _summarize(f: Fragment, max_chars: int = 200) -> str:
    declared = str(f.get("summary", "")).strip()
    text = declared or " ".join(
        line.strip()
        for line in f.body.strip().split("\n\n", 1)[0].splitlines()
        if line.strip()
    )
    text = text.lstrip("# ").strip()
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    for stop in ("。", ". ", "；", "; ", "，", ", ", " "):
        cut = window.rfind(stop)
        if cut > max_chars // 2:
            return window[: cut + (1 if stop in "。；，" else 0)].strip() + "…"
    return window.strip() + "…"


def _to_dict(f: Fragment) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f.id,
        "time": f.time,
        "kind": f.kind,
        "lane": lane_of(f),
        "refs": f.refs,
        "tags": f.tags,
    }
    base.update(f.extra)
    base["summary"] = _summarize(f)
    base["path"] = f.path
    return base


def supersession_map(frags: Iterable[Fragment]) -> dict[str, list[str]]:
    """id -> ids of later fragments that explicitly supersede it."""
    out: dict[str, list[str]] = {}
    for f in frags:
        for target in f.id_list("supersedes"):
            if target != f.id:
                out.setdefault(target, []).append(f.id)
    return out


def closure_map(frags: Iterable[Fragment]) -> dict[str, list[str]]:
    """id -> ids of fragments that declare it closed."""
    out: dict[str, list[str]] = {}
    for f in frags:
        for target in f.id_list("closes"):
            if target != f.id:
                out.setdefault(target, []).append(f.id)
    return out


# ---------------------------------------------------------------------------
# Rule sheet. The boot is the one view every agent reads, so it carries the
# rules themselves, maintained as one sheet, instead of the title of every
# judgment ever made: a title names an event, and an agent that reads only
# titles knows something happened but not what it must now do.


def rules_heads(frags: Iterable[Fragment]) -> list[Fragment]:
    """Rule-sheet versions nothing supersedes. One is normal; more is a fork."""
    sheets = [f for f in frags if f.kind == "rules"]
    retired = supersession_map(sheets)
    return [f for f in sheets if f.id not in retired]


def sheet_rules(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("- ")]


def sheet_problems(text: str) -> list[str]:
    problems = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith("## ") and line[3:].strip():
            continue
        if line.startswith("- ") and line[2:].strip():
            if line in seen:
                problems.append(f"line {number}: duplicate rule")
            seen.add(line)
            continue
        problems.append(f"line {number}: must be a `## ` heading or a `- ` rule")
    if not seen:
        problems.append("sheet has no rule lines")
    return problems


def _is_satisfied(intent: Fragment, frags: list[Fragment]) -> bool:
    if closure_map(frags).get(intent.id):
        return True
    if intent.kind != "goal" and "done_when" not in intent.extra:
        return False
    results = [f for f in frags if intent.id in f.refs and f.kind == "verification-fact"]
    if not results:
        return False
    latest_time = max(time_key(f.time) for f in results)
    latest = [f for f in results if time_key(f.time) == latest_time]
    return all(f.get("passed") in {True, "true"} for f in latest)


def open_directions(frags: list[Fragment]) -> list[Fragment]:
    return [f for f in frags if lane_of(f) == "direction" and not _is_satisfied(f, frags)]


def view_list(frags: list[Fragment]) -> list[dict[str, Any]]:
    return [_to_dict(f) for f in frags]


def view_goals(frags: list[Fragment]) -> list[dict[str, Any]]:
    out = []
    for g in frags:
        if lane_of(g) != "direction":
            continue
        verifications = [f for f in frags if g.id in f.refs and f.kind == "verification-fact"]
        out.append(
            {
                "goal": _to_dict(g),
                "verifications": [_to_dict(f) for f in verifications],
                "met": _is_satisfied(g, frags),
            }
        )
    return out


def view_effective(frags: list[Fragment]) -> dict[str, Any]:
    """Judgments in force, with the supersession trail attached."""
    superseded = supersession_map(frags)
    by_id = {f.id: f for f in frags}
    in_force: list[dict[str, Any]] = []
    retired: list[dict[str, Any]] = []
    for f in frags:
        if lane_of(f) != "judgment":
            continue
        entry = _to_dict(f)
        if f.id in superseded:
            entry["superseded_by"] = [
                {
                    "id": sid,
                    "time": by_id[sid].time if sid in by_id else "",
                    "summary": _summarize(by_id[sid]) if sid in by_id else "",
                }
                for sid in superseded[f.id]
            ]
            retired.append(entry)
        else:
            in_force.append(entry)
    return {"in_force": in_force, "retired": retired}


def view_journal(frags: list[Fragment]) -> list[dict[str, Any]]:
    """Day-by-day project journal: what was decided, what was produced."""
    days: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for f in frags:
        if f.kind in {"principle", TRANSCRIPT_KIND}:
            continue
        day = f.time[:10] or "unknown"
        bucket = days.setdefault(day, {lane: [] for lane in LANES})
        bucket[lane_of(f)].append(_to_dict(f))
    return [
        {
            "day": day,
            "judgment": days[day]["judgment"],
            "evidence": days[day]["evidence"],
            "direction": days[day]["direction"],
        }
        for day in sorted(days)
    ]


def is_symbolic_ref(target: str) -> bool:
    """A ref whose target is a namespace key, not a fragment id.

    Doctor skips these because `family:<key>` and `thread:<id>` are links in
    the refs graph that can never resolve to a filename. Keep this predicate
    single-sourced: note.py must accept exactly what doctor will not call
    dangling.
    """
    return ":" in target and not target.startswith("20")


def view_doctor(frags: list[Fragment], problems: list[Problem]) -> dict[str, Any]:
    """Structural integrity of the vector. Pure function, no side effects."""
    found = [p.as_dict() for p in problems]
    ids = {f.id for f in frags}

    seen: dict[str, str] = {}
    for f in frags:
        if f.id in seen:
            found.append(
                Problem("duplicate-id", f.id, f.path, f"also at {seen[f.id]}").as_dict()
            )
        seen[f.id] = f.path

    # A list, not a scalar: one project carried 483 dangling refs from
    # hand-written v1.0-era fragments, and one-fragment-per-ref is a repair path
    # nobody walks.
    acknowledged = {
        target for f in frags for target in f.id_list("broken_ref")
    }
    for f in frags:
        for target in f.refs + f.id_list("supersedes") + f.id_list("closes"):
            if is_symbolic_ref(target):
                continue
            if target in ids or target in acknowledged:
                continue
            found.append(
                Problem("dangling-ref", f.id, f.path, f"-> {target}").as_dict()
            )

    for f in frags:
        if f.kind == "goal" and not str(f.get("verifier_ref", "")).strip():
            found.append(
                Problem("goal-without-verifier", f.id, f.path, "B9/E9").as_dict()
            )

    heads = rules_heads(frags)
    if len(heads) > 1:
        found.append(
            Problem(
                "rules-fork",
                heads[-1].id,
                heads[-1].path,
                f"{len(heads)} current rule sheets — merge them with `rules.py . set --from <file>`",
            ).as_dict()
        )
    for head in heads:
        for detail in sheet_problems(head.body):
            found.append(Problem("rules-malformed", head.id, head.path, detail).as_dict())

    by_code: dict[str, int] = {}
    for p in found:
        by_code[p["code"]] = by_code.get(p["code"], 0) + 1
    return {
        "fragments": len(frags),
        "problems": found,
        "by_code": dict(sorted(by_code.items(), key=lambda x: (-x[1], x[0]))),
        "ok": not found,
    }


def view_changes_summary(frags: list[Fragment]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    fragment_entries: list[dict[str, Any]] = []
    for f in frags:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
        entry: dict[str, Any] = {
            "id": f.id,
            "time": f.time,
            "kind": f.kind,
            "lane": lane_of(f),
            "summary": _summarize(f, max_chars=120),
            "refs": list(f.refs),
        }
        if f.kind == "verification-fact":
            entry["passed"] = f.get("passed") in {True, "true"}
        fragment_entries.append(entry)
    return {
        "total": len(frags),
        "by_kind": dict(sorted(by_kind.items(), key=lambda x: (-x[1], x[0]))),
        "fragments": fragment_entries,
    }


def render_changes_summary_block(frags: list[Fragment]) -> str:
    if not frags:
        return "[sula] no changes"
    width = max(max(len(f.kind) for f in frags), len("verification-fact"))
    lines = [f"[sula] +{len(frags)} this turn:"]
    for f in frags:
        marker = "+"
        summary = _summarize(f, max_chars=120)
        if f.kind == "verification-fact":
            passed = f.get("passed") in {True, "true"}
            marker = "✓" if passed else "✗"
            target = f.refs[0] if f.refs else ""
            short_target = target.split("--", 1)[-1] if "--" in target else target
            summary = f"{'PASS' if passed else 'FAIL'}  {short_target}"
        lines.append(f"  {marker} {f.kind.ljust(width)}  {summary}")
    return "\n".join(lines)


def render_principles_block(frags: list[Fragment]) -> str:
    superseded = supersession_map(frags)
    grouped: dict[str, list[Fragment]] = {t: [] for t in PRINCIPLE_ORDER}
    for f in frags:
        if f.kind != "principle" or f.id in superseded:
            continue
        tier = str(f.get("tier", "")).strip()
        grouped[tier if tier in grouped else PROJECT_TIER].append(f)
    if not any(grouped.values()):
        return ""
    lines: list[str] = ["## Principles in force", ""]
    for tier in PRINCIPLE_ORDER:
        if not grouped[tier]:
            continue
        lines.append(f"### {TIER_TITLES[tier]}")
        lines.append("")
        for p in grouped[tier]:
            if p.body.strip():
                lines.append(p.body.strip())
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_doctor_block(report: dict[str, Any]) -> str:
    if report["ok"]:
        return f"[sula] doctor OK — {report['fragments']} fragments, 0 problems\n"
    lines = [
        f"[sula] doctor found {len(report['problems'])} problem(s) "
        f"in {report['fragments']} fragments:"
    ]
    for code, count in report["by_code"].items():
        lines.append(f"  {count:4d}  {code}")
    lines.append("")
    for p in report["problems"]:
        lines.append(f"  {p['code']}: {p['fragment']}")
        if p["detail"]:
            lines.append(f"      {p['detail']}")
    return "\n".join(lines) + "\n"


def render_for_agent(frags: list[Fragment], project_name: str = "") -> str:
    transcripts = sum(1 for f in frags if f.kind == TRANSCRIPT_KIND)
    frags = [f for f in frags if f.kind != TRANSCRIPT_KIND]
    superseded = supersession_map(frags)
    activity = [f for f in frags if f.kind != "principle"]
    lines: list[str] = [
        f"# {project_name} (Sula vector)" if project_name else "# Project context (Sula vector)",
        "",
        f"Convention: v{CONVENTION_VERSION}",
        f"Fragments: {len(frags)}, latest activity at {activity[-1].time if activity else 'n/a'}",
        "",
    ]

    heads = rules_heads(frags)
    if heads:
        if len(heads) > 1:
            lines.append(
                f"! The rule sheet has forked into {len(heads)} versions. Both are shown; "
                "merge them with `rules.py . set --from <file> --why \"<why>\"` before editing."
            )
            lines.append("")
        for head in heads:
            lines.append(f"## Rules — follow these; version {head.id}")
            lines.append("")
            lines.append(head.body.strip())
            lines.append("")
    else:
        lines.append("## Rules — no rule sheet yet")
        lines.append("")
        lines.append(
            "This project has not written its rule sheet. Until it does, the principles and "
            "every judgment still in force follow; each line is a title, so read the fragment "
            "before relying on it. Write the sheet with `rules.py . set --from <file> --why \"<why>\"`."
        )
        lines.append("")
        principles = render_principles_block(frags)
        if principles:
            lines.append(principles.rstrip())
            lines.append("")
        lines.append("## Judgments in force")
        in_force = [
            f for f in activity
            if lane_of(f) == "judgment" and f.id not in superseded
        ]
        if not in_force:
            lines.append("- (none)")
        for f in in_force:
            lines.append(f"- [{f.time}] {f.kind} {f.id}: {_summarize(f)}")
        lines.append("")

    lines.append("## Open goals")
    directions = open_directions(activity)
    if not directions:
        lines.append("- (none)")
    for f in directions:
        lines.append(f"- [{f.time}] {f.kind} {f.id}: {_summarize(f)}")
        if f.get("done_when"):
            lines.append(f"    done when: {f.get('done_when')}")
        if f.get("verifier_ref"):
            lines.append(f"    verifier: {f.get('verifier_ref')}")
    lines.append("")

    if heads:
        recent = [
            f for f in activity
            if lane_of(f) == "judgment" and f.kind != "rules" and f.id not in superseded
        ][-RECENT_JUDGMENTS:]
        lines.append(f"## Recent judgments (last {RECENT_JUDGMENTS}; titles only)")
        if not recent:
            lines.append("- (none)")
        for f in recent:
            lines.append(f"- [{f.time}] {f.kind} {f.id}: {_summarize(f)}")
        lines.append("")

    lines.append("## How to look things up and act")
    lines.append(
        "The reasons behind the rules and all history are in fragments/, append-only. "
        "Read one with `cat fragments/<id>.md`; a rule's bracketed tag is a filename prefix "
        "(`ls fragments | grep '^<tag>'`); search a topic with `grep -ril '<term>' fragments/`."
    )
    if transcripts:
        lines.append(
            f"The dialogue of past turns is in {transcripts} transcript fragments, local to this "
            "machine: `grep -il '<term>' fragments/*--transcript-*` finds what was actually said."
        )
    lines.append(
        "Record a decision with `note.py . --kind decision --title \"<one line>\" \"<why>\"`. "
        "Change a rule with `rules.py . add|edit|remove ... --why \"<why>\"`. Never edit a fragment. "
        "Close every turn with `turn.py` as AGENTS.md describes."
    )
    return "\n".join(lines).rstrip() + "\n"


def _format_human(view: str, result: Any, out: Any) -> None:
    if view == "goals":
        for row in result:
            g = row["goal"]
            out.write(f"{'✓' if row['met'] else '·'} {g['id']}: {g.get('summary','')}\n")
            for v in row["verifications"]:
                passed = v.get("passed") in {True, "true"}
                out.write(f"    {'PASS' if passed else 'FAIL'} [{v['time']}]: {v.get('summary','')}\n")
        return
    if view == "effective":
        out.write(f"## in force ({len(result['in_force'])})\n")
        for it in result["in_force"]:
            out.write(f"- [{it['time']}] {it['kind']}: {it.get('summary','')}\n")
        out.write(f"\n## retired ({len(result['retired'])})\n")
        for it in result["retired"]:
            out.write(f"- [{it['time']}] {it['kind']}: {it.get('summary','')}\n")
            for s in it.get("superseded_by", []):
                out.write(f"    ↳ superseded by [{s['time']}] {s['summary']}\n")
        return
    if view == "journal":
        for day in result:
            out.write(f"## {day['day']}\n")
            for it in day["judgment"]:
                out.write(f"  ◆ {it['kind']}: {it.get('summary','')}\n")
            for it in day["direction"]:
                out.write(f"  → {it['kind']}: {it.get('summary','')}\n")
            for it in day["evidence"]:
                pointer = it.get("pointer")
                tail = f"  [{pointer}]" if pointer else ""
                out.write(f"  · {it['kind']}: {it.get('summary','')}{tail}\n")
            out.write("\n")
        return
    for it in result:
        out.write(f"[{it['time']}] {it.get('kind','?')} {it.get('id','')}: {it.get('summary','')}\n")


VIEWS = ["list", "goals", "effective", "journal", "doctor", "changes-summary"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render a Sula vector folder.")
    p.add_argument("folder", help="path to a folder containing fragments/")
    p.add_argument("--view", default="list", choices=VIEWS)
    p.add_argument("--kind")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--tag")
    p.add_argument("--ref")
    p.add_argument("--lane", choices=LANES)
    p.add_argument("--for-agent", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--project-name", default="")
    args = p.parse_args(argv)

    root = Path(args.folder)
    fragments_dir = root / "fragments" if (root / "fragments").is_dir() else root
    if not fragments_dir.exists():
        print(f"folder not found: {fragments_dir}", file=sys.stderr)
        return 2

    frags, problems = load_report(fragments_dir)
    if args.until:
        frags = filter_fragments(frags, until=args.until)

    if args.for_agent:
        sys.stdout.write(render_for_agent(frags, args.project_name))
        report = view_doctor(frags, problems)
        if not report["ok"]:
            sys.stdout.write("\n" + render_doctor_block(report))
        return 0

    if args.view == "doctor":
        report = view_doctor(frags, problems)
        if args.json:
            json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(render_doctor_block(report))
        return 0 if report["ok"] else 1

    filtered = filter_fragments(
        frags,
        kind=args.kind,
        since=args.since,
        tag=args.tag,
        ref=args.ref,
        lane=args.lane,
    )
    selected = {f.id for f in filtered}

    if args.view == "changes-summary":
        activity = [f for f in filtered if f.kind not in {"principle", TRANSCRIPT_KIND}]
        if args.json:
            json.dump(view_changes_summary(activity), sys.stdout, ensure_ascii=False)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(render_changes_summary_block(activity) + "\n")
        return 0
    if args.view == "goals":
        result: Any = [row for row in view_goals(frags) if row["goal"]["id"] in selected]
    elif args.view == "effective":
        result = {key: [row for row in rows if row["id"] in selected]
                  for key, rows in view_effective(frags).items()}
    elif args.view == "journal":
        result = view_journal(filtered)
    else:
        result = view_list(filtered)

    if args.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _format_human(args.view, result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
