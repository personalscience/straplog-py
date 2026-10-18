# CLAUDE.md — straplog-py

Public Python package `straplog` (PyPI): reads StrapLog iOS-app exports (Polar H10 RR in SQLite) and holds the shared HRV algorithms for the StrapLog skills (`personalscience/straplog-skills`). Split out of the app repo's `tools/py` on 2026-10-18 with history.

## Commands

```
uv run --group dev pytest -q · uv build · uv publish (TestPyPI first)
```

## Rules that the tree does not tell you

- The file format contract is `docs/SCHEMA.md` in the StrapLog app repo (`~/dev/ios projects/straplog`), enforced there by `SchemaTests.docsMatch`. A schema bump lands in the app first, then here.
- `straplog.hrv` must stay format-agnostic: no imports from `db`/`export`.
- Metric semantics are fixed for log continuity (hrv-resting's CSV log): ddof=1, `hr_mean` = mean of beat HRs. Changing them is a breaking change.
- Never commit real exports (`*.sqlite` is ignored): they are personal health data. Tests use synthetic fixtures (`tests/conftest.py`).

## Vault

- Plan: `~/.claude/plans/straplog-skills-consolidation.md`
