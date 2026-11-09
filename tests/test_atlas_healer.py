import tempfile
import unittest
from pathlib import Path

from atlas_healer import AtlasHealer


class AtlasHealerTests(unittest.TestCase):
    def make_script(self, directory: Path, text: str) -> Path:
        path = directory / "research.py"
        path.write_text(text, encoding="utf-8")
        return path

    def test_detects_notebook_shell_command_and_absolute_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_script(
                Path(temp_dir),
                'data_path = "/home/user/data.csv"\n!pip install numpy\nprint("ok")\n',
            )
            report = AtlasHealer(path).scan_reproducibility()
            self.assertTrue(report.syntax_valid)
            self.assertEqual(
                {finding.code for finding in report.findings},
                {"ABSOLUTE_PATH", "IPYTHON_SHELL_ESCAPE"},
            )

    def test_heal_comments_shell_escape_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_script(Path(temp_dir), 'print("ok")\n!pip install numpy\n')
            original = path.read_text(encoding="utf-8")
            output, report, edits = AtlasHealer(path).heal()
            self.assertEqual(edits, 1)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertIn("# ATLAS-HEALED (not executed): !pip install numpy", output.read_text(encoding="utf-8"))
            self.assertTrue(report.syntax_valid)
            self.assertTrue(report.reproducible)

    def test_reports_syntax_error_without_guessing_a_fix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_script(Path(temp_dir), 'print("broken)\n')
            report = AtlasHealer(path).scan_reproducibility()
            self.assertFalse(report.syntax_valid)
            self.assertIn("PYTHON_SYNTAX_ERROR", {finding.code for finding in report.findings})

    def test_ignores_shell_symbols_inside_string_and_comment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_script(Path(temp_dir), 'text = "!pip install"\n# %timeit x\nprint(text)\n')
            report = AtlasHealer(path).scan_reproducibility()
            self.assertTrue(report.reproducible)


if __name__ == "__main__":
    unittest.main()
