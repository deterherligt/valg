# Contributing to valg

## Branch naming

- `feat/<short-description>` — new feature
- `fix/<short-description>` — bug fix
- `docs/<short-description>` — documentation only
- `test/<short-description>` — tests only
- `chore/<short-description>` — tooling, deps, CI

## Workflow

1. Branch off `main`: `git checkout -b feat/my-thing`
2. Make changes — commit frequently, each commit should pass tests
3. Push and open a PR against `main`
4. Merge when ready (solo: self-merge is fine; open project: request review)

## Commit messages

Use the `type: short description` format:

    feat: add seat flip momentum tracking
    fix: handle missing party votes gracefully
    test: add e2e test for UC3

## Tests

All PRs must pass `pytest tests/ -v` before merge. No exceptions.

## Code style

- Python 3.11+
- No external formatters required, but keep functions short and focused
- Follow existing patterns in the codebase

## Note on `valg-data/`

The data repo (`valg-data/`) auto-commits directly to `main` via the sync loop.
GitHub flow applies to the **code repo only**.
