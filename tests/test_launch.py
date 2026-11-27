from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from launch import preflight, REQUIRED

class LaunchTests(unittest.TestCase):
    def test_old_python_has_actionable_message(self):
        self.assertIn("3.11", preflight(Path("."), (3, 10))[0])

    def test_current_complete_release_passes(self):
        self.assertEqual(preflight(Path(__file__).resolve().parents[1], (3, 11)), [])

    def test_incomplete_extract_does_not_touch_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            sentinel = root / "data/workbench.sqlite3"
            sentinel.write_bytes(b"existing database sentinel")
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertIn("Incomplete extraction", preflight(root, (3, 11))[0])
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)

    def test_failed_entrypoint_creates_no_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = Path(__file__).resolve().parents[1] / "launch.py"
            (root / "launch.py").write_bytes(source.read_bytes())
            result = subprocess.run([sys.executable, "-B", str(root / "launch.py")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Extract the entire ZIP", result.stderr)
            self.assertFalse((root / "data").exists())

    def test_missing_main_asset_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in REQUIRED:
                if name == "web/app.js":
                    continue
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            self.assertIn("web/app.js", preflight(root, (3, 11))[0])
