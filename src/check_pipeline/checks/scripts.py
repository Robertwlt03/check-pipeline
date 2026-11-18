"""Checks the scripts: each one reads as its tool reads it, keeps the line length, and opens with
the shared head when the project asks for one.

Start:  run by the pipeline as a step, not started on its own
Needs:  Python; swiftc for Swift scripts and make for Makefiles
[scripts] head names a word every script states in its first lines, such as "Start:", so each
opens the same way; no_shell_scripts = true reports every shell script, for projects that write
their tools in one language.
"""

import re
import sys
from pathlib import Path

from check_pipeline.project import Codebase, lines_of, place, run

# MARK: Settings

HEAD_LINES = 12  # how many lines at the top of a script count as its head
MAKE_RULE = re.compile(r"^([a-z][\w-]*):", re.MULTILINE)  # a rule name such as "build:"
# Reads a Python script the way Python would, without running it and without leaving a cache
# beside it (py_compile would), in the same Python that runs the checks.
COMPILE_ONLY = "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')"


# MARK: Steps


def script_problems(codebase: Codebase) -> list[str]:
    findings = script_layout_problems(codebase)
    for command in syntax_checks(codebase):
        findings += run(command, codebase.root).findings([])
    return findings


def script_layout_problems(codebase: Codebase) -> list[str]:
    settings = codebase.section("scripts")
    head = settings.get("head")
    problems = [
        f"{place(path, 1)}: a shell script; this project writes its tools in another language"
        for path in codebase.shell_scripts if settings.get("no_shell_scripts")
    ]
    for path in codebase.all_scripts():
        problems += long_lines(path, codebase.line_length)
        if head and not any(head in line for line in lines_of(path)[:HEAD_LINES]):
            problems.append(f"{place(path, 1)}: the head lacks '{head}'")
    return problems


def long_lines(path: Path, line_length: int) -> list[str]:
    return [
        f"{place(path, number)}: line longer than {line_length} characters"
        for number, line in enumerate(lines_of(path), start=1)
        if len(line) > line_length
    ]


def syntax_checks(codebase: Codebase) -> list[list[str]]:
    """Each tool reads a script without running it."""
    checks = [
        *([sys.executable, "-c", COMPILE_ONLY, str(path)] for path in codebase.python_scripts),
        *(["swiftc", "-typecheck", str(path)] for path in codebase.swift_scripts),
    ]
    for makefile in codebase.makefiles:
        rules = MAKE_RULE.findall(makefile.read_text())
        checks.append(["make", "--dry-run", "--file", str(makefile), *rules])
    return checks
