"""The command line: check-pipeline runs a project's checks, one step after another.

Start:  check-pipeline (every step of check-pipeline.toml), check-pipeline <step or group> …,
        or python3 -m check_pipeline …; in the project's root
Needs:  Python 3.13 or newer, and what each chosen step needs (see its module)
It ends with status 1 as soon as one finding is left, so it guards every pull request; on GitHub
each finding also becomes an annotation beside its line (see report.py).
"""

import sys
import time

import console_look as console

from check_pipeline import project, report
from check_pipeline.pipeline import Step, chosen_steps, findings_of
from check_pipeline.project import Codebase, SettingsProblem

# MARK: Settings

PASSED, FAILED, UNKNOWN_STEP = 0, 1, 2  # the exit status of the command

# MARK: Run


def run_steps(codebase: Codebase, steps: list[Step]) -> list[tuple[str, int]]:
    """Runs each step and prints its result; returns each step's title and number of findings."""
    results = []
    for step in steps:
        console.running(step.title)
        started = time.monotonic()
        findings = findings_of(step, codebase)
        if findings is None:
            console.step(step.title, "skipped: needs macOS")
            continue
        report.step_finished(step.title, findings, time.monotonic() - started)
        results.append((step.title, len(findings)))
    return results


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        codebase = project.load()
        steps = chosen_steps(codebase, arguments)
    except SettingsProblem as problem:
        console.heading("check pipeline")
        console.stopped("The settings cannot be used", str(problem),
                        (f"See {project.SETTINGS_FILE} and the README of check-pipeline.",))
        return UNKNOWN_STEP
    report.header(codebase.name, len(steps))
    results = run_steps(codebase, steps)
    report.summary(results)
    return FAILED if any(count for _, count in results) else PASSED


if __name__ == "__main__":
    sys.exit(main())
