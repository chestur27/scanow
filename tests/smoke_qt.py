"""Offscreen smoke test for Qt navigation and a mock scanner job."""

import os
import gc
import shutil
import uuid
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
root = Path(__file__).resolve().parent / f".qt-smoke-{uuid.uuid4().hex}"
root.mkdir()
os.environ["LOCALAPPDATA"] = str(root)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.ui.main_window import ScaNowWindow


app = QApplication([])
window = ScaNowWindow()
window.settings.set(library_dir=str(root / "archive"))
assert window.stack.count() == 3
window.show_view(1)
window.show_view(2)
window.show_view(0)
window._scanners_found([])
window.source.setCurrentIndex(0)
window.start_scan()
jobs = 0
preview_ready = False

def check():
    global jobs
    if window.running:
        QTimer.singleShot(100, check)
    else:
        jobs += 1
        if jobs == 1:
            assert len(window.session.pages) == 1
            assert window.session.selected == {window.session.pages[0].id}
            window.rotate_page_by(90)
            assert window.session.pages[0].rotation == 90
            window.undo()
            assert window.session.pages[0].rotation == 0
            window.scan_button.click()
            QTimer.singleShot(100, check)
            return
        try:
            assert len(window.session.pages) == 2
            window.library.add_category("Invoice")
            category = next(row for row in window.library.categories() if row["name"] == "Invoice")
            window.archive.save_session(window.session, {"title": "Qt smoke", "category_id": category["id"]})
            window.show_view(1)
            window.table.selectRow(0)
            QTimer.singleShot(100, finish)
        except Exception:
            window.close()
            app.quit()
            raise

def finish():
    global preview_ready
    if window.pdf.pageCount() == 0:
        QTimer.singleShot(100, finish)
        return
    try:
        assert window.pdf.pageCount() == 2
        window.change_pdf_page(1)
        preview_ready = True
        print("Qt navigation, mock scan, archive, and PDF preview: OK")
    finally:
        window.pdf_view.setDocument(None)
        window.pdf.close()
        window.close()
        app.quit()

QTimer.singleShot(100, check)
QTimer.singleShot(10000, app.quit)
try:
    app.exec()
    if not preview_ready:
        print("preview diagnostics:", window.details.text(), window.pdf.status(), window.pdf.pageCount())
    assert preview_ready, "Qt PDF preview did not load"
finally:
    window.deleteLater()
    app.processEvents()
    del window
    del app
    gc.collect()
    shutil.rmtree(root)
