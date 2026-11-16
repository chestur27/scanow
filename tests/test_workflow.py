import os
import unittest
import shutil
import uuid
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from app.database.repository import LibraryRepository
from app.documents.archive_service import ArchiveService
from app.documents.session import DocumentSession
from app.scanner.base import ScanOptions
from app.scanner.mock_backend import MockBackend
from app.settings_store import SettingsStore


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / f".runtime-{uuid.uuid4().hex}"
        self.root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.root))
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = SettingsStore()
        self.settings.set(library_dir=str(self.root / "archive"))
        self.library = LibraryRepository()
        self.service = ArchiveService(self.library, self.settings)
        self.session = DocumentSession()

    def test_legacy_categories_are_cleared_once(self):
        self.library.add_category("Old preset")
        with closing(self.library.connect()) as con, con:
            con.execute("PRAGMA user_version=0")
        self.library = LibraryRepository()
        self.assertEqual([row["name"] for row in self.library.categories()], ["Uncategorized"])
        self.library.add_category("My category")
        self.library = LibraryRepository()
        self.assertEqual({row["name"] for row in self.library.categories()}, {"Uncategorized", "My category"})

    def test_visible_crop_maps_rotated_page(self):
        from app.documents.session import PageItem
        page = PageItem("crop-test", "unused.png", rotation=90, crop=(.1, .2, .9, .8))
        self.session.pages = [page]
        self.session.crop_visible_page(page, (.25, .25, .75, .75))
        self.assertEqual(tuple(round(value, 3) for value in page.crop), (.3, .35, .7, .65))

    def test_mock_scan_archive_search_backup_restore(self):
        scanner = MockBackend()
        pdf = self.root / "scan.pdf"
        scanner.scan(ScanOptions(scanner.discover()[0], source="duplex", pages=2), pdf)
        imported = self.session.import_pdf(pdf, duplex=True)
        self.assertEqual(len(imported), 2)
        self.library.add_category("Invoice")
        category = next(c for c in self.library.categories() if c["name"] == "Invoice")
        metadata = dict(title="November invoice", category_id=category["id"],
                        reference_number="INV-42", related_entity="Example Ltd",
                        document_date="2026-11-16", description="Monthly billing")
        first = self.service.save_session(self.session, metadata)
        self.assertFalse(self.session.pages)
        record = self.library.get(first)
        self.assertTrue(Path(record["file_path"]).is_file())
        with fitz.open(record["file_path"]) as saved:
            self.assertEqual(saved.page_count, 2)
        self.assertEqual(len(self.library.documents("INV-42")), 1)
        self.assertEqual(len(self.library.documents("Example Ltd", category["id"])), 1)
        self.assertEqual(len(self.library.documents(date_from="2026-11-17")), 0)
        archived = record["created_at"][:10]
        self.assertEqual(len(self.library.documents(date_from=archived, date_to=archived,
                                                    date_field="archived")), 1)

        self.session.import_pdf(pdf)
        self.service.save_session(self.session, metadata, first)
        self.assertTrue(list((self.service.documents_dir / "recovery").glob("previous-*.pdf")))
        self.session.import_pdf(pdf)
        second = self.service.save_session(self.session, metadata)
        self.assertNotEqual(self.library.get(first)["file_path"], self.library.get(second)["file_path"])
        backup = self.root / "backup.zip"
        self.service.backup(backup)
        with self.assertRaises(FileExistsError):
            self.service.backup(backup)
        self.library.delete(first)
        recovery = self.service.restore(backup)
        self.assertTrue(recovery.is_dir())
        self.assertEqual(self.library.integrity_check(), "ok")
        self.assertEqual(len(self.library.documents("INV-42")), 2)
        self.assertTrue(Path(self.library.get(first)["file_path"]).is_file())

    def test_failed_index_keeps_session_pages(self):
        scanner = MockBackend()
        pdf = self.root / "scan.pdf"
        scanner.scan(ScanOptions(scanner.discover()[0]), pdf)
        self.session.import_pdf(pdf)
        with self.assertRaises(Exception):
            self.service.save_session(self.session, {"title": "Test", "category_id": 9999})
        self.assertEqual(len(self.session.pages), 1)
        self.assertFalse(list(self.service.documents_dir.glob("*.pdf")))

    def test_existing_database_is_extended_without_losing_records(self):
        legacy = self.root / "legacy" / "ScaNow"
        legacy.mkdir(parents=True)
        with closing(sqlite3.connect(legacy / "library.db")) as con, con:
            con.executescript("""
                CREATE TABLE categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
                INSERT INTO categories VALUES(1,'Uncategorized');
                CREATE TABLE documents(id INTEGER PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE, category_id INTEGER NOT NULL DEFAULT 1,
                    description TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
                    page_count INTEGER NOT NULL, file_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                INSERT INTO documents VALUES(1,'Legacy PDF','legacy.pdf','C:/legacy.pdf',1,'old notes','',1,100,
                    '2025-01-01','2025-01-01');
            """)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "legacy")}):
            migrated = LibraryRepository()
            record = migrated.get(1)
            self.assertEqual(record["title"], "Legacy PDF")
            self.assertEqual(record["description"], "old notes")
            self.assertEqual(record["reference_number"], "")
            self.assertEqual(migrated.integrity_check(), "ok")


if __name__ == "__main__":
    unittest.main()
