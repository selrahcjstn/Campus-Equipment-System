import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import demo


class DemoConfigurationTests(unittest.TestCase):
    def test_first_setup_uses_private_separate_database_and_preserves_credentials(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ):
            root = Path(temp)
            with patch.multiple(demo, ROOT=root, CONFIG=root / ".env.demo", DATABASE=root / "demo.sqlite3"):
                os.environ["DJANGO_DATABASE_PATH"] = str(root / "db.sqlite3")
                demo.configure(create=True)
                self.assertEqual(Path(os.environ["DJANGO_DATABASE_PATH"]), root / "demo.sqlite3")
                original = (root / ".env.demo").read_bytes()
                self.assertGreaterEqual(len(os.environ["CAMPUS_DEMO_PASSWORD"]), 24)
                demo.configure(create=True)
                self.assertEqual((root / ".env.demo").read_bytes(), original)
                self.assertFalse((root / "db.sqlite3").exists())

    def test_existing_database_without_private_configuration_is_not_adopted(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "demo.sqlite3").write_bytes(b"existing data")
            with patch.multiple(demo, ROOT=root, CONFIG=root / ".env.demo", DATABASE=root / "demo.sqlite3"):
                with self.assertRaises(SystemExit):
                    demo.configure(create=True)
                self.assertEqual((root / "demo.sqlite3").read_bytes(), b"existing data")
                self.assertFalse((root / ".env.demo").exists())

    def test_configuration_cannot_target_working_database(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ):
            root = Path(temp)
            (root / ".env.demo").write_text(f"DJANGO_DATABASE_PATH={(root/'db.sqlite3').as_posix()}\n", encoding="utf-8")
            with patch.multiple(demo, ROOT=root, CONFIG=root / ".env.demo", DATABASE=root / "demo.sqlite3"):
                with self.assertRaisesRegex(SystemExit, "separate"):
                    demo.configure()


if __name__ == "__main__":
    unittest.main()
