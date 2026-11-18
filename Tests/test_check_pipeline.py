"""Tests the core of check-pipeline: settings, steps, commands, custom checks and the command line.

Start:  python3 -m unittest discover -s Tests (with check-pipeline installed: pip install -e .)
Needs:  Python 3.13 or newer; the built-in checks are tested by the samples step instead
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from check_pipeline import pipeline, project
from check_pipeline.__main__ import main
from check_pipeline.project import SettingsProblem, load, matches

CUSTOM_CHECK = '''
def todo_problems(codebase):
    return [f"notes.txt:1: a TODO" for path in codebase.text_files if path.name == "notes.txt"]
'''


class ProjectFolder(unittest.TestCase):
    """Every test runs in an empty project folder of its own, as its current folder."""

    def setUp(self) -> None:
        self.here = Path.cwd()
        self.root = Path(tempfile.mkdtemp()).resolve()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self.here)
        shutil.rmtree(self.root)

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run_quietly(self, *arguments: str) -> int:
        with redirect_stdout(io.StringIO()):
            return main(list(arguments))


class SettingsTests(ProjectFolder):
    def test_files_follow_the_globs(self) -> None:
        self.write("Sources/App/Main.swift", "")
        self.write("scripts/tool.py", "")
        self.write("README.md", "")
        codebase = load()
        self.assertEqual([path.name for path in codebase.swift_sources], ["Main.swift"])
        self.assertEqual([path.name for path in codebase.python_scripts], ["tool.py"])
        self.assertEqual([path.name for path in codebase.guides], ["README.md"])
        self.assertEqual(codebase.name, self.root.name)

    def test_excluded_files_are_left_out(self) -> None:
        self.write("check-pipeline.toml", '[files]\nexclude = ["generated/**"]\n')
        self.write("generated/model.py", "")
        self.assertEqual(load().python_scripts, ())

    def test_broken_settings_are_named(self) -> None:
        self.write("check-pipeline.toml", "steps = [\n")
        with self.assertRaises(SettingsProblem):
            load()

    def test_misspelled_settings_are_named(self) -> None:
        for text in ("[archtecture]\n", "[files]\npython = []\n"):
            self.write("check-pipeline.toml", text)
            with self.subTest(text), self.assertRaises(SettingsProblem):
                load()

    def test_globs_match_like_git(self) -> None:
        self.assertTrue(matches("README.md", "**/*.md"))
        self.assertTrue(matches("docs/a/b.md", "**/*.md"))
        self.assertFalse(matches("docs/b.txt", "**/*.md"))


class StepTests(ProjectFolder):
    def test_a_custom_check_runs_and_replaces_nothing_else(self) -> None:
        self.write("checks.py", CUSTOM_CHECK)
        self.write("notes.txt", "TODO")
        self.write("check-pipeline.toml", 'steps = ["todo"]\n[custom.todo]\ntitle = "No TODO"\n'
                                          'function = "checks.py:todo_problems"\n')
        codebase = load()
        [step] = pipeline.chosen_steps(codebase, [])
        self.assertEqual(step.title, "No TODO")
        self.assertEqual(pipeline.findings_of(step, codebase), ["notes.txt:1: a TODO"])

    def test_a_missing_custom_function_is_named(self) -> None:
        self.write("checks.py", CUSTOM_CHECK)
        self.write("check-pipeline.toml", '[custom.todo]\nfunction = "checks.py:absent"\n')
        with self.assertRaises(SettingsProblem):
            pipeline.steps_of(load())

    def test_a_broken_custom_file_is_named(self) -> None:
        self.write("checks.py", "def broken(:\n")
        self.write("check-pipeline.toml", '[custom.todo]\nfunction = "checks.py:broken"\n')
        with self.assertRaises(SettingsProblem):
            pipeline.steps_of(load())

    def test_a_command_reports_its_placed_lines(self) -> None:
        tool = f'import sys; print("a.py:3:5: E501 line too long"); print("noise"); sys.exit(1)'
        self.write("check-pipeline.toml", f'[commands.lint]\ncommand = ["{sys.executable}", "-c", '
                                          f"'{tool}']\n")
        codebase = load()
        step = pipeline.steps_of(codebase)["lint"]
        self.assertEqual(pipeline.findings_of(step, codebase), ["a.py:3:5: E501 line too long"])

    def test_a_missing_tool_is_one_finding(self) -> None:
        self.write("check-pipeline.toml", '[commands.lint]\ncommand = ["no-such-tool-here"]\n')
        codebase = load()
        step = pipeline.steps_of(codebase)["lint"]
        self.assertEqual(pipeline.findings_of(step, codebase),
                         ["no-such-tool-here is not installed"])

    def test_a_breaking_step_becomes_a_finding(self) -> None:
        def broken(_):
            raise ValueError("bad input")
        step = pipeline.Step("broken", "Broken", broken)
        [finding] = pipeline.findings_of(step, load())
        self.assertIn("ValueError: bad input", finding)

    def test_macos_steps_are_skipped_elsewhere(self) -> None:
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIsNone(pipeline.findings_of(pipeline.BUILT_IN["language"], load()))

    def test_groups_expand_to_their_steps(self) -> None:
        self.write("check-pipeline.toml", '[groups]\nsafety = ["secrets", "security"]\n')
        names = [step.name for step in pipeline.chosen_steps(load(), ["safety"])]
        self.assertEqual(names, ["secrets", "security"])


class CommandLineTests(ProjectFolder):
    def test_a_clean_project_passes(self) -> None:
        self.write("check-pipeline.toml", 'steps = ["secrets", "duplicates"]\n')
        self.assertEqual(self.run_quietly(), 0)

    def test_a_finding_fails(self) -> None:
        # Put together here, so this file itself holds no line that looks like a secret.
        self.write("settings.txt", "pass" + "word = 'a-real-looking-one'\n")
        self.assertEqual(self.run_quietly("secrets"), 1)

    def test_an_unknown_step_is_named(self) -> None:
        self.assertEqual(self.run_quietly("no-such-step"), 2)

    def test_places_count_from_the_root(self) -> None:
        load()
        self.assertEqual(project.place(self.root / "a" / "b.py", 3), "a/b.py:3")


if __name__ == "__main__":
    unittest.main()
