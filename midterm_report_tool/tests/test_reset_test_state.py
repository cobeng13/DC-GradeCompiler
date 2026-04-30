import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reset_test_state import apply_reset_plan, build_reset_plan


class ResetTestStateTests(unittest.TestCase):
    @contextmanager
    def workspace_tempdir(self):
        temp_root = Path(__file__).resolve().parents[1] / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        temp_dir = temp_root / f"reset_{uuid.uuid4().hex}"
        temp_dir.mkdir()
        try:
            yield temp_dir
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def make_fake_tool_state(self, base: Path) -> None:
        (base / "data").mkdir()
        (base / "data" / "grade_compiler.sqlite3").write_text("db")
        (base / "output").mkdir()
        (base / "output" / ".gitkeep").write_text("")
        (base / "output" / "passed_midterm_report.xlsx").write_text("report")
        (base / "output" / "nested").mkdir()
        (base / "output" / "nested" / "artifact.txt").write_text("artifact")
        (base / ".test_tmp").mkdir()
        (base / ".test_tmp" / "scratch.txt").write_text("scratch")
        (base / "__pycache__").mkdir()
        (base / "__pycache__" / "module.pyc").write_text("cache")
        (base / "input" / "grades").mkdir(parents=True)
        (base / "input" / "grades" / ".gitkeep").write_text("")
        (base / "input" / "grades" / "faculty.xlsx").write_text("input")
        (base / "input" / "masterlist").mkdir(parents=True)
        (base / "input" / "masterlist" / ".gitkeep").write_text("")
        (base / "input" / "masterlist" / "masterlist.csv").write_text("input")

    def test_default_reset_preserves_inputs_and_gitkeep(self):
        with self.workspace_tempdir() as base:
            self.make_fake_tool_state(base)
            plan = build_reset_plan(base)
            apply_reset_plan(plan, base)

            self.assertFalse((base / "data" / "grade_compiler.sqlite3").exists())
            self.assertFalse((base / "output" / "passed_midterm_report.xlsx").exists())
            self.assertFalse((base / "output" / "nested").exists())
            self.assertFalse((base / ".test_tmp").exists())
            self.assertFalse((base / "__pycache__").exists())
            self.assertTrue((base / "output" / ".gitkeep").exists())
            self.assertTrue((base / "input" / "grades" / "faculty.xlsx").exists())
            self.assertTrue((base / "input" / "masterlist" / "masterlist.csv").exists())

    def test_dry_run_deletes_nothing(self):
        with self.workspace_tempdir() as base:
            self.make_fake_tool_state(base)
            plan = build_reset_plan(base)
            apply_reset_plan(plan, base, dry_run=True)

            self.assertTrue((base / "data" / "grade_compiler.sqlite3").exists())
            self.assertTrue((base / "output" / "passed_midterm_report.xlsx").exists())
            self.assertTrue((base / ".test_tmp").exists())

    def test_include_inputs_removes_local_inputs_but_keeps_gitkeep(self):
        with self.workspace_tempdir() as base:
            self.make_fake_tool_state(base)
            plan = build_reset_plan(base, include_inputs=True)
            apply_reset_plan(plan, base)

            self.assertFalse((base / "input" / "grades" / "faculty.xlsx").exists())
            self.assertFalse((base / "input" / "masterlist" / "masterlist.csv").exists())
            self.assertTrue((base / "input" / "grades" / ".gitkeep").exists())
            self.assertTrue((base / "input" / "masterlist" / ".gitkeep").exists())

    def test_reset_continues_when_generated_temp_dir_is_locked(self):
        with self.workspace_tempdir() as base:
            self.make_fake_tool_state(base)
            locked_child = base / ".test_tmp" / "locked"
            locked_child.mkdir()
            (locked_child / "artifact.txt").write_text("locked")
            plan = build_reset_plan(base)
            test_tmp_dir = base / ".test_tmp"
            real_rmtree = shutil.rmtree

            def fake_rmtree(path, *args, **kwargs):
                target = Path(path)
                if target == locked_child or target == test_tmp_dir:
                    raise PermissionError(5, "Access is denied", str(path))
                return real_rmtree(path, *args, **kwargs)

            with patch("reset_test_state.shutil.rmtree", side_effect=fake_rmtree):
                apply_reset_plan(plan, base)

            self.assertFalse((base / "data" / "grade_compiler.sqlite3").exists())
            self.assertFalse((base / "output" / "passed_midterm_report.xlsx").exists())
            self.assertTrue(locked_child.exists())
            self.assertFalse((base / ".test_tmp" / "scratch.txt").exists())


if __name__ == "__main__":
    unittest.main()
