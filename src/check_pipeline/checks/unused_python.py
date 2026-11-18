"""Finds what the Python scripts define or import but never use, as dead_code.py does for Swift.

Start:  run by the pipeline as a step, not started on its own
Needs:  nothing beyond Python (its own parser, ast, reads the scripts)
A function, class or setting at the top of a module counts as used when its own module reads it,
another module imports it by name, or any module reaches it as module.name. An import counts as
used when its module reads the name. Names Python itself calls, such as __name__, are left out.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

from check_pipeline.project import Codebase, place

# MARK: Settings

CALLED_BY_PYTHON = "__"  # names such as __init__ start and end like this
TEST_CASE = "TestCase"  # unittest runs every class built on it, so nothing has to name them


@dataclass(frozen=True)
class Module:
    path: Path
    tree: ast.Module

    def definitions(self) -> list[tuple[str, int]]:
        """Each name the module defines at its top, with its line."""
        found = []
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                found.append((node.name, node.lineno))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                found += [(name, node.lineno) for name in assigned_names(node)]
        tests = self.test_classes()
        return [(name, line) for name, line in found
                if not name.startswith(CALLED_BY_PYTHON) and name not in tests]

    def test_classes(self) -> set[str]:
        """The classes built on unittest's TestCase, also through a class of the module itself."""
        classes = [node for node in self.tree.body if isinstance(node, ast.ClassDef)]
        tests: set[str] = set()
        while True:
            found = {node.name for node in classes
                     if any(base_name(base) in tests | {TEST_CASE} for base in node.bases)}
            if found <= tests:
                return tests
            tests |= found

    def imports(self) -> list[tuple[str, int]]:
        return [
            ((alias.asname or alias.name).split(".")[0], node.lineno)
            for node in ast.walk(self.tree) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]

    def imported_names(self) -> set[str]:
        return {
            alias.name for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }

    def read_names(self) -> set[str]:
        return {
            node.id for node in ast.walk(self.tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }

    def reached_names(self) -> set[str]:
        """The names after a dot, such as header in report.header."""
        return {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)}


def base_name(base: ast.expr) -> str:
    """The name of a base class: TestCase in unittest.TestCase."""
    return base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")


def assigned_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = []
    for target in targets:
        parts = target.elts if isinstance(target, ast.Tuple) else [target]
        names += [part.id for part in parts if isinstance(part, ast.Name)]
    return names


# MARK: Steps


def unused_definitions(modules: list[Module]) -> list[str]:
    used_elsewhere = set().union(
        *(module.imported_names() | module.reached_names() for module in modules)
    )
    return [
        f"{place(module.path, line)}: '{name}' is declared but never used"
        for module in modules for name, line in module.definitions()
        if name not in module.read_names() and name not in used_elsewhere
    ]


def unused_imports(modules: list[Module]) -> list[str]:
    return [
        f"{place(module.path, line)}: '{name}' is imported but never used"
        for module in modules for name, line in module.imports()
        if name not in module.read_names() and name not in module.reached_names()
    ]


# MARK: Step


def unused_python_problems(codebase: Codebase) -> list[str]:
    modules = [Module(path, ast.parse(path.read_text())) for path in codebase.python_scripts]
    return unused_definitions(modules) + unused_imports(modules)
