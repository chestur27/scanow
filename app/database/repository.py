import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from app.paths import app_data


class LibraryRepository:
    def __init__(self):
        self.path = app_data() / "library.db"
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
                INSERT OR IGNORE INTO categories(id,name) VALUES(1,'Uncategorized');
                CREATE TABLE IF NOT EXISTS documents(
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE, category_id INTEGER NOT NULL DEFAULT 1,
                    description TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
                    page_count INTEGER NOT NULL, file_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(category_id) REFERENCES categories(id));
                CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);
                CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category_id);
            """)

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def categories(self):
        with self.connect() as con:
            return con.execute("SELECT * FROM categories ORDER BY name COLLATE NOCASE").fetchall()

    def add_category(self, name):
        with self.connect() as con:
            con.execute("INSERT INTO categories(name) VALUES(?)", (name.strip(),))

    def rename_category(self, category_id, name):
        if category_id == 1:
            raise ValueError("Uncategorized cannot be renamed.")
        with self.connect() as con:
            con.execute("UPDATE categories SET name=? WHERE id=?", (name.strip(), category_id))

    def delete_category(self, category_id):
        if category_id == 1:
            raise ValueError("Uncategorized cannot be removed.")
        with self.connect() as con:
            con.execute("UPDATE documents SET category_id=1 WHERE category_id=?", (category_id,))
            con.execute("DELETE FROM categories WHERE id=?", (category_id,))

    def documents(self, query="", category=None, sort="newest"):
        order = {"newest": "d.updated_at DESC", "oldest": "d.updated_at ASC",
                 "az": "d.title COLLATE NOCASE ASC", "za": "d.title COLLATE NOCASE DESC",
                 "size": "d.file_size DESC"}.get(sort, "d.updated_at DESC")
        needle = f"%{query}%"
        with self.connect() as con:
            return con.execute(f"""SELECT d.*, c.name AS category FROM documents d
                JOIN categories c ON c.id=d.category_id
                WHERE (? IS NULL OR d.category_id=?) AND
                (d.title LIKE ? OR d.filename LIKE ? OR c.name LIKE ? OR d.tags LIKE ? OR d.description LIKE ?)
                ORDER BY {order}""", (category, category, *([needle] * 5))).fetchall()

    def get(self, document_id):
        with self.connect() as con:
            return con.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()

    def by_path(self, path):
        with self.connect() as con:
            return con.execute("SELECT * FROM documents WHERE file_path=?", (str(path),)).fetchone()

    def save(self, title, path, category_id, description, tags, page_count, document_id=None):
        now = datetime.now(timezone.utc).isoformat()
        path = Path(path)
        with self.connect() as con:
            if document_id:
                con.execute("""UPDATE documents SET title=?,filename=?,file_path=?,category_id=?,description=?,
                    tags=?,page_count=?,file_size=?,updated_at=? WHERE id=?""",
                    (title, path.name, str(path), category_id, description, tags,
                     page_count, path.stat().st_size, now, document_id))
                return document_id
            cursor = con.execute("""INSERT INTO documents(title,filename,file_path,category_id,description,tags,
                page_count,file_size,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (title, path.name, str(path), category_id, description, tags,
                 page_count, path.stat().st_size, now, now))
            return cursor.lastrowid

    def update_metadata(self, document_id, title, category_id, description, tags):
        with self.connect() as con:
            con.execute("UPDATE documents SET title=?,category_id=?,description=?,tags=?,updated_at=? WHERE id=?",
                        (title, category_id, description, tags, datetime.now(timezone.utc).isoformat(), document_id))

    def relink(self, document_id, path):
        with self.connect() as con:
            con.execute("UPDATE documents SET file_path=?,filename=?,file_size=? WHERE id=?",
                        (str(path), path.name, path.stat().st_size, document_id))

    def delete(self, document_id):
        with self.connect() as con:
            con.execute("DELETE FROM documents WHERE id=?", (document_id,))
