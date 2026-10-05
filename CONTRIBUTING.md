# Contributing To Sula Vector

Thanks for improving Sula Vector.

## Before You Start

- read [AGENTS.md](AGENTS.md)
- read [README.md](README.md)
- run `python3 tools/sula_vector/render.py . --for-agent` to see the current project context
- keep a project's truth in `fragments/` as an append-only folder of typed fragments; every view is `render(fragments, conventions)` (Tier A)

## Development Flow

1. work in a non-`main` branch, usually with the `codex/` prefix
2. keep changes focused and coherent
3. record judgments with `tools/sula_vector/note.py`; never edit past fragments
4. consider sync impact on adopted projects before changing managed templates
5. run the relevant verification commands before opening a pull request

## Verification Baseline

For substantial code or template changes, run:

```bash
python3 -m py_compile tools/sula_vector/*.py tools/sula_vector/skills/*.py
python3 -m unittest discover -s tools/sula_vector/tests -v
python3 tools/sula_vector/render.py . --view doctor
python3 tools/sula_vector/render.py tools/sula_vector/example --view doctor
python3 tools/sula_vector/tests/handoff_scenarios.py > /dev/null
```

Record why with `note.py`, and change the rule sheet with `rules.py` when a
standing rule changes. The commit message carries the why of the commit.

## Pull Request Expectations

- explain why the change is needed
- call out sync impact explicitly when managed behavior changes
- mention what was verified
- avoid mixing unrelated cleanup into the same batch

## Public Release Guardrail

Do not assume the repository is ready to be made public just because the working tree is clean. Re-check the vector (`render . --for-agent`), the done-gate (`render . --view doctor`), and the sync impact note in the pull request before opening the repository or migrating it to a public remote.
