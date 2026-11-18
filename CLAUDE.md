# check-pipeline: working notes for Claude

## Toolchain

- Python 3.13 or newer; dependencies are console-look and index-store-reader (pinned to tags in
  `pyproject.toml`), nothing else.
- Swift and macOS for the samples and the steps that read the index or spell.
- Lines at most 100 characters (`.editorconfig`); every script opens with a head that says `Start:`.

## Commands

- Install for work: `pip install -e .`
- Everything, as CI runs it: `check-pipeline` (in the root)
- One step or group: `check-pipeline tests`, `check-pipeline samples`, `check-pipeline code`

## Hard rules

- No check names a project: paths, tables and thresholds come from `check-pipeline.toml`.
- A check is a function `(codebase) -> list[str]`, each finding `path:line: message`.
- Every rule has a planted mistake in `Tests/samples` with `expect:`; a new rule gets one in the
  same commit, and the samples step must pass.
- No dependency beyond the standard library, console-look and index-store-reader.

## Where things go

- Settings, files, tools, index: `src/check_pipeline/project.py`
- Steps, commands, custom checks: `src/check_pipeline/pipeline.py`; report: `report.py`
- The checks: `src/check_pipeline/checks/`, one module per check
- Planted mistakes: `Tests/samples/`; unit tests of the core: `Tests/test_check_pipeline.py`
- README pictures: `docs/pictures/` → `assets/pictures/` (markdown-graphics)

## Before every commit

Run `check-pipeline`; add a line to `CHANGELOG.md` under a new version for anything a user notices.

## Git

- English everywhere; commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:` …).
- Work on a branch and merge into `main` through a pull request with green CI.
- A release is a tag `vX.Y.Z` that matches `pyproject.toml` and `CHANGELOG.md`.
