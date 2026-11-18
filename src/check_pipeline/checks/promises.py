"""Guards what a project promises its users, such as never going online, or removing files only
where it asks first.

Start:  run by the pipeline as a step, not started on its own
Needs:  Swift with its index (the compiler's index shows every interface the code calls)
Each [[promises]] entry names the interfaces that would break it (a readable name and the start
of the unique name the index gives them) and the only files, if any, that may call them. A call
anywhere else is reported, so the promise holds for code written later too.
"""

from dataclasses import dataclass

from index_store_reader import Role
from check_pipeline.project import Codebase, compiler_index, place, relative_path

# MARK: Settings


@dataclass(frozen=True)
class Promise:
    message: str
    # The interfaces that would break the promise, by a readable name and the start of the
    # unique name the compiler's index gives them. The unique name keeps apart what shares a
    # name: FileManager's removeItem deletes a file, a Set's remove only forgets a value.
    interfaces: dict[str, str]
    allowed_in: tuple[str, ...] = ()  # files, relative to the project, that may call them




# MARK: Step



def promise_problems(codebase: Codebase) -> list[str]:
    index = compiler_index(codebase)
    if index.build_problems:
        return list(index.build_problems)
    app_code = set(codebase.swift_sources)
    findings = []
    promises = [Promise(entry["message"], entry["interfaces"], tuple(entry.get("allowed_in", ())))
                for entry in codebase.settings.get("promises", [])]
    for found in index.occurrences:
        if found.roles & Role.REFERENCE and found.path in app_code:
            findings += [
                f"{place(found.path, found.line)}: {interface} {promise.message}"
                for promise in promises for interface in broken_by(promise, found)
            ]
    return sorted(set(findings))


def broken_by(promise: Promise, found) -> list[str]:
    """The readable names of the interfaces this use calls, unless its file may call them."""
    if relative_path(found.path) in promise.allowed_in:
        return []
    return [
        readable for readable, unique_start in promise.interfaces.items()
        if found.unique_name.startswith(unique_start)
    ]
