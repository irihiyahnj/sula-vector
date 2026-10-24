#!/usr/bin/env python3
"""Recall what a Sula vector already knows.

The reader is always a model: it navigates by topic and picks by meaning,
instead of guessing the words a writer used. Topics and search words are
written by the writer, once; every view here is computed from the fragments:

    recall.py --project-root .
        the topic directory: each topic with its count and newest record

    recall.py --project-root . --topic <topic> [--topic ...]
        the records in force under those topics, one line each
        (--no-topic: those without one; --all: every record in force)

    recall.py --project-root . <id-prefix> ...
        trace a record: what it replaced, what replaced it and what is in force
        now, the current rules citing it, references both ways, the other
        records of its turn and the dialogue of that turn

    recall.py --project-root . <term> ...
        every fragment and transcript containing any term, literally and
        ignoring case, most terms matched first

Every join happens at read time, so fragments written before this skill
existed are found the same way. Turns are exact for fragments signed with a
session and inferred, and labelled so, for unsigned ones. Appends nothing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from render import (TRANSCRIPT_KIND, Fragment, _summarize, closure_map, is_symbolic_ref, lane_of,
                    load_fragments, rules_heads, search_words_of, session_of, sheet_rules, standing,
                    supersession_map, time_key, topics, topics_of)

ID_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}")
RULE_TAGS = re.compile(r"\[([^\[\]]+)\]\s*$")


def short(fid: str) -> str:
    return fid.split("--", 1)[0]


def row(f: Fragment, words: list[str]) -> str:
    labels = "".join(f"  #{w}" for w in words)
    return f"{short(f.id)}  {f.kind}  {_summarize(f)}{labels}"


def heads_after(fid: str, superseded: dict[str, list[str]]) -> list[str]:
    """Ids in force that a chain of supersessions leads to from `fid`."""
    seen: set[str] = set()
    frontier = list(superseded.get(fid, []))
    heads: list[str] = []
    while frontier:
        current = frontier.pop(0)
        if current in seen:
            continue
        seen.add(current)
        later = superseded.get(current, [])
        if later:
            frontier.extend(later)
        else:
            heads.append(current)
    return sorted(heads)


def render_directory(frags: list[Fragment]) -> str:
    rows = standing(frags)
    assigned = topics_of(frags)
    directory, none = topics(frags)
    lines = [f"# {len(directory)} topics over {len(rows)} records in force, largest first; "
             "--topic <topic> lists one"]
    for topic, count in directory:
        newest = [f for f in rows if topic in assigned[f.id]][-1]
        lines.append(f"{topic}  {count}  newest: {short(newest.id)}  {_summarize(newest, max_chars=80)}")
    if none:
        lines.append(f"(no topic)  {none}  --no-topic lists them")
    return "\n".join(lines) + "\n"


def render_list(frags: list[Fragment], wanted: list[str], no_topic: bool) -> str:
    rows = standing(frags)
    assigned = topics_of(frags)
    wanted = [w.strip().lower() for w in wanted]
    if no_topic:
        picked, title = [f for f in rows if not assigned[f.id]], "records in force without a topic"
    elif wanted:
        picked = [f for f in rows if set(wanted) & set(assigned[f.id])]
        title = f"records in force under {' · '.join(wanted)}"
    else:
        picked, title = rows, "records in force"
    retired = sum(1 for f in frags if lane_of(f) in {"judgment", "direction"}
                  and f.kind not in {"rules", TRANSCRIPT_KIND, "annotation"}) - len(rows)
    lines = [f"# {len(picked)} {title}, oldest first; {retired} superseded ones are reached "
             "by tracing what replaced them"]
    lines += [row(f, assigned[f.id]) for f in picked]
    return "\n".join(lines) + "\n"


def render_terms(frags: list[Fragment], terms: list[str]) -> str:
    superseded = supersession_map(frags)
    tags = search_words_of(frags)
    shown = topics_of(frags)
    by_id = {f.id: f for f in frags}
    found: list[tuple[list[str], Fragment]] = []
    said: list[tuple[list[str], Fragment]] = []
    for f in frags:
        if f.kind in {"rules", "annotation"}:
            continue
        hay = "\n".join([str(f.get("summary", "")), " ".join(tags[f.id]), f.kind, f.body]).casefold()
        matched = [t for t in terms if t.casefold() in hay]
        if matched:
            (said if f.kind == TRANSCRIPT_KIND else found).append((matched, f))
    for bucket in (found, said):
        bucket.sort(key=lambda hit: time_key(hit[1].time), reverse=True)
        bucket.sort(key=lambda hit: (-len(hit[0]), hit[1].id in superseded))

    lines = [f"# {' · '.join(terms)}: {len(found)} fragments, {len(said)} transcripts; "
             "most terms first, then in force before superseded, then newest"]
    for matched, f in found:
        lines.append(f"[{len(matched)}/{len(terms)} {','.join(matched)}] {row(f, shown[f.id])}")
        if f.id in superseded:
            for head in heads_after(f.id, superseded):
                lines.append(f"    ↳ superseded; in force now: {row(by_id[head], shown[head])}")
    if said:
        lines.append(f"## transcripts ({len(said)})")
        for matched, f in said:
            lines.append(f"[{len(matched)}/{len(terms)} {','.join(matched)}] "
                         f"{short(f.id)}  {_summarize(f, max_chars=120)}")
    return "\n".join(lines) + "\n"


def turn_of(f: Fragment, transcripts: list[Fragment]) -> tuple[Fragment | None, bool]:
    """The transcript that closed the turn `f` was written in, and whether that is exact."""
    session = session_of(f)
    for t in transcripts:
        if time_key(t.time) < time_key(f.time):
            continue
        if session and session_of(t) == session:
            return t, True
        if not session:
            return t, False
    return None, bool(session)


def turn_members(t: Fragment, frags: list[Fragment], transcripts: list[Fragment]) -> list[Fragment]:
    session = session_of(t)
    earlier = [x for x in transcripts if time_key(x.time) < time_key(t.time)
               and (not session or session_of(x) == session)]
    start = time_key(earlier[-1].time) if earlier else (time_key(session) if session else "")
    return [
        f for f in frags
        if f.kind != TRANSCRIPT_KIND
        and start <= time_key(f.time) <= time_key(t.time)
        and (session_of(f) == session if session else True)
    ]


def citing_rules(frags: list[Fragment], fid: str) -> list[str]:
    out = []
    for head in rules_heads(frags):
        for rule in sheet_rules(head.body):
            match = RULE_TAGS.search(rule)
            if match and any(ID_PREFIX.match(tag) and fid.startswith(tag)
                             for tag in match.group(1).split()):
                out.append(rule)
    return out


def render_trace(frags: list[Fragment], f: Fragment) -> str:
    superseded = supersession_map(frags)
    closed = closure_map(frags)
    tags = search_words_of(frags)
    assigned = topics_of(frags)
    by_id = {x.id: x for x in frags}
    transcripts = [x for x in frags if x.kind == TRANSCRIPT_KIND]

    def entry(fid: str) -> str:
        if fid in by_id:
            return row(by_id[fid], assigned[fid])
        return fid if is_symbolic_ref(fid) else f"{fid} (not in this vector)"

    state = "superseded" if f.id in superseded else "in force"
    if lane_of(f) == "direction":
        state = "closed" if f.id in closed else state
    lines = [f"## {f.id}",
             f"kind: {f.kind} ({lane_of(f)}, {state})",
             f"path: fragments/{Path(f.path).name}"]
    if f.get("summary"):
        lines.append(f"summary: {f.get('summary')}")
    if assigned[f.id]:
        lines.append("topic: " + ", ".join(assigned[f.id]))
    if tags[f.id]:
        lines.append("search words: " + ", ".join(tags[f.id]))
    lines.append(f"session: {session_of(f) or 'unsigned'}")
    if f.get("no_judgment"):
        lines.append(f"no judgment: {f.get('no_judgment')}")
    lines += ["", f.body.strip(), ""]

    def section(title: str, ids: list[str]) -> None:
        if ids:
            lines.append(f"{title}:")
            lines.extend(f"  {entry(i)}" for i in ids)

    section("replaces", f.id_list("supersedes"))
    section("replaced by", superseded.get(f.id, []))
    if f.id in superseded:
        section("in force now", heads_after(f.id, superseded))
    section("closes", f.id_list("closes"))
    section("closed by", closed.get(f.id, []))
    section("refers to", f.refs)
    section("referred to by", [x.id for x in frags if f.id in x.refs])
    rules = citing_rules(frags, f.id)
    if rules:
        lines.append("cited by the current rules:")
        lines.extend(f"  {rule}" for rule in rules)

    if f.kind == TRANSCRIPT_KIND:
        exact = bool(session_of(f))
        members = turn_members(f, frags, transcripts)
        label = "recorded in this turn" if exact else \
            "recorded since the previous transcript (inferred: unsigned, any session)"
        section(label, [x.id for x in members])
    else:
        t, exact = turn_of(f, transcripts)
        if t is None:
            lines.append("dialogue: none closed after it yet" if exact
                         else "dialogue: no transcript after it")
        else:
            others = [x.id for x in turn_members(t, frags, transcripts) if x.id != f.id]
            how = "same session" if exact else \
                "inferred: unsigned, so the nearest transcript after it, possibly another session's"
            lines.append(f"dialogue ({how}): {short(t.id)}  {_summarize(t, max_chars=120)}")
            lines.append(f"  cat fragments/{Path(t.path).name}")
            section("same turn" if exact else "same turn (inferred)", others)
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Recall what a Sula vector already knows.")
    p.add_argument("--project-root", required=True)
    p.add_argument("--topic", action="append", default=[], help="list the records under this topic")
    p.add_argument("--no-topic", action="store_true", help="list the records without a topic")
    p.add_argument("--all", action="store_true", help="list every record in force")
    p.add_argument("query", nargs="*", help="id prefixes to trace, or terms to match")
    args = p.parse_args(argv)

    fragments_dir = Path(args.project_root) / "fragments"
    if not fragments_dir.is_dir():
        print(f"no fragments/ in {args.project_root}", file=sys.stderr)
        return 2
    frags = load_fragments(fragments_dir)
    listing = bool(args.topic or args.no_topic or args.all)
    if listing and args.query:
        p.error("list by topic or query by id/terms, not both")
    if listing:
        sys.stdout.write(render_list(frags, args.topic, args.no_topic))
        return 0
    if not args.query:
        sys.stdout.write(render_directory(frags))
        return 0

    prefixes = [q for q in args.query if ID_PREFIX.match(q)]
    if prefixes and len(prefixes) != len(args.query):
        p.error("give id prefixes to trace or terms to match, not both")
    if not prefixes:
        sys.stdout.write(render_terms(frags, args.query))
        return 0

    shown = topics_of(frags)
    blocks = []
    for prefix in prefixes:
        hits = [f for f in frags if f.id.startswith(prefix)]
        if not hits:
            print(f"no fragment id starts with {prefix}", file=sys.stderr)
            return 1
        if len({short(f.id) for f in hits}) == 1:
            blocks.extend(render_trace(frags, f) for f in hits)
        else:
            blocks.append(f"# {len(hits)} fragments start with {prefix}; trace one by its full time\n"
                          + "\n".join(row(f, shown[f.id]) for f in hits) + "\n")
    sys.stdout.write("\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
