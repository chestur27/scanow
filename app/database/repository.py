import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from app.paths import app_data


class LibraryRepository:
    def __init__(self):
        self.path = app_data() / "library.db"
        with closing(self.connect()) as con, con:
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
            columns = {row[1] for row in con.execute("PRAGMA table_info(documents)")}
            additions = {
                "reference_number": "TEXT NOT NULL DEFAULT ''",
                "related_entity": "TEXT NOT NULL DEFAULT ''",
                "document_date": "TEXT NOT NULL DEFAULT ''",
                "ocr_text": "TEXT NOT NULL DEFAULT ''",
                "checksum": "TEXT NOT NULL DEFAULT ''",
            }
            for name, definition in additions.items():
                if name not in columns:
                    con.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
            con.execute("CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(document_date)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at)")
            # One-time cleanup of categories seeded by older releases. New user categories persist.
            if con.execute("PRAGMA user_version").fetchone()[0] < 1:
                con.execute("UPDATE documents SET category_id=1 WHERE category_id<>1")
                con.execute("DELETE FROM categories WHERE id<>1")
                con.execute("PRAGMA user_version=1")
            try:
                present = con.execute("SELECT 1 FROM sqlite_master WHERE name='document_search'").fetchone()
                con.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS document_search USING fts5(
                        title, description, tags, reference_number, related_entity, ocr_text,
                        content='documents', content_rowid='id');
                    CREATE TRIGGER IF NOT EXISTS documents_search_insert AFTER INSERT ON documents BEGIN
                        INSERT INTO document_search(rowid,title,description,tags,reference_number,related_entity,ocr_text)
                        VALUES(new.id,new.title,new.description,new.tags,new.reference_number,new.related_entity,new.ocr_text);
                    END;
                    CREATE TRIGGER IF NOT EXISTS documents_search_delete AFTER DELETE ON documents BEGIN
                        INSERT INTO document_search(document_search,rowid,title,description,tags,reference_number,related_entity,ocr_text)
                        VALUES('delete',old.id,old.title,old.description,old.tags,old.reference_number,old.related_entity,old.ocr_text);
                    END;
                    CREATE TRIGGER IF NOT EXISTS documents_search_update AFTER UPDATE ON documents BEGIN
                        INSERT INTO document_search(document_search,rowid,title,description,tags,reference_number,related_entity,ocr_text)
                        VALUES('delete',old.id,old.title,old.description,old.tags,old.reference_number,old.related_entity,old.ocr_text);
                        INSERT INTO document_search(rowid,title,description,tags,reference_number,related_entity,ocr_text)
                        VALUES(new.id,new.title,new.description,new.tags,new.reference_number,new.related_entity,new.ocr_text);
                    END;
                """)
                if not present:
                    con.execute("INSERT INTO document_search(document_search) VALUES('rebuild')")
                self.fts_available = True
            except sqlite3.OperationalError:
                self.fts_available = False

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def categories(self):
        with closing(self.connect()) as con, con:
            return con.execute("SELECT * FROM categories ORDER BY name COLLATE NOCASE").fetchall()

    def add_category(self, name):
        with closing(self.connect()) as con, con:
            con.execute("INSERT INTO categories(name) VALUES(?)", (name.strip(),))

    def rename_category(self, category_id, name):
        if category_id == 1:
            raise ValueError("Uncategorized cannot be renamed.")
        with closing(self.connect()) as con, con:
            con.execute("UPDATE categories SET name=? WHERE id=?", (name.strip(), category_id))

    def delete_category(self, category_id):
        if category_id == 1:
            raise ValueError("Uncategorized cannot be removed.")
        with closing(self.connect()) as con, con:
            con.execute("UPDATE documents SET category_id=1 WHERE category_id=?", (category_id,))
            con.execute("DELETE FROM categories WHERE id=?", (category_id,))

    def documents(self, query="", category=None, sort="newest", date_from="", date_to="", date_field="document"):
        order = {"newest": "COALESCE(NULLIF(d.document_date,''), d.created_at) DESC",
                 "oldest": "COALESCE(NULLIF(d.document_date,''), d.created_at) ASC",
                 "az": "d.title COLLATE NOCASE ASC", "za": "d.title COLLATE NOCASE DESC",
                 "category_az": "c.name COLLATE NOCASE ASC, d.title COLLATE NOCASE ASC",
                 "category_za": "c.name COLLATE NOCASE DESC, d.title COLLATE NOCASE ASC",
                 "reference_az": "d.reference_number COLLATE NOCASE ASC",
                 "reference_za": "d.reference_number COLLATE NOCASE DESC",
                 "size": "d.file_size DESC"}.get(sort, "d.updated_at DESC")
        needle = f"%{query}%"
        fts = bool(query.strip()) and self.fts_available
        fts_term = '"' + query.strip().replace('"', '""') + '"'
        fts_clause = " OR d.id IN (SELECT rowid FROM document_search WHERE document_search MATCH ?)" if fts else ""
        field = "d.created_at" if date_field == "archived" else "d.document_date"
        upper = date_to + "T~" if date_field == "archived" and date_to else date_to
        with closing(self.connect()) as con, con:
            return con.execute(f"""SELECT d.*, c.name AS category FROM documents d
                JOIN categories c ON c.id=d.category_id
                WHERE (? IS NULL OR d.category_id=?) AND
                (d.title LIKE ? OR d.filename LIKE ? OR c.name LIKE ? OR d.tags LIKE ? OR d.description LIKE ?
                 OR d.reference_number LIKE ? OR d.related_entity LIKE ? OR d.document_date LIKE ?
                 OR d.created_at LIKE ? OR d.ocr_text LIKE ?{fts_clause})
                AND (?='' OR {field}>=?) AND (?='' OR {field}<=?)
                ORDER BY {order}""", (category, category, *([needle] * 10),
                                       *((fts_term,) if fts else ()),
                                       date_from, date_from, date_to, upper)).fetchall()

    def get(self, document_id):
        with closing(self.connect()) as con, con:
            return con.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()

    def by_path(self, path):
        with closing(self.connect()) as con, con:
            return con.execute("SELECT * FROM documents WHERE file_path=?", (str(path),)).fetchone()

    def save(self, title, path, category_id, description, tags, page_count, document_id=None,
             reference_number="", related_entity="", document_date="", checksum="", ocr_text=""):
        now = datetime.now(timezone.utc).isoformat()
        path = Path(path)
        with closing(self.connect()) as con, con:
            if document_id:
                con.execute("""UPDATE documents SET title=?,filename=?,file_path=?,category_id=?,description=?,
                    tags=?,page_count=?,file_size=?,updated_at=?,reference_number=?,related_entity=?,
                    document_date=?,checksum=?,ocr_text=? WHERE id=?""",
                    (title, path.name, str(path), category_id, description, tags,
                     page_count, path.stat().st_size, now, reference_number, related_entity,
                     document_date, checksum, ocr_text, document_id))
                return document_id
            cursor = con.execute("""INSERT INTO documents(title,filename,file_path,category_id,description,tags,
                page_count,file_size,created_at,updated_at,reference_number,related_entity,
                document_date,checksum,ocr_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title, path.name, str(path), category_id, description, tags,
                 page_count, path.stat().st_size, now, now, reference_number, related_entity,
                 document_date, checksum, ocr_text))
            return cursor.lastrowid

    def update_metadata(self, document_id, title, category_id, description, tags,
                        reference_number="", related_entity="", document_date=""):
        with closing(self.connect()) as con, con:
            con.execute("""UPDATE documents SET title=?,category_id=?,description=?,tags=?,updated_at=?,
                        reference_number=?,related_entity=?,document_date=? WHERE id=?""",
                        (title, category_id, description, tags, datetime.now(timezone.utc).isoformat(),
                         reference_number, related_entity, document_date, document_id))

    def integrity_check(self):
        with closing(self.connect()) as con, con:
            return con.execute("PRAGMA integrity_check").fetchone()[0]

    def duplicate_of(self, document_id):
        with closing(self.connect()) as con, con:
            return con.execute("""SELECT other.id, other.title FROM documents current
                JOIN documents other ON other.checksum=current.checksum AND other.id<>current.id
                WHERE current.id=? AND current.checksum<>'' ORDER BY other.created_at LIMIT 1""",
                (document_id,)).fetchone()

    def relink(self, document_id, path):
        with closing(self.connect()) as con, con:
            con.execute("UPDATE documents SET file_path=?,filename=?,file_size=? WHERE id=?",
                        (str(path), path.name, path.stat().st_size, document_id))

    def delete(self, document_id):
        with closing(self.connect()) as con, con:
            con.execute("DELETE FROM documents WHERE id=?", (document_id,))
