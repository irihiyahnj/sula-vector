# Sula Vector

> **Project memory for AI agents: the rules to follow, and why.**
> Append-only, any model, any device, standard library only.

```
project_view  =  render(fragments, conventions)
```

A project's memory is an ordered, append-only folder of typed text files.
Every view is a pure function of that folder. No daemon, no state directory,
no vendor. The same shape covers a code repository, a synced folder of
company documents, and a personal project.

**Current release: v1.4.0** (2026-10-05), the stable line. Convention `1.3`;
every older fragment still parses.
[Changes and upgrade steps](tools/sula_vector/RELEASE-NOTES.md#v140--the-boot-carries-the-rules-stable)

---

## What it does

An agent joining a project — another model, another machine, months later —
runs one command and gets:

1. **The rule sheet**: the project's standing rules, one actionable line each,
   with a pointer to the fragment that holds the reason.
2. **Open goals**, each with the condition that closes it and its verifier.
3. **The last ten judgments**, as titles.
4. **How to look up** anything else in the append-only history.

It is a memory and rationale layer, not a project operating system. It does not
schedule, assign, track effort or coordinate actors; git, your sync service and
your existing tools keep doing that.

## Honest assessment

**Measured** (one adopted project with 444 judgments in force, two exams written
independently of the material under test, two blind graders agreeing on 248 of
250 grades):

| agent reads, closed book | standing rules | task scenarios | rules that changed | boot size |
| --- | --- | --- | --- | --- |
| the v1.3 boot (judgment titles) | 5 / 14 | 3–4 / 16 | 2 / 6 | 130.7 KB |
| the v1.4 rule sheet | **14 / 14** | **16 / 16** | **6 / 6** | **48 KB** |

With lookup allowed, the sheet answered all 50 questions and needed lookup for
12. Three agents each changed the sheet one line; no line outside the intended
change moved.

**Not solved:**

- **The first sheet is the risky step.** Distilling 444 judgments produced 5
  wrong lines out of 149; one fix round introduced a new unsupported line. A
  project needs audit → fix → re-check until the check finds nothing.
- **An error in the sheet is acted on.** Agents follow it without checking.
- **History needs lookup.** Closed book, the sheet answered 4 of 14 history
  questions; that is by design — reasons live in the log.
- **Only exams were measured**, on one project, by one model family. The effect
  on real work is inferred, not observed.
- **The tooling detects a missing or malformed sheet, never a wrong rule.**

## Quick start

```bash
git clone https://github.com/irihiyahnj/sula-vector.git
mkdir -p my-project/fragments
cp -r sula-vector/tools/sula_vector my-project/tools/sula_vector
cp sula-vector/tools/sula_vector/AGENTS.md my-project/AGENTS.md
python3 my-project/tools/sula_vector/render.py my-project --for-agent
```

No install, no network, no daemon. Then, from the project root:

```bash
# a decision and its reason
python3 tools/sula_vector/note.py . --kind decision --title "<one line>" "<why>"

# the first rule sheet, then one line at a time
python3 tools/sula_vector/rules.py . set --from sheet.md --why "<why>"
python3 tools/sula_vector/rules.py . add --section "部署" --why "<why>" "<rule> [<source tag>]"
python3 tools/sula_vector/rules.py . edit --match "<text in one rule>" --why "<why>" "<new rule>"
python3 tools/sula_vector/rules.py . remove --match "<text in one rule>" --why "<why>"

# integrity, before claiming done
python3 tools/sula_vector/render.py . --view doctor
```

## Updating an adopted project

```bash
bash tools/sula_vector/update-from-canonical.sh --project-root <path>
```

The update refreshes `tools/sula_vector/`, removes tooling that earlier
releases shipped, removes the capture triggers they installed (only when they
are recognisably Sula's), rewrites the protocol region of `AGENTS.md`, refreshes
host pointers that still hold generated text, and reports doctor. It never
rewrites a fragment. Each project decides when to update.

After updating, write the project's first rule sheet. Until one exists, the
boot shows the principles and every judgment in force, as v1.3 did, with a
notice to create the sheet.

## The rule sheet

One `kind: rules` fragment holds the whole sheet:

```markdown
## 部署
- 只从 restore-bandworks-upstream 分支部署；改其他分支须先移植 [2026-09-28T15-03-06Z]
- 生产 BW_MAX_HOPS=8 是 Owner 的成本拍板，agent 不得自行修改 [2026-09-18T02-46-23Z]
```

- `## ` headings group rules; each rule is one line starting with `- `, enough
  on its own to act on, ending with the filename prefixes of its source fragments.
- Every change appends a complete new version that supersedes the previous one
  and records its `--why`. `rules.py . log` lists every version and reason.
- Line operations select a rule by text that occurs in exactly one line, so a
  stale line number can never edit the wrong rule.
- Two versions with the same parent are a fork: boot shows both, doctor fails,
  and line edits are refused until `set` writes the merge.

## Fragment format

```
fragments/2026-05-23T04-21-56.123456Z--decision-monthly-cadence-<random>.md
```

```markdown
---
kind: decision
refs: [2026-04-12T10-00-00Z--fact-contract-signed]
summary: Monthly delivery cadence
---
Matches the procurement cycle.
```

`id` and `time` come from the filename. `kind` is the only required field and
is a free-form string. A file with no frontmatter, no `kind` or an unparsable
name still loads and surfaces in doctor; nothing is silently dropped.

| field | meaning |
| --- | --- |
| `refs` | related fragment ids |
| `tags` | labels |
| `summary` | one-line headline |
| `lane` | override the lane derived from `kind` |
| `supersedes` | judgments this replaces; they leave force |
| `closes` | directions this closes |
| `done_when` / `verifier_ref` | a goal's success condition and what proves it |
| `passed` | on a `verification-fact` |
| `broken_ref` | ids that never existed; acknowledges references to them |
| `pointer` / `author` | external artifact; who appended this |

Lanes: `judgment` (decision, correction, assessment, rules, principle…),
`direction` (goal, intent), `evidence` (everything else).

## Views

```bash
python3 tools/sula_vector/render.py . --for-agent
python3 tools/sula_vector/render.py . --view journal      # day by day
python3 tools/sula_vector/render.py . --view effective    # judgments in force + supersession trail
python3 tools/sula_vector/render.py . --view goals        # goals + verification
python3 tools/sula_vector/render.py . --view doctor       # integrity; exit 1 on problems
python3 tools/sula_vector/render.py . --view changes-summary --since <ISO>
python3 tools/sula_vector/render.py . --view list --kind decision --tag delivery
```

Filters: `--kind --lane --tag --ref --since --until`, and `--json`.

Doctor checks: `no-frontmatter`, `missing-kind`, `unparsable-filename`,
`unparsable-time`, `header-disagreement`, `duplicate-id`, `dangling-ref`,
`goal-without-verifier`, `rules-fork`, `rules-malformed`.

## Goals

```bash
python3 tools/sula_vector/note.py . --kind goal --title "<outcome>" \
  --done-when "<condition>" --verifier "shell: <command>" "<context>"
python3 tools/sula_vector/skills/verifier-shell.py --project-root .
```

A goal without a verifier is refused. A goal is met when closed
(`note.py --kind fact --closes <id>`) or when its latest verification passed.

## Evidence

On git, history records what changed and the commit message records why.
For a folder without version control, `skills/witness.py` records path and
SHA-256 for every changed file. It is optional; nothing gates on it.

## Principles

Sula is built under five tiers of principles — append-only truth, byte-stable
views, no state beside `fragments/`, free-form kinds, standard library only, no
claim of done without verification. They are this repository's own rules and
are in its rule sheet. Adopting projects carry their own rules, not Sula's.

## Repository layout

```
AGENTS.md                      the protocol agents follow in this repository
CLAUDE.md CODEX.md GEMINI.md   pointers to AGENTS.md (also .cursor/ and .github/)
docs/sula-vector-convention.md the convention spec
tools/sula_vector/             the tooling every project copies
  render.py  note.py  rules.py  append.py  migrate.py  capture.py
  skills/witness.py  skills/verifier-shell.py
  tests/                       stdlib unittest suite and handoff scenarios
  example/                     a small worked vector
fragments/                     this project's own memory
legacy/                        the archived 0.18.x runtime, reference only
```

## Verification

```bash
python3 -m unittest discover -s tools/sula_vector/tests
python3 tools/sula_vector/render.py . --view doctor
python3 tools/sula_vector/render.py tools/sula_vector/example --view doctor
python3 tools/sula_vector/tests/handoff_scenarios.py
```

CI runs these on Python 3.10–3.12 and checks that `--for-agent` renders
byte-identically twice.

## Versioning

- **v1.x** keeps every fragment parseable with its meaning. Tool behaviour may
  change where it was wrong; read the release notes before updating a project
  whose CI depends on doctor.
- **v2.0** would only ship if a previously valid fragment stopped parsing.
- No support window is promised. Pin a tag for stability.

Release history and details: [`tools/sula_vector/RELEASE-NOTES.md`](tools/sula_vector/RELEASE-NOTES.md)

## Governance

[CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) ·
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

Licensing: see the repository's license file if present; otherwise treat the
contents as all rights reserved until one is added.
