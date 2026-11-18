"""Tests the checks themselves: each rule must find the mistake planted for it in the samples.

Start:  run by the pipeline as the samples step, not started on its own
Needs:  what the checks on the samples need; Swift for a samples package the index steps read
Every planted mistake carries a note on its line, `expect: <part of the finding>`, or on the line
above it, `expect below: …`. The step fails when a check no longer finds a planted mistake, or
when it finds something nobody planted. The samples are a codebase of their own with their own
check-pipeline.toml, so they test a project's custom checks just like the built-in ones.
"""

import re
from collections.abc import Callable

from check_pipeline.project import Codebase, is_text, numbered_lines, place

# MARK: Settings

# The note on a planted mistake: "expect: is short for", or "expect below: …" for the next line.
EXPECTATION = re.compile(r"""
    expect (?P<below> \s below )? :     # expect: or expect below:
    \s* (?P<part> .+? )                 # the part of the finding that must appear
    \s* (?: --> | \*/ )? \s* $          # the end of the note, or of a comment around it
""", re.VERBOSE)


# MARK: Steps


def expectations(codebase: Codebase) -> list[tuple[str, str]]:
    """Each planted mistake: where it is and the part of the finding it must produce."""
    expected = []
    paths = (path for path in codebase.text_files if is_text(path))
    for path, number, line in numbered_lines(paths):
        note = EXPECTATION.search(line)
        if note:
            line_of_mistake = number + 1 if note["below"] else number
            expected.append((place(path, line_of_mistake), note["part"]))
    return expected


def matches(finding: str, where: str, part: str) -> bool:
    return finding.startswith(f"{where}:") and part in finding


# MARK: Step


def sample_findings(codebase: Codebase, checks: list[Callable[[Codebase], list[str]]]
                    ) -> list[str]:
    found = [finding for check in checks for finding in check(codebase)]
    expected = expectations(codebase)
    problems = [
        f"{where}: no check finds '{part}' any more"
        for where, part in expected
        if not any(matches(finding, where, part) for finding in found)
    ]
    problems += [
        f"not planted, but found in the samples: {finding}"
        for finding in found
        if not any(matches(finding, where, part) for where, part in expected)
    ]
    return problems
