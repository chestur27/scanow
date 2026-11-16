"""Filesystem and SQLite operations for the local document archive."""

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import uuid
import zipfile
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path

import pymupdf as fitz

from app.documents.pdf_service import export_pdf


@contextmanager
def staging_directory(parent):
    path = Path(parent) / f".scanow-stage-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


class ArchiveService:
    def __init__(self, library, settings):
        self.library = library
        self.settings = settings

    @property
    def documents_dir(self):
        return Path(self.settings.get("library_dir")) / "documents"

    def save_session(self, session, metadata, document_id=None):
        if not session.pages:
            raise ValueError("There are no pages to save.")
        title = metadata["title"].strip()
        if not title or any(char in title for char in '<>:"/\\|?*') or any(ord(char) < 32 for char in title):
            raise ValueError("Enter a valid document name.")
        if metadata.get("document_date"):
            try:
                date.fromisoformat(metadata["document_date"])
            except ValueError as exc:
                raise ValueError("Use YYYY-MM-DD for the document date.") from exc
        existing = self.library.get(document_id) if document_id else None
        if document_id and existing is None:
            raise ValueError("The original archive record is missing.")
        root = Path(metadata.get("destination_dir") or self.documents_dir)
        if existing:
            root = Path(existing["file_path"]).parent
        root.mkdir(parents=True, exist_ok=True)
        destination = Path(existing["file_path"]) if existing else root / f"{uuid.uuid4().hex}.pdf"
        if existing and not destination.is_file():
            raise FileNotFoundError("The original PDF is missing. Export a copy before editing it.")
        temporary = destination.parent / f".{uuid.uuid4().hex}.pdf"
        backup = destination.parent / f".{uuid.uuid4().hex}.previous"
        replaced = False
        committed = False
        try:
            export_pdf(session, temporary)
            with fitz.open(temporary) as pdf:
                if pdf.page_count != len(session.pages):
                    raise ValueError("PDF validation failed; scanned pages are still available.")
            digest = hashlib.sha256()
            with temporary.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            checksum = digest.hexdigest()
            if existing:
                shutil.copy2(destination, backup)
            os.replace(temporary, destination)
            replaced = True
            try:
                result = self.library.save(title, destination, int(metadata["category_id"]),
                    metadata.get("description", ""), metadata.get("tags", ""), len(session.pages),
                    document_id, metadata.get("reference_number", ""), metadata.get("related_entity", ""),
                    metadata.get("document_date", ""), checksum)
            except Exception:
                if existing:
                    os.replace(backup, destination)
                else:
                    destination.unlink(missing_ok=True)
                raise
            committed = True
            session.reset()
            return result
        finally:
            temporary.unlink(missing_ok=True)
            if committed and backup.exists():
                try:
                    recovery = destination.parent / "recovery"
                    recovery.mkdir(exist_ok=True)
                    os.replace(backup, recovery / f"previous-{uuid.uuid4().hex}.pdf")
                except OSError:
                    logging.exception("Could not move previous PDF into recovery")
            elif not replaced:
                backup.unlink(missing_ok=True)

    def backup(self, destination):
        """Snapshot SQLite, then archive that snapshot and its referenced managed files."""
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError("Choose a new backup filename; existing backups are never replaced.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with staging_directory(destination.parent) as folder:
            snapshot = Path(folder) / "library.db"
            with closing(self.library.connect()) as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
            with closing(sqlite3.connect(snapshot)) as con:
                rows = con.execute("SELECT file_path FROM documents").fetchall()
            managed = self.documents_dir.resolve()
            files = []
            for (name,) in rows:
                path = Path(name)
                if path.parent.resolve() == managed:
                    if not path.is_file():
                        raise FileNotFoundError(f"Managed archive file is missing: {path.name}")
                    files.append(path)
            temporary = destination.with_name(f".{uuid.uuid4().hex}.zip")
            try:
                with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(snapshot, "library.db")
                    archive.writestr("manifest.json", json.dumps({"managed_dir": str(managed),
                        "files": [path.name for path in files]}))
                    archive.writestr("settings.json", json.dumps(self.settings.values))
                    for path in files:
                        archive.write(path, f"documents/{path.name}")
                with zipfile.ZipFile(temporary) as archive:
                    if archive.testzip():
                        raise ValueError("Backup verification failed.")
                os.link(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return destination

    def restore(self, source):
        """Restore to the configured directory after the UI confirms replacement."""
        source = Path(source)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        with staging_directory(self.documents_dir) as folder, zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
            if not {"library.db", "manifest.json"} <= names:
                raise ValueError("This is not a ScaNow backup.")
            manifest = json.loads(archive.read("manifest.json"))
            files = manifest.get("files", [])
            if any(Path(name).name != name or f"documents/{name}" not in names for name in files):
                raise ValueError("The backup has invalid document paths.")
            snapshot = Path(folder) / "library.db"
            snapshot.write_bytes(archive.read("library.db"))
            with closing(sqlite3.connect(snapshot)) as con:
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("The backup database is damaged.")
                old_root = Path(manifest["managed_dir"])
                for record_id, path in con.execute("SELECT id,file_path FROM documents").fetchall():
                    original = Path(path)
                    if original.parent == old_root:
                        if original.name not in files:
                            raise ValueError("The backup is missing a managed PDF.")
                        con.execute("UPDATE documents SET file_path=? WHERE id=?",
                                    (str(self.documents_dir / original.name), record_id))
                con.commit()
            if archive.testzip():
                raise ValueError("The backup archive is damaged.")
            target = self.documents_dir
            target.mkdir(parents=True, exist_ok=True)
            stage = Path(folder) / "documents"
            stage.mkdir()
            for name in files:
                (stage / name).write_bytes(archive.read(f"documents/{name}"))
            recovery = target / "recovery" / f"before-restore-{uuid.uuid4().hex}"
            recovery.mkdir(parents=True)
            previous = list(target.glob("*.pdf"))
            installed = []
            before_db = None
            try:
                for file in previous:
                    os.replace(file, recovery / file.name)
                for name in files:
                    destination = target / name
                    os.replace(stage / name, destination)
                    installed.append(destination)
                before_db = self.library.path.with_name(f"library.before-restore-{uuid.uuid4().hex}.db")
                shutil.copy2(self.library.path, before_db)
                os.replace(snapshot, self.library.path)
                self.library.__init__()
            except Exception:
                if before_db and before_db.exists():
                    shutil.copy2(before_db, self.library.path)
                for file in installed:
                    file.unlink(missing_ok=True)
                for file in previous:
                    saved = recovery / file.name
                    if saved.exists():
                        os.replace(saved, file)
                raise
            return recovery

