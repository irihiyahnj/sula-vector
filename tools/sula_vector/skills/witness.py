#!/usr/bin/env python3
"""witness skill: mechanical capture of what actually changed.

Works on any substrate — a git repository, a Drive/Dropbox folder, a plain
folder of company documents. The previously witnessed state is not stored in
a state directory; it is folded out of the prior `kind: witness` fragments,
each of which records only its own delta. Truth stays in fragments (B2, B4).

    python3 witness.py --project-root .
    python3 witness.py --project-root . --label "季度提案定稿" --refs <decision-id>

Optional. On git the history already records what changed; witness is for
folders without version control. Silent and non-appending when nothing
changed. Run it by hand or from any scheduler the substrate already has.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from render import load_fragments

from append import append_fragment, utc_now
from capture import (
    DOCUMENT_SUFFIXES, MAX_ARTIFACT_FRAGMENTS, CaptureError, _encode_path,
    capture_graph, diff_tree, fold_witnessed, ignore_patterns, scan_tree, tree_digest,
)


def now_iso() -> str:
    return utc_now()


def git_info(root: Path) -> dict[str, str]:
    if not (root / ".git").exists():
        return {}
    def run(*cmd: str) -> str:
        try:
            result = subprocess.run(
                cmd, cwd=str(root), capture_output=True, text=True, timeout=20
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    return {
        "commit": run("git", "rev-parse", "HEAD"),
        "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
    }


def git_commits_since(root: Path, since_commit: str) -> list[str]:
    if not (root / ".git").exists() or not since_commit:
        return []
    # `%x00` separates hash+subject from the file list so a commit that only
    # touched fragments/ (e.g. committing a previous witness) is dropped;
    # otherwise each capture would report the commit of the one before it.
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--no-decorate",
                "--name-only",
                "--format=%x00%h %s",
                f"{since_commit}..HEAD",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    out: list[str] = []
    for block in result.stdout.split("\x00"):
        block = block.strip("\n")
        if not block:
            continue
        header, _, files = block.partition("\n")
        paths = [p for p in files.splitlines() if p.strip()]
        if paths and all(p.startswith("fragments/") for p in paths):
            continue
        out.append(header.strip())
    return out


def last_witness_commit(frags: list) -> str:
    for f in reversed(frags):
        if f.kind == "witness" and f.get("commit"):
            return str(f.get("commit"))
    return ""


def write_witness(
    fragments_dir: Path,
    *,
    added: list[str],
    changed: list[str],
    removed: list[str],
    tree: dict[str, tuple[str, int]],
    label: str,
    refs: list[str],
    substrate: str,
    git: dict[str, str],
    commits: list[str],
    baseline: bool,
    parents: list[str] | None = None,
    snapshot: bool = False,
    patterns: list[str] | None = None,
) -> Path:
    headline = label or (
        f"Baseline of {len(tree)} file(s)."
        if baseline
        else f"+{len(added)} ~{len(changed)} -{len(removed)} file(s)."
    )
    fields = {
        "kind": "witness", "refs": refs, "tags": ["witness", "skill"],
        "summary": headline, "substrate": substrate,
        "files_added": len(added), "files_changed": len(changed), "files_removed": len(removed),
        "tree_files": len(tree), "tree_digest": tree_digest(tree), "hash_method": "sha256",
        "baseline": baseline, **git,
        "capture_format": "2", "capture_parents": parents or [], "snapshot": snapshot,
        "capture_ignore": patterns or [], "coverage": "regular-files; symlinks excluded",
    }
    body = [headline, ""]
    if commits:
        body.append("## commits")
        body.extend(f"  {c}" for c in commits)
        body.append("")
    body.append("## delta")
    for rel in sorted(tree) if snapshot else added:
        digest, size = tree[rel]
        body.append(f"+ {digest} {size} {_encode_path(rel)}")
    for rel in [] if snapshot else changed:
        digest, size = tree[rel]
        body.append(f"~ {digest} {size} {_encode_path(rel)}")
    for rel in [] if snapshot else removed:
        body.append(f"- - - {_encode_path(rel)}")

    return append_fragment(fragments_dir, "witness-baseline" if baseline else "witness",
                           fields, "\n".join(body), stamp=now_iso())


def write_artifact(fragments_dir: Path, rel: str, witness_id: str) -> Path:
    return append_fragment(fragments_dir, "artifact", {
        "kind": "artifact", "refs": [witness_id], "tags": ["witness", "skill"],
        "summary": Path(rel).name, "pointer": rel,
    }, f"{Path(rel).name} appeared in the project. Witnessed mechanically; no claim about its content.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Witness what changed in a project folder and append evidence."
    )
    p.add_argument("--project-root", required=True)
    p.add_argument("--label", default="", help="human/agent headline for this change")
    p.add_argument("--refs", nargs="*", default=[], help="ids this evidence supports")
    p.add_argument("--ignore", nargs="*", default=[], help="extra ignore patterns")
    p.add_argument(
        "--no-artifacts",
        action="store_true",
        help="do not emit a kind:artifact fragment per new document",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reconcile", action="store_true", help="After fully syncing, publish a complete snapshot merging capture heads")
    args = p.parse_args(argv)

    root = Path(args.project_root).resolve()
    fragments_dir = root / "fragments"
    if not fragments_dir.is_dir():
        print(f"no fragments/ in {root}", file=sys.stderr)
        return 2

    frags = load_fragments(fragments_dir)
    _, heads, ancestry_errors = capture_graph(frags)
    if ancestry_errors or (len(heads) > 1 and not args.reconcile):
        print("[witness] sync capture history before proceeding; multiple heads require --reconcile: "
              + "; ".join(ancestry_errors or heads), file=sys.stderr)
        return 2
    unknown = [r for r in args.refs if r not in {f.id for f in frags}]
    if unknown:
        print(f"unknown fragment id(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    patterns = ignore_patterns(frags, args.ignore)
    try:
        tree = scan_tree(root, patterns)
    except CaptureError as exc:
        print(f"[witness] incomplete capture: {exc}", file=sys.stderr)
        return 2
    before, witness_count = fold_witnessed(frags)
    added, changed, removed = diff_tree(before, tree)

    git = git_info(root)
    commits = git_commits_since(root, last_witness_commit(frags))
    substrate = "git" if git.get("commit") else "folder"
    baseline = witness_count == 0

    if not (added or changed or removed or commits or baseline or (args.reconcile and len(heads) > 1)):
        print("[witness] no change")
        return 0

    if args.dry_run:
        print(
            f"[witness] would append: +{len(added)} ~{len(changed)} "
            f"-{len(removed)} file(s), {len(commits)} new commit(s), "
            f"substrate={substrate}, baseline={baseline}"
        )
        for rel in (added + changed + removed)[:20]:
            print(f"    {rel}")
        return 0

    target = write_witness(
        fragments_dir,
        added=added,
        changed=changed,
        removed=removed,
        tree=tree,
        label=args.label,
        refs=list(args.refs),
        substrate=substrate,
        git=git,
        commits=commits,
        baseline=baseline,
        parents=heads,
        snapshot=args.reconcile,
        patterns=patterns,
    )
    print(
        f"[witness] + witness  {target.name}  "
        f"(+{len(added)} ~{len(changed)} -{len(removed)}, {len(commits)} commit(s))"
    )

    if args.no_artifacts:
        return 0

    documents = [
        rel for rel in added if Path(rel).suffix.lower() in DOCUMENT_SUFFIXES
    ]
    if not documents:
        return 0
    if len(documents) > MAX_ARTIFACT_FRAGMENTS:
        print(
            f"[witness] {len(documents)} new documents exceeds "
            f"{MAX_ARTIFACT_FRAGMENTS}; recorded in the witness delta only"
        )
        return 0
    for rel in documents:
        created = write_artifact(fragments_dir, rel, target.stem)
        print(f"[witness] + artifact  {created.name}  -> {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
