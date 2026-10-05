## Summary

- what changed
- why it changed

## Verification

- [ ] `python3 -m unittest discover -s tools/sula_vector/tests -v`
- [ ] `python3 tools/sula_vector/render.py . --view doctor`
- [ ] `python3 tools/sula_vector/render.py . --for-agent > /dev/null`
- [ ] `python3 tools/sula_vector/render.py tools/sula_vector/example --view doctor`
- [ ] other project-specific verification is described below

## Sync Impact

- [ ] no adopted-project sync impact
- [ ] sync impact is described below

## Traceability

- [ ] fragments/ contains a judgment explaining this change (`note.py`)
- [ ] the rule sheet reflects any standing rule this change creates or retires (`rules.py`)

## Notes

Describe any rollout caveats, follow-up work, or explicit non-goals.
