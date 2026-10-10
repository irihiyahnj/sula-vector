# CLAUDE.md

This project runs on the Sula Vector convention. **[AGENTS.md](AGENTS.md) is
the authoritative protocol** — read it first and follow it exactly.

Boot (two steps): note the current UTC time as your session start, then run

```bash
python3 tools/sula_vector/render.py . --for-agent
```

Follow the **Rules** section of that output. Record decisions with
`tools/sula_vector/note.py`; change a rule with `tools/sula_vector/rules.py`.
Close every turn with `tools/sula_vector/turn.py` as AGENTS.md describes.

Nothing in this file overrides AGENTS.md. Legacy Sula 0.18.x instructions
(`scripts/sula.py`, `.sula/`, `STATUS.md`) are historical reference only.
