import json
import shutil
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
import pymupdf as fitz
from PIL import Image, ImageOps
from app.paths import app_data


@dataclass
class PageItem:
    id: str
    original: str
    rotation: int = 0
    crop: tuple[float, float, float, float] | None = None
    sheet_id: str | None = None


class DocumentSession:
    def __init__(self):
        self.directory = app_data() / "sessions" / "active"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = self.directory / "session.json"
        self.pages: list[PageItem] = []
        self.selected: set[str] = set()
        self.source_document_id: int | None = None
        self._undo = []
        self._redo = []
        self.load()

    def load(self):
        try:
            data = json.loads(self.manifest.read_text(encoding="utf-8"))
            self.pages = [PageItem(**item) for item in data["pages"] if (self.directory / item["original"]).is_file()]
            self.source_document_id = data.get("source_document_id")
        except (OSError, ValueError, KeyError, TypeError):
            self.pages = []

    def persist(self):
        data = {"pages": [asdict(item) for item in self.pages], "source_document_id": self.source_document_id}
        temp = self.manifest.with_suffix(".tmp")
        temp.write_text(json.dumps(data), encoding="utf-8")
        temp.replace(self.manifest)

    def checkpoint(self):
        self._undo.append([PageItem(**asdict(p)) for p in self.pages])
        self._undo = self._undo[-30:]
        self._redo.clear()

    def undo(self):
        if self._undo:
            self._redo.append(self.pages)
            self.pages = self._undo.pop()
            self.persist()

    def redo(self):
        if self._redo:
            self._undo.append(self.pages)
            self.pages = self._redo.pop()
            self.persist()

    def import_pdf(self, path: Path, at: int | None = None, replace: int = 0, duplex=False):
        doc = fitz.open(path)
        if not doc.page_count:
            doc.close()
            raise ValueError("The scan contained no pages.")
        imported = []
        try:
            sheet_ids = [uuid.uuid4().hex for _ in range((doc.page_count + 1) // 2)] if duplex else []
            for number, page in enumerate(doc):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                name = f"{uuid.uuid4().hex}.png"
                pix.save(self.directory / name)
                imported.append(PageItem(uuid.uuid4().hex, name,
                                         sheet_id=sheet_ids[number // 2] if duplex else None))
        except Exception:
            for item in imported:
                (self.directory / item.original).unlink(missing_ok=True)
            raise
        finally:
            doc.close()
        self.checkpoint()
        index = len(self.pages) if at is None else at
        if replace == 1 and index < len(self.pages) and len(imported) == 1:
            imported[0].sheet_id = self.pages[index].sheet_id
        self.pages[index:index + replace] = imported
        self.selected = {p.id for p in imported}
        self.persist()
        return imported

    def reorder(self, old: int, new: int):
        self.checkpoint()
        self.pages.insert(new, self.pages.pop(old))
        self.persist()

    def reorder_range(self, start: int, end: int, destination: int):
        self.checkpoint()
        moved = self.pages[start:end + 1]
        del self.pages[start:end + 1]
        target = destination - len(moved) if destination > start else destination
        self.pages[target:target] = moved
        self.persist()

    def rotate(self, degrees: int):
        self.checkpoint()
        for page in self.pages:
            if page.id in self.selected:
                page.rotation = (page.rotation + degrees) % 360
        self.persist()

    def crop(self, bounds: tuple[float, float, float, float]):
        self.checkpoint()
        for page in self.pages:
            if page.id in self.selected:
                page.crop = bounds
        self.persist()

    def crop_visible_page(self, item: PageItem, bounds: tuple[float, float, float, float]):
        """Apply a drag rectangle on the displayed page to its original image."""
        l, t, r, b = bounds
        corners = ((l, t), (r, t), (l, b), (r, b))
        def unrotate(x, y):
            return {0: (x, y), 90: (y, 1 - x), 180: (1 - x, 1 - y),
                    270: (1 - y, x)}[item.rotation % 360]
        mapped = [unrotate(x, y) for x, y in corners]
        old_l, old_t, old_r, old_b = item.crop or (0, 0, 1, 1)
        new_bounds = (old_l + min(x for x, _ in mapped) * (old_r - old_l),
                      old_t + min(y for _, y in mapped) * (old_b - old_t),
                      old_l + max(x for x, _ in mapped) * (old_r - old_l),
                      old_t + max(y for _, y in mapped) * (old_b - old_t))
        if not (0 <= new_bounds[0] < new_bounds[2] <= 1 and
                0 <= new_bounds[1] < new_bounds[3] <= 1):
            raise ValueError("Choose a valid crop area.")
        self.checkpoint()
        item.crop = new_bounds
        self.persist()

    def delete(self):
        self.checkpoint()
        self.pages = [p for p in self.pages if p.id not in self.selected]
        self.selected.clear()
        self.persist()

    def image(self, item: PageItem):
        with Image.open(self.directory / item.original) as original:
            image = ImageOps.exif_transpose(original).copy()
        if item.crop:
            l, t, r, b = item.crop
            image = image.crop((round(l * image.width), round(t * image.height),
                                round(r * image.width), round(b * image.height)))
        if item.rotation:
            image = image.rotate(-item.rotation, expand=True)
        return image

    def preview_path(self, item: PageItem, width=900):
        image = self.image(item)
        image.thumbnail((width, width * 2))
        dest = self.directory / f"preview-{item.id}.png"
        image.save(dest)
        return dest

    def reset(self):
        self.pages.clear()
        self.selected.clear()
        self.source_document_id = None
        self._undo.clear()
        self._redo.clear()
        self.persist()
        for path in self.directory.iterdir():
            if path != self.manifest and path.is_file():
                path.unlink(missing_ok=True)
