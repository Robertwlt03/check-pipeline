"""A check of a project's own, as a sample: every FIXME left in the Swift code is a finding.

Start:  run by check-pipeline as the step [custom.fixme] of the samples
Needs:  check-pipeline
"""

from check_pipeline.project import Codebase, numbered_lines, place


def fixme_problems(codebase: Codebase) -> list[str]:
    return [
        f"{place(path, number)}: a FIXME left in the code; fix it or open an issue"
        for path, number, line in numbered_lines(codebase.swift_sources) if "FIXME" in line
    ]
