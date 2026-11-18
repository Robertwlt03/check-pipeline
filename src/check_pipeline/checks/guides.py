"""Checks the guides: every link leads to a file that exists, and the texts use American spelling.

Start:  run by the pipeline as a step, not started on its own
Needs:  macOS for the spelling (its spell checker, see unknown_words.swift); links everywhere
The guides are English only, like the rest of the repository; english_only.py reports German in
them and in every other file.
"""

import re
from pathlib import Path

from check_pipeline.checks.language import (
    BRITISH_VARIANTS, NOT_PROSE, PLAIN_WORD, spell_checker_exists, unknown_words,
)
from check_pipeline.project import Codebase, numbered_lines, place

# MARK: Settings

# A link inside the project: Markdown's (target) or HTML's src= and href=.
LINK = re.compile(r"""
    \] \( (?P<markdown> [^)\s]+ ) \)            # [text](target)
    | (?: src | href ) = " (?P<html> [^"]+ ) "  # <img src="target"> or <a href="target">
""", re.VERBOSE)
# Targets that are no file of the project: web addresses, mail, a place on the same page, and
# GitHub's own pages such as ../../issues, which lie outside the repository.
OUTSIDE = re.compile(r"^(?:[a-z]+:|#|\.\./\.\./)")
HTML_TAG = re.compile(r"<[^>]+>")
CODE_SPAN = re.compile(r"`[^`]*`")


# MARK: Links and spelling


def link_problems(guides: tuple[Path, ...], root: Path) -> list[str]:
    problems = []
    for path, number, line in numbered_lines(guides):
        links = LINK.finditer(CODE_SPAN.sub("", line))  # a link in `code` is an example
        targets = [match["markdown"] or match["html"] for match in links]
        problems += [
            f"{place(path, number)}: the link to {target} leads nowhere"
            for target in targets if is_broken(path, target, root)
        ]
    return problems


def is_broken(guide: Path, target: str, root: Path) -> bool:
    if OUTSIDE.match(target):
        return False
    file = (guide.parent / target.split("#", 1)[0]).resolve()
    return not file.exists() or not file.is_relative_to(root)


def spelling_problems(guides: tuple[Path, ...]) -> list[str]:
    words = [
        (path, number, word)
        for path, number, line in numbered_lines(guides)
        for word in PLAIN_WORD.findall(NOT_PROSE.sub(" ", HTML_TAG.sub(" ", line)))
    ]
    verdicts = unknown_words({word.lower() for _, _, word in words}, set())
    return [
        f"{place(path, number)}: '{word}' is British; American English writes '{american}'"
        for path, number, word in words
        if (american := american_spelling(word.lower(), verdicts))
    ]


def american_spelling(word: str, verdicts: dict) -> str | None:
    if word in BRITISH_VARIANTS:
        return BRITISH_VARIANTS[word]
    kind, guess = verdicts.get(word, ("", ""))
    return guess if kind == "british" else None


# MARK: Step



def guide_problems(codebase: Codebase) -> list[str]:
    links = link_problems(codebase.guides, codebase.root)
    return links + (spelling_problems(codebase.guides) if spell_checker_exists() else [])
