"""Checks that the code reads and writes the disk only where it is free of the main thread.

Start:  run by the pipeline as a step, not started on its own
Needs:  Swift with its index (the compiler's index shows every interface the code calls)
For projects where every type runs on the main thread unless it is marked `nonisolated` (Swift's
default isolation), and the main thread draws the window: a slow disk there makes the app stutter.
So every call that reaches the disk stands inside a declaration marked `nonisolated`, a function
marked `@concurrent` or a task started with `Task.detached`. [disk_access] left_out names folders
to skip, such as diagnostics that test the app themselves; interfaces adds to the list below.
"""

import re

from index_store_reader import Occurrence, Role
from check_pipeline.checks.nesting import braces_of, swift_code
from check_pipeline.project import Codebase, compiler_index, place, relative_path

# MARK: Settings

# What reaches the disk, by a readable name and the start of the index's unique name.
DISK_INTERFACES = {
    "FileManager": "c:objc(cs)NSFileManager(im)",
    "fts": "c:@F@fts_",
    "stat": "c:@F@stat",
    "lstat": "c:@F@lstat",
    "getattrlist": "c:@F@getattrlist",
    "opendir": "c:@F@opendir",
    "readdir": "c:@F@readdir",
    "Data(contentsOf:)": "s:10Foundation4DataV10contentsOf",
    "String(contentsOf:)": "s:SS10FoundationE10contentsOf",
    "URL.resourceValues": "s:10Foundation3URLV14resourceValues",
    "Bundle(path:)": "c:objc(cs)NSBundle(im)initWithPath",
    "NSDictionary(contentsOfFile:)": "c:objc(cs)NSDictionary(im)initWithContentsOf",
    "NSWorkspace.icon(forFile:)": "c:objc(cs)NSWorkspace(im)iconForFile",
    "Quick Look thumbnails": "c:objc(cs)QLThumbnailGenerator",
}
# The text before a brace that opens code free of the main thread.
OFF_THE_MAIN_THREAD = re.compile(r"""
    \b nonisolated \b (?! \s* \( \s* unsafe )     # nonisolated, but not nonisolated(unsafe)
    | \b Task\.detached \b                         # a task of its own
    | @ concurrent \b                              # a function that leaves the caller's actor
""", re.VERBOSE)
# The words that open a declaration. The text before a brace can start with earlier members of a
# type, so only the line of the last such word on belongs to the brace's own declaration.
DECLARATION = re.compile(r"""
    \b (?: func | init | deinit | subscript | var | let       # a function or a property
         | struct | class | enum | extension | actor | protocol ) \b   # or a type
""", re.VERBOSE)
# A line that holds nothing but attributes, such as `@concurrent` or `@available(macOS 27, *)`.
ATTRIBUTE_LINE = re.compile(r"""
    [ \t]* (?: (?: @ \w+ (?: \( [^()\n]* \) )? | nonisolated ) [ \t]* )+
""", re.VERBOSE)
SETTINGS = "disk_access"


# MARK: Step



def disk_access_problems(codebase: Codebase) -> list[str]:
    index = compiler_index(codebase)
    if index.build_problems:
        return list(index.build_problems)
    settings = codebase.section(SETTINGS)
    left_out = tuple(settings.get("left_out", ()))
    interfaces = DISK_INTERFACES | settings.get("interfaces", {})
    app_code = {
        path for path in codebase.swift_sources if not relative_path(path).startswith(left_out)
    }
    findings = set()
    for found in index.occurrences:
        interface = disk_interface(found, interfaces)
        if interface and found.path in app_code and not runs_off_the_main_thread(found):
            findings.add(
                f"{place(found.path, found.line)}: {interface} reaches the disk on the main "
                "thread; move it into a nonisolated service, an @concurrent function or a "
                "Task.detached"
            )
    return sorted(findings)


def disk_interface(found: Occurrence, interfaces: dict[str, str]) -> str | None:
    if not found.roles & Role.REFERENCE:
        return None
    matching = (
        name for name, start in interfaces.items() if found.unique_name.startswith(start)
    )
    return next(matching, None)


def runs_off_the_main_thread(found: Occurrence) -> bool:
    return any(OFF_THE_MAIN_THREAD.search(text) for text in enclosing_texts(found))


def enclosing_texts(found: Occurrence) -> list[str]:
    """The text before each brace that is still open where the call stands."""
    open_texts = []
    for line, column, text_before, character in braces_of(swift_code(found.path)):
        if (line, column) > (found.line, found.column):
            break
        if character == "{":
            open_texts.append(own_declaration(text_before))
        elif open_texts:
            open_texts.pop()
    return open_texts


def own_declaration(text_before: str) -> str:
    """The text that belongs to a brace: from the line of its declaration on, so the
    `nonisolated` of a property above does not count for the method below it."""
    declarations = list(DECLARATION.finditer(text_before))
    if not declarations:  # a closure, such as .task {: only its own line belongs to it
        return text_before.rpartition("\n")[2]
    start = line_start(text_before, declarations[-1].start())
    while start:  # attributes on lines of their own above, such as @concurrent, belong to it
        above = line_start(text_before, start - 1)
        if not ATTRIBUTE_LINE.fullmatch(text_before, above, start - 1):
            break
        start = above
    return text_before[start:]


def line_start(text: str, position: int) -> int:
    return text.rfind("\n", 0, position) + 1
