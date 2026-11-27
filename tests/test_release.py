import tempfile
from pathlib import Path
import unittest
import zipfile
from tools.build_release import build, decode_backup

class ReleaseTests(unittest.TestCase):
    def fixture(self, root):
        (root / "VERSION").write_text("1.2.3")
        (root / "server.py").write_text("# fixture")
        (root / "data").mkdir()
        (root / "data/workbench.sqlite3").write_bytes(b"private-sentinel")
        (root / "__pycache__").mkdir()
        (root / "__pycache__/server.pyc").write_bytes(b"cache")

    def test_roundtrip_excludes_data_and_cache_and_keeps_unicode_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "中文 source"; root.mkdir(); self.fixture(root)
            zipped, backup, _ = build(root, Path(temp) / "新 release")
            self.assertEqual(decode_backup(backup.read_text()), zipped.read_bytes())
            self.assertEqual((root / "data/workbench.sqlite3").read_bytes(), b"private-sentinel")
            with zipfile.ZipFile(zipped) as z:
                self.assertEqual(set(z.namelist()), {"job-workbench/VERSION", "job-workbench/server.py"})
                self.assertIsNone(z.testzip())

    def test_refuses_existing_release_without_changing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.fixture(root); out = root / "release"
            zipped, backup, _ = build(root, out)
            before = (zipped.read_bytes(), backup.read_bytes())
            with self.assertRaises(FileExistsError): build(root, out)
            self.assertEqual(before, (zipped.read_bytes(), backup.read_bytes()))

    def test_rejects_damaged_and_incomplete_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.fixture(root)
            _, backup, digest = build(root, root / "release")
            text = backup.read_text()
            with self.assertRaisesRegex(ValueError, "SHA256"):
                decode_backup(text.replace(digest, "0" * 64))
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                decode_backup(text.split("-----BEGIN JOB WORKBENCH ZIP-----")[0])
