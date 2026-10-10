# Sula Vector tooling

Project memory is an append-only `fragments/` folder. Render reads it; tools
publish complete new fragments. Python standard library only.

## A session

```bash
python3 tools/sula_vector/render.py . --for-agent        # boot: rules, open goals, recent judgments
python3 tools/sula_vector/note.py . --kind decision --title "<one line>" "<why>"
python3 tools/sula_vector/rules.py . edit --match "<unique text>" --why "<why>" "<new rule>"
python3 tools/sula_vector/render.py . --view doctor      # structural integrity, exit 1 on problems
```

## The rule sheet

The boot carries one maintained sheet of rules instead of the title of every
judgment ever made. A title names an event; an agent that reads only titles
knows something happened but not what it must now do.

```bash
python3 tools/sula_vector/rules.py . show
python3 tools/sula_vector/rules.py . add --section "部署" --why "<why>" "<rule> [<source tag>]"
python3 tools/sula_vector/rules.py . edit --match "<text in exactly one rule>" --why "<why>" "<new rule>"
python3 tools/sula_vector/rules.py . remove --match "<text in exactly one rule>" --why "<why>"
python3 tools/sula_vector/rules.py . set --from sheet.md --why "<why>"   # first version, or merging a fork
python3 tools/sula_vector/rules.py . log
```

Format: `## ` topic headings; every rule is one line starting with `- `, stated
so that the line alone is enough to act on, ending with the filename prefixes
of the fragments that hold its reason, e.g. `[2026-09-18T02-46-23Z]`.

Every change appends a complete new `kind: rules` fragment that supersedes the
previous version and records `--why`. The tool prints the lines it added and
removed. Two versions superseding the same parent are a fork: boot shows both,
doctor reports `rules-fork`, and line edits are refused until `set` merges them.

Writing the first sheet for a project with history is the one risky step.
Build it from the judgments in force, then have a reader that did not write it
check every line against its sources, fix what it finds, and re-check the
changed lines, until the check finds nothing.

## Goals

```bash
python3 tools/sula_vector/note.py . --kind goal --title "Delivery checks pass" \
  --done-when "checks.py exits 0" --verifier "shell: python3 checks.py" "<context>"
python3 tools/sula_vector/skills/verifier-shell.py --project-root .
python3 tools/sula_vector/render.py . --view goals
```

A goal is met when it is closed (`note.py --closes <id>`) or its latest
verification passed.

## Views

`--for-agent`, `--view list | journal | effective | goals | doctor | changes-summary`,
filtered by `--kind --lane --tag --ref --since --until`, with `--json`.

## Evidence

On git, history records what changed and the commit message records why that
change was made. For a folder without version control, `skills/witness.py`
records path and SHA-256 per changed file as a `witness` fragment. It is
optional and nothing gates on it.

## Storage and sync

`append.py` creates each fragment with `O_EXCL` (never replaces a file) and
writes the body's sha256 as the first header line; names carry microsecond time
and a random suffix. No hard links or atomic rename are needed, so exFAT drives
and SMB/NFS/WebDAV mounts work. A crash can leave a torn file; the loader
excludes it and `doctor` reports `incomplete-fragment`. Fragments written
before the checksum existed still load.

Verified: local disks, exFAT (disk image) and SMB shares (concurrent writers,
`doctor` clean). Not verified: NFS, WebDAV, sshfs, AFP and cloud-sync folders;
they should work if `O_EXCL` and `fsync` are honoured, but that is untested.
macOS writes a `._<name>` companion beside every file on filesystems without
native extended attributes (exFAT, SMB). Sula ignores dot files; remove them
with `dot_clean <folder>` if they bother you.

`update-from-canonical.sh` / `migrate.py` refresh this folder, remove tooling
earlier releases shipped, remove capture triggers they installed, and rewrite
the protocol region of `AGENTS.md`. Existing fragments are never rewritten.
