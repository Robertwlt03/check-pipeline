"""The steps that hand the work to Swift's own tools: the build, the tests, their coverage, plutil.

Start:  run by the pipeline as steps, not started on its own
Needs:  Swift; macOS for plutil
Building and testing share the build options of the codebase, so neither rebuilds what the other
built. [coverage] minimum names the least share of lines the tests must reach in each folder below
the source root; not_measured names folders the tests do not measure, each with its reason.
"""

import json
import re
from collections import Counter
from pathlib import Path

from console_look import DIM, paint, table

from check_pipeline.project import Codebase, place, run

# MARK: Settings

PERCENT_WIDTH = 6  # the coverage report's percent column, in characters
PROPERTY_LISTS = {".plist", ".strings"}  # what plutil reads

# A failed expectation in the output of Swift Testing:
# ✘ Test "Sizes …" recorded an issue at FormatTests.swift:18:9: Expectation failed: …
TEST_ISSUE = re.compile(r"""
    Test \s "(?P<test> [^"]+ )" \s recorded \s an \s issue \s at \s   # the test
    (?P<file> [^:\s]+ ) : (?P<line> \d+ ) : \d+ : \s                # its file, line and column
    (?P<message> .+ )                                               # what failed
""", re.VERBOSE)


# MARK: Build and tests


def compiler_problems(codebase: Codebase) -> list[str]:
    result = run(["swift", "build", "--build-tests", "--package-path", str(codebase.package),
                  *codebase.build_options], codebase.root)  # the same build as the index's
    return result.findings(result.diagnostics())


def test_problems(codebase: Codebase) -> list[str]:
    result = run(["swift", "test", "--package-path", str(codebase.package),
                  *codebase.build_options], codebase.root)
    failures = [
        readable_failure(line.strip(), codebase) for line in result.output.splitlines()
        if TEST_ISSUE.search(line) or ": error:" in line
    ]
    return result.findings(failures)


def readable_failure(line: str, codebase: Codebase) -> str:
    """A failed expectation as "Tests/…/File.swift:18: the test: what failed", so the report sorts
    it under its file."""
    issue = TEST_ISSUE.search(line)
    if not issue:
        return line
    test_files = {path.name: path for path in codebase.swift_tests}
    path = test_files.get(issue["file"])
    where = place(path, int(issue["line"])) if path else f"{issue['file']}:{issue['line']}"
    return f"{where}: {issue['test']}: {issue['message']}"


def property_list_problems(codebase: Codebase) -> list[str]:
    files = [path for path in codebase.text_files if path.suffix in PROPERTY_LISTS]
    if not files:
        return []
    result = run(["plutil", "-lint", *map(str, files)], codebase.root)
    return [line for line in result.output.splitlines() if not line.endswith(": OK")]


# MARK: Test coverage


def coverage_problems(codebase: Codebase) -> list[str]:
    """Each folder below the source root whose share of reached lines is below its minimum, and
    each folder that has no rule yet."""
    if codebase.source_root is None:
        return ["no source folder to measure; set [swift] source_root"]
    report = coverage_data(codebase)
    if isinstance(report, list):
        return report
    settings = codebase.section("coverage")
    minimum, not_measured = settings.get("minimum", {}), settings.get("not_measured", {})
    covered_lines, all_lines = lines_per_folder(report, codebase.source_root)
    findings = []
    for folder in sorted(all_lines):
        where = f"{place(codebase.source_root / folder, 1)}"
        share = covered_lines[folder] / all_lines[folder]
        if folder in not_measured:
            continue
        if folder not in minimum:
            findings.append(f"{where}: no coverage rule yet; add the folder to [coverage] minimum "
                            "or not_measured")
        elif share < minimum[folder]:
            findings.append(f"{where}: the tests reach {share:.1%} of the lines, at least "
                            f"{minimum[folder]:.0%} are due")
    return findings


def coverage_data(codebase: Codebase) -> dict | list[str]:
    """The report of the last test run, which measured coverage; the tests run again only when
    they are not current."""
    command = ["swift", "test", "--package-path", str(codebase.package), *codebase.build_options]
    result = run(command, codebase.root)
    if not result.succeeded:
        return result.findings([])
    report_path = run([*command, "--show-codecov-path"], codebase.root).last_line()
    return json.loads(Path(report_path).read_text())


def coverage_report(codebase: Codebase) -> list[str]:
    """Prints how much of each source folder the tests reach."""
    report = coverage_data(codebase)
    if isinstance(report, list):
        return report
    covered_lines, all_lines = lines_per_folder(report, codebase.source_root)
    folders = [*sorted(all_lines), "all"]
    covered_lines["all"], all_lines["all"] = sum(covered_lines.values()), sum(all_lines.values())
    table([(folder, coverage_text(covered_lines[folder], all_lines[folder])) for folder in folders])
    return []


def coverage_text(covered: int, lines: int) -> str:
    """One row of the report, such as "84.2%  (412 of 489 lines)"."""
    percent = f"{covered / lines:.1%}"
    return f"{percent.rjust(PERCENT_WIDTH)}  {paint(f'({covered} of {lines} lines)', DIM)}"


def lines_per_folder(report: dict, source_root: Path | None) -> tuple[Counter, Counter]:
    """Covered and all lines of each folder below the source root, from the report's files."""
    covered_lines, all_lines = Counter(), Counter()
    for source in report["data"][0]["files"]:
        file_name = Path(source["filename"])
        if source_root is None or not file_name.is_relative_to(source_root):
            continue
        folder = file_name.relative_to(source_root).parts[0]
        covered_lines[folder] += source["summary"]["lines"]["covered"]
        all_lines[folder] += source["summary"]["lines"]["count"]
    return covered_lines, all_lines
