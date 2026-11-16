"""ScaNow's Qt Widgets desktop interface."""

import logging
import shutil
from contextlib import closing
from datetime import date
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QBuffer, QIODevice, QModelIndex, QObject, QPointF, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal, QSize
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QPixmap, QColor, QPalette
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QPlainTextEdit, QPushButton,
    QSplitter, QStackedWidget, QTableView, QVBoxLayout, QWidget, QCheckBox, QScrollArea,
    QGraphicsDropShadowEffect, QAbstractItemView, QHeaderView, QSizePolicy)

from app.database.repository import LibraryRepository
from app.documents.archive_service import ArchiveService, staging_directory
from app.documents.pdf_service import export_pdf
from app.documents.session import DocumentSession
from app.scanner.base import ScanOptions
from app.scanner.mock_backend import MockBackend
from app.scanner.naps2_backend import Naps2Backend
from app.settings_store import SettingsStore
from app.ui.theme import stylesheet
from app.ui.components import action, icon_button, field_label, line
from app.ui.prompts import QMessageBox, QInputDialog
from app.ui.crop_dialog import CropDialog
from app.ui.smooth_scroll import SmoothPageList, SmoothPaperScroll


def button(label, slot, primary=False):
    return action(label, slot, primary=primary)


def combo(options, value=None):
    control = QComboBox()
    for label, data in options:
        control.addItem(label, data)
    index = control.findData(value)
    if index >= 0:
        control.setCurrentIndex(index)
    return control


def heading(text, subtle=False):
    label = QLabel(text)
    label.setObjectName("subtle" if subtle else "title")
    return label


class JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = JobSignals()

    def run(self):
        try:
            self.signals.done.emit(self.operation())
        except Exception as exc:
            logging.exception("Background operation failed")
            self.signals.failed.emit(str(exc))


class MetadataDialog(QDialog):
    def __init__(self, library, record=None, parent=None, draft=None):
        super().__init__(parent)
        self.setWindowTitle("Edit details" if record else "Save to Archive")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QDialog { background: transparent; }")
        self.setFixedWidth(600)
        self.record = record
        self._overlay = None
        source = record or draft or {}
        def val(key, default=""):
            return source[key] if key in source.keys() else default
        frame = QFrame()
        frame.setObjectName("modalCard")
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(31, 41, 61, 65))
        frame.setGraphicsEffect(shadow)
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(18, 18, 18, 18)
        wrap.addWidget(frame)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(8)
        outer.addWidget(heading("Edit details" if record else "Save to Archive"))
        count = len(parent.session.pages) if parent else 0
        subtitle = heading("Update searchable document details." if record else
                           f"{count} {'page' if count == 1 else 'pages'} · added to your library and searchable.", True)
        outer.addWidget(subtitle)
        outer.addSpacing(4)
        outer.addWidget(field_label("Document name *"))
        self.title_edit = QLineEdit(val("title", "Untitled scan"))
        outer.addWidget(self.title_edit)
        self.name_error = QLabel("")
        self.name_error.setObjectName("error")
        self.name_error.hide()
        outer.addWidget(self.name_error)
        columns = QHBoxLayout()
        columns.setSpacing(10)
        category_box = QVBoxLayout()
        category_box.setSpacing(4)
        category_box.addWidget(field_label("Category *"))
        self.category = combo([(r["name"], r["id"]) for r in library.categories()],
                              val("category_id", 1))
        self.category.addItem("+ Add category…", None)
        self.category.currentIndexChanged.connect(self.add_category_if_requested)
        self.library = library
        category_row = QHBoxLayout()
        category_row.setSpacing(4)
        category_row.addWidget(self.category, 1)
        category_row.addWidget(icon_button("plus", self.create_category, "Add category"))
        category_box.addLayout(category_row)
        columns.addLayout(category_box, 1)
        date_box = QVBoxLayout()
        date_box.setSpacing(4)
        date_box.addWidget(field_label("Document date *"))
        self.date_edit = QLineEdit(val("document_date") or date.today().isoformat())
        self.date_edit.setPlaceholderText("YYYY-MM-DD")
        date_box.addWidget(self.date_edit)
        columns.addLayout(date_box, 1)
        outer.addLayout(columns)
        if not record:
            outer.addWidget(field_label("Save PDF in folder *"))
            folder_row = QHBoxLayout()
            default_folder = str(Path(parent.settings.get("library_dir")) / "documents") if parent else ""
            self.folder_edit = QLineEdit(val("destination_dir", default_folder))
            folder_row.addWidget(self.folder_edit, 1)
            folder_row.addWidget(action("Browse…", self.browse_folder))
            outer.addLayout(folder_row)
        else:
            self.folder_edit = None
        self.date_error = QLabel("")
        self.date_error.setObjectName("error")
        self.date_error.hide()
        outer.addWidget(self.date_error)
        self.reference = QLineEdit(val("reference_number"))
        self.entity = QLineEdit(val("related_entity"))
        self.notes = QPlainTextEdit(val("description"))
        self.tags = QLineEdit(val("tags"))
        if record:
            details = QFormLayout()
            self.notes.setFixedHeight(60)
            details.addRow("Reference", self.reference)
            details.addRow("Person or company", self.entity)
            details.addRow("Notes", self.notes)
            details.addRow("Tags", self.tags)
            outer.addLayout(details)
        outer.addSpacing(12)
        controls = QHBoxLayout()
        controls.addStretch()
        controls.addWidget(action("Cancel  Esc", self.reject))
        save = action("Save  Ctrl+↵", self.validate, primary=True)
        controls.addWidget(save)
        outer.addLayout(controls)
        shortcut = QAction(self)
        shortcut.setShortcut(QKeySequence("Ctrl+Return"))
        shortcut.triggered.connect(self.validate)
        self.addAction(shortcut)

    def browse_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose archive folder", self.folder_edit.text())
        if chosen:
            self.folder_edit.setText(chosen)

    def add_category_if_requested(self):
        if self.category.currentData() is not None:
            return
        self.create_category()

    def create_category(self):
        name, accepted = QInputDialog.getText(self, "Add category", "Category name:")
        if accepted and name.strip():
            try:
                self.library.add_category(name.strip())
                self.category.blockSignals(True)
                self.category.clear()
                for row in self.library.categories():
                    self.category.addItem(row["name"], row["id"])
                self.category.addItem("+ Add category…", None)
                self.category.setCurrentIndex(self.category.findText(name.strip()))
                self.category.blockSignals(False)
                parent = self.parentWidget()
                if parent and hasattr(parent, "category_filter"):
                    parent.category_filter.addItem(name.strip(), self.category.currentData())
                return
            except Exception as exc:
                QMessageBox.warning(self, "Category", str(exc))
        self.category.setCurrentIndex(0)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent and isinstance(parent, QMainWindow):
            self._overlay = QFrame(parent.centralWidget())
            self._overlay.setGeometry(parent.centralWidget().rect())
            self._overlay.setStyleSheet("background:rgba(40,48,70,70);")
            self._overlay.show()
            self._overlay.raise_()
            center = parent.mapToGlobal(parent.rect().center())
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def done(self, result):
        if self._overlay:
            self._overlay.deleteLater()
            self._overlay = None
        super().done(result)

    def validate(self):
        name = self.title_edit.text().strip()
        self.name_error.setText("Enter a valid document name." if not name or any(c in name for c in '<>:"/\\|?*') else "")
        self.name_error.setVisible(bool(self.name_error.text()))
        try:
            date.fromisoformat(self.date_edit.text().strip())
            self.date_error.setText("")
        except ValueError:
            self.date_error.setText("Enter a date as YYYY-MM-DD.")
        self.date_error.setVisible(bool(self.date_error.text()))
        if self.folder_edit is not None and not self.folder_edit.text().strip():
            self.date_error.setText("Choose a folder for the archived PDF.")
            self.date_error.show()
        if self.name_error.text() or self.date_error.text():
            (self.title_edit if self.name_error.text() else self.date_edit).setFocus()
            return
        self.accept()

    def values(self):
        return dict(title=self.title_edit.text().strip(), category_id=self.category.currentData(),
                    document_date=self.date_edit.text().strip(), reference_number=self.reference.text().strip(),
                    related_entity=self.entity.text().strip(), description=self.notes.toPlainText().strip(),
                    tags=self.tags.text().strip(),
                    destination_dir=self.folder_edit.text().strip() if self.folder_edit else "")


class DocumentModel(QAbstractTableModel):
    columns = ("Date ↓", "Name", "Category")

    def __init__(self):
        super().__init__()
        self.records = []

    def set_records(self, records):
        self.beginResetModel()
        self.records = list(records)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self.records[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            raw_date = r["document_date"] or r["created_at"][:10]
            try:
                readable_date = date.fromisoformat(raw_date).strftime("%b %d, %Y")
            except ValueError:
                readable_date = raw_date
            return (readable_date, r["title"], r["category"])[index.column()]
        if role == Qt.ItemDataRole.FontRole and index.column() == 1:
            from PySide6.QtGui import QFont
            font = QFont("Arial", 10)
            font.setWeight(QFont.Weight.DemiBold)
            return font
        return None


class ScaNowWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = SettingsStore()
        self.library = LibraryRepository()
        self.archive = ArchiveService(self.library, self.settings)
        self.session = DocumentSession()
        self.mock = MockBackend()
        self.naps2 = Naps2Backend(self.settings.get("naps2_path"))
        self.pool = QThreadPool.globalInstance()
        self.jobs = set()
        self.scanners = self.mock.discover()
        self.running = False
        self.active_backend = None
        self.current_page = 0
        self.preview_request = 0
        self.pending_metadata = None
        self.preview_cache = {}
        self.setWindowTitle("ScaNow 2.0")
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1366, available.width()), min(768, available.height()))
        self.setMinimumSize(940, 600)
        self.setStyleSheet(stylesheet(self.settings.get("theme")))
        self._build_shell()
        self._build_scan()
        self._build_library()
        self._build_settings()
        self._shortcuts()
        self.show_view(0)
        self.refresh_pages()
        self.refresh_scanners()
        if self.session.pages:
            self.message(f"Recovered {len(self.session.pages)} unsaved page(s).")

    def _build_shell(self):
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(56)
        nav = QVBoxLayout(rail)
        nav.setContentsMargins(8, 9, 8, 24)
        nav.setSpacing(5)
        self.nav_buttons = []
        for index, (name, label) in enumerate((("scan", "Scan workspace"), ("archive", "Archive library"))):
            item = icon_button(name, lambda i=index: self.show_view(i), label, nav=True)
            nav.addWidget(item)
            self.nav_buttons.append(item)
        nav.addStretch()
        item = icon_button("settings", lambda: self.show_view(2), "Settings", nav=True)
        nav.addWidget(item)
        self.nav_buttons.append(item)
        self.stack = QStackedWidget()
        layout.addWidget(rail)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Ready")

    def _shortcuts(self):
        for text, key, slot in (("Scan", "Ctrl+Shift+S", self.start_scan),
                                 ("Save to archive", "Ctrl+S", self.save_document),
                                 ("New document", "Ctrl+N", self.new_document),
                                 ("Find documents", "Ctrl+F", self.focus_search)):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(lambda checked=False, handler=slot: handler())
            self.addAction(action)

    def message(self, text, error=False):
        self.statusBar().showMessage(text, 12000 if error else 8000)
        if error:
            QMessageBox.warning(self, "ScaNow", text)

    def run_job(self, operation, success, failure=None):
        job = Job(operation)
        job.setAutoDelete(False)
        self.jobs.add(job)
        def complete(result):
            try:
                success(result)
            finally:
                self.jobs.discard(job)
        def fail(error):
            try:
                (failure or (lambda text: self.message(text, True)))(error)
            finally:
                self.jobs.discard(job)
        job.signals.done.connect(complete)
        job.signals.failed.connect(fail)
        self.pool.start(job)

    def show_view(self, index):
        self.stack.setCurrentIndex(index)
        for number, control in enumerate(self.nav_buttons):
            control.setProperty("active", number == index)
            control.style().unpolish(control)
            control.style().polish(control)
        if index == 1:
            self.refresh_library()

    def focus_search(self):
        self.show_view(1)
        self.search.setFocus()

    def remember_scanner(self):
        if self.scanner_select.currentData():
            self.settings.set(default_scanner=self.scanner_select.currentData())

    def refresh_scanners(self):
        if self.running:
            return
        self.scan_status.setText("Searching for scanners…")
        self.statusBar().showMessage("Searching for scanners…")
        driver = self.settings.get("driver")
        drivers = (driver,) if driver in ("twain", "wia") else ("twain", "wia")
        self.run_job(lambda: self.naps2.discover(drivers), self._scanners_found)

    def _scanners_found(self, discovered):
        unique = {}
        for scanner in discovered + self.mock.discover():
            unique.setdefault(scanner.name.lower(), scanner)
        self.scanners = list(unique.values())
        preferred = self.settings.get("default_scanner")
        self.scanner_select.blockSignals(True)
        self.scanner_select.clear()
        for scanner in self.scanners:
            self.scanner_select.addItem(f"{scanner.name} ({scanner.driver.upper()})", f"{scanner.driver}|{scanner.name}")
        selected = self.scanner_select.findData(preferred)
        self.scanner_select.setCurrentIndex(max(0, selected))
        self.scanner_select.blockSignals(False)
        count = sum(not scanner.mock for scanner in self.scanners)
        self.scan_status.setText(f"{count} physical scanner(s) ready" if count else "Mock scanner ready · No physical scanner detected")
        self.scanner_status_dot.setStyleSheet("color:#19965D; font-size:11pt" if self.scanners else
                                              "color:#C9362C; font-size:11pt")
        self.scanner_select.setToolTip(self.scan_status.text())
        self.statusBar().showMessage(self.scan_status.text(), 8000)

    def selected_scanner(self):
        key = self.scanner_select.currentData()
        return next((s for s in self.scanners if f"{s.driver}|{s.name}" == key), None)

    def start_scan(self, replace=None):
        if self.running:
            return
        scanner = self.selected_scanner()
        if scanner is None:
            self.message("Select a scanner and try again.", True)
            return
        self.settings.set(source=self.source.currentData(), dpi=self.dpi.currentData(),
                          color=self.color.currentData(), paper=self.paper.currentData(),
                          deskew=self.deskew.isChecked())
        options = ScanOptions(scanner=scanner, source=self.source.currentData(), dpi=self.dpi.currentData(),
                              color=self.color.currentData(), paper=self.paper.currentData(),
                              deskew=self.deskew.isChecked())
        backend = self.mock if scanner.mock else self.naps2
        self.active_backend = backend
        self.running = True
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.scan_status.setText("Scanning…")
        def operation():
            with staging_directory(self.session.directory) as directory:
                path = Path(directory) / "scan.pdf"
                backend.scan(options, path)
                return self.session.import_pdf(path, at=replace, replace=1 if replace is not None else 0,
                                               duplex=options.source == "duplex")
        self.run_job(operation, self._scan_complete, self._scan_failed)

    def cancel_scan(self):
        if self.active_backend:
            self.active_backend.cancel()
            self.scan_status.setText("Canceling…")

    def _scan_complete(self, pages):
        self._end_scan()
        self.refresh_pages()
        self.message(f"Added {len(pages)} page(s).")

    def _scan_failed(self, error):
        self._end_scan()
        self.message(error or "Scanning failed. Previously scanned pages were kept.", True)

    def _end_scan(self):
        self.running = False
        self.active_backend = None
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.cancel_button.hide()
        self.scan_status.setText("Ready")

    def import_pdf(self):
        if self.running:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Add PDF pages", "", "PDF files (*.pdf)")
        if path:
            self.running = True
            self.scan_status.setText("Importing PDF…")
            self.run_job(lambda: self.session.import_pdf(Path(path)),
                         lambda pages: (setattr(self, "running", False), self.scan_status.setText("Ready"),
                                        self.refresh_pages(), self.message(f"Added {len(pages)} page(s).")),
                         lambda error: (setattr(self, "running", False), self.scan_status.setText("Import failed"),
                                        self.message(error, True)))

    def refresh_pages(self):
        self.preview_cache.clear()
        self.thumbnails.blockSignals(True)
        self.thumbnails.clear()
        for number, page in enumerate(self.session.pages):
            item = QListWidgetItem(str(number + 1))
            try:
                item.setIcon(QIcon(str(self.session.preview_path(page, 100))))
            except Exception:
                logging.exception("Page thumbnail failed")
            item.setData(Qt.ItemDataRole.UserRole, page.id)
            item.setSizeHint(QSize(108, 152))
            self.thumbnails.addItem(item)
        count = len(self.session.pages)
        size = sum((self.session.directory / p.original).stat().st_size for p in self.session.pages)
        size_label = f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.0f} KB"
        format_name = self.paper.currentText() if count and self.paper.currentData() != "auto" else ""
        self.page_count.setText(f"{count} {'page' if count == 1 else 'pages'}" +
                                (f" · {format_name} · {size_label}" if format_name else f" · {size_label}" if count else ""))
        self.position_label.setText(f"{min(self.current_page + 1, count) if count else 0} of {count}")
        self.document_name.setText("Untitled scan" if not self.session.source_document_id else
                                   (self.library.get(self.session.source_document_id) or {"title": "Untitled scan"})["title"])
        self.save_button.setEnabled(bool(count))
        self.export_button.setEnabled(bool(count))
        for control in self.page_actions:
            control.setEnabled(bool(count))
        self.scan_button.setText("Scan page")
        self.thumbnails.blockSignals(False)
        if self.session.pages:
            row = min(self.current_page, len(self.session.pages) - 1)
            self.thumbnails.setCurrentRow(row)
            self.thumbnails.item(row).setSelected(True)
            self.sync_selection()
            self.show_page()
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Scan a page or import a PDF to begin")
            self.preview.setStyleSheet("background:transparent; color:#647083")
            self.preview.setFixedSize(270, 80)
            self.preview.graphicsEffect().setEnabled(False)
            self.zoom_label.setText("Fit")

    def select_page(self, index):
        if index < 0 or index >= len(self.session.pages):
            return
        self.current_page = index
        self.show_page()

    def sync_selection(self):
        self.session.selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.thumbnails.selectedItems()}

    def show_page(self):
        if not self.session.pages:
            return
        page = self.session.pages[self.current_page]
        if page.id not in self.preview_cache:
            self.preview_cache[page.id] = QPixmap(str(self.session.preview_path(page, 1200)))
        pix = self.preview_cache[page.id]
        original_width = pix.width()
        available = self.paper_scroll.viewport().size() - QSize(42, 30)
        if self.zoom_scale == 0:
            pix = pix.scaled(available, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        elif self.zoom_scale == -1:
            pix = pix.scaledToWidth(max(200, available.width()), Qt.TransformationMode.SmoothTransformation)
        else:
            pix = pix.scaled(int(pix.width() * self.zoom_scale), int(pix.height() * self.zoom_scale),
                             Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.display_scale = pix.width() / original_width if original_width else 1
        self.zoom_label.setText(f"{round(self.display_scale * 100)}%")
        self.preview.setText("")
        self.preview.setStyleSheet("background:white")
        self.preview.graphicsEffect().setEnabled(True)
        self.preview.setFixedSize(pix.size())
        self.preview.setPixmap(pix)
        self.position_label.setText(f"{self.current_page + 1} of {len(self.session.pages)}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview") and self.session.pages and self.zoom_scale <= 0:
            QTimer.singleShot(0, self.show_page)

    def set_zoom(self, scale):
        self.zoom_scale = scale
        self.show_page()

    def reorder_pages(self, parent, start, end, destination, row):
        if self.running:
            return
        ordered_ids = [self.thumbnails.item(i).data(Qt.ItemDataRole.UserRole)
                       for i in range(self.thumbnails.count())]
        pages = {page.id: page for page in self.session.pages}
        if len(ordered_ids) == len(pages) and set(ordered_ids) == set(pages):
            self.session.checkpoint()
            current_id = self.session.pages[self.current_page].id
            self.session.pages = [pages[page_id] for page_id in ordered_ids]
            self.session.persist()
            self.current_page = ordered_ids.index(current_id)
            self.refresh_pages()

    def rotate_page(self):
        if self.running:
            return
        if self.session.selected:
            self.session.rotate(90)
            self.refresh_pages()

    def crop_page(self):
        if self.running or not self.session.pages:
            return
        page = self.session.pages[self.current_page]
        preview = QPixmap(str(self.session.preview_path(page, 1200)))
        dialog = CropDialog(preview, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.bounds():
            self.session.crop_visible_page(page, dialog.bounds())
            self.refresh_pages()
            self.message("Page cropped. Use Undo to restore the previous view.")

    def delete_pages(self):
        if self.running:
            return
        if self.session.selected and QMessageBox.question(self, "Delete pages", "Remove selected pages from this scan?") == QMessageBox.StandardButton.Yes:
            self.session.delete()
            self.refresh_pages()

    def retake_page(self):
        if self.running:
            return
        if self.current_page < len(self.session.pages):
            self.start_scan(self.current_page)

    def undo(self):
        if self.running:
            return
        self.session.undo()
        self.refresh_pages()

    def redo(self):
        if self.running:
            return
        self.session.redo()
        self.refresh_pages()

    def new_document(self):
        if self.running:
            return
        if self.session.pages and QMessageBox.question(self, "New document", "Discard the current unsaved pages?") != QMessageBox.StandardButton.Yes:
            return
        self.session.reset()
        self.pending_metadata = None
        self.current_page = 0
        self.refresh_pages()

    def save_document(self):
        if not self.session.pages or self.running:
            self.message("Scan or import pages before saving.", True)
            return
        record = self.library.get(self.session.source_document_id) if self.session.source_document_id else None
        dialog = MetadataDialog(self.library, record, self, self.pending_metadata)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.pending_metadata = values
        self.running = True
        self.scan_status.setText("Saving PDF…")
        self.scan_button.setEnabled(False)
        self.run_job(lambda: self.archive.save_session(self.session, values,
                    self.session.source_document_id), self._saved, self._save_failed)

    def export_session(self):
        if not self.session.pages or self.running:
            self.message("Scan or import pages before exporting.", True)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export current PDF", "ScaNow-document.pdf", "PDF files (*.pdf)")
        if not path:
            return
        destination = Path(path)
        if destination.exists() and QMessageBox.question(self, "Replace PDF", "Replace the selected PDF?") != QMessageBox.StandardButton.Yes:
            return
        self.running = True
        self.scan_status.setText("Exporting PDF…")
        def complete(result):
            self.running = False
            self.scan_status.setText("Ready")
            self.message(f"Exported {result.name}.")
        def failed(error):
            self.running = False
            self.scan_status.setText("Export failed")
            self.message(error, True)
        self.run_job(lambda: export_pdf(self.session, destination), complete, failed)

    def _saved(self, document_id):
        self.pending_metadata = None
        self.running = False
        self.scan_button.setEnabled(True)
        self.scan_status.setText("Ready")
        self.refresh_pages()
        self.refresh_library()
        duplicate = self.library.duplicate_of(document_id)
        suffix = f" Possible duplicate of #{duplicate['id']}." if duplicate else ""
        self.message(f"Saved document #{document_id} to archive.{suffix}")

    def _save_failed(self, error):
        self.running = False
        self.scan_button.setEnabled(True)
        self.scan_status.setText("Save failed · pages kept")
        self.message(f"Could not save document: {error}", True)

    def refresh_library(self):
        if not hasattr(self, "model"):
            return
        try:
            records = self.library.documents(self.search.text().strip(),
                self.category_filter.currentData(), self.sort_filter.currentData(),
                self.date_from.text().strip(), self.date_to.text().strip(), self.date_field.currentData())
            self.model.set_records(records)
            self.result_count.setText(f"{len(records)} document(s)")
            for control in self.library_actions:
                control.setEnabled(False)
            self.preview_request += 1
            self.clear_pdf()
            self.selected_title.setText("Select a document" if records else "No documents found")
            self.details.setText("Choose a row to preview its PDF and details." if records else
                                 "Try another search or clear the filters." if self.search.text() or self.category_filter.currentData() else
                                 "Scan a document and save it to the archive to begin.")
        except Exception as exc:
            logging.exception("Archive search failed")
            self.message(f"Could not search archive: {exc}", True)

    def selected_record(self):
        row = self.table.currentIndex().row()
        return self.model.records[row] if 0 <= row < len(self.model.records) else None

    def preview_selected(self):
        self.preview_request += 1
        request = self.preview_request
        record = self.selected_record()
        for control in self.library_actions:
            control.setEnabled(record is not None)
        self.clear_pdf()
        self.pdf_page_label.setText("0 / 0")
        if not record:
            self.selected_title.setText("Select a document")
            self.details.setText("Choose a row to preview its PDF and details.")
            return
        path = Path(record["file_path"])
        self.selected_title.setText(record["title"])
        raw_date = record["document_date"] or record["created_at"][:10]
        try:
            readable_date = date.fromisoformat(raw_date).strftime("%b %d, %Y")
        except ValueError:
            readable_date = raw_date
        self.details.setText(f"{record['category']} · {record['reference_number'] or 'No reference'} · {readable_date}\n"
                             f"Related: {record['related_entity'] or '—'} · {record['page_count']} page(s)")
        if path.is_file():
            self.details.setText(self.details.text() + "\nLoading preview…")
            self.run_job(path.read_bytes,
                         lambda data: self.load_pdf_preview(request, record["id"], data),
                         lambda error: self.preview_error(request, error))
        else:
            self.details.setText(self.details.text() + "\nPDF missing. Use Locate in the document menu.")

    def load_pdf_preview(self, request, document_id, data):
        selected = self.selected_record()
        if request != self.preview_request or not selected or selected["id"] != document_id:
            return
        self.pdf_buffer = QBuffer(self)
        self.pdf_buffer.setData(data)
        self.pdf_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.pdf.load(self.pdf_buffer)
        if self.pdf.pageCount() == 0:
            self.pdf_page_label.setText("0 / 0")
            self.details.setText(self.details.text().replace("Loading preview…", "Preview unavailable or invalid PDF."))
            return
        self.pdf_page_label.setText(f"1 / {self.pdf.pageCount()}")
        self.details.setText(self.details.text().replace("\nLoading preview…", ""))
        QTimer.singleShot(50, self.pdf_fit)

    def preview_error(self, request, error):
        if request == self.preview_request:
            self.details.setText(self.details.text().replace("Loading preview…", f"Preview unavailable: {error}"))

    def clear_pdf(self):
        self.pdf.close()
        if self.pdf_buffer:
            self.pdf_buffer.close()
            self.pdf_buffer.deleteLater()
            self.pdf_buffer = None

    def pdf_fit(self):
        if self.pdf.pageCount():
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)

    def change_pdf_page(self, offset):
        count = self.pdf.pageCount()
        if not count:
            return
        navigator = self.pdf_view.pageNavigator()
        page = max(0, min(count - 1, navigator.currentPage() + offset))
        navigator.jump(page, QPointF(0, 0), navigator.currentZoom())
        self.pdf_page_label.setText(f"{page + 1} / {count}")

    def pdf_zoom(self, factor):
        if self.pdf.pageCount():
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(max(.25, min(4, self.pdf_view.zoomFactor() * factor)))

    def open_selected(self):
        record = self.selected_record()
        if record and Path(record["file_path"]).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(record["file_path"]))
        elif record:
            self.message("The PDF is missing. Use Locate in the document menu to reconnect it.", True)

    def library_menu_at_button(self):
        sender = self.sender()
        point = sender.mapToGlobal(sender.rect().bottomLeft()) if sender else self.table.mapToGlobal(self.table.rect().center())
        self.library_menu(self.table.viewport().mapFromGlobal(point))

    def library_menu(self, position):
        if not self.selected_record():
            return
        menu = QMenu(self)
        for label, slot in (("Open PDF", self.open_selected), ("Open containing folder", self.open_folder),
                            ("Export a copy", self.export_copy), ("Open in workspace", self.open_workspace),
                            ("Edit metadata", self.edit_selected), ("Locate missing PDF", self.locate_file),
                            ("Remove from archive index", self.remove_index),
                            ("Delete managed PDF", self.delete_managed)):
            menu.addAction(label, slot)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def open_folder(self):
        record = self.selected_record()
        if record:
            folder = Path(record["file_path"]).parent
            if folder.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def export_copy(self):
        record = self.selected_record()
        if not record or not Path(record["file_path"]).is_file():
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Export PDF copy", f"{record['title']}.pdf", "PDF files (*.pdf)")
        if destination:
            target = Path(destination)
            if target.exists() and QMessageBox.question(self, "Replace copy", "Replace the selected export file?") != QMessageBox.StandardButton.Yes:
                return
            try:
                shutil.copy2(record["file_path"], target)
                self.message(f"Exported {target.name}.")
            except OSError as exc:
                self.message(str(exc), True)

    def open_workspace(self):
        if self.running:
            return
        record = self.selected_record()
        if not record or not Path(record["file_path"]).is_file():
            return
        if self.session.pages and QMessageBox.question(self, "Open in workspace", "Discard the current unsaved pages?") != QMessageBox.StandardButton.Yes:
            return
        self.clear_pdf()
        self.session.reset()
        self.running = True
        self.run_job(lambda: self.session.import_pdf(Path(record["file_path"])),
                     lambda pages: self._opened_workspace(record["id"]),
                     lambda error: (setattr(self, "running", False), self.message(error, True)))

    def _opened_workspace(self, document_id):
        self.running = False
        self.pending_metadata = None
        self.session.source_document_id = document_id
        self.session.persist()
        self.current_page = 0
        self.refresh_pages()
        self.show_view(0)
        self.message("PDF opened for page editing. Saving will replace its archive copy.")

    def edit_selected(self):
        record = self.selected_record()
        if not record:
            return
        dialog = MetadataDialog(self.library, record, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.values()
            try:
                self.library.update_metadata(record["id"], values["title"], values["category_id"],
                    values["description"], values["tags"], values["reference_number"],
                    values["related_entity"], values["document_date"])
                self.refresh_library()
                self.message("Document details updated.")
            except Exception as exc:
                self.message(str(exc), True)

    def locate_file(self):
        record = self.selected_record()
        if not record:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Locate PDF", "", "PDF files (*.pdf)")
        if path:
            try:
                if self.library.by_path(path):
                    raise ValueError("That PDF is already in the archive.")
                self.library.relink(record["id"], Path(path))
                self.refresh_library()
            except Exception as exc:
                self.message(str(exc), True)

    def remove_index(self):
        record = self.selected_record()
        if record and QMessageBox.question(self, "Remove from archive", "Remove this record from the archive index? The PDF will stay on disk.") == QMessageBox.StandardButton.Yes:
            self.library.delete(record["id"])
            self.refresh_library()
            self.message("Record removed. PDF kept on disk.")

    def delete_managed(self):
        record = self.selected_record()
        if not record:
            return
        path = Path(record["file_path"])
        if path.parent.resolve() != self.archive.documents_dir.resolve():
            self.message("Only PDFs in the managed archive can be deleted here. Remove this index record instead.", True)
            return
        if QMessageBox.question(self, "Delete managed PDF", "Move this PDF to the archive's recovery folder and remove its index record?") != QMessageBox.StandardButton.Yes:
            return
        recovery = self.archive.documents_dir / "recovery"
        recovery.mkdir(exist_ok=True)
        target = recovery / f"{record['id']}-{path.name}"
        if target.exists():
            self.message("A recovery copy already exists; deletion was canceled.", True)
            return
        try:
            if path.exists():
                shutil.move(str(path), str(target))
            self.library.delete(record["id"])
            self.refresh_library()
            self.message("PDF moved to recovery folder and removed from index.")
        except Exception as exc:
            if target.exists():
                shutil.move(str(target), str(path))
            self.message(str(exc), True)

    def save_settings(self):
        if self.running:
            return
        if not self.library_path.text().strip():
            self.message("Choose an archive folder.", True)
            return
        new_root = Path(self.library_path.text().strip())
        old_root = Path(self.settings.get("library_dir"))
        if new_root != old_root and self.library.documents() and QMessageBox.question(self, "Move archive", "Copy managed PDFs to the new archive folder and update their paths?") != QMessageBox.StandardButton.Yes:
            return
        try:
            if new_root != old_root:
                source = old_root / "documents"
                target = new_root / "documents"
                target.mkdir(parents=True, exist_ok=True)
                with closing(self.library.connect()) as con, con:
                    records = con.execute("SELECT id,file_path FROM documents").fetchall()
                    for record in records:
                        original = Path(record["file_path"])
                        if original.parent == source:
                            destination = target / original.name
                            if destination.exists():
                                raise FileExistsError(f"Archive migration would overwrite {destination.name}.")
                            shutil.copy2(original, destination)
                            con.execute("UPDATE documents SET file_path=? WHERE id=?", (str(destination), record["id"]))
            self.settings.set(library_dir=str(new_root), naps2_path=self.naps2_path.text().strip(),
                              driver=self.driver.currentData(), theme=self.theme.currentData())
            self.naps2 = Naps2Backend(self.settings.get("naps2_path"))
            self.setStyleSheet(stylesheet(self.settings.get("theme")))
            self._apply_pdf_background()
            self.refresh_scanners()
            self.message("Settings saved.")
        except Exception as exc:
            self.message(str(exc), True)

    def manage_categories(self):
        names = [r["name"] for r in self.library.categories()]
        action, chosen = QInputDialog.getItem(self, "Categories", "Action:", ["Add", "Rename", "Delete"], 0, False)
        if not chosen:
            return
        if action == "Add":
            new, accepted = QInputDialog.getText(self, "Add category", "New category name:")
            if accepted and new.strip():
                try:
                    self.library.add_category(new.strip())
                except Exception as exc:
                    self.message(str(exc), True)
        else:
            choice, ok = QInputDialog.getItem(self, "Categories", "Category:", names, 0, False)
            if not ok:
                return
            record = next(r for r in self.library.categories() if r["name"] == choice)
            if action == "Delete":
                if QMessageBox.question(self, "Delete category", "Move its documents to Uncategorized and delete this category?") == QMessageBox.StandardButton.Yes:
                    try:
                        self.library.delete_category(record["id"])
                    except Exception as exc:
                        self.message(str(exc), True)
            else:
                new, accepted = QInputDialog.getText(self, "Rename category", "New name:", text=choice)
                if accepted and new.strip():
                    try:
                        self.library.rename_category(record["id"], new.strip())
                    except Exception as exc:
                        self.message(str(exc), True)
        self.category_filter.clear()
        self.category_filter.addItem("All categories", None)
        for record in self.library.categories():
            self.category_filter.addItem(record["name"], record["id"])

    def check_database(self):
        self.message(f"Database integrity: {self.library.integrity_check()}")

    def create_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Create backup", "ScaNow-backup.zip", "ZIP files (*.zip)")
        if path:
            self.running = True
            self.run_job(lambda: self.archive.backup(path),
                         lambda result: (setattr(self, "running", False), self.message(f"Backup saved to {result}.")),
                         lambda error: (setattr(self, "running", False), self.message(error, True)))

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", "", "ZIP files (*.zip)")
        if not path:
            return
        if QMessageBox.question(self, "Restore backup", "Restore this backup? Current metadata and managed PDFs will be moved to recovery copies first.") != QMessageBox.StandardButton.Yes:
            return
        self.running = True
        self.run_job(lambda: self.archive.restore(path),
                     lambda recovery: (setattr(self, "running", False), self.refresh_library(),
                                       self.message(f"Backup restored. Previous PDFs: {recovery}")),
                     lambda error: (setattr(self, "running", False), self.message(error, True)))

    def closeEvent(self, event):
        if self.running:
            self.message("Wait for scanning to finish or cancel it before closing.")
            event.ignore()
        else:
            event.accept()

    # Reference layout: compact top controls, page strip, paper canvas, action panel.
    def _build_scan(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        bar = QHBoxLayout(top)
        bar.setContentsMargins(14, 5, 14, 5)
        bar.setSpacing(7)
        self.scanner_status_dot = QLabel("●")
        self.scanner_status_dot.setStyleSheet("color:#9AA4B3; font-size:11pt")
        bar.addWidget(self.scanner_status_dot)
        self.scanner_select = QComboBox()
        self.scanner_select.setMinimumWidth(230)
        self.scanner_select.setMaximumWidth(300)
        self.scanner_select.addItem("Finding scanners…", None)
        self.scanner_select.currentIndexChanged.connect(self.remember_scanner)
        bar.addWidget(self.scanner_select)
        self.dpi = combo([(f"{n} dpi", n) for n in (150, 200, 300, 600)], self.settings.get("dpi"))
        self.color = combo([("Color", "color"), ("Gray", "gray"), ("B&W", "bw")], self.settings.get("color"))
        self.paper = combo([("Auto", "auto")] + [(n.upper(), n) for n in ("a4", "letter", "legal")],
                           self.settings.get("paper"))
        self.source = combo([("Flatbed", "glass"), ("ADF", "feeder"), ("Duplex", "duplex")], self.settings.get("source"))
        for control, tip in ((self.dpi, "Resolution"), (self.color, "Color mode"),
                             (self.paper, "Paper size"), (self.source, "Scan source")):
            control.setToolTip(tip)
            bar.addWidget(control)
        self.deskew = QCheckBox("Deskew")
        self.deskew.setChecked(self.settings.get("deskew"))
        self.scan_options = icon_button("more", self.scan_options_menu, "More scan and page options")
        bar.addWidget(self.scan_options)
        bar.addStretch()
        bar.addWidget(action("Import PDF", self.import_pdf))
        self.scan_button = action("Scan page", self.start_scan, primary=True, tip="Scan page (Ctrl+Shift+S)")
        bar.addWidget(self.scan_button)
        self.cancel_button = action("Cancel", self.cancel_scan)
        self.cancel_button.setEnabled(False)
        self.cancel_button.hide()
        bar.addWidget(self.cancel_button)
        outer.addWidget(top)
        outer.addSpacing(10)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(1)
        strip = QFrame()
        strip.setObjectName("thumbnailPanel")
        strip.setMinimumWidth(132)
        strip.setMaximumWidth(166)
        strip_layout = QVBoxLayout(strip)
        strip_layout.setContentsMargins(6, 8, 6, 10)
        strip_layout.setSpacing(6)
        self.thumbnails = SmoothPageList()
        self.thumbnails.setObjectName("thumbnails")
        self.thumbnails.setViewMode(QListWidget.ViewMode.ListMode)
        self.thumbnails.setFlow(QListWidget.Flow.TopToBottom)
        self.thumbnails.setWrapping(False)
        self.thumbnails.setIconSize(QSize(86, 116))
        self.thumbnails.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnails.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.thumbnails.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.thumbnails.setDragEnabled(True)
        self.thumbnails.setAcceptDrops(True)
        self.thumbnails.setDropIndicatorShown(True)
        self.thumbnails.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.thumbnails.currentRowChanged.connect(self.select_page)
        self.thumbnails.itemSelectionChanged.connect(self.sync_selection)
        self.thumbnails.model().rowsMoved.connect(self.reorder_pages)
        self.thumbnails.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnails.customContextMenuRequested.connect(self.page_context_menu)
        strip_layout.addWidget(self.thumbnails, 1)
        strip_layout.addWidget(action("+ Add pages", self.import_pdf, kind="quiet"))
        split.addWidget(strip)

        canvas = QFrame()
        canvas.setObjectName("documentCanvas")
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(10, 10, 10, 12)
        canvas_layout.setSpacing(8)
        self.paper_scroll = SmoothPaperScroll()
        self.paper_scroll.setWidgetResizable(True)
        self.paper_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.paper_scroll.setObjectName("paperScroll")
        self.paper_surface = QFrame()
        self.paper_surface.setObjectName("documentCanvas")
        paper_layout = QVBoxLayout(self.paper_surface)
        paper_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        paper_layout.setContentsMargins(14, 14, 14, 8)
        self.preview = QLabel("Scan a page or import a PDF to begin")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("paper")
        self.preview.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        shadow = QGraphicsDropShadowEffect(self.preview)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(44, 55, 76, 42))
        self.preview.setGraphicsEffect(shadow)
        paper_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignCenter)
        self.paper_scroll.setWidget(self.paper_surface)
        floating = QFrame()
        floating.setObjectName("floatingTools")
        editing = QHBoxLayout(floating)
        editing.setContentsMargins(6, 2, 7, 2)
        editing.setSpacing(2)
        editing.addWidget(heading("Rotate", True))
        self.page_actions = [icon_button("rotate_left", lambda: self.rotate_page_by(-90), "Rotate left"),
                             icon_button("rotate_right", lambda: self.rotate_page_by(90), "Rotate right"),
                             action("Crop", self.crop_page, kind="quiet"),
                             action("Delete page", self.delete_pages, kind="danger")]
        self.page_actions[-1].setMinimumWidth(94)
        for control in self.page_actions:
            editing.addWidget(control)
        editing.addWidget(line())
        editing.addWidget(icon_button("left", lambda: self.change_page(-1), "Previous page"))
        self.position_label = heading("0 of 0", True)
        editing.addWidget(self.position_label)
        editing.addWidget(icon_button("right", lambda: self.change_page(1), "Next page"))
        editing.addWidget(line())
        editing.addWidget(action("−", lambda: self.zoom_step(.8), kind="quiet", tip="Zoom out"))
        self.zoom_label = heading("Fit", True)
        editing.addWidget(self.zoom_label)
        editing.addWidget(action("+", lambda: self.zoom_step(1.25), kind="quiet", tip="Zoom in"))
        fit = action("Fit", self.zoom_menu, kind="quiet", tip="Fit page or width")
        editing.addWidget(fit)
        float_row = QHBoxLayout()
        float_row.addStretch()
        float_row.addWidget(floating)
        float_row.addStretch()
        canvas_layout.addWidget(self.paper_scroll, 1)
        canvas_layout.addLayout(float_row)
        split.addWidget(canvas)

        panel = QFrame()
        panel.setObjectName("actionPanel")
        panel.setMinimumWidth(188)
        panel.setMaximumWidth(310)
        info = QVBoxLayout(panel)
        info.setContentsMargins(16, 16, 16, 12)
        info.setSpacing(7)
        self.document_name = heading("Untitled scan")
        info.addWidget(self.document_name)
        self.page_count = heading("0 pages", True)
        info.addWidget(self.page_count)
        info.addSpacing(12)
        self.save_button = action("Save to Archive", self.save_document, primary=True)
        info.addWidget(self.save_button)
        note = heading("Stores it in your library with searchable details.", True)
        note.setWordWrap(True)
        info.addWidget(note)
        info.addSpacing(3)
        self.export_button = action("Export PDF…", self.export_session)
        info.addWidget(self.export_button)
        note = heading("Saves a copy anywhere you choose. Not added to the library.", True)
        note.setWordWrap(True)
        info.addWidget(note)
        info.addStretch()
        split.addWidget(panel)
        split.setSizes([132, 820, 260])
        outer.addWidget(split, 1)
        outer.addSpacing(12)
        self.scan_status = heading("Ready", True)
        self.zoom_scale = 0
        self.zoom_mode = "page"
        self.stack.addWidget(page)

    def scan_options_menu(self):
        menu = QMenu(self)
        for label, slot in (("Refresh scanners", self.refresh_scanners), ("New document", self.new_document),
                            ("Undo", self.undo), ("Redo", self.redo), ("Retake selected page", self.retake_page)):
            menu.addAction(label, slot)
        menu.addSeparator()
        menu.addAction("Deskew scans", lambda: self.deskew.setChecked(not self.deskew.isChecked())).setCheckable(True)
        menu.actions()[-1].setChecked(self.deskew.isChecked())
        menu.exec(self.scan_options.mapToGlobal(self.scan_options.rect().bottomLeft()))

    def rotate_page_by(self, degrees):
        if not self.running and self.session.selected:
            self.session.rotate(degrees)
            self.refresh_pages()

    def rotate_menu(self):
        menu = QMenu(self)
        menu.addAction("Rotate left", lambda: self.rotate_page_by(-90))
        menu.addAction("Rotate right", lambda: self.rotate_page_by(90))
        sender = self.sender()
        menu.exec(sender.mapToGlobal(sender.rect().bottomLeft()))

    def page_context_menu(self, position):
        item = self.thumbnails.itemAt(position)
        if item is None:
            return
        self.thumbnails.setCurrentItem(item)
        item.setSelected(True)
        self.sync_selection()
        menu = QMenu(self)
        menu.addAction("Rotate left", lambda: self.rotate_page_by(-90))
        menu.addAction("Rotate right", lambda: self.rotate_page_by(90))
        menu.addAction("Crop page", self.crop_page)
        menu.addAction("Delete page", self.delete_pages)
        menu.exec(self.thumbnails.viewport().mapToGlobal(position))

    def change_page(self, offset):
        if self.session.pages:
            self.thumbnails.setCurrentRow(max(0, min(len(self.session.pages) - 1, self.current_page + offset)))

    def zoom_step(self, factor):
        self.set_zoom(max(.25, min(3, getattr(self, "display_scale", 1) * factor)))

    def zoom_menu(self):
        menu = QMenu(self)
        menu.addAction("Fit page", lambda: self.set_zoom(0))
        menu.addAction("Fit width", lambda: self.set_zoom(-1))
        menu.addAction("100%", lambda: self.set_zoom(1))
        menu.exec(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))

    # Reference layout: one search bar, dense table, persistent document preview.
    def _build_library(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        filters = QHBoxLayout(top)
        filters.setContentsMargins(14, 6, 14, 6)
        filters.setSpacing(7)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, reference, company…    Ctrl+F")
        self.search.setMinimumWidth(210)
        self.search.setMaximumWidth(450)
        filters.addWidget(self.search, 1)
        self.category_filter = combo([("Category: All", None)] +
                                     [(r["name"], r["id"]) for r in self.library.categories()])
        filters.addWidget(self.category_filter)
        self.date_filter = combo([("Date: All", "all"), ("This year", "year"), ("This month", "month"),
                                  ("Custom…", "custom")])
        self.date_filter.currentIndexChanged.connect(self.apply_date_filter)
        filters.addWidget(self.date_filter)
        more = icon_button("more", self.advanced_filters, "Sort and advanced filters")
        filters.addWidget(more)
        self.sort_filter = combo([("Newest", "newest"), ("Oldest", "oldest"),
                                  ("Name A–Z", "az"), ("Name Z–A", "za"),
                                  ("Category A–Z", "category_az"), ("Category Z–A", "category_za"),
                                  ("Reference A–Z", "reference_az"), ("Reference Z–A", "reference_za"),
                                  ("Largest", "size")])
        self.date_from = QLineEdit()
        self.date_to = QLineEdit()
        self.date_field = combo([("Document date", "document"), ("Archived date", "archived")])
        filters.addStretch()
        self.result_count = heading("0 documents", True)
        filters.addWidget(self.result_count)
        outer.addWidget(top)
        self.search_delay = QTimer(self)
        self.search_delay.setSingleShot(True)
        self.search_delay.setInterval(250)
        self.search_delay.timeout.connect(self.refresh_library)
        for field in (self.search, self.date_from, self.date_to):
            field.textChanged.connect(lambda: self.search_delay.start())
        self.date_field.currentIndexChanged.connect(self.refresh_library)
        self.category_filter.currentIndexChanged.connect(self.refresh_library)
        self.sort_filter.currentIndexChanged.connect(self.refresh_library)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(1)
        self.model = DocumentModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(2, 190)
        self.table.horizontalHeader().sectionClicked.connect(self.sort_by_column)
        self.table.doubleClicked.connect(self.open_selected)
        self.table.selectionModel().selectionChanged.connect(self.preview_selected)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.library_menu)
        split.addWidget(self.table)

        details = QFrame()
        details.setObjectName("libraryPreview")
        details.setMinimumWidth(240)
        details.setMaximumWidth(370)
        right = QVBoxLayout(details)
        right.setContentsMargins(16, 16, 16, 12)
        right.setSpacing(8)
        self.pdf = QPdfDocument(self)
        self.pdf_buffer = None
        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self.pdf)
        self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
        self.pdf_view.setFixedHeight(205)
        self.pdf_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pdf_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._apply_pdf_background()
        right.addWidget(self.pdf_view)
        pdf_tools = QHBoxLayout()
        pdf_tools.addStretch()
        pdf_tools.addWidget(icon_button("left", lambda: self.change_pdf_page(-1), "Previous PDF page"))
        self.pdf_page_label = heading("0 / 0", True)
        pdf_tools.addWidget(self.pdf_page_label)
        pdf_tools.addWidget(icon_button("right", lambda: self.change_pdf_page(1), "Next PDF page"))
        pdf_tools.addWidget(action("−", lambda: self.pdf_zoom(.8), kind="quiet"))
        pdf_tools.addWidget(action("Fit", self.pdf_fit, kind="quiet"))
        pdf_tools.addWidget(action("+", lambda: self.pdf_zoom(1.25), kind="quiet"))
        pdf_tools.addStretch()
        right.addLayout(pdf_tools)
        title_row = QHBoxLayout()
        self.selected_title = heading("Select a document")
        title_row.addWidget(self.selected_title, 1)
        title_row.addWidget(icon_button("more", self.library_menu_at_button, "More document actions"))
        right.addLayout(title_row)
        self.details = QLabel("Select a document to preview")
        self.details.setObjectName("meta")
        self.details.setWordWrap(True)
        self.details.setMinimumHeight(45)
        right.addWidget(self.details)
        self.open_button = action("Open", self.open_selected, primary=True)
        right.addWidget(self.open_button)
        row = QHBoxLayout()
        folder_button = action("Show in folder", self.open_folder)
        copy_button = action("Export copy", self.export_copy)
        row.addWidget(folder_button)
        row.addWidget(copy_button)
        right.addLayout(row)
        row = QHBoxLayout()
        edit_button = action("Edit details", self.edit_selected)
        delete_button = action("Delete…", self.delete_selected, kind="danger")
        row.addWidget(edit_button)
        row.addWidget(delete_button)
        right.addLayout(row)
        self.library_actions = (self.open_button, folder_button, copy_button, edit_button, delete_button)
        for control in self.library_actions:
            control.setEnabled(False)
        right.addStretch()
        split.addWidget(details)
        split.setSizes([830, 300])
        outer.addWidget(split, 1)
        self.stack.addWidget(page)

    def sort_by_column(self, column):
        options = {0: ("newest", "oldest"), 1: ("az", "za"),
                   2: ("category_az", "category_za")}
        pair = options[column]
        choice = pair[1] if self.sort_filter.currentData() == pair[0] else pair[0]
        self.sort_filter.setCurrentIndex(self.sort_filter.findData(choice))

    def apply_date_filter(self):
        choice = self.date_filter.currentData()
        today = date.today()
        if choice == "custom":
            self.advanced_filters()
            return
        self.date_from.setText(today.replace(day=1).isoformat() if choice == "month" else
                               today.replace(month=1, day=1).isoformat() if choice == "year" else "")
        self.date_to.setText(today.isoformat() if choice in ("month", "year") else "")

    def advanced_filters(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Search filters")
        form = QFormLayout(dialog)
        sorting = combo([(self.sort_filter.itemText(i), self.sort_filter.itemData(i))
                         for i in range(self.sort_filter.count())], self.sort_filter.currentData())
        date_field = combo([("Document date", "document"), ("Archived date", "archived")],
                           self.date_field.currentData())
        from_edit = QLineEdit(self.date_from.text())
        to_edit = QLineEdit(self.date_to.text())
        from_edit.setPlaceholderText("YYYY-MM-DD")
        to_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Sort", sorting)
        form.addRow("Date field", date_field)
        form.addRow("From", from_edit)
        form.addRow("To", to_edit)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        controls.rejected.connect(dialog.reject)
        form.addRow(controls)
        dialog.exec()
        self.sort_filter.setCurrentIndex(self.sort_filter.findData(sorting.currentData()))
        self.date_field.setCurrentIndex(self.date_field.findData(date_field.currentData()))
        self.date_from.setText(from_edit.text().strip())
        self.date_to.setText(to_edit.text().strip())
        self.refresh_library()

    def delete_selected(self):
        record = self.selected_record()
        if not record:
            return
        if Path(record["file_path"]).parent.resolve() == self.archive.documents_dir.resolve():
            self.delete_managed()
        else:
            self.remove_index()

    def _apply_pdf_background(self):
        if not hasattr(self, "pdf_view"):
            return
        background = "#171B22" if self.settings.get("theme") == "dark" else "#E9EDF2"
        self.pdf_view.setStyleSheet(f"QPdfView, QPdfView QWidget {{ background:{background}; }}")
        palette = self.pdf_view.palette()
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base,
                     QPalette.ColorRole.Dark, QPalette.ColorRole.Mid):
            palette.setColor(role, QColor(background))
        self.pdf_view.setPalette(palette)
        self.pdf_view.viewport().setPalette(palette)

    def _build_settings(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(20, 7, 20, 7)
        top_layout.addWidget(heading("Settings"))
        top_layout.addStretch()
        top_layout.addWidget(action("Save settings", self.save_settings, primary=True))
        page_layout.addWidget(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 22, 24, 26)
        body.setSpacing(10)
        content.setMaximumWidth(800)
        body.addWidget(heading("General"))
        body.addWidget(heading("ScaNow keeps scans and document metadata on this computer.", True))
        body.addSpacing(9)
        body.addWidget(line())
        body.addSpacing(8)
        body.addWidget(heading("Scanner"))
        body.addWidget(heading("Choose how NAPS2 discovers connected scanners. Scan options are in the workspace toolbar.", True))
        self.driver = combo([("Auto (TWAIN then WIA)", "auto"), ("TWAIN", "twain"),
                             ("WIA", "wia")], self.settings.get("driver"))
        self.naps2_path = QLineEdit(self.settings.get("naps2_path"))
        self.naps2_path.setPlaceholderText("NAPS2.Console.exe path (auto-detect if blank)")
        scanner_form = QFormLayout()
        scanner_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        scanner_form.addRow("Scanner driver", self.driver)
        scanner_form.addRow("NAPS2 Console", self.naps2_path)
        body.addLayout(scanner_form)
        body.addWidget(action("Refresh scanners", self.refresh_scanners))
        body.addSpacing(8)
        body.addWidget(line())
        body.addSpacing(8)
        body.addWidget(heading("Archive"))
        body.addWidget(heading("Managed PDFs are stored in the folder below. Metadata is indexed locally.", True))
        self.library_path = QLineEdit(self.settings.get("library_dir"))
        archive_form = QFormLayout()
        archive_form.addRow("Archive folder", self.library_path)
        body.addLayout(archive_form)
        archive_actions = QHBoxLayout()
        archive_actions.addWidget(action("Categories", self.manage_categories))
        archive_actions.addWidget(action("Check database", self.check_database))
        archive_actions.addStretch()
        body.addLayout(archive_actions)
        body.addSpacing(8)
        body.addWidget(line())
        body.addSpacing(8)
        body.addWidget(heading("Appearance"))
        self.theme = combo([("Light", "light"), ("Dark", "dark")], self.settings.get("theme"))
        appearance_form = QFormLayout()
        appearance_form.addRow("Theme", self.theme)
        body.addLayout(appearance_form)
        body.addSpacing(8)
        body.addWidget(line())
        body.addSpacing(8)
        body.addWidget(heading("Backup and recovery"))
        body.addWidget(heading("Create a portable archive backup or restore a previous backup.", True))
        backup_actions = QHBoxLayout()
        backup_actions.addWidget(action("Create backup", self.create_backup))
        backup_actions.addWidget(action("Restore backup", self.restore_backup))
        backup_actions.addStretch()
        body.addLayout(backup_actions)
        body.addSpacing(8)
        body.addWidget(line())
        body.addSpacing(8)
        body.addWidget(heading("PDF and about"))
        body.addWidget(heading("PDF import, preview, and export run locally. ScaNow 2.0 uses NAPS2 Console for scanning.", True))
        body.addStretch()
        scroll.setWidget(content)
        page_layout.addWidget(scroll, 1)
        self.stack.addWidget(page)
