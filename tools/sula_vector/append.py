"""Publish complete, immutable fragments using filesystem no-replace semantics."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if any(c in text for c in '\n\r,[]"') or text.lower() in {"true", "false"}:
        return json.dumps(text, ensure_ascii=False)
    return text


def frontmatter_lines(fields: dict[str, object]) -> list[str]:
    lines = []
    for key, value in fields.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
            raise ValueError(f"invalid field key: {key!r}")
        if value in (None, "", [], ()):
            continue
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: {json.dumps(list(value), ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {scalar(value)}")
    return lines


def fragment_text(fields: dict[str, object], body: str) -> str:
    text = "---\n" + "\n".join(frontmatter_lines(fields)) + "\n---\n" + body.strip() + "\n"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        # Arguments arrive with undecodable bytes when a shell splits a
        # multibyte character, e.g. `$VAR：` in a non-UTF-8 locale.
        raise ValueError(f"text is not valid UTF-8 near {text[max(0, exc.start - 20):exc.start]!r}; "
                         "check how the shell passed it, or pass it through stdin") from None
    return text


def publish(target: Path, text: str) -> bool:
    """False means the destination already exists, never that it was overwritten.

    A same-directory hard link publishes the complete inode atomically without
    replacing another writer's file. A crash can leave only an ignored .tmp,
    never a partially written .md. Unsupported substrates fail explicitly.
    """
    fd, staging = tempfile.mkstemp(prefix=".append-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(staging, target)
        except FileExistsError:
            return False
        return True
    finally:
        os.unlink(staging)


def append_fragment(
    folder: Path, slug: str, fields: dict[str, object], body: str, *, stamp: str | None = None
) -> Path:
    stamp = stamp or utc_now()
    datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug).strip("-")[:100] or "fragment"
    while True:
        target = folder / f"{stamp.replace(':', '-')}--{slug}-{uuid4().hex}.md"
        metadata = {"id": target.stem, "time": stamp, **fields}
        metadata["id"], metadata["time"] = target.stem, stamp
        if publish(target, fragment_text(metadata, body)):
            return target
