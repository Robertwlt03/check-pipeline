"""What every check needs: the files, the settings, the compiler's index, a way to run a tool.

Start:  imported by the pipeline and the checks, not started on its own
Needs:  Python 3.13 or newer; Swift with its index reader for the checks that read the index
A Codebase is the files and settings one run of the checks reads. A project is one codebase; its
samples, which hold a mistake for every rule, are another, so the checks can test themselves
(see checks/samples.py). Both come from a check-pipeline.toml; every setting has a default.
"""

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path, PurePosixPath

from index_store_reader import IndexStore, Occurrence

# MARK: Settings

SETTINGS_FILE = "check-pipeline.toml"
# ponytail: one root per run, set by load(); a second project in the same run would need it in
# the Codebase, and place() taking the codebase.
ROOT = Path.cwd()
SHELL_LINE = re.compile(r"#!.*\b(?:sh|bash|zsh|dash|ksh)\b")  # the first line of a shell script
DEFAULT_LINE_LENGTH = 100

# Which files each list holds, as globs relative to the codebase's root, matched against the
# files git knows (and new files it does not ignore yet).
DEFAULT_FILES = {
    "swift_sources": ["Sources/**/*.swift"],
    "swift_tests": ["Tests/**/*.swift"],
    "swift_scripts": [],
    "python_scripts": ["**/*.py"],
    "makefiles": ["Makefile", "**/*.mk"],
    "guides": ["**/*.md"],
    "workflows": [".github/workflows/*.yml", ".github/workflows/*.yaml",
                  ".github/actions/*/action.yml"],
    "exclude": [],  # left out of every list, such as generated code or samples
}

# Building and testing share one configuration, so neither rebuilds what the other built.
BUILD_OPTIONS = (
    "--enable-index-store",  # the compiler's index, which several steps read
    "-Xswiftc", "-warnings-as-errors",  # a single warning already fails the build
    "--enable-code-coverage",  # the tests measure what they reach, for the coverage step
)

# A line a tool prints for a problem, such as "File.swift:12:5: warning: …".
TOOL_DIAGNOSTIC = re.compile(r": (?:warning|error):")

# Colors and links that tools write into their output for a terminal; they hide the words above.
TERMINAL_FORMATTING = re.compile(r"""
    \x1b \[ [0-9;]* m              # a color: ESC [ 1;31 m
    | \x1b \] 8 ;; [^\x1b]* \x1b \\  # a link: ESC ] 8 ;; address ESC \
""", re.VERBOSE)


class SettingsProblem(Exception):
    """The settings file cannot be used; the message says why."""


# Every section the settings file may have, so a misspelled one is named instead of ignored.
KNOWN_SETTINGS = {
    "name", "line_length", "steps", "groups", "files", "swift", "commands", "custom", "samples",
    "architecture", "promises", "disk_access", "console_output", "dead_code", "translations",
    "coverage", "scripts", "commits", "language",
}


# MARK: Codebases


@dataclass(frozen=True)
class Codebase:
    """The files one run of the checks reads, its settings, and how to build its Swift code."""

    root: Path
    name: str
    line_length: int
    swift_sources: tuple[Path, ...] = ()  # the project's code: every rule applies
    swift_tests: tuple[Path, ...] = ()
    swift_scripts: tuple[Path, ...] = ()
    python_scripts: tuple[Path, ...] = ()
    shell_scripts: tuple[Path, ...] = ()
    makefiles: tuple[Path, ...] = ()
    guides: tuple[Path, ...] = ()  # the Markdown files
    workflows: tuple[Path, ...] = ()  # the GitHub workflows and the actions they share
    text_files: tuple[Path, ...] = ()  # every file that could carry a secret
    source_root: Path | None = None  # its folders are the parts of the architecture
    translations: Path | None = None  # the folder with one <language>.lproj per language
    # The whole settings file, for the checks that read a section of their own; left out of the
    # comparison, so a codebase can be the key of a cache.
    settings: dict = field(default_factory=dict, compare=False, hash=False)

    def swift_files(self) -> tuple[Path, ...]:
        return self.swift_sources + self.swift_tests + self.swift_scripts

    def all_scripts(self) -> tuple[Path, ...]:
        return self.shell_scripts + self.python_scripts + self.swift_scripts + self.makefiles

    def section(self, name: str) -> dict:
        """One section of the settings file, such as [architecture]; empty when it is missing."""
        return self.settings.get(name, {})

    @property
    def package(self) -> Path:
        """The folder with Package.swift."""
        return self.root / self.section("swift").get("package", ".")

    @property
    def build_folder(self) -> Path:
        return self.root / ".build" / "check"

    @property
    def build_options(self) -> tuple[str, ...]:
        extra = tuple(self.section("swift").get("build_options", ()))
        return ("--scratch-path", str(self.build_folder), *BUILD_OPTIONS, *extra)


def load(root: Path | None = None, is_main: bool = True) -> Codebase:
    """The codebase in `root` (the current folder by default), with its check-pipeline.toml.
    The main codebase also sets the root that every finding's place is counted from."""
    global ROOT
    root = (root or Path.cwd()).resolve()
    if is_main:
        ROOT = root
    settings = read_settings(root / SETTINGS_FILE)
    unknown = sorted(set(settings) - KNOWN_SETTINGS) + sorted(
        f"files.{key}" for key in set(settings.get("files", {})) - set(DEFAULT_FILES))
    if unknown:
        raise SettingsProblem(f"{SETTINGS_FILE}: unknown setting {', '.join(unknown)}")
    globs = DEFAULT_FILES | settings.get("files", {})
    known = known_files(root, globs["exclude"])
    lists = {name: matching(root, known, globs[name]) for name in DEFAULT_FILES
             if name != "exclude"}
    swift = settings.get("swift", {})
    source_root = root / swift.get("source_root", "Sources")
    translations = root / swift.get("translations", "Resources")
    return Codebase(
        root=root,
        name=settings.get("name", root.name),
        line_length=settings.get("line_length", swift_format_line_length(root)),
        shell_scripts=tuple(filter(is_shell_script, known)),
        text_files=known,
        source_root=source_root if source_root.is_dir() else None,
        translations=translations if translations.is_dir() else None,
        settings=settings,
        **lists,
    )


def read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise SettingsProblem(f"{path.name} cannot be read: {error}") from error


def swift_format_line_length(root: Path) -> int:
    """The line length swift format uses, when the project has a .swift-format; else 100."""
    swift_format = root / ".swift-format"
    if not swift_format.exists():
        return DEFAULT_LINE_LENGTH
    return json.loads(swift_format.read_text()).get("lineLength", DEFAULT_LINE_LENGTH)


def known_files(root: Path, exclude: list[str]) -> tuple[Path, ...]:
    """The files git knows below the root, and new ones it does not ignore; never a build folder
    or a local note. Outside a git repository, every file below the root."""
    listed = run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], root)
    names = listed.output.splitlines() if listed.succeeded else [
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()]
    kept = (name for name in names if not any(matches(name, pattern) for pattern in exclude))
    return tuple(sorted(path for name in kept if (path := root / name).is_file()))


def matching(root: Path, files: tuple[Path, ...], patterns: list[str]) -> tuple[Path, ...]:
    return tuple(
        path for path in files
        if any(matches(path.relative_to(root).as_posix(), pattern) for pattern in patterns)
    )


def matches(name: str, pattern: str) -> bool:
    """A glob with ** for any number of folders, as git reads it; **/x also matches x itself."""
    path = PurePosixPath(name)
    return path.full_match(pattern) or (
        pattern.startswith("**/") and path.full_match(pattern.removeprefix("**/")))


# MARK: Reading files


def is_text(path: Path) -> bool:
    """A file that reads as text; images, icons and other binary files do not. The lines stay
    cached, so the checks that read the file next do not read it again."""
    try:
        lines_of(path)
    except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
        return False
    return True


def is_shell_script(path: Path) -> bool:
    """A .sh file, or a text file whose first line starts a shell, such as #!/usr/bin/env bash."""
    if path.suffix == ".sh":
        return True
    first_line = lines_of(path)[:1] if is_text(path) else []
    return any(SHELL_LINE.match(line) for line in first_line)


@cache
def lines_of(path: Path) -> list[str]:
    return path.read_text().splitlines()


def numbered_lines(paths):
    """Each line of the files with its file and its number, counted from 1."""
    for path in paths:
        for number, line in enumerate(lines_of(path), start=1):
            yield path, number, line


def relative_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def place(path: Path, line_number: int) -> str:
    """Where a finding is, in the form editors open with a click: Sources/File.swift:12."""
    return f"{relative_path(path)}:{line_number}"


# MARK: Running tools


@dataclass(frozen=True)
class ToolResult:
    succeeded: bool
    output: str

    def diagnostics(self) -> list[str]:
        """The warnings and errors the tool printed, each once."""
        return sorted({line for line in self.output.splitlines() if TOOL_DIAGNOSTIC.search(line)})

    def findings(self, readable_findings: list[str]) -> list[str]:
        """The findings; when the tool failed without one, its last line tells why."""
        if not self.succeeded and not readable_findings:
            return [self.last_line() or "the tool failed without saying why"]
        return readable_findings

    def last_line(self) -> str:
        return self.output.strip().rpartition("\n")[2]


def run(command: list[str], folder: Path | None = None, given_input: str | None = None
        ) -> ToolResult:
    """A tool's result; a tool that is not installed fails with a line that names it."""
    try:
        result = subprocess.run(command, cwd=folder or ROOT, input=given_input,
                                capture_output=True, text=True)
    except FileNotFoundError:
        return ToolResult(False, f"{command[0]} is not installed")
    output = TERMINAL_FORMATTING.sub("", result.stdout + result.stderr)
    return ToolResult(result.returncode == 0, output)


# MARK: The compiler's index


@dataclass(frozen=True)
class CompilerIndex:
    """Every declaration and use in a codebase's files, or why its build failed."""

    occurrences: tuple[Occurrence, ...]
    build_problems: tuple[str, ...]


def swift_index(codebase: Codebase) -> CompilerIndex:
    """The compiler's index for a codebase with a Swift package; empty for one without, such as a
    project of Python scripts, so the checks that also read the index still read the rest."""
    if not (codebase.package / "Package.swift").exists():
        return CompilerIndex((), ())
    return compiler_index(codebase)


@cache
def compiler_index(codebase: Codebase) -> CompilerIndex:
    """Builds the codebase (nothing happens when it is current) and reads the index once."""
    # With the tests, so their names are read too and the build step finds this build current.
    command = ["swift", "build", "--build-tests", "--package-path", str(codebase.package),
               *codebase.build_options]
    result = run(command, codebase.root)
    if not result.succeeded:
        return CompilerIndex((), tuple(result.findings(result.diagnostics())))
    store = next(codebase.build_folder.glob("**/index/store"), None)
    if store is None:
        return CompilerIndex((), ("the build wrote no index; does the package hold Swift code?",))
    return CompilerIndex(tuple(IndexStore(store).occurrences(inside=codebase.package)), ())
