"""Keeps every command's output in one look: everything printed goes through the shared console.

Start:  run by the pipeline as a step, not started on its own
Needs:  nothing beyond Python
console-look draws headings, lines with marks, hints and frames the same way in every language:
console_look for Python and make (the console-look command), and ConsoleLook for Swift. Any
other echo, printf or print is reported. Output that another program reads, not a person, says
so in the head of its script (Output:) and stays plain. Of the Swift sources, only the files that
[console_output] may_print names are read (globs, such as Sources/Diagnostics/**).
"""

import re
from pathlib import Path

from check_pipeline.checks.scripts import HEAD_LINES
from check_pipeline.project import (
    Codebase, lines_of, matches, numbered_lines, place, relative_path,
)

# MARK: Settings

CONSOLE_NAME = "console"  # console.py and Console.swift draw the shared look
DATA_OUTPUT = "Output:"  # in a script's head: what it prints is data for another program
SHELL_OUTPUT = re.compile(r"""
    ^ (?! \s* \# )                      # not a comment
    .* (?: \b (?: echo | printf ) \b    # echo or printf ...
         | \b cat \b [^>]* << )          # ... or a text block handed to cat ...
    (?! .* > \s* [^&\s] )               # ... unless it goes into a file
""", re.VERBOSE)
PYTHON_OUTPUT = re.compile(r"""
    ^ (?! \s* \# )                      # not a comment
    .* (?: \b print \(                  # a call of print ...
         | \b sys \. std (?: out | err ) \. write \b )  # ... or a direct write
    (?! .* \b file \s* = )              # ... unless it goes into a file
""", re.VERBOSE)
SWIFT_OUTPUT = re.compile(r"""
    ^ (?! \s* // )                       # not a comment
    .* (?: \b (?: print | debugPrint | dump | fputs | NSLog ) \(   # a printing function
         | \b FileHandle \. standard (?: Output | Error ) \b )     # or the terminal itself
""", re.VERBOSE)
MESSAGE = (
    "prints past the shared console; use console-look (console_look, ConsoleLook), "
    "or name data for another program in the head (Output:)"
)


# MARK: Steps


def prints_data(path: Path) -> bool:
    return any(line.lstrip("#/ ").startswith(DATA_OUTPUT) for line in lines_of(path)[:HEAD_LINES])


def output_problems_in(paths: tuple[Path, ...], output: re.Pattern) -> list[str]:
    checked = [
        path for path in paths if path.stem.lower() != CONSOLE_NAME and not prints_data(path)
    ]
    return [
        f"{place(path, number)}: {MESSAGE}"
        for path, number, line in numbered_lines(checked) if output.search(line)
    ]


def swift_files_that_may_print(codebase: Codebase) -> tuple[Path, ...]:
    """The scripts, and the sources that [console_output] may_print names."""
    patterns = codebase.section("console_output").get("may_print", [])
    printing = [path for path in codebase.swift_sources
                if any(matches(relative_path(path), pattern) for pattern in patterns)]
    return (*codebase.swift_scripts, *printing)


# MARK: Step



def console_output_problems(codebase: Codebase) -> list[str]:
    return (
        output_problems_in(codebase.makefiles, SHELL_OUTPUT)
        + output_problems_in(codebase.python_scripts, PYTHON_OUTPUT)
        + output_problems_in(swift_files_that_may_print(codebase), SWIFT_OUTPUT)
    )
