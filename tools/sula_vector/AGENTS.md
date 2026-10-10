<!-- sula-vector -->
# AGENTS.md — Sula Vector

This project's memory lives in `fragments/`: an append-only folder of typed
text files. Every view is computed from it. Past fragments are never edited.

## Boot

1. Note the current ISO-8601 UTC time as your `session_start`.
2. Run and read:

```bash
python3 tools/sula_vector/render.py . --for-agent
```

The output is authoritative project context. Its **Rules** section is the
project's rule sheet: follow every line. Each rule ends with the filename
prefixes of the fragments that hold its reason; read them when you need the why
(`ls fragments | grep '^<prefix>'`, then `cat`). Search other history with
`grep -ril '<term>' fragments/`.

## During the turn

Record a judgment whenever you choose a direction, revise one, correct a past
claim, or assess state — one append each:

```bash
python3 tools/sula_vector/note.py . --kind decision --title "<one line>" "<why>"
python3 tools/sula_vector/note.py . --kind correction --supersedes <id> "<what was wrong>"
python3 tools/sula_vector/note.py . --kind goal --title "<outcome>" \
  --done-when "<condition>" --verifier "shell: <command>" "<context>"
python3 tools/sula_vector/note.py . --kind fact --closes <goal-id> "<what closed it>"
```

When a decision creates, changes or retires a standing rule, change the rule
sheet in the same turn, one line at a time:

```bash
python3 tools/sula_vector/rules.py . add --section "<heading>" --why "<why>" "<rule> [<source tag>]"
python3 tools/sula_vector/rules.py . edit --match "<text in exactly one rule>" --why "<why>" "<new rule>"
python3 tools/sula_vector/rules.py . remove --match "<text in exactly one rule>" --why "<why>"
```

Write each rule so that the line alone is enough to act on: what must or must
not be done, the concrete names, values, paths and who decides. Its source tag
is the time prefix of the fragment holding the reason — usually the decision
you just recorded. If no rule sheet exists yet, the boot says so; create the
first one with `rules.py . set --from <file> --why "<why>"`.

On git, the commit message carries the why of each change; there is no
separate capture step.

## Never

- Edit or delete a past fragment. Append a `correction` with `--supersedes`.
- Hand-write a fragment file; `note.py` and `rules.py` derive id and time.
- Declare a goal without a verifier.
- Append a judgment when nothing meaningful changed. (`turn.py` is not a
  judgment: it runs every turn.)
- Move a transcript anywhere git can commit or push it.
- Add a state directory, cache or index beside `fragments/`.

## End of turn

Before claiming done, run the project's own checks and:

```bash
python3 tools/sula_vector/render.py . --view doctor   # must exit 0
```

Then close the turn — every turn, whether or not you recorded anything. Pass
the user's message and your reply as they are; do not summarise or select:

```bash
python3 tools/sula_vector/turn.py . --since <session_start> <<'SULA_TURN'
## User
<the user's message this turn, verbatim>

## Reply
<your reply to the user, verbatim>
SULA_TURN
```

It redacts secrets, keeps the text as a `transcript` fragment that stays on
this machine (`.gitignore` excludes it; the turn is refused if git would still
track it) and prints a receipt. End your reply with its full output, from
`[sula] turn recorded` through the `[sula] +N this turn:` block if one follows.
A reply without that line tells the user the turn was not recorded; if
`turn.py` fails, say so.

## Views

```bash
python3 tools/sula_vector/render.py . --view journal     # day by day
python3 tools/sula_vector/render.py . --view effective   # judgments in force + supersession trail
python3 tools/sula_vector/render.py . --view goals       # goals + verification status
python3 tools/sula_vector/rules.py . log                 # every rule-sheet change and its why
grep -il '<term>' fragments/*--transcript-*              # what was actually said
```

## Adopt into a new project

```bash
mkdir -p new-project/fragments
cp -r tools/sula_vector new-project/tools/sula_vector
cp tools/sula_vector/AGENTS.md new-project/AGENTS.md
```

The full convention is `docs/sula-vector-convention.md`.
