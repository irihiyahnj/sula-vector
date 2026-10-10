#!/usr/bin/env python3
"""Close a turn: keep its dialogue verbatim, redacted, on this machine only.

Recording a judgment needs the agent to decide what is worth keeping, and a
missed decision is silent. Closing a turn needs no decision: the agent passes
the user's message and its reply as they are, every turn, and the receipt this
prints is the user's evidence that it happened. Any format is accepted; the
reader of a transcript is a model, so nothing here parses a host's log.

    python3 tools/sula_vector/turn.py . --since <session_start> <<'SULA_TURN'
    ## User
    <the user's message, verbatim>

    ## Reply
    <the reply, verbatim>
    SULA_TURN

Transcripts are local: the project's .gitignore excludes them, and the turn is
refused if git would still pick one up.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from append import append_fragment
from render import TRANSCRIPT_KIND, load_fragments, render_changes_summary_block, filter_fragments

IGNORE_LINE = "fragments/*--transcript-*"
REDACTED = "[REDACTED]"

# Format-agnostic: each pattern matches a secret by its own shape, wherever it
# appears. Names, client data and prose are not secrets in this sense and stay;
# that is why transcripts never leave the machine.
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]
# Only the value is replaced, so the text still says which credential it was.
VALUE_PATTERNS = [
    re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)"),
    re.compile(r"(?i)(\bauthorization\s*[:=]\s*[\"']?(?:bearer|basic|token)\s+)([^\s\"']+)()"),
    re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._~+/-]{16,}=*)()"),
    re.compile(
        r"(?i)(\b[a-z0-9_.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
        r"private[_-]?key|auth[_-]?key)[a-z0-9_.-]*[\"']?\s*[:=]\s*[\"']?)"
        r"(?![<$*\[{])(?!\d+\b)([^\s\"'`,;)]{6,})()"
    ),
]


def redact(text: str) -> tuple[str, int]:
    count = 0
    for pattern in SECRET_PATTERNS:
        text, n = pattern.subn(REDACTED, text)
        count += n

    def keep_name(m: re.Match) -> str:
        nonlocal count
        if m.group(2).startswith(REDACTED):
            return m.group(0)
        count += 1
        return f"{m.group(1)}{REDACTED}{m.group(3)}"

    for pattern in VALUE_PATTERNS:
        text = pattern.sub(keep_name, text)
    return text, count


def git_root(root: Path) -> Path | None:
    for folder in (root, *root.parents):
        if (folder / ".git").exists():
            return folder
    return None


def ensure_local_only(root: Path) -> str:
    """Make sure git will never pick up a transcript; return how that holds.

    The ignore line is written even without git, so a later `git init` cannot
    sweep the transcripts into the first commit.
    """
    ignore = root / ".gitignore"
    text = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    if IGNORE_LINE not in text.splitlines():
        prefix = "" if not text or text.endswith("\n") else "\n"
        with ignore.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefix}# Sula transcripts stay on this machine\n{IGNORE_LINE}\n")
    if git_root(root) is None:
        return "no git"
    if shutil.which("git") is None:
        return "git-ignored"
    probe = "fragments/2000-01-01T00-00-00Z--transcript-probe.md"
    try:
        result = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", probe],
                                capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "git-ignored"
    if result.returncode == 1:
        raise RuntimeError(f"git would track transcripts here despite `{IGNORE_LINE}` in "
                           f"{ignore}; a later rule re-includes them. Fix .gitignore first.")
    return "git-ignored"


def summary_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and line.lower() not in {"user", "reply", "assistant"}:
            return line[:80]
    return "turn"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Close a turn: keep its dialogue, redacted and local.")
    p.add_argument("project_root")
    p.add_argument("--since", help="session start; also prints what was recorded since then")
    p.add_argument("--author", default="")
    args = p.parse_args(argv)

    root = Path(args.project_root).resolve()
    fragments_dir = root / "fragments"
    if not fragments_dir.is_dir():
        print(f"no fragments/ in {root}", file=sys.stderr)
        return 2
    text = "" if sys.stdin.isatty() else sys.stdin.read().strip()
    if not text:
        print("nothing to record: pass the user's message and your reply on stdin", file=sys.stderr)
        return 2
    try:
        where = ensure_local_only(root)
        body, hidden = redact(text)
        fields = {"kind": TRANSCRIPT_KIND, "summary": summary_line(body), "author": args.author,
                  "redacted": hidden}
        append_fragment(fragments_dir, "transcript", fields, body)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[sula] turn NOT recorded: {exc}", file=sys.stderr)
        return 2

    tail = f", {hidden} secret(s) redacted" if hidden else ""
    print(f"[sula] turn recorded ({len(body)} chars, {where}, stays on this machine{tail})")
    if args.since:
        recorded = [f for f in filter_fragments(load_fragments(fragments_dir), since=args.since)
                    if f.kind not in {"principle", TRANSCRIPT_KIND}]
        if recorded:
            print(render_changes_summary_block(recorded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
