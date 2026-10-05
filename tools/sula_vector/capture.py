"""Content observation and pure replay shared by capture and readers."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

DEFAULT_IGNORE = [
    ".git",
    ".hg",
    ".svn",
    "fragments",
    ".sula",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".DS_Store",
    ".idea",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "~$*",
]

DOCUMENT_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".pages",
    ".numbers",
    ".key",
    ".odt",
    ".ods",
    ".odp",
    ".csv",
}

MAX_ARTIFACT_FRAGMENTS = 20


class CaptureError(OSError):
    pass


def ignore_patterns(frags: list, extra: list[str]) -> list[str]:
    patterns = list(DEFAULT_IGNORE)
    for f in frags:
        raw = f.get("witness_ignore")
        if not raw:
            continue
        items = raw if isinstance(raw, list) else str(raw).split(",")
        patterns.extend(str(i).strip() for i in items if str(i).strip())
    patterns.extend(extra)
    return patterns


def is_ignored(rel: Path, patterns: list[str]) -> bool:
    parts = rel.parts
    for pattern in patterns:
        if any(Path(part).match(pattern) for part in parts):
            return True
        if rel.match(pattern):
            return True
    return False


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
        current = path.stat()
    except OSError as exc:
        raise CaptureError(f"cannot read {path}: {exc}") from exc
    def signature(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    if signature(before) != signature(after) or signature(after) != signature(current):
        raise CaptureError(f"file changed while hashing: {path}")
    return digest.hexdigest()


def scan_tree(root: Path, patterns: list[str]) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    def failed(exc):
        raise CaptureError(str(exc)) from exc
    for folder, dirs, files in os.walk(root, onerror=failed, followlinks=False):
        base = Path(folder)
        dirs[:] = sorted(d for d in dirs if not is_ignored((base / d).relative_to(root), patterns)
                         and not (base / d).is_symlink())
        for name in sorted(files):
            path = base / name
            rel = path.relative_to(root)
            if is_ignored(rel, patterns) or path.is_symlink():
                continue
            try:
                if not stat.S_ISREG(path.stat().st_mode):
                    continue
                digest = hash_file(path)
                size = path.stat().st_size
            except OSError as exc:
                raise CaptureError(f"cannot capture {rel}: {exc}") from exc
            out[rel.as_posix()] = (digest, size)
    return out


def tree_digest(tree: dict[str, tuple[str, int]]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(tree):
        digest.update(f"{len(rel.encode('utf-8'))}:{rel}:{tree[rel][0]}:{tree[rel][1]}\n".encode("utf-8"))
    return digest.hexdigest()


def _encode_path(rel: str) -> str:
    """JSON quoting preserves leading whitespace and controls in a one-line delta."""
    return json.dumps(rel, ensure_ascii=False)


def decode_path(rel: str, legacy: bool) -> str:
    """Old writers escape only control characters; format-2 writers JSON-quote."""
    if not legacy:
        try:
            parsed = json.loads(rel)
        except json.JSONDecodeError as exc:
            raise CaptureError(f"malformed capture path: {rel}") from exc
        if not isinstance(parsed, str):
            raise CaptureError(f"malformed capture path: {rel}")
        return parsed
    out: list[str] = []
    i = 0
    while i < len(rel):
        if rel[i] == "\\" and i + 1 < len(rel):
            nxt = rel[i + 1]
            if nxt in {"n", "r", "\\"}:
                out.append({"n": "\n", "r": "\r", "\\": "\\"}[nxt])
                i += 2
                continue
        out.append(rel[i])
        i += 1
    return "".join(out)


def capture_graph(frags: list) -> tuple[list, list[str], list[str]]:
    witnesses = [f for f in frags if f.kind == "witness"]
    by_id = {f.id: f for f in witnesses}
    parents = {}
    previous = None
    for f in witnesses:
        if f.get("capture_format") == "2":
            parents[f.id] = f.id_list("capture_parents")
        else:
            parents[f.id] = [previous.id] if previous and previous.get("capture_format") != "2" else []
            previous = f
    errors = [f"{fid} -> missing capture {p}" for fid, ps in parents.items()
              for p in ps if p not in by_id]
    errors.extend(f"{fid}: joining captures requires a full snapshot"
                  for fid, ps in parents.items() if len(ps) > 1
                  and by_id[fid].get("snapshot") not in {True, "true"})
    remaining = dict(parents)
    ordered, seen = [], set()
    while remaining:
        ready = [fid for fid, ps in remaining.items() if all(p in seen for p in ps)]
        if not ready:
            errors.append("capture ancestry is cyclic or incomplete")
            break
        for fid in ready:
            ordered.append(by_id[fid])
            seen.add(fid)
            del remaining[fid]
    heads = sorted(set(by_id) - {p for ps in parents.values() for p in ps})
    return ordered, heads, errors


def fold_witnessed(frags: list) -> tuple[dict[str, tuple[str, int]], int]:
    """Replay every prior witness delta into the last known tree state."""
    state: dict[str, tuple[str, int]] = {}
    count = 0
    ordered, _, errors = capture_graph(frags)
    if errors:
        raise CaptureError("; ".join(errors))
    for f in ordered:
        count += 1
        legacy = f.get("capture_format") != "2"
        if f.get("snapshot") in {True, "true"}:
            state.clear()
        for line in f.body.splitlines():
            parts = line.split(None, 3)
            if len(parts) != 4 or parts[0] not in {"+", "~", "-"}:
                continue
            marker, digest, size, rel = parts
            rel = decode_path(rel, legacy)
            if marker == "-":
                state.pop(rel, None)
            else:
                state[rel] = (digest, int(size) if size.isdigit() else 0)
    return state, count


def diff_tree(
    before: dict[str, tuple[str, int]], after: dict[str, tuple[str, int]]
) -> tuple[list[str], list[str], list[str]]:
    added = sorted(p for p in after if p not in before)
    removed = sorted(p for p in before if p not in after)
    changed = sorted(
        p for p in after if p in before and after[p][0] != before[p][0]
    )
    return added, changed, removed
