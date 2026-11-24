# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-11-20

### Fixed

- `secrets` no longer reports a value read through optional chaining as a secret written into a
  setting, such as `const token = env.DISCORD_TOKEN?.trim();` or `apiKey: config?.apiKey`.

## [0.1.1] - 2026-11-20

### Fixed

- `deadscripts` no longer reports a function that `check-pipeline.toml` names as a project's own
  step, such as `function = "scripts/checks.py:todo_problems"`; the pipeline calls it.

## [0.1.0] - 2026-11-18

### Added

- `check-pipeline` with 23 built-in steps, taken from storage-manager and made project-neutral.
- `check-pipeline.toml`: file lists, steps, groups, and the rules of each check (architecture,
  promises, coverage, disk access, translations, scripts, commits, language terms).
- `[commands.<name>]` for any tool and `[custom.<name>]` for a project's own checks; both can
  replace a built-in step.
- The `samples` step: planted mistakes marked with `expect:` test every check, built-in or own.
- Annotations and a summary table on GitHub; steps that need macOS are skipped elsewhere.

[0.1.2]: https://github.com/Robertwlt03/check-pipeline/releases/tag/v0.1.2
[0.1.1]: https://github.com/Robertwlt03/check-pipeline/releases/tag/v0.1.1
[0.1.0]: https://github.com/Robertwlt03/check-pipeline/releases/tag/v0.1.0
