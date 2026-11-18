"""The steps of the pipeline: the built-in checks, the project's tool commands and its own checks.

Start:  imported by the command line (__main__.py), not started on its own
Needs:  Python 3.13 or newer
check-pipeline.toml picks the steps and their order (steps = […]), groups them for CI (a [groups]
table), adds tool commands ([commands.<name>] with a title and a command list) and checks of the
project's own ([custom.<name>] with a title and function = "file.py:function"). A step returns its
findings, each "path:line: message"; a step that breaks down becomes one finding, so the steps
after it still run. A [custom.<name>] or [commands.<name>] with a built-in step's name replaces it.
"""

import importlib.util
import re
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from check_pipeline import project
from check_pipeline.checks import (
    accessibility, architecture, commits, console_output, dead_code, disk_access, duplicates,
    english_only, guides, language, nesting, promises, samples, scripts, secrets, security,
    swift_tools, translations, unused_files, unused_python,
)
from check_pipeline.project import Codebase, SettingsProblem, run

# MARK: Settings


@dataclass(frozen=True)
class Step:
    name: str  # to start the step alone: check-pipeline tests
    title: str  # in the report
    check: Callable[[Codebase], list[str]]  # returns the findings
    needs_macos: bool = False  # skipped elsewhere, with a line that says so
    reads_code: bool = True  # runs on the samples too; tool steps such as the build do not


BUILT_IN = {step.name: step for step in [
    Step("build", "Build without warnings (swift build)", swift_tools.compiler_problems,
         reads_code=False),
    Step("tests", "Unit tests (swift test)", swift_tools.test_problems, reads_code=False),
    Step("coverage", "Test coverage at least the minimum", swift_tools.coverage_problems,
         reads_code=False),
    Step("plists", "Property lists and translation files (plutil)",
         swift_tools.property_list_problems, needs_macos=True, reads_code=False),
    Step("accessibility", "Every image decided for VoiceOver",
         accessibility.accessibility_problems),
    Step("nesting", "Flat methods (two blocks deep at most)", nesting.nesting_problems),
    Step("duplicates", "No code written twice", duplicates.duplicate_problems),
    Step("architecture", "Layers of the architecture", architecture.architecture_problems),
    Step("promises", "Promises the project makes its users", promises.promise_problems),
    Step("disk", "The disk only off the main thread", disk_access.disk_access_problems),
    Step("deadcode", "Dead code (compiler index)", dead_code.dead_code_problems),
    Step("deadscripts", "Dead code in the Python scripts", unused_python.unused_python_problems),
    Step("files", "No unused images or media", unused_files.unused_file_problems),
    Step("language", "American English names and comments", language.language_problems,
         needs_macos=True),
    Step("translations", "Every text translated", translations.translation_problems,
         needs_macos=True),
    Step("guides", "Guides: links whole, American spelling", guides.guide_problems),
    Step("english", "English everywhere but the translations",
         english_only.english_only_problems),
    Step("secrets", "No passwords or keys in the repository", secrets.secret_problems),
    Step("security", "No way in: shells, signing, workflows", security.security_problems),
    Step("scripts", "Scripts read whole, short lines", scripts.script_problems),
    Step("output", "Every output through console-look", console_output.console_output_problems),
    Step("commits", "Commit messages in the shared form", commits.commit_problems),
    # The built-in samples spell and build a Swift package, so they need a Mac.
    Step("samples", "Every planted mistake found", lambda codebase: sample_problems(codebase),
         needs_macos=True, reads_code=False),
]}
# Without a steps list, the steps that need nothing but the files themselves.
DEFAULT_STEPS = ["secrets", "security", "duplicates", "nesting", "guides", "files",
                 "deadscripts", "scripts", "commits"]
# Reports that run only when asked for by name, like `check-pipeline coverage-report`.
EXTRA_STEPS = {"coverage-report": Step("coverage-report", "Test coverage per folder",
                                       swift_tools.coverage_report, reads_code=False)}
# A line of a tool's output that names a place: "Sources/File.swift:12: …" or "a.py:3:5: E501 …".
PLACED_LINE = re.compile(r"^[^\s:]+:\d+(?::\d+)?:\s")


# MARK: Steps of a codebase


def steps_of(codebase: Codebase) -> dict[str, Step]:
    """Every step this codebase knows: the built-in ones, then its commands and its own checks,
    which replace a built-in step of the same name."""
    known = dict(BUILT_IN)
    for kind, make in (("commands", command_step), ("custom", custom_step)):
        known |= {name: make(codebase, name, entry) for name, entry in tables(codebase, kind)}
    return known


def tables(codebase: Codebase, kind: str) -> list[tuple[str, dict]]:
    """The [commands.<name>] or [custom.<name>] tables; any other shape is named."""
    entries = codebase.settings.get(kind, {}).items()
    for name, entry in entries:
        if not isinstance(entry, dict):
            raise SettingsProblem(f"[{kind}.{name}] is a table, such as title = \"…\"")
    return list(entries)


def command_step(_: Codebase, name: str, entry: dict) -> Step:
    """A tool the project runs, such as SwiftLint or ruff: its lines that name a place are its
    findings; when it fails without one, its last line tells why."""
    command = entry.get("command")
    if not isinstance(command, list) or not command:
        raise SettingsProblem(f"[commands.{name}] needs command = [\"tool\", \"argument\", …]")

    def problems(codebase: Codebase) -> list[str]:
        result = run(command, codebase.root)
        lines = result.output.splitlines()
        return result.findings(sorted({line for line in lines if PLACED_LINE.match(line)}))

    return Step(name, entry.get("title", " ".join(command)), problems, reads_code=False)


def custom_step(codebase: Codebase, name: str, entry: dict) -> Step:
    """A check of the project's own: a function in a Python file that takes the codebase and
    returns its findings, such as function = "scripts/house_rules.py:house_rule_problems"."""
    file_name, _, function_name = entry.get("function", "").partition(":")
    path = codebase.root / file_name
    if not file_name or not function_name or not path.is_file():
        raise SettingsProblem(f"[custom.{name}] needs function = \"file.py:function\", "
                              f"and the file to exist (looked for {file_name or 'nothing'})")
    module_name = f"check_pipeline_custom_{name.replace('-', '_')}"
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None:
        raise SettingsProblem(f"[custom.{name}]: {file_name} is no Python file")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module  # so dataclasses and pickling inside it find the module
    try:
        specification.loader.exec_module(module)
    except Exception as error:  # the project's own code: any error it raises while loading
        raise SettingsProblem(f"[custom.{name}]: {file_name} cannot be loaded: "
                              f"{type(error).__name__}: {error}") from error
    if not callable(check := getattr(module, function_name, None)):
        raise SettingsProblem(f"[custom.{name}]: {file_name} has no function {function_name}")
    return Step(name, entry.get("title", name), check)


def chosen_steps(codebase: Codebase, names: list[str]) -> list[Step]:
    """The steps or groups named on the command line, or the codebase's steps list without
    names; an unknown name is a SettingsProblem that lists the known ones."""
    known = steps_of(codebase) | EXTRA_STEPS
    groups = codebase.settings.get("groups", {})
    asked = names or codebase.settings.get("steps", DEFAULT_STEPS)
    step_names = [step for name in asked for step in groups.get(name, [name])]
    unknown = [name for name in step_names if name not in known]
    if unknown:
        raise SettingsProblem(f"unknown step {', '.join(unknown)}; steps: {', '.join(known)}"
                              + (f"; groups: {', '.join(groups)}" if groups else ""))
    return [known[name] for name in step_names]


def findings_of(step: Step, codebase: Codebase) -> list[str] | None:
    """The step's findings, or None when it cannot run on this system; a step that breaks down
    becomes one finding at the line where it stopped, so the steps after it still run."""
    if step.needs_macos and sys.platform != "darwin":
        return None
    try:
        return step.check(codebase)
    except Exception as error:
        # The last place inside the project or this package, as the error may come from the
        # standard library.
        frames = traceback.extract_tb(error.__traceback__)
        ours = [frame for frame in frames if is_ours(Path(frame.filename), codebase.root)]
        where = place_of(Path(ours[-1].filename), ours[-1].lineno) if ours else "general"
        return [f"{where}: the step stopped with {type(error).__name__}: {error}"]


def place_of(path: Path, line: int) -> str:
    """A place below the root as the report reads it; a file of this package by its name."""
    return project.place(path, line) if path.is_relative_to(project.ROOT) else f"{path.name}:{line}"


def is_ours(path: Path, root: Path) -> bool:
    return path.is_relative_to(root) or path.is_relative_to(Path(__file__).parent)


# MARK: Samples


def sample_problems(codebase: Codebase) -> list[str]:
    """Every check that reads code runs on the samples ([samples] folder, a codebase of its own
    with its own check-pipeline.toml) and must find exactly the mistakes planted there."""
    folder = codebase.section("samples").get("folder")
    if not folder:
        raise SettingsProblem("the samples step needs [samples] folder = \"…\"")
    sample_codebase = project.load(codebase.root / folder, is_main=False)
    steps = chosen_steps(sample_codebase, [])
    checks = [step.check for step in steps if step.reads_code]
    return samples.sample_findings(sample_codebase, checks)
