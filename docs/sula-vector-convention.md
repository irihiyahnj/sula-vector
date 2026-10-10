# Sula Vector Convention

> **A project's truth is an ordered folder of small typed text fragments.
> Every view (status, AI context, governance report, edit decision list)
> is a pure function of that folder.**
>
> No daemon. No kernel directory. No cache as truth. No central type registry.
> The same shape works for code projects, governance projects, client-service
> projects, and creative projects (e.g. video edits).

Convention version: `1.3` (Sula Vector v1.4.0)

v1.1 added **derived identity** (id and time come from the filename, never
from hand-written frontmatter) and **three lanes** (a render-time projection of
every fragment into judgment / evidence / direction).

v1.2 added **atomic no-replace publication** for every built-in writer and
microsecond filenames with a unique suffix.

v1.3 adds the **rule sheet**: one maintained `kind: rules` fragment that the
boot carries in place of the title of every judgment ever made. Doctor is
structural only. See [The rule sheet (1.3)](#the-rule-sheet-13).

Every fragment written under 1.0–1.2 still parses. Fields that 1.3 no longer
reads are ignored; no fragment is rewritten.

---

## The one-line model

```
project_view  =  render(fragments, conventions)
```

`fragments` is a folder of text files. `conventions` is this document. `render`
is a pure function. Everything else (status, AI context blocks, project
memory, agent handoffs) is derived and disposable.

This is the same shape as MadCut's render-as-pure-function:
`EDL = render(transcript, intelligence, master, instructions[])`. Sula is the
generalization to arbitrary project domains.

---

## Workspace shape

Any folder that holds fragments is a **Sula vector**. Typical layout:

```
<project-root>/
├── AGENTS.md          ← the agent protocol (copy of tools/sula_vector/AGENTS.md)
├── tools/sula_vector/ ← reference tooling, optional
└── fragments/         ← every fragment is one file here, append-only
    ├── 2026-05-23T04-21-56Z--decision-monthly-cadence.md
    ├── 2026-05-23T04-30-12Z--fact-contract-signed.md
    └── …
```

The substrate is whatever the project already uses:

- **Code project** — folder lives in git; commits hold the history
- **Company management / client service** — folder syncs through Drive, Dropbox, SharePoint
- **Personal project** — plain local folder
- **Mixed teams** — any combination, because fragments are independent files

A Sula vector is portable: copy the folder to any device, hand it to any LLM,
run `render`, and the agent has full project context. Nothing else needs to
travel with it.

---

## Fragment file

### Filename

```
<ISO-8601-time-Z>--<short-slug>.md
```

Example: `2026-05-23T04-21-56Z--decision-monthly-cadence.md`

The timestamp is the canonical creation time. `:` is replaced by `-` so the
filename is filesystem-safe. Since 1.2 the time may carry microseconds and the
built-in writers append a random suffix, e.g.
`2026-09-05T00-00-00.123456Z--decision-<slug>-<hex>.md`. Readers normalize
whole and fractional seconds when ordering; plain lexical sorting across both
formats is insufficient.

### File body

```
---
id: 2026-05-23T04-21-56Z--decision-monthly-cadence
time: 2026-05-23T04:21:56Z
kind: decision
refs: [2026-04-12T10-00-00Z--fact-contract-signed]
tags: [hospital-acme, cadence]
---
Decided: monthly delivery cadence for hospital-acme.
Rationale: matches their procurement cycle and intake report rhythm.
```

### Identity is derived, not declared (v1.1)

| field  | source of truth                                                     |
| ------ | ------------------------------------------------------------------- |
| `id`   | **the filename stem** — always                                       |
| `time` | **parsed from the filename** — always                                |
| `kind` | frontmatter; the only field that must be authored                    |

`id` and `time` may still appear in frontmatter (every v1.0 fragment has
them, and the built-in writers still emit them). They are then treated as a
redundant copy: render ignores them for identity and reports any disagreement
as a `header-disagreement` problem. A fragment can therefore never carry a
wrong id or a wrong timestamp.

A fragment is **never silently dropped**. A file missing `kind`, or with an
unparsable filename, still loads and surfaces through `--view doctor`. Silent
loss is the one failure an append-only store cannot recover from.

Use `note.py` and `rules.py` rather than writing files by hand — they derive
identity from the clock and refuse unknown `refs` / `closes` / `supersedes`
targets, so a dangling reference cannot be created in the first place.

`kind` is a free-form string. The convention does **not** enumerate kinds
centrally. Projects add new kinds whenever they need them. Render functions
operate generically by filtering on `kind` strings supplied at query time.
The one kind the tooling treats specially is `rules`; see below.

### Three lanes (v1.1)

Every fragment projects into exactly one lane. The lane is computed from
`kind` at render time (override with an explicit `lane:` field). This is a
projection for readers, not a validated enumeration — B3 and E4 still hold.

| lane        | question    | metaphor | typical kinds                                              |
| ----------- | ----------- | -------- | ---------------------------------------------------------- |
| `judgment`  | **why**     | 方向     | `rules`, `decision`, `correction`, `principle`, `assessment`, `annotation`, `preference`, `pitfall` |
| `evidence`  | **what**    | 位置     | `fact`, `verification-fact`, `artifact`, `witness`, `release`, `operation` (and any unlisted kind) |
| `direction` | **where to**| 去向     | `intent`, `goal`                                            |

The division carries the operating rule: **a human or agent supplies judgment;
the substrate and the runtime supply evidence.** Anything mechanical (a file
appeared, a commit landed, a hash changed) is not narrated by hand — see
*Evidence* below.

### Supersession and closure (v1.1)

Optional list fields make the append-only graph resolvable:

| field         | meaning                                                             |
| ------------- | ------------------------------------------------------------------- |
| `supersedes`  | ids of judgments this fragment replaces; render drops them from the boot and shows the trail in `--view effective` |
| `closes`      | ids of directions this fragment closes; closed directions leave the open list |

Both are explicit only. Referencing a fragment in `refs` never implies
replacing or closing it, so context links stay free of side effects.

### Common optional fields

| field          | meaning                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------- |
| `refs`         | list of other fragment ids (or symbolic refs containing `:`, which doctor does not resolve) |
| `tags`         | free-form labels                                                                         |
| `lane`         | overrides the lane derived from `kind`                                                   |
| `summary`      | one-line title shown in views (`note.py --title`)                                        |
| `pointer`      | URL or relative path to an external artifact (PDF, deck, sheet, code path, video)        |
| `done_when`    | success condition for goals/intents                                                      |
| `verifier_ref` | how `done_when` is checked, e.g. `shell: <command>`                                      |
| `passed`       | `true`/`false` on a `verification-fact` fragment                                         |
| `broken_ref`   | ids of dangling references this fragment acknowledges (see doctor)                       |
| `witness_ignore` | extra ignore patterns for the `witness` skill                                          |
| `author`       | who appended this fragment (human, agent name, system)                                   |

Projects may add any other field. Fields that earlier releases read —
`explains`, `explained_by`, `governs`, `review_after`, `review_when`, `scope`,
`verification_paths`, `verification_scope`, `verified_tree_digest`,
`thread_id`, `family_key`, `artifact_role`, `pinned` — still parse and are
ignored since 1.3.

---

## Recommended starter kinds

Common across domains. Treat as starters, not as a closed schema.

| kind                 | purpose                                                            |
| -------------------- | ------------------------------------------------------------------ |
| `rules`              | the project's rule sheet; written only by `rules.py`               |
| `intent`             | a desired direction or action                                      |
| `decision`           | a chosen option with rationale                                     |
| `correction`         | a past claim that was wrong (uses `supersedes`)                    |
| `fact`               | something that happened or was observed                            |
| `artifact`           | a deliverable (with `pointer`)                                     |
| `annotation`         | comment/markup on another fragment (uses `refs`)                   |
| `goal`               | a long-running intent with `done_when` and `verifier_ref`          |
| `verification-fact`  | output of a verifier (test, benchmark, manual sign-off)            |
| `skill`              | a reusable workflow recipe                                         |
| `preference`         | persistent agent memory (likes/dislikes, defaults)                 |
| `pitfall`            | known issue to remember                                            |

Domain-specific kinds (`milestone`, `regulatory-approval`, `edit-instruction`,
`rendered-cut`, `ticket`, `incident`, `release`, …) are added by writing them.
The render function does not need to know them in advance.

---

## How relationships emerge

Relationships are not stored in a central index. They live in `refs`,
`supersedes` and `closes` on individual fragments and are joined at render
time:

- Judgments in force = judgment-lane fragments that nothing supersedes
- Current rule sheet = the `rules` fragment that nothing supersedes
- Goal status = `goal` plus its `verification-fact` fragments via `refs`, or a fragment that `closes` it

There is no separate "relations table" to keep in sync. There is only the
fragment graph and a render call.

This is the same property as MadCut: given the same `(fragments, conventions)`,
every view is byte-stable. Nothing depends on history of who rendered what
when.

---

## Standard views

The reference renderer exposes a small set of named views. Each view is a
deterministic function of the fragments and a query.

| view              | what it returns                                                       |
| ----------------- | --------------------------------------------------------------------- |
| `--for-agent`     | the boot: rule sheet, open goals, recent judgments, lookup instructions |
| `list`            | all fragments matching the filter, sorted by `time`                   |
| `journal`         | day by day: what was decided, what was produced (the human/company view) |
| `effective`       | judgments in force plus the retired ones and what superseded them     |
| `goals`           | goals and intents with their verifications and whether each is met    |
| `doctor`          | structural integrity of the vector; exit code 1 when problems exist   |
| `changes-summary` | what was appended in a window (used for the turn-mark)                |

Filters: `--kind`, `--lane`, `--since`, `--until`, `--tag`, `--ref`; `--json`
for machine output. `--until` bounds the history before relations are
resolved; the other filters select what is displayed. New views are added by
writing a new function; they never require a new on-disk format.

### `--view doctor`

Doctor is a pure function of the fragments — no state, no network, no writes.
It reports: `unreadable`, `no-frontmatter`, `missing-kind`,
`unparsable-filename`, `unparsable-time`, `header-disagreement`,
`duplicate-id`, `dangling-ref`, `goal-without-verifier`, `rules-fork`,
`rules-malformed`. Exit code is 1 when anything is found, so the same command
works as a CI gate and as a goal verifier
(`verifier_ref: shell: python3 tools/sula_vector/render.py . --view doctor`).

Doctor checks structure only. Whether a change has a recorded why, whether a
judgment is still current, and whether a file was observed are not doctor
questions. `--for-agent` appends the doctor block whenever problems exist.

A dangling reference is treated as acknowledged when some fragment records it
in a `broken_ref` field — the append-only repair path, since the broken
fragment itself can never be edited (B1, E3). `broken_ref` takes one id or a
list, so a project that inherited hundreds of bad references from hand-written
fragments settles them in one append:

```bash
python3 tools/sula_vector/render.py . --view doctor --json \
  | python3 -c "import json,sys;print(','.join(sorted({p['detail'][3:] for p in json.load(sys.stdin)['problems'] if p['code']=='dangling-ref'})))"
python3 tools/sula_vector/note.py . --kind correction --broken-ref <the ids> "<what was lost>"
```

`--broken-ref` is the one write flag `note.py` does not validate: those ids are
broken precisely because nothing carries them.

---

## The rule sheet (1.3)

The boot is the one view every agent reads. Before 1.3 it carried the title of
every judgment in force. A title names an event; an agent that reads only
titles knows something happened but not what it must now do. The rule sheet
is the list of what must now be done, maintained as one document.

### Format

The sheet is the body of a `kind: rules` fragment:

```
## 部署
- Deploy only from main after `make check` passes; the release owner decides hotfixes. [2026-09-18T02-46-23Z]

## 客户
- Acme receives deliverables monthly, on the first business day. [2026-04-15T03-00-00Z]
```

- `## ` lines are topic headings.
- Every rule is one line starting with `- `, written so that the line alone is
  enough to act on: what must or must not be done, the concrete names, values,
  paths and who decides.
- Each rule ends with the filename prefixes (time part) of the fragments that
  hold its reason. The reason stays in those fragments; the sheet does not
  repeat it.
- Nothing else is allowed: blank lines are fine, any other line, a duplicate
  rule, or a sheet with no rule is malformed.

### Operations

```bash
python3 tools/sula_vector/rules.py . show
python3 tools/sula_vector/rules.py . add    --section "<heading>" --why "<why>" "<rule> [<source tag>]"
python3 tools/sula_vector/rules.py . edit   --match "<text in exactly one rule>" --why "<why>" "<new rule>"
python3 tools/sula_vector/rules.py . remove --match "<text in exactly one rule>" --why "<why>"
python3 tools/sula_vector/rules.py . set    --from <file> --why "<why>"
python3 tools/sula_vector/rules.py . log
```

`add`, `edit` and `remove` change one line; `--match` must select exactly one
rule. `set` replaces the whole sheet and is reserved for writing the first
version and for merging a fork. `show` prints the current version(s); `log`
lists every version with the count of rules added and removed and its why.

### Supersession per version

Every write appends a **complete new** `kind: rules` fragment whose
`supersedes` names the version it replaces and whose `summary` records the
`--why`. Every version stays on disk; the current sheet is the version nothing
supersedes, a pure function of the fragments. The tool prints the lines it
added and removed. A write that leaves the sheet unchanged appends nothing.

`--why` is required on every write: a rule change without its reason cannot be
reviewed later. `--refs` may name the fragments behind the change; unknown ids
are refused. The resulting sheet is validated before it is published, so
`rules.py` cannot write a malformed sheet. `note.py --kind rules` is refused.

When a decision creates, changes or retires a standing rule, the agent records
the decision with `note.py` and changes the sheet in the same turn; the
decision's time prefix becomes the rule's source tag.

### Forks

Two versions that supersede the same parent — two agents or two devices
editing at once, joined by the substrate — are a fork. Both are current:

- `--for-agent` shows every current version, preceded by a fork notice;
- doctor reports `rules-fork`;
- `add`, `edit` and `remove` are refused until `set --from <file>` publishes a
  merged sheet that supersedes all current versions.

A current version that does not match the format (for example one written by
hand) is reported as `rules-malformed`.

### Writing the first sheet

Until a sheet exists, the boot says so and falls back (see *Agent boot
contract*); `add`, `edit` and `remove` are refused. For a project with
history, the first sheet is the one risky step: build it from
`--view effective`, have a reader that did not write it check every line
against its sources, fix what it finds, and re-check the changed lines until
the check finds nothing.

---

## Evidence

On git, the history records what changed and the commit message carries the
why of each change. There is no separate capture step.

For a folder without version control, the optional `witness` skill records
what changed:

```bash
python3 tools/sula_vector/skills/witness.py --project-root .
```

It scans the project folder, compares against the last witnessed state, and
appends one `kind: witness` fragment recording the delta — path, SHA-256 and
size for every added, changed, and removed file. On a git repository it also
records `commit` and `branch` and the commits since the previous witness.
Newly appeared documents (`.pdf`, `.docx`, `.xlsx`, `.pptx`, `.pages`, `.key`,
…) additionally get one `kind: artifact` fragment each with a `pointer`, so
they show up in `--view journal`.

- **No state directory.** The previous state is folded out of the prior
  witness fragments, each of which carries only its own delta (B2, B4, E1, E2).
- **Silent when nothing changed.** Running it twice appends nothing (C7).
- **Configuration is a fragment.** Ignore patterns come from the defaults plus
  any fragment carrying `witness_ignore` (B2).
- If synced copies have produced diverging witness histories, witness refuses
  to capture until `--reconcile`, run after the sync is complete, records the
  local tree as a full snapshot.

Nothing gates on witness: doctor does not read it, and a project that never
runs it is complete. Sula installs no capture trigger; run it by hand or from
a scheduler the substrate already has.

### Judgment has no mechanical source

| lane | source | end |
| --- | --- | --- |
| `evidence` | the substrate (git), optionally `witness` | not needed; evidence only recedes into the past |
| `direction` | authored | `closes`, or the latest verification passed (B9) |
| `judgment` | **authored — nothing can supply it** | explicit supersession |

The supply of *why* is not mechanizable and must not be faked. Generating it
from commit messages or chat transcripts would put a machine's inference into
the one lane that exists to hold deliberate thought — E1 in a new costume, and
worse than an empty lane because it reads as if someone had thought.

A judgment stays in force until something supersedes it. What an agent must
act on now is kept current in the rule sheet; the judgments hold the reasons.

### A verifier is required, not proven

B9 makes a goal carry a verifier: `note.py --kind goal` refuses without
`--verifier`, and doctor reports `goal-without-verifier`. A goal is met when a
fragment `closes` it, or when its latest `verification-fact` passed.

```bash
python3 tools/sula_vector/skills/verifier-shell.py --project-root .
```

`verifier-shell` runs the command of every unmet goal whose `verifier_ref`
starts with `shell:` and appends a `verification-fact` with `passed` and the
command output.

Nothing checks that the verifier tests the claim, and in general nothing can:
whether a command proves a `done_when` is not decidable from the fragments.
Nor does a passing result prove anything about external state. Judging that
stays with the reader.

---

## Worked example: a company, not a codebase

A client-service folder on Drive. No git, no code, no build.

```bash
mkdir -p acme/fragments
cp -r tools/sula_vector acme/tools/sula_vector
cp tools/sula_vector/AGENTS.md acme/AGENTS.md
```

Work happens the way it already happens — someone writes a proposal, someone
exports a quote sheet:

```bash
# a judgment: why, in one append
python3 acme/tools/sula_vector/note.py acme --kind decision \
  --title "对 Acme 采用月度交付节奏" --tags acme cadence "理由：匹配他们的采购周期。"

# the evidence: no git here, so witness records it
python3 acme/tools/sula_vector/skills/witness.py --project-root acme \
  --label "Acme 提案与报价定稿"
```

```
$ python3 acme/tools/sula_vector/render.py acme --view journal
## 2026-07-25
  ◆ decision: 对 Acme 采用月度交付节奏
  · witness: Acme 提案与报价定稿
  · artifact: acme-提案-v1.pdf  [客户资料/acme-提案-v1.pdf]
  · artifact: acme-报价.xlsx  [客户资料/acme-报价.xlsx]
```

Later, the proposal is revised and the quote sheet withdrawn. Nobody records
that by hand:

```
$ python3 acme/tools/sula_vector/skills/witness.py --project-root acme
[witness] + witness  2026-07-25T11-15-35.204871Z--witness-<hex>.md  (+0 ~1 -1, 0 commit(s))
$ python3 acme/tools/sula_vector/skills/witness.py --project-root acme
[witness] no change
```

Any LLM handed the `acme/` folder now boots into the same context, on any
device, with no install and no network.

---

## Agent boot contract

Any LLM, on any device, joining a Sula vector for the first time does exactly
two things:

1. Read `AGENTS.md` (the agent protocol).
2. Run `render --for-agent` over the fragment folder.

Step 2 produces a text block with:

- **Rules** — the current rule sheet, to be followed line by line (every
  current version and a notice if it has forked);
- **Open goals** — directions not yet met, with `done_when` and verifier;
- **Recent judgments** — the titles of the last 10 judgments in force (rule
  sheets excluded);
- **How to look things up** — `cat fragments/<id>.md`; a rule's source tag is a
  filename prefix (`ls fragments | grep '^<tag>'`); `grep -ril '<term>'
  fragments/` for anything else; and the commands to record a decision or
  change a rule.

If doctor finds problems, its report follows the block.

**Without a rule sheet** the boot says so and keeps the pre-1.3 shape: the
notice, any `kind: principle` fragments the project carries, the titles of
every judgment in force, open goals, and the lookup instructions.

Every subsequent agent action is one operation: **append a new fragment**. The
agent never edits past fragments and never maintains hidden state. When the
agent stops, the next agent — even on a different model and a different device
— resumes by repeating the same two-step boot.

This is what makes a Sula vector a vector in the strict sense: it points
somewhere (the folder), it carries direction (time-ordered fragments), and it
composes (multiple vectors merge by union of fragments).

---

## Agent superpowers, expressed in this convention

Each capability is a fragment kind plus an optional adapter. No new
dimension is required.

| Capability                           | fragment realisation                                                       |
| ------------------------------------ | -------------------------------------------------------------------------- |
| Standing rules                       | the `kind: rules` sheet, changed one line at a time                        |
| Voice input                          | transcribed body in a `kind: intent` or `kind: decision` fragment          |
| Browser / chrome / computer / MCP    | adapters that read `intent`, write `fact` and `artifact` fragments         |
| Skills                               | `kind: skill`, body holds the recipe                                       |
| Mobile                               | same vector; whichever device can write to the substrate writes a fragment |
| Goals with verifiers                 | `kind: goal` with `done_when` and `verifier_ref`; a passing `kind: verification-fact` meets it |
| Side-panel artifacts                 | `kind: artifact` with `pointer`                                            |
| Annotations                          | `kind: annotation` with `refs`                                             |
| Shared memory / Obsidian-style vault | the fragment folder itself                                                 |
| Memories (preferences, pitfalls)     | `kind: preference`, `kind: pitfall`                                        |

---

## Substrate and concurrency

Sula does not handle storage, sync, or concurrency. The substrate does.

| substrate                           | what it gives                                                       |
| ----------------------------------- | ------------------------------------------------------------------- |
| **git**                             | content-addressed history, signing, branching, merge, distributed clone |
| **Google Drive / Dropbox / OneDrive** | live multi-user sync with per-file granularity                      |
| **plain local folder**              | trivial portability                                                 |
| **any combination**                 | works because fragments are independent files                       |

Multiple agents and multiple devices appending in parallel produce multiple new
files. Filesystem semantics resolve concurrency. Sula does not invent locking,
transactions, or consensus. The one place parallel writers meet is the rule
sheet, and a collision there surfaces as a fork rather than a lost write.

Every built-in writer publishes through `append.py`: it creates the file with
`O_EXCL`, so an existing file is never overwritten, and writes the sha256 of the
body as the first header line. Names carry microsecond time and a random suffix,
so independent writers do not collide. Nothing depends on hard links or atomic
rename, so exFAT drives and network mounts work. Visibility is not atomic: a
crash can leave an empty, unclosed or checksum-mismatched file. The loader
excludes it and `doctor` reports `incomplete-fragment`. `sha256` is optional on
read, so earlier fragments stay valid. Dot files (e.g. macOS `._*`) are not
fragments.

---

## What is explicitly outside Sula

These are deliberately **not** part of the convention:

- a daemon or long-running process
- a kernel directory of derived state (`.sula/state`, `.sula/objects`, `.sula/indexes`, etc.)
- a central catalog or registry kept in sync with fragments
- a runtime that must be installed before reading the vector
- enumerated `kind` types
- bundled scheduling, orchestration, capture triggers, or fleet-management subsystems
- a versioning protocol projects must follow to "upgrade Sula"

A Sula vector remains valid even if no Sula tooling exists on the device.
Anyone can re-implement `render` in any language.

---

## Design principles (Tier A through E)

These are the principles Sula itself is designed by. They are not installed
into adopting projects and are not part of the boot. A project states the
rules it works by in its own rule sheet. Principle fragments that earlier
releases copied into a project remain ordinary judgments; they appear only in
the fallback boot of a project without a rule sheet.

### Tier A — Highest rule

> A project's truth is an ordered, append-only folder of typed fragments.
> Every view is `render(fragments, conventions)`.
> No mutation. No implicit state. No truth outside this convention.
>
> If anything else conflicts with this rule, this rule wins.

### Tier B — Invariants (must hold at all times)

- **B1.** No mutation. Append-only. Past fragments are immutable.
- **B2.** No implicit state. Anything that affects render output must be a named fragment.
- **B3.** `kind` is a free-form string. No central enumeration of kinds. New scenarios add strings, not dimensions.
- **B4.** No daemon, no kernel directory, no cache-as-truth, no central catalog.
- **B5.** Given the same `(fragments, conventions)`, the rendered view is byte-stable.
- **B6.** Any LLM, any device, two-step boot: read AGENTS.md, run `render --for-agent`. Anything more required is a leak.
- **B7.** The substrate (git / Drive / filesystem) handles storage and concurrency. Sula does not invent its own.
- **B8.** Important context must land in fragments. Conversation transcripts alone do not count as durable memory.
- **B9.** Goals must carry a verifier. Ambition without verification is a wish, not a goal.

### Tier C — Aesthetics

- **C1.** 找到本质的维度，在那一层解决问题。极简和高级感不是目标，是维度找对了的结果。
- **C2.** 不搏斗，站上去。代码量骤降、问题消失（不是被处理，是不存在了）才是对的层。
- **C3.** 几何 > 尺寸。文件远超参考线 = 去看几何，不要拿剪刀。
- **C4.** 越过界限。常规的不要参考。
- **C5.** 极简交互：每一次变化 = 追加一个片段；不超过一个动作。
- **C6.** 隐喻贯穿一切。在 Sula 这一层，隐喻是“矢量与流”。
- **C7.** 不要 churn。没有有意义的变化就不追加片段。

### Tier D — Implementation discipline

- **D1.** Standard library only when reasonable. No mandatory third-party dependencies.
- **D2.** Zero comments unless WHY is non-obvious (hidden constraint, workaround, non-obvious invariant).
- **D3.** No TODO, no placeholder functions, no half-implementations.
- **D4.** No backwards-compatibility shims. Change the code directly.
- **D5.** No claim of done without verification. Build / tests / byte-stable replay must pass where applicable.

### Tier E — Anti-patterns (delete on sight)

- **E1.** Storing derived views as truth (status snapshots, indexes, catalogs as primary).
- **E2.** Adding a new state directory beside `fragments/`.
- **E3.** Editing or deleting past fragments. Even "cleanup" or "merge" — append a new fragment that refs the old instead.
- **E4.** Centralizing the `kind` enumeration or central kind validation.
- **E5.** Inventing a new substrate / runtime / daemon when an existing one already solves it.
- **E6.** Wrapping fragments in a SaaS-shaped registry / orchestration / API surface.
- **E7.** Splitting a file purely to satisfy a line count.
- **E8.** Leaving decisions and context in chat transcripts only, never landed in fragments.
- **E9.** Declaring a goal without a verifier.

## Skills (Superpowers)

The convention deliberately keeps the core minimal: one folder of fragments
plus one render function. New capabilities — verifiers, voice transcription,
browser automation, anything an agent might want to add — live **outside**
the core, as **skills**.

A skill is a small, independent program that:

1. Takes `--project-root <path>` as its argument.
2. Reads fragments from `<project-root>/fragments/`.
3. Filters to fragments it cares about (by `kind`, `refs`, `tags`).
4. Does its work.
5. Appends new fragments back through `append.py`.
6. Exits.

Skills must obey every Tier B invariant. Skills must not introduce a state
directory, daemon, central registry, or SaaS-shaped wrapper. The "registry"
of available skills is `ls tools/sula_vector/skills/` — no manifest, no
plugin descriptor, no version negotiation.

Skills are invoked by whatever the substrate already provides (cron,
file-watchers, git hooks, agents, humans). Sula does not start, schedule,
supervise, or install triggers for skills (B7).

Two skills ship: `verifier-shell.py` (runs shell-command goal verifiers and
emits `verification-fact` fragments) and `witness.py` (optional evidence for
folders without git). The full skills contract is in
`tools/sula_vector/skills/README.md`.

Adding a new skill is one action: drop a script into the skills folder.
Removing one is one action: delete it. No project changes are required.

## Turn-mark for user visibility

The convention itself is silent (C5, C7). The agent protocol asks the agent to
show its user a mark at the end of any turn in which it appended fragments.
The mark is generated from the existing `--since` filter:

```
$ python3 tools/sula_vector/render.py . --view changes-summary --since <session-start-ISO>
[sula] +2 this turn:
  + decision           对 Acme 采用月度交付节奏
  ✓ verification-fact  PASS  goal-q3-renewal
```

If nothing was appended this turn, the output is `[sula] no changes` and the
host displays nothing (C7).

The session-start timestamp is **host-local** state, not Sula state. Sula
remains stateless. The agent notes the time at boot and calls
`--view changes-summary --since ...` once per turn.

This pattern is principle-compatible:
- B2 (no implicit state): the timestamp lives in the host, not in Sula
- C5 (minimal interaction): one render call, one block out
- C7 (no churn): silent when nothing happened

## Reference implementation

A pure-Python reference renderer lives at `tools/sula_vector/render.py`. It is
standard library only and implements every standard view. Reimplement it in
any language; given the same `(fragments, conventions)`, the rendered view is
byte-stable.

The write path:

- `note.py` — judgments, goals, facts, corrections, closures. Refuses unknown
  targets, a goal without `--verifier`, and `--kind rules`.
- `rules.py` — the rule sheet.
- `skills/verifier-shell.py` — verification results.
- `skills/witness.py` — optional evidence for folders without git.

All of them publish through `append.py`. All are optional: a fragment is just
a text file, and a project stays valid if no Sula tooling exists on the
device.

`update-from-canonical.sh` / `migrate.py` refresh an adopted project's
`tools/sula_vector/`, remove tooling and capture triggers earlier releases
installed (only when recognisably Sula's), and rewrite the protocol region of
`AGENTS.md`. Existing fragments are never rewritten.

---

## Versioning the convention

Bump the convention version when the fragment filename grammar requires a new
reader, a previously valid fragment would no longer parse, or readers change
which fields they give meaning to. Bumps are rare. Adding a recommended kind, a
new view, or a new optional field is **not** a bump — projects add those
locally without coordination.

Current convention version: `1.3` (Sula Vector v1.4.0, 2026-10-05). Every
1.0–1.2 fragment still parses; fields 1.3 no longer reads are ignored. Readers
must accept the microsecond filenames introduced in 1.2.

See `tools/sula_vector/RELEASE-NOTES.md` for release notes and the upgrade
path.
