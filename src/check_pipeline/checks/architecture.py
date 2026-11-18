"""Checks that every part of the code uses only the parts its layer may use.

Start:  run by the pipeline as a step, not started on its own
Needs:  Swift with its index (the compiler's index tells who uses whose types and functions)
A part is a folder below the source root, such as Services or Features. [architecture] may_use
names each part and the parts it may use besides itself; own_parts gives single files a part of
their own, such as design tokens every layer may name. A folder that is not in the table is
reported, so a new part needs a place in the architecture before it can be used.
"""

from pathlib import Path

from index_store_reader import Occurrence, Role
from check_pipeline.project import Codebase, compiler_index, place

# MARK: Settings

SETTINGS = "architecture"  # the section of check-pipeline.toml: may_use and own_parts


# MARK: Parts


def part_of(path: Path, codebase: Codebase) -> str | None:
    """The part a file belongs to; files right in the source folder belong to none."""
    if codebase.source_root is None or not path.is_relative_to(codebase.source_root):
        return None
    below = path.relative_to(codebase.source_root)
    own_parts = codebase.section(SETTINGS).get("own_parts", {})
    if own_part := own_parts.get(below.as_posix()):
        return own_part
    return below.parts[0] if len(below.parts) > 1 else None


# MARK: Step



def architecture_problems(codebase: Codebase) -> list[str]:
    index = compiler_index(codebase)
    if index.build_problems:
        return list(index.build_problems)
    homes = {
        found.unique_name: part_of(found.path, codebase)
        for found in index.occurrences if found.roles & Role.DEFINITION
    }
    findings = {}  # one finding per file and used part
    for found in index.occurrences:
        problem = crossing_problem(found, homes, codebase)
        if problem:
            key = (found.path, homes.get(found.unique_name))
            findings.setdefault(key, f"{place(found.path, found.line)}: {problem}")
    return list(findings.values())


def crossing_problem(found: Occurrence, homes: dict[str, str | None], codebase: Codebase):
    """What is wrong when this use crosses into a part its own part may not use."""
    user = part_of(found.path, codebase)
    used = homes.get(found.unique_name)
    if not (found.roles & Role.REFERENCE) or user is None or used is None or user == used:
        return None
    may_use = codebase.section(SETTINGS).get("may_use", {})
    if user not in may_use:
        return (f"the folder {user} has no place in the architecture yet; add it to [{SETTINGS}] "
                "may_use")
    if used in may_use[user]:
        return None
    allowed = ", ".join(sorted(may_use[user])) or "no other part"
    return f"{user} may not use {used} (it uses {found.name}); {user} may use {allowed}"
