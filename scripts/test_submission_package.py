import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import package_submission as package


class SubmissionPackageTests(unittest.TestCase):
    def test_rejects_local_data_and_credentials_even_when_git_lists_them(self):
        for name in [".env", ".env.demo", "apps/.env", "apps/data.sqlite3", "apps/data.sqlite3-wal", "apps/data.db", "docs/run.log", ".git/config", ".venv/site.py", "../manage.py", "/manage.py", "dist/old.zip", "docs/final-submission/Campus_Equipment_Borrowing_System_Documentation.pdf"]:
            with self.subTest(name=name):
                self.assertFalse(package.allowed(name))
        for name in [".env.example", "manage.py", "apps/inventory/models.py", "templates/base.html", "docs/final-submission/BASIC_USER_GUIDE.md"]:
            self.assertTrue(package.allowed(name))

    def fixtures(self, root):
        for name in ["manage.py", "requirements.txt", ".env.example", "DEMO_SETUP.md"]:
            (root / name).write_text("example source", encoding="utf-8")
        (root / ".env").write_text("DJANGO_SECRET_KEY=private-test-key-never-include", encoding="utf-8")
        (root / "db.sqlite3").write_bytes(b"private database")
        return b"manage.py\0requirements.txt\0.env.example\0DEMO_SETUP.md\0.env\0db.sqlite3\0"

    def test_archive_contains_only_permitted_sources_and_manifest(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            listing = self.fixtures(root)
            with patch.object(package, "ROOT", root), patch.object(package.subprocess, "check_output", return_value=listing):
                target = package.build("BSIT4A", "1", root / "dist")
            with ZipFile(target) as archive:
                self.assertIsNone(archive.testzip())
                manifest = json.loads(archive.read("campus-equipment-system/SUBMISSION_MANIFEST.json"))
                self.assertEqual(len(manifest["files"]), 4)
                self.assertFalse(manifest["contains_database_or_credentials"])
                self.assertFalse(any(name.endswith((".env", ".sqlite3")) for name in archive.namelist()))

    def test_local_secret_in_document_aborts_before_writing_archive(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            listing = self.fixtures(root)
            (root / "DEMO_SETUP.md").write_text("private-test-key-never-include", encoding="utf-8")
            with patch.object(package, "ROOT", root), patch.object(package.subprocess, "check_output", return_value=listing):
                with self.assertRaisesRegex(ValueError, "private credential"):
                    package.build("BSIT4A", "1", root / "dist")
            self.assertFalse(list(root.rglob("*.zip")))

    def test_rejects_path_characters_in_section_and_group(self):
        for section, group in [("../outside", "1"), ("BSIT4A", "../../outside"), ("", "1")]:
            with self.assertRaises(ValueError):
                package.build(section, group, Path("unused"))


if __name__ == "__main__":
    unittest.main()
