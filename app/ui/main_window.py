import asyncio
import base64
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import json
import zipfile
from pathlib import Path
import fitz
import flet as ft
from app.paths import app_data
from app.settings_store import SettingsStore
from app.scanner.base import ScanOptions, ScannerError
from app.scanner.mock_backend import MockBackend
from app.scanner.naps2_backend import Naps2Backend
from app.documents.session import DocumentSession
from app.documents.pdf_service import export_pdf
from app.database.repository import LibraryRepository


logging.basicConfig(filename=app_data() / "scanow.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
INK = "#0F172A"
MUTED = "#64748B"
ACCENT = "#2563EB"
SIDEBAR = "#1E293B"
PALE = "#EFF6FF"
BORDER = "#E2E8F0"
BACKGROUND = "#F8FAFC"
CONTENT = "#FFFFFF"


def option(key, label=None):
    return ft.DropdownOption(key=str(key), text=str(label if label is not None else key))


def title(text, size=22):
    return ft.Text(text, size=size, weight=ft.FontWeight.BOLD, color=INK)


def quiet_button_style():
    return ft.ButtonStyle(color=INK, bgcolor=CONTENT,
        shape=ft.RoundedRectangleBorder(radius=7),
        side=ft.BorderSide(1, BORDER))


class ScaNowApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "ScaNow"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(
            color_scheme_seed=ACCENT,
            color_scheme=ft.ColorScheme(primary=ACCENT, on_primary=CONTENT,
                secondary=SIDEBAR, surface=CONTENT, on_surface=INK,
                on_surface_variant=MUTED, outline=BORDER),
            font_family="Segoe UI", scaffold_bgcolor=BACKGROUND,
            canvas_color=BACKGROUND, dialog_theme=ft.DialogTheme(bgcolor=CONTENT),
            input_decoration_theme=ft.InputDecorationTheme(
                border=ft.OutlineInputBorder(side=ft.BorderSide(1, BORDER), border_radius=7),
                filled=True, fill_color=CONTENT))
        self.page.window.width = 1320
        self.page.window.height = 700
        self.page.window.min_width = 1080
        self.page.window.min_height = 620
        self.page.bgcolor = BACKGROUND
        self.page.padding = 0
        self.settings = SettingsStore()
        self.library = LibraryRepository()
        self.session = DocumentSession()
        self.mock = MockBackend()
        self.naps2 = Naps2Backend(self.settings.get("naps2_path"))
        self.scanners = []
        self.busy = False
        self._discovering = False
        self._active_backend = None
        self.active_page_id = None
        self.active_view = "scan"
        self.sidebar_expanded = True
        self.gallery = ft.ReorderableListView(expand=True, spacing=8, on_reorder=self.reorder)
        self.preview = ft.Container(expand=True, alignment=ft.Alignment.CENTER)
        self.status = ft.Text("Ready", color=MUTED, size=12)
        self.body = ft.Container(expand=True, padding=ft.Padding(16, 12, 16, 10))
        self.nav = {}
        self._build_shell()
        self.refresh_scanners()
        self.show_scan()
        if self.session.pages:
            self.message(f"Recovered {len(self.session.pages)} unsaved page(s).")

    def _build_shell(self):
        self.sidebar = ft.Column(spacing=4)
        self.sidebar_container = ft.Container(content=self.sidebar, width=200, bgcolor=SIDEBAR,
                                              padding=ft.Padding(8, 8, 8, 8))
        self._render_sidebar()
        self.page.add(ft.Row(expand=True, spacing=0, controls=[
            self.sidebar_container,
            ft.Column(expand=True, spacing=0, controls=[self.body,
                ft.Container(content=self.status, bgcolor=CONTENT,
                             border=ft.Border(top=ft.BorderSide(1, BORDER)),
                             padding=ft.Padding(20, 7, 12, 7))])]))

    def _render_sidebar(self):
        self.sidebar.controls.clear()
        self.nav.clear()
        expanded = self.sidebar_expanded
        self.sidebar_container.width = 200 if expanded else 68
        self.sidebar.controls.append(ft.Row(controls=[
            ft.Column(spacing=0, expand=True, controls=[
                ft.Text("ScaNow", size=26, weight=ft.FontWeight.BOLD, color="white"),
                ft.Text("DOCUMENT STUDIO", size=10, color="#CBD5E1")]) if expanded else ft.Container(expand=True),
            ft.IconButton(icon=ft.Icons.CHEVRON_LEFT if expanded else ft.Icons.CHEVRON_RIGHT,
                          icon_color="white", tooltip="Collapse sidebar" if expanded else "Expand sidebar",
                          on_click=lambda e: self.toggle_sidebar())]))
        self.sidebar.controls.append(ft.Container(height=22))
        for key, label, icon, handler in [
            ("scan", "Scan Workspace", ft.Icons.DOCUMENT_SCANNER, self.show_scan),
            ("library", "Document Library", ft.Icons.FOLDER_OPEN, self.show_library),
            ("settings", "Settings", ft.Icons.SETTINGS, self.show_settings)]:
            button = ft.TextButton(label if expanded else None, icon=icon,
                                   tooltip=label, on_click=lambda e, f=handler: f(),
                                   width=176 if expanded else 52,
                                   style=ft.ButtonStyle(color="white", bgcolor=ACCENT if key == self.active_view else SIDEBAR,
                                       shape=ft.RoundedRectangleBorder(radius=8)))
            self.nav[key] = button
            self.sidebar.controls.append(button)
        self.sidebar.controls.append(ft.Container(expand=True))
        if expanded:
            self.sidebar.controls.append(ft.Container(
                content=ft.Text("OFFLINE  •  PRIVATE", size=10, color="#CBD5E1"), padding=12))

    def toggle_sidebar(self):
        self.sidebar_expanded = not self.sidebar_expanded
        self._render_sidebar()
        self.page.update()

    def message(self, text, error=False):
        self.status.value = text
        self.status.color = "#B63B36" if error else MUTED
        self.page.update()

    def dialog(self, heading, content, actions):
        self.page.show_dialog(ft.AlertDialog(title=title(heading, 18), content=content,
                                             actions=actions, modal=True))

    def close_dialog(self):
        self.page.pop_dialog()

    def confirm(self, heading, text, action):
        def run(e):
            self.close_dialog()
            action()
        self.dialog(heading, ft.Text(text), [ft.TextButton("Cancel", on_click=lambda e: self.close_dialog()),
                                           ft.Button("Continue", on_click=run)])

    def switch(self, key, content):
        self.active_view = key
        self.body.content = content
        for name, button in self.nav.items():
            button.style = ft.ButtonStyle(color="white", bgcolor=ACCENT if name == key else SIDEBAR,
                                          shape=ft.RoundedRectangleBorder(radius=8))
        self.page.update()

    def refresh_scanners(self):
        if self._discovering:
            return
        self._discovering = True
        self.message("Searching for scanners…")
        asyncio.create_task(self._discover_scanners())

    async def _discover_scanners(self):
        drivers = self._driver_preference()
        try:
            found = await asyncio.to_thread(self.naps2.discover, drivers)
        except Exception:
            logging.exception("Scanner discovery failed")
            found = []
        finally:
            self._discovering = False
        # TWAIN is queried first, so a device exposed by both drivers keeps TWAIN.
        pool = self.mock.discover() + found
        seen = set()
        self.scanners = []
        for scanner in pool:
            if scanner.name.lower() in seen:
                continue
            seen.add(scanner.name.lower())
            self.scanners.append(scanner)
        self._apply_scanner_options()
        real = [s for s in self.scanners if not s.mock]
        if real:
            self.message(f"Found {len(real)} scanner device(s). Ready to scan.")
        elif self.naps2.diagnostic == "engine_missing":
            self.message("NAPS2 scanning engine is missing. Reinstall ScaNow or set its Console path in Settings. "
                         "Mock scanning remains available.", True)
        elif self.naps2.diagnostic == "driver_missing":
            self.message("No TWAIN/WIA scanner driver is available. Install the scanner manufacturer's driver, "
                         "then click Refresh. Mock scanning remains available.", True)
        elif self.naps2.diagnostic == "engine_error":
            self.message("NAPS2 could not query scanner drivers. Check its runtime and driver installation, "
                         "then click Refresh. Mock scanning remains available.", True)
        else:
            self.message("No physical scanner detected. Check power, connection, and driver installation, "
                         "then click Refresh. Mock scanning remains available.")

    def _driver_preference(self):
        driver = str(self.settings.get("driver") or "auto").lower()
        return (driver,) if driver in ("twain", "wia") else ("twain", "wia")

    def _apply_scanner_options(self):
        driver = str(self.settings.get("driver") or "auto").lower()
        pool = [s for s in self.scanners if not s.mock and (driver == "auto" or s.driver == driver)]
        pool += [s for s in self.scanners if s.mock]
        if not hasattr(self, "scanner_select"):
            return
        self.scanner_select.options = [option(f"{s.driver}|{s.name}", self._scanner_label(s)) for s in pool]
        keys = [o.key for o in self.scanner_select.options]
        preferred = self.settings.get("default_scanner")
        if preferred in keys:
            self.scanner_select.value = preferred
        elif self.scanner_select.value not in keys or self.scanner_select.value.startswith("mock|"):
            self.scanner_select.value = keys[0] if keys else None
        self.page.update()

    @staticmethod
    def _scanner_label(scanner):
        if scanner.mock:
            return "Mock scanner (sample pages)"
        return f"{scanner.name}  ({scanner.driver.upper()})"

    def selected_scanner(self):
        if not getattr(self, "scanner_select", None) or not self.scanner_select.value:
            return None
        return next((s for s in self.scanners if f"{s.driver}|{s.name}" == self.scanner_select.value), None)

    def show_scan(self):
        self.scanner_select = ft.Dropdown(label="Selected Scanner", width=285, dense=True,
            options=[option(f"{s.driver}|{s.name}", self._scanner_label(s)) for s in self.scanners],
            value=self.settings.get("default_scanner") if self.settings.get("default_scanner") in
                  [f"{s.driver}|{s.name}" for s in self.scanners] else None,
            on_select=lambda e: self.settings.set(default_scanner=self.scanner_select.value))
        self.source = ft.Dropdown(label="Scan Source", width=145, dense=True, value=self.settings.get("source"),
            options=[option("glass", "Flatbed"), option("feeder", "ADF"), option("duplex", "ADF duplex")])
        self.dpi = ft.Dropdown(label="Resolution", width=120, dense=True, value=str(self.settings.get("dpi")),
            options=[option(i, f"{i} dpi") for i in (150, 200, 300, 600)])
        self.driver_select = ft.Dropdown(label="Driver", width=130, value=self.settings.get("driver"),
            options=[option("auto", "Auto"), option("twain", "TWAIN"), option("wia", "WIA")],
            on_select=lambda e: self.on_driver_change())
        self.color = ft.Dropdown(label="Color", width=145, value=self.settings.get("color"),
            options=[option("color", "Color"), option("gray", "Grayscale"), option("bw", "B&W")])
        self.paper = ft.Dropdown(label="Paper", width=120, value=self.settings.get("paper"),
            options=[option("a4", "A4"), option("letter", "Letter"), option("legal", "Legal")])
        self.deskew = ft.Checkbox(label="Deskew", value=self.settings.get("deskew"))
        self.scan_button = ft.Button("Scan More Pages" if self.session.pages else "Start Scanning",
            icon=ft.Icons.DOCUMENT_SCANNER, style=ft.ButtonStyle(bgcolor=ACCENT, color="white"),
            on_click=lambda e: self.start_scan_primary())
        self.scan_progress = ft.ProgressRing(width=18, height=18, stroke_width=2.5, visible=False)
        self.cancel_button = ft.TextButton("Cancel", tooltip="Cancel the running scan",
            visible=self.busy, on_click=lambda e: self.cancel_scan())
        self.settings_button = ft.TextButton("Scan Settings", icon=ft.Icons.TUNE,
            tooltip="Driver, color, paper size, and deskew settings",
            style=quiet_button_style(),
            on_click=lambda e: self.open_scan_setup())
        self.refresh_button = ft.TextButton("Refresh", icon=ft.Icons.REFRESH,
            style=quiet_button_style(),
            tooltip="Find connected scanners", on_click=lambda e: self.refresh_scanners())
        scanner_toolbar = ft.Container(bgcolor=CONTENT, border=ft.Border.all(1, BORDER),
            border_radius=8, padding=ft.Padding(10, 6, 10, 6), content=ft.Row(
                wrap=True, spacing=10, run_spacing=8, controls=[
                    self.scan_button, self.scan_progress, self.cancel_button,
                    self.scanner_select, self.source, self.dpi,
                    self.settings_button, self.refresh_button]))
        self.gallery = ft.ReorderableListView(expand=True, spacing=8, on_reorder=self.reorder)
        self.page_count = ft.Text(f"({len(self.session.pages)})", color=MUTED, size=13)
        self.page_menu = ft.PopupMenuButton(icon=ft.Icons.MORE_HORIZ, tooltip="Page options",
            items=[ft.PopupMenuItem(content="Undo", on_click=lambda e: self.history(True)),
                   ft.PopupMenuItem(content="Redo", on_click=lambda e: self.history(False)),
                   ft.PopupMenuItem(content="Retake duplex pair", on_click=lambda e: self.retake(True))])
        gallery_panel = ft.Container(width=178, bgcolor=CONTENT, border=ft.Border.all(1, BORDER),
            border_radius=8, padding=ft.Padding(8, 8, 8, 8), content=ft.Column(
                expand=True, spacing=4, controls=[
                    ft.Row(spacing=3, controls=[title("Pages", 16), self.page_count,
                                                ft.Container(expand=True), self.page_menu]),
                    self.gallery]))
        self.edit_buttons = [
            ft.TextButton("Rotate Left", icon=ft.Icons.ROTATE_LEFT, tooltip="Rotate selected page left",
                          style=quiet_button_style(), expand=1, on_click=lambda e: self.edit_rotate(-90)),
            ft.TextButton("Rotate Right", icon=ft.Icons.ROTATE_RIGHT, tooltip="Rotate selected page right",
                          style=quiet_button_style(), expand=1, on_click=lambda e: self.edit_rotate(90)),
            ft.TextButton("Crop", icon=ft.Icons.CROP, tooltip="Crop selected page",
                          style=quiet_button_style(), expand=1, on_click=self.crop_dialog),
            ft.TextButton("Retake", icon=ft.Icons.REPLAY, tooltip="Rescan selected page",
                          style=quiet_button_style(), expand=1, on_click=lambda e: self.retake(False)),
            ft.TextButton("Delete", icon=ft.Icons.DELETE_OUTLINE, tooltip="Delete selected page",
                          style=quiet_button_style(), expand=1, on_click=lambda e: self.edit_delete()),
        ]
        edit_toolbar = ft.Container(bgcolor=CONTENT, border=ft.Border.all(1, BORDER),
            border_radius=8, padding=ft.Padding(4, 2, 4, 2),
            content=ft.Row(spacing=4, controls=self.edit_buttons))
        self.preview = ft.Container(expand=True, bgcolor="#E8EEF5", alignment=ft.Alignment.CENTER)
        self.zoom_label = ft.Text("100%", color=INK, weight=ft.FontWeight.BOLD, size=12)
        self.zoom_controls = ft.Row(spacing=4, alignment=ft.MainAxisAlignment.CENTER, controls=[
            ft.IconButton(icon=ft.Icons.REMOVE, tooltip="Zoom out", on_click=lambda e: asyncio.create_task(self.zoom(0.8))),
            ft.Container(width=52, alignment=ft.Alignment.CENTER, content=self.zoom_label),
            ft.IconButton(icon=ft.Icons.ADD, tooltip="Zoom in", on_click=lambda e: asyncio.create_task(self.zoom(1.25))),
            ft.Container(width=1, height=22, bgcolor=BORDER),
            ft.TextButton("Fit to Page", icon=ft.Icons.FIT_SCREEN, tooltip="Fit document to preview",
                          on_click=lambda e: asyncio.create_task(self.fit())),
            ft.TextButton("Reset", icon=ft.Icons.RESTART_ALT, tooltip="Reset zoom and position",
                          on_click=lambda e: asyncio.create_task(self.fit()))])
        zoom_bar = ft.Container(bgcolor=CONTENT,
            border=ft.Border(top=ft.BorderSide(1, BORDER)),
            padding=ft.Padding(4, 0, 4, 0), content=self.zoom_controls)
        preview_frame = ft.Container(expand=True, bgcolor="#E8EEF5",
            border=ft.Border.all(1, BORDER), border_radius=8,
            content=ft.Column(expand=True, spacing=0, controls=[self.preview, zoom_bar]))
        self.document_status = ft.Text("", color=INK, size=12, expand=True,
                                       no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
        self.page_status = ft.Text("", color=MUTED, size=12)
        preview_area = ft.Column(expand=True, spacing=6, controls=[edit_toolbar, preview_frame,
            ft.Row(controls=[self.document_status, self.page_status])])
        self.switch("scan", ft.Column(expand=True, spacing=10, controls=[
            ft.Row(controls=[title("Scan Workspace"), ft.Container(expand=True),
                ft.TextButton("New Document", icon=ft.Icons.NOTE_ADD_OUTLINED,
                              on_click=lambda e: self.new_document()),
                ft.TextButton("Save As", on_click=lambda e: self.save_dialog(save_as=True)) if self.session.source_document_id else ft.Container(),
                ft.Button("Save Document", icon=ft.Icons.SAVE,
                          style=ft.ButtonStyle(bgcolor=ACCENT, color="white"), on_click=self.save_dialog)]),
            scanner_toolbar,
            ft.Row(expand=True, spacing=10, vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                   controls=[gallery_panel, preview_area])]))
        if self.busy:
            self._set_scan_ui(True)
        self.refresh_pages()

    def open_scan_setup(self, at=None, replace=0, pair=False):
        if self.busy:
            self.message("A scan is already running.", True)
            return
        if replace == 1:
            self.source.value = "glass"
        elif pair:
            self.source.value = "duplex"
        def start(e):
            if not self.selected_scanner():
                self.message("Select a scanner first. If none are listed, click Refresh.", True)
                return
            self.close_dialog()
            self.page.update()
            asyncio.create_task(self.scan(at=at, replace=replace, pair=pair))
        self.dialog("Scan setup", ft.Column(width=440, tight=True, spacing=10, controls=[
            ft.Text("Choose the scanner, source, and resolution on the toolbar.", color=MUTED),
            ft.Row(controls=[self.driver_select,
                             ft.TextButton("Refresh scanners", icon=ft.Icons.REFRESH,
                                           on_click=lambda e: self.refresh_scanners())]),
            ft.Row(controls=[self.color, self.paper, self.deskew]),
            ft.Text("TWAIN is preferred when available; switch to WIA if the device is not listed. "
                    "The mock scanner generates sample pages without hardware.", color=MUTED, size=11)
        ]), [ft.TextButton("Cancel", on_click=lambda e: self.close_dialog()),
             ft.Button("Start scanning", icon=ft.Icons.DOCUMENT_SCANNER,
                       style=ft.ButtonStyle(bgcolor=ACCENT, color="white"), on_click=start)])

    def refresh_pages(self):
        self.session.selected.intersection_update(p.id for p in self.session.pages)
        self.page_count.value = f"({len(self.session.pages)})"
        self.gallery.controls.clear()
        for index, item in enumerate(self.session.pages):
            try:
                thumb_src = base64.b64encode(self.session.preview_path(item, 150).read_bytes()).decode("ascii")
                thumb = ft.Image(src=thumb_src, width=66, height=82, fit=ft.BoxFit.CONTAIN)
            except (OSError, ValueError):
                logging.exception("Could not render page thumbnail")
                thumb = ft.Icon(ft.Icons.INSERT_DRIVE_FILE, color=ACCENT, size=42)
            selected_page = item.id in self.session.selected
            self.gallery.controls.append(ft.Container(key=item.id, border_radius=7,
                bgcolor=PALE if selected_page else CONTENT,
                border=ft.Border.all(2 if selected_page else 1, ACCENT if selected_page else BORDER),
                padding=5, content=ft.Row(spacing=6, controls=[thumb,
                    ft.Text(f"Page {index + 1}", weight=ft.FontWeight.BOLD,
                            color=ACCENT if selected_page else INK, size=11)]),
                on_click=lambda e, id=item.id: self.select_page(id)))
        selected = next((p for p in self.session.pages
                         if p.id == self.active_page_id and p.id in self.session.selected), None)
        if selected is None:
            selected = next((p for p in self.session.pages if p.id in self.session.selected), None)
        if selected is None:
            selected = next((p for p in self.session.pages if p.id == self.active_page_id), None)
        if selected is None and self.session.pages:
            selected = self.session.pages[0]
        can_edit = bool(self.session.selected) and not self.busy
        for button in self.edit_buttons:
            button.disabled = not can_edit
        self.page_menu.items[0].disabled = not bool(self.session._undo)
        self.page_menu.items[1].disabled = not bool(self.session._redo)
        self.page_menu.items[2].disabled = not can_edit
        self.zoom_controls.disabled = selected is None
        document = self.library.get(self.session.source_document_id) if self.session.source_document_id else None
        document_name = document["title"] if document else "New Document"
        self.document_status.value = f"Document: {document_name} ({len(self.session.pages)} pages)"
        self.page_status.value = (f"Page {self.session.pages.index(selected) + 1} of {len(self.session.pages)}"
                                  if selected else "No page selected")
        self.viewer = None
        self.zoom_label.value = "100%"
        if selected:
            try:
                image_src = base64.b64encode(self.session.preview_path(selected).read_bytes()).decode("ascii")
                self.viewer = ft.InteractiveViewer(min_scale=0.5, max_scale=5,
                    boundary_margin=ft.Margin.all(100),
                    on_transform_changed=lambda e: self.update_zoom_label(e.scale),
                    content=ft.Image(src=image_src, fit=ft.BoxFit.CONTAIN, expand=True), expand=True)
                self.preview.content = self.viewer
            except (OSError, ValueError):
                logging.exception("Could not render page preview")
                self.preview.content = ft.Text("Preview unavailable for this page", color=INK, size=16)
        else:
            self.preview.content = ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER, controls=[
                    ft.Icon(ft.Icons.DOCUMENT_SCANNER, size=72, color=ACCENT),
                    ft.Text("Ready to scan your first page", color=INK, size=22, weight=ft.FontWeight.BOLD),
                    ft.Text("Choose your scanner and settings to begin.", color=MUTED, size=14),
                    ft.Button("Start Scanning", icon=ft.Icons.DOCUMENT_SCANNER,
                              style=ft.ButtonStyle(bgcolor=ACCENT, color="white"),
                              on_click=lambda e: self.start_scan_primary())])
        if self.active_view == "scan":
            self.page.update()

    def select_page(self, page_id):
        if page_id in self.session.selected:
            self.session.selected.remove(page_id)
        else:
            self.session.selected.add(page_id)
        self.active_page_id = page_id
        self.refresh_pages()

    async def zoom(self, factor):
        if self.viewer:
            await self.viewer.zoom(factor)

    def update_zoom_label(self, scale):
        self.zoom_label.value = f"{scale * 100:.0f}%"
        if self.active_view == "scan":
            self.zoom_label.update()

    async def fit(self):
        if self.viewer:
            await self.viewer.reset()

    def reorder(self, e):
        self.session.reorder(e.old_index, e.new_index)
        self.refresh_pages()

    def on_driver_change(self):
        self.settings.set(driver=self.driver_select.value or "auto")
        self.refresh_scanners()

    def start_scan_primary(self):
        if self.busy:
            self.message("A scan is already running.", True)
            return
        if self.selected_scanner() is None:
            self.message("Select a scanner first. If none are listed, click Refresh.", True)
            return
        asyncio.create_task(self.scan())

    def cancel_scan(self):
        if not self.busy or not self._active_backend:
            self.message("No scan is running.")
            return
        self.message("Canceling the scan…")
        try:
            self._active_backend.cancel()
        except Exception:
            logging.exception("Could not cancel the scan")

    def _set_scan_ui(self, busy, scanner=None):
        if not hasattr(self, "scan_button"):
            return
        self.scan_button.disabled = busy
        self.cancel_button.visible = busy
        for control in (self.scanner_select, self.source, self.dpi,
                        self.settings_button, self.refresh_button):
            control.disabled = busy
        for button in self.edit_buttons:
            button.disabled = busy or not bool(self.session.selected)
        self.page_menu.items[2].disabled = busy or not bool(self.session.selected)
        if busy:
            self.scan_button.text = "Generating pages…" if scanner and scanner.mock else "Scanning…"
            self.scan_progress.visible = True
        else:
            self.scan_button.text = "Scan More Pages" if self.session.pages else "Start Scanning"
            self.scan_progress.visible = False
        self.page.update()

    async def scan(self, e=None, at=None, replace=0, pair=False):
        if self.busy:
            return
        scanner = self.selected_scanner()
        if scanner is None:
            self.message("Select a scanner first.", True)
            return
        options = ScanOptions(scanner=scanner, source="duplex" if pair else ("glass" if replace == 1 else self.source.value),
            dpi=int(self.dpi.value), color=self.color.value, paper=self.paper.value,
            deskew=bool(self.deskew.value), pages=2 if pair and scanner.mock else 1)
        self.settings.set(source=self.source.value, dpi=options.dpi, color=options.color,
                          paper=options.paper, deskew=options.deskew,
                          driver=(self.driver_select.value or "auto") if hasattr(self, "driver_select") else self.settings.get("driver"),
                          default_scanner=self.scanner_select.value)
        self.busy = True
        self._active_backend = self.mock if scanner.mock else self.naps2
        self._set_scan_ui(True, scanner)
        self.message("Scanning…" if not scanner.mock else "Generating mock pages…")
        path = self.session.directory / f"job-{uuid.uuid4().hex}.pdf"
        try:
            try:
                await asyncio.to_thread(self._active_backend.scan, options, path)
                failure = None
            except ScannerError as exc:
                if not path.is_file():
                    raise
                # NAPS2 hit a problem but wrote a partial output file; recover those pages.
                failure = str(exc)
            if replace:
                with fitz.open(path) as scanned:
                    if scanned.page_count != replace:
                        raise ScannerError(f"Retake produced {scanned.page_count} page(s); expected {replace}. Original pages were kept.")
            items = await asyncio.to_thread(self.session.import_pdf, path, at, replace,
                                            options.source == "duplex")
            self.refresh_pages()
            if failure is None:
                self.message(f"Added {len(items)} page(s). Use Scan More Pages to add more, "
                             "or Save Document when finished.")
            else:
                self.message(f"The scan ended with a problem, but {len(items)} page(s) were "
                             f"recovered: {failure}", True)
        except (ScannerError, OSError, ValueError, RuntimeError) as exc:
            logging.exception("Scan failed")
            if "cancel" in str(exc).lower():
                self.message("Scan canceled. Previously scanned pages were kept.", True)
            else:
                self.message(f"Scan failed: {exc}", True)
        finally:
            path.unlink(missing_ok=True)
            self.busy = False
            self._active_backend = None
            self._set_scan_ui(False)

    def require_selection(self):
        if not self.session.selected:
            self.message("Select a page first.", True)
            return False
        return True

    def edit_rotate(self, degrees):
        if self.require_selection():
            self.session.rotate(degrees)
            self.refresh_pages()

    def edit_delete(self):
        if self.require_selection():
            self.session.delete()
            self.refresh_pages()

    def history(self, undo):
        self.session.undo() if undo else self.session.redo()
        self.refresh_pages()

    def crop_dialog(self, e=None):
        if not self.require_selection():
            return
        fields = [ft.TextField(label=name, value=value, width=90) for name, value in
                  [("Left %", "0"), ("Top %", "0"), ("Right %", "100"), ("Bottom %", "100")]]
        def apply(e):
            try:
                l, t, r, b = [float(f.value) / 100 for f in fields]
                if not (0 <= l < r <= 1 and 0 <= t < b <= 1):
                    raise ValueError()
                self.session.crop((l, t, r, b))
                self.close_dialog()
                self.refresh_pages()
            except ValueError:
                self.message("Enter crop percentages from 0 to 100 with left < right and top < bottom.", True)
        self.dialog("Crop selected pages", ft.Row(controls=fields),
                    [ft.TextButton("Cancel", on_click=lambda e: self.close_dialog()),
                     ft.Button("Apply", on_click=apply)])

    def retake(self, pair):
        if not self.require_selection():
            return
        index = next(i for i, p in enumerate(self.session.pages) if p.id in self.session.selected)
        if pair:
            sheet_id = self.session.pages[index].sheet_id
            if not sheet_id:
                self.message("This page has no recorded duplex partner. Retake one side instead.", True)
                return
            members = [i for i, p in enumerate(self.session.pages) if p.sheet_id == sheet_id]
            if len(members) != 2 or members[1] != members[0] + 1:
                self.message("The duplex pair is no longer adjacent. Rearrange it before retaking both sides.", True)
                return
            index = members[0]
        self.open_scan_setup(at=index, replace=2 if pair else 1, pair=pair)

    def new_document(self):
        if self.session.pages:
            self.confirm("Discard unsaved pages?", "This will clear the current scan session.", self._reset)
        else:
            self._reset()

    def _reset(self):
        self.session.reset()
        self.refresh_pages()
        self._set_scan_ui(False)
        self.message("New document ready.")

    def save_dialog(self, e=None, save_as=False):
        if not self.session.pages:
            self.message("Scan or open a document first.", True)
            return
        existing = self.library.get(self.session.source_document_id) if self.session.source_document_id else None
        name = ft.TextField(label="Document name", value=existing["title"] if existing else "Untitled scan", width=420)
        category = ft.Dropdown(label="Category", width=200, value=str(existing["category_id"] if existing else 1),
            options=[option(c["id"], c["name"]) for c in self.library.categories()])
        description = ft.TextField(label="Description", value=existing["description"] if existing else "", multiline=True)
        tags = ft.TextField(label="Tags (comma separated)", value=existing["tags"] if existing else "")
        location = ft.RadioGroup(content=ft.Column(controls=[ft.Radio(value="library", label="Default Document Library"),
                                                       ft.Radio(value="custom", label="Choose location…")]),
                                 value="library" if save_as or not existing else "existing")
        if existing and not save_as:
            location.content.controls.insert(0, ft.Radio(value="existing", label="Save changes to this PDF"))
        include = ft.Checkbox(label="Include in Document Library", value=True)
        async def commit(e):
            try:
                clean = name.value.strip()
                if not clean or re.search(r'[<>:"/\\|?*\x00-\x1f]', clean) or clean.rstrip(" .") != clean:
                    raise ValueError("Enter a valid Windows document name.")
                if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", clean, re.I):
                    raise ValueError("That name is reserved by Windows.")
                mode = location.value
                if mode == "existing":
                    dest = Path(existing["file_path"])
                    if not dest.exists():
                        raise ValueError("Original PDF is missing. Use Save As instead.")
                elif mode == "custom":
                    chosen = await ft.FilePicker().save_file(dialog_title="Save PDF", file_name=f"{clean}.pdf",
                        initial_directory=self.settings.get("last_save_dir"),
                        file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"])
                    if not chosen:
                        return
                    dest = Path(chosen)
                    if dest.suffix.lower() != ".pdf":
                        dest = dest.with_suffix(".pdf")
                else:
                    root = Path(self.settings.get("library_dir")) / "documents"
                    root.mkdir(parents=True, exist_ok=True)
                    dest = root / (f"{uuid.uuid4().hex}-{clean}.pdf")
                registered = self.library.by_path(dest)
                if registered and (not existing or registered["id"] != existing["id"]):
                    raise ValueError("This PDF is already managed by the library. Choose another name.")
                if dest.exists() and mode != "existing":
                    self.close_dialog()
                    self.confirm("Replace existing file?", f"{dest.name} already exists. Replace it?",
                                 lambda: asyncio.create_task(self._save_to(dest, clean, category.value,
                                     description.value, tags.value, include.value, existing, mode)))
                    return
                self.close_dialog()
                await self._save_to(dest, clean, category.value, description.value,
                                    tags.value, include.value, existing, mode)
            except (ValueError, OSError, sqlite3.Error) as exc:
                logging.exception("Save setup failed")
                self.message(str(exc), True)
        self.dialog("Save Document", ft.Column(width=450, tight=True, controls=[name, category,
            description, tags, location, include]),
            [ft.TextButton("Cancel", on_click=lambda e: self.close_dialog()),
             ft.Button("Save PDF", on_click=commit)])

    async def _save_to(self, dest, clean, category_id, description, tags, include, existing, mode):
        backup = None
        existed = dest.exists()
        try:
            if existed:
                handle, backup_name = tempfile.mkstemp(prefix="scanow-backup-", suffix=".pdf")
                os.close(handle)
                backup = Path(backup_name)
                shutil.copy2(dest, backup)
            await asyncio.to_thread(export_pdf, self.session, dest)
            if mode == "existing" or include or mode == "library":
                document_id = existing["id"] if mode == "existing" and existing else None
                self.library.save(clean, dest, int(category_id), description, tags,
                                  len(self.session.pages), document_id)
            self.settings.set(last_save_dir=str(dest.parent))
            self.session.reset()
            self.refresh_pages()
            self._set_scan_ui(False)
            self.message(f"Saved {dest.name}")
        except (OSError, ValueError, sqlite3.Error) as exc:
            logging.exception("Save failed")
            try:
                if backup and backup.exists():
                    shutil.copy2(backup, dest)
                elif not existed:
                    dest.unlink(missing_ok=True)
            except OSError:
                logging.exception("Could not restore PDF after failed save")
            self.message(f"Could not save PDF: {exc}", True)
        finally:
            if backup:
                backup.unlink(missing_ok=True)

    def show_library(self):
        search = ft.TextField(label="Search documents", prefix_icon=ft.Icons.SEARCH, width=280,
                              on_change=lambda e: render())
        category = ft.Dropdown(label="Category", width=180, value="all",
            options=[option("all", "All categories")] + [option(c["id"], c["name"]) for c in self.library.categories()],
            on_select=lambda e: render())
        sort = ft.Dropdown(label="Sort", width=160, value="newest", options=[option(k, v) for k, v in
            [("newest", "Newest"), ("oldest", "Oldest"), ("az", "Name A–Z"),
             ("za", "Name Z–A"), ("size", "File size")]], on_select=lambda e: render())
        availability = ft.Dropdown(label="Availability", width=160, value="all", options=[
            option("all", "All files"), option("available", "Available"), option("missing", "File missing")],
            on_select=lambda e: render())
        rows = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=4)
        def render():
            rows.controls.clear()
            records = self.library.documents(search.value or "", None if category.value == "all" else int(category.value), sort.value)
            for record in records:
                present = Path(record["file_path"]).is_file()
                if availability.value == "available" and not present or availability.value == "missing" and present:
                    continue
                rows.controls.append(ft.Container(bgcolor=CONTENT,
                    border=ft.Border.all(1, BORDER),
                    border_radius=8, padding=12, content=ft.Row(spacing=10, controls=[
                        ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ACCENT),
                        ft.Column(expand=True, spacing=2, controls=[
                            ft.Text(record["title"], weight=ft.FontWeight.BOLD, color=INK),
                            ft.Text(f"{record['category']}  •  {record['page_count']} pages  •  "
                                    f"{record['file_size'] // 1024} KB  •  {record['updated_at'][:10]}", size=11, color=MUTED),
                            ft.Text(record["file_path"], size=10, color=MUTED, overflow=ft.TextOverflow.ELLIPSIS)]),
                        ft.Text("File missing" if not present else "", color="#B63B36", size=11),
                        ft.TextButton("Preview" if present else "Locate", on_click=lambda e, r=record: self.preview_document(r) if Path(r["file_path"]).is_file() else self.locate(r)),
                        ft.PopupMenuButton(items=[
                            ft.PopupMenuItem(content=ft.Text("Open PDF"), on_click=lambda e, r=record: self.open_file(r)),
                            ft.PopupMenuItem(content=ft.Text("Open folder"), on_click=lambda e, r=record: self.open_folder(r)),
                            ft.PopupMenuItem(content=ft.Text("Edit metadata"), on_click=lambda e, r=record: self.edit_metadata(r)),
                            ft.PopupMenuItem(content=ft.Text("Edit pages"), on_click=lambda e, r=record: self.open_workspace(r)),
                            ft.PopupMenuItem(content=ft.Text("Export copy"), on_click=lambda e, r=record: asyncio.create_task(self.export_copy(r))),
                            ft.PopupMenuItem(content=ft.Text("Delete record"), on_click=lambda e, r=record: self.delete_document(r)),
                        ])])))
            if not rows.controls:
                rows.controls.append(ft.Container(content=ft.Text("No documents found.", color=MUTED), padding=30))
            self.page.update()
        self.switch("library", ft.Column(expand=True, spacing=16, controls=[
            ft.Row(controls=[title("Document Library"), ft.Container(expand=True),
                             ft.Button("Categories", on_click=lambda e: self.category_manager())]),
            ft.Row(wrap=True, spacing=10, controls=[search, category, sort, availability]), rows]))
        render()

    def preview_document(self, record):
        try:
            with fitz.open(record["file_path"]) as doc:
                images = [page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False).tobytes("png")
                          for page in list(doc)[:20]]
            content = ft.Column(width=650, height=560, scroll=ft.ScrollMode.AUTO, controls=[
                ft.Image(src=data, width=580, fit=ft.BoxFit.CONTAIN) for data in images])
            self.dialog(record["title"], content, [ft.TextButton("Close", on_click=lambda e: self.close_dialog())])
        except (OSError, RuntimeError) as exc:
            self.message(f"Could not preview PDF: {exc}", True)

    def open_file(self, record):
        try:
            os.startfile(record["file_path"])
        except OSError as exc:
            self.message(f"Could not open PDF: {exc}", True)

    def open_folder(self, record):
        path = Path(record["file_path"])
        if path.parent.exists():
            os.startfile(path.parent)
        else:
            self.message("The containing folder is unavailable.", True)

    async def export_copy(self, record):
        path = Path(record["file_path"])
        if not path.exists():
            self.message("Locate the missing PDF first.", True)
            return
        dest = await ft.FilePicker().save_file(file_name=path.name, dialog_title="Export PDF copy",
            file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"])
        if dest:
            target = Path(dest)
            if target.resolve() == path.resolve():
                self.message("Choose a different destination for the copy.", True)
                return
            shutil.copy2(path, target)
            self.message(f"Exported copy to {target}")

    async def locate(self, record):
        selected = await ft.FilePicker().pick_files(allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"])
        if selected:
            path = Path(selected[0].path)
            try:
                with fitz.open(path) as doc:
                    if not doc.page_count:
                        raise ValueError("The selected PDF has no pages.")
                self.library.relink(record["id"], path)
                self.show_library()
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                self.message(f"Could not relink: {exc}", True)

    def edit_metadata(self, record):
        name = ft.TextField(label="Document name", value=record["title"])
        category = ft.Dropdown(label="Category", value=str(record["category_id"]),
            options=[option(c["id"], c["name"]) for c in self.library.categories()])
        description = ft.TextField(label="Description", value=record["description"])
        tags = ft.TextField(label="Tags", value=record["tags"])
        def save(e):
            self.library.update_metadata(record["id"], name.value.strip(), int(category.value),
                                         description.value, tags.value)
            self.close_dialog()
            self.show_library()
        self.dialog("Edit document", ft.Column(tight=True, controls=[name, category, description, tags]),
                    [ft.TextButton("Cancel", on_click=lambda e: self.close_dialog()), ft.Button("Save", on_click=save)])

    def delete_document(self, record):
        def delete():
            self.library.delete(record["id"])
            self.show_library()
            self.message("Library record removed. The PDF remains on disk.")
        self.confirm("Remove from library?", f"Remove {record['title']} from the library? The PDF will remain on disk.", delete)

    def open_workspace(self, record):
        def load():
            try:
                self.session.reset()
                self.session.import_pdf(Path(record["file_path"]))
                self.session.source_document_id = record["id"]
                self.session.persist()
                self.show_scan()
                self.message(f"Editing {record['title']}. Save Document updates this PDF; choose Save As for a copy.")
            except (OSError, RuntimeError, ValueError) as exc:
                self.message(f"Could not open PDF for editing: {exc}", True)
        if self.session.pages:
            self.confirm("Replace current session?", "The current unsaved pages will be discarded.", load)
        else:
            load()

    def category_manager(self):
        name = ft.TextField(label="Category name")
        categories = ft.Dropdown(label="Existing category", options=[option(c["id"], c["name"])
            for c in self.library.categories() if c["id"] != 1], width=260)
        def add(e):
            try:
                self.library.add_category(name.value)
                self.close_dialog()
                self.show_library()
            except sqlite3.IntegrityError:
                self.message("That category already exists.", True)
        def rename(e):
            if categories.value:
                try:
                    self.library.rename_category(int(categories.value), name.value)
                    self.close_dialog()
                    self.show_library()
                except sqlite3.IntegrityError:
                    self.message("That category already exists.", True)
        def remove(e):
            if categories.value:
                self.close_dialog()
                self.confirm("Delete category?", "Its documents will move to Uncategorized.",
                    lambda: (self.library.delete_category(int(categories.value)), self.show_library()))
        self.dialog("Manage categories", ft.Column(tight=True, controls=[name, categories]), [
            ft.TextButton("Close", on_click=lambda e: self.close_dialog()),
            ft.TextButton("Delete", on_click=remove), ft.TextButton("Rename", on_click=rename),
            ft.Button("Add", on_click=add)])

    def show_settings(self):
        path = ft.TextField(label="Document Library location", value=self.settings.get("library_dir"), expand=True)
        naps2 = ft.TextField(label="NAPS2 Console path", value=self.settings.get("naps2_path"), expand=True)
        async def pick_dir(e):
            selected = await ft.FilePicker().get_directory_path()
            if selected:
                path.value = selected
                self.page.update()
        async def pick_naps2(e):
            selected = await ft.FilePicker().pick_files(allow_multiple=False)
            if selected:
                naps2.value = selected[0].path
                self.page.update()
        def save(e):
            new_root = Path(path.value).expanduser()
            old_root = Path(self.settings.get("library_dir"))
            try:
                if new_root != old_root:
                    new_root.mkdir(parents=True, exist_ok=True)
                    old_managed = old_root / "documents"
                    if old_managed.exists() and any(old_managed.iterdir()):
                        self.confirm("Move managed PDFs?", "Managed files will move to the new folder. External files will stay where they are.",
                            lambda: self._migrate(old_root, new_root, naps2.value))
                        return
                self.settings.set(library_dir=str(new_root), naps2_path=naps2.value)
                self.naps2 = Naps2Backend(naps2.value)
                self.refresh_scanners()
                self.message("Settings saved.")
            except OSError as exc:
                self.message(f"Could not change location: {exc}", True)
        content = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=18, controls=[
            title("Settings"),
            ft.Container(bgcolor=CONTENT, border=ft.Border.all(1, BORDER),
                         padding=16, border_radius=8, content=ft.Column(controls=[
                title("Document storage", 17), ft.Row(controls=[path, ft.Button("Browse", on_click=pick_dir)]),
                ft.Text("Managed PDFs live here. Database and recovery files live in local AppData.", size=12, color=MUTED)])),
            ft.Container(bgcolor=CONTENT, border=ft.Border.all(1, BORDER),
                         padding=16, border_radius=8, content=ft.Column(controls=[
                title("Scanner integration", 17), ft.Row(controls=[naps2, ft.Button("Browse", on_click=pick_naps2)]),
                ft.Text("NAPS2 scanning engine ready" if self.naps2.available else
                        "NAPS2 scanning engine missing. Reinstall ScaNow or browse to an external NAPS2.Console.exe. The mock scanner remains available.",
                        color=MUTED)])),
            ft.Row(controls=[ft.Button("Save settings", on_click=save),
                ft.Button("Back up library", on_click=self.backup),
                ft.Button("Restore library", on_click=self.restore)]),
            ft.Text("ScaNow 0.1  •  Fully offline", color=MUTED)])
        self.switch("settings", content)

    def _migrate(self, old_root, new_root, naps2_path):
        source = old_root / "documents"
        target = new_root / "documents"
        target.mkdir(parents=True, exist_ok=True)
        try:
            for file in source.glob("*.pdf"):
                shutil.copy2(file, target / file.name)
            with self.library.connect() as con:
                for record in con.execute("SELECT id,file_path FROM documents").fetchall():
                    original = Path(record["file_path"])
                    if original.parent.resolve() == source.resolve():
                        con.execute("UPDATE documents SET file_path=? WHERE id=?",
                                    (str(target / original.name), record["id"]))
            self.settings.set(library_dir=str(new_root), naps2_path=naps2_path)
            self.naps2 = Naps2Backend(naps2_path)
            self.refresh_scanners()
            self.message("Managed PDFs copied to the new library location.")
        except (OSError, sqlite3.Error) as exc:
            self.message(f"Migration failed: {exc}", True)

    async def backup(self, e):
        destination = await ft.FilePicker().save_file(file_name="ScaNow-backup.zip")
        if destination:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    snapshot = Path(folder) / "library.db"
                    with self.library.connect() as source, sqlite3.connect(snapshot) as target:
                        source.backup(target)
                    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                        archive.write(snapshot, "library.db")
                        root = Path(self.settings.get("library_dir")) / "documents"
                        archive.writestr("manifest.json", json.dumps({"managed_dir": str(root)}))
                        if root.exists():
                            for file in root.glob("*.pdf"):
                                archive.write(file, f"documents/{file.name}")
                self.message(f"Backup saved to {destination}")
            except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
                logging.exception("Backup failed")
                self.message(f"Backup failed: {exc}", True)

    async def restore(self, e):
        selected = await ft.FilePicker().pick_files(allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["zip"])
        if not selected:
            return
        archive_path = Path(selected[0].path)
        self.confirm("Restore library?", "This replaces the current library metadata and managed PDFs. Back up the current library first.",
            lambda: self._restore_archive(archive_path))

    def _restore_archive(self, archive_path):
        try:
            target_root = Path(self.settings.get("library_dir")) / "documents"
            target_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(archive_path) as archive:
                if not {"library.db", "manifest.json"}.issubset(archive.namelist()):
                    raise ValueError("This is not a ScaNow backup.")
                original_root = Path(json.loads(archive.read("manifest.json"))["managed_dir"])
                snapshot = Path(folder) / "library.db"
                snapshot.write_bytes(archive.read("library.db"))
                with sqlite3.connect(snapshot) as con:
                    valid = con.execute("PRAGMA integrity_check").fetchone()[0]
                    if valid != "ok":
                        raise ValueError("The backup database is damaged.")
                    rows = con.execute("SELECT id,file_path FROM documents").fetchall()
                    for document_id, file_path in rows:
                        original = Path(file_path)
                        if original.parent == original_root:
                            con.execute("UPDATE documents SET file_path=? WHERE id=?",
                                        (str(target_root / original.name), document_id))
                    con.commit()
                for name in archive.namelist():
                    if name.startswith("documents/") and name.endswith(".pdf") and len(Path(name).parts) == 2:
                        destination = target_root / Path(name).name
                        temporary = target_root / f".{uuid.uuid4().hex}.tmp"
                        temporary.write_bytes(archive.read(name))
                        temporary.replace(destination)
                snapshot.replace(self.library.path)
            self.show_library()
            self.message("Library restored.")
        except (OSError, ValueError, KeyError, sqlite3.Error, zipfile.BadZipFile) as exc:
            logging.exception("Restore failed")
            self.message(f"Restore failed: {exc}", True)

