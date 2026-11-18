"""Checks the commit messages: a subject in the shared form, lines of the usual length, a blank
line before the body, and English in American spelling.

Start:  run by the pipeline as a step, not started on its own
Needs:  git; macOS for the spelling (its spell checker, see unknown_words.swift)
A subject reads like `fix(scan): canceled scans stop at once`: a kind from Conventional Commits
(conventionalcommits.org), maybe a part in brackets, then what changed. On GitHub the commits of
a pull request are checked, elsewhere the commits not yet on the remote's main; [commits] since
names the first commit the rule holds for, so earlier history stays as it is. Every word must be
American English, a known technical term or a word the project's own code uses (`nonisolated`,
`fts`), so a message in German is reported as well. With [commits] samples, the messages come
from that file instead, kept apart by lines of three dashes (see checks/samples.py).
"""

import os
import re
from dataclasses import dataclass

from check_pipeline.checks.language import (
    BRITISH_VARIANTS, CODE_NAME, NOT_PROSE, is_known_term, known_terms, spell_checker_exists,
    unknown_words, words_of,
)
from check_pipeline.project import Codebase, lines_of, place, run, swift_index

# MARK: Settings

KINDS = "feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert"  # Conventional Commits
SUBJECT = re.compile(rf"""
    ^ (?: {KINDS} )             # the kind of change
    (?: \( [a-z0-9-]+ \) )?     # maybe the part it touches: (scan)
    !? : \s \S                  # maybe ! for a breaking change, then the summary
""", re.VERBOSE)
LINK = re.compile(r"\w+://\S+")
UNIT_SEPARATOR, RECORD_SEPARATOR = "\x1f", "\x1e"  # keep commits apart in git's output
MESSAGE_SEPARATOR = "---"  # between the messages of a samples file
# A word of any language, umlauts included, so German words are read too; digits do not count.
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


# MARK: Messages


@dataclass(frozen=True)
class CommitMessage:
    place: str  # "commit 1a2b3c4", or a file and line for the samples
    text: str


def commits_to_check(codebase: Codebase) -> list[CommitMessage]:
    """The commits the remote's main does not hold yet, from [commits] since on if it is set."""
    settings = codebase.section("commits")
    if "samples" in settings:
        return sample_messages(codebase)
    since = settings.get("since")
    excluded = ([f"^{since}^"] if since else []) + [f"^{base}" for base in comparison_bases()]
    message_format = f"--format=%h{UNIT_SEPARATOR}%B{RECORD_SEPARATOR}"
    # Merge commits are written by git and GitHub, such as the one a pull request is checked on.
    output = run(["git", "log", "--no-merges", message_format, "HEAD", *excluded], codebase.root)
    records = [record.strip("\n") for record in output.output.split(RECORD_SEPARATOR)]
    pairs = [record.split(UNIT_SEPARATOR, 1) for record in records if UNIT_SEPARATOR in record]
    return [CommitMessage(f"commit {short_id}", text.strip()) for short_id, text in pairs]


def comparison_bases() -> list[str]:
    """What the commits are compared with: a pull request's base, or the remote's main."""
    base_branch = os.environ.get("GITHUB_BASE_REF") or "main"
    remote_branch = f"origin/{base_branch}"
    exists = run(["git", "rev-parse", "--verify", "--quiet", remote_branch]).succeeded
    return [remote_branch] if exists else []


def sample_messages(codebase: Codebase) -> list[CommitMessage]:
    """The messages of the samples file; lines starting with # are notes, as git leaves them out
    of a message too."""
    samples = codebase.root / codebase.section("commits")["samples"]
    messages, kept, first_line = [], [], 0
    for number, line in enumerate(lines_of(samples) + [MESSAGE_SEPARATOR], start=1):
        if line == MESSAGE_SEPARATOR:
            messages.append(CommitMessage(place(samples, first_line), "\n".join(kept)))
            kept = []
        elif not line.startswith("#"):
            first_line = first_line if kept else number
            kept.append(line)
    return messages


# MARK: Judging


def message_problems(message: CommitMessage, line_length: int) -> list[str]:
    lines = message.text.splitlines()
    subject = lines[0] if lines else ""
    problems = []
    if not SUBJECT.match(subject):
        problems.append(f"'{subject}' is not a commit subject like 'fix(scan): what changed'")
    if len(lines) > 1 and lines[1].strip():
        problems.append("a blank line belongs between the subject and the body")
    problems += [
        f"line {number} is longer than {line_length} characters"
        for number, line in enumerate(lines, start=1)
        if len(line) > line_length and not LINK.search(line)
    ]
    return [f"{message.place}: {problem}" for problem in problems]


def language_problems(messages: list[CommitMessage], terms: set[str]) -> list[str]:
    """British spellings, and words that are no English at all, such as a message in German."""
    words = {(message.place, word) for message in messages for word in message_words(message)}
    to_check = {word.lower() for _, word in words if not is_known_term(word.lower(), terms)}
    verdicts = unknown_words(to_check, set())
    return sorted(filter(None, (word_problem(where, word, verdicts) for where, word in words)))


def word_problem(where: str, word: str, verdicts: dict) -> str | None:
    kind, guess = verdicts.get(word.lower(), ("", ""))
    american = BRITISH_VARIANTS.get(word.lower()) or (guess if kind == "british" else None)
    if american:
        return f"{where}: '{word}' is British; American English writes '{american}'"
    if kind == "unknown":
        return f"{where}: '{word}' is not an English word; commit messages are written in English"
    return None


def message_words(message: CommitMessage) -> set[str]:
    """The prose words of a message; code in backticks, links, paths and names are left out."""
    prose = NOT_PROSE.sub(" ", LINK.sub(" ", message.text))
    return {word for word in WORD.findall(prose) if not CODE_NAME.search(word)}


def project_terms(codebase: Codebase) -> set[str]:
    """The known technical terms, and every word the project's own code holds, whole and in its
    parts: `nonisolated`, `fts`, `fileCount` as file and count."""
    code = codebase.swift_files() + codebase.python_scripts
    words = {word for path in code for line in lines_of(path) for word in WORD.findall(line)}
    parts = {part for word in words for part in words_of(word)}
    return {word.lower() for word in words} | parts | known_terms(codebase, swift_index(codebase))


# MARK: Step


def commit_problems(codebase: Codebase) -> list[str]:
    messages = commits_to_check(codebase)
    findings = [
        problem for message in messages
        for problem in message_problems(message, codebase.line_length)
    ]
    if not spell_checker_exists():
        return findings
    return findings + language_problems(messages, project_terms(codebase))
