# ScaNow

ScaNow is an offline Windows desktop document scanner and PDF library. It uses Flet for the interface, NAPS2 Console for TWAIN/WIA scanning, PyMuPDF and Pillow for page editing and PDF export, and SQLite for metadata.

## Run from source

Install Python 3.11 or later, then run:

```powershell
uv sync
uv run python main.py
```

The mock scanner is always listed and generates sample pages. It never reports a hardware scan. Source runs need NAPS2 Console installed separately or selected in Settings. The Windows installer bundles NAPS2; a physical scanner still needs its manufacturer's TWAIN or WIA driver. Refresh devices after changing driver installation or scanner connection.

## Workflow

1. Choose a scanner, source (Flatbed, ADF, or ADF duplex), and resolution in the Scan Workspace toolbar, then click **Start Scanning**. **Scan Settings** opens the TWAIN/WIA driver, color, paper size, and deskew options; **Refresh** re-detects devices.
2. Each job appends to the active session and the button becomes **Scan More Pages**. Keep scanning until the document is complete, then Save Document. Drag pages to reorder. Click pages to select; rotate, crop, retake, and delete from the toolbar above the preview. Undo, redo, and duplex-pair retake are in the Pages menu. A failed scan never clears previously acquired pages.
3. Save Document to a managed library PDF or use the Windows Save dialog for another location. The custom-location checkbox controls whether the actual PDF path is registered in the library.
4. Search and manage saved PDFs in Document Library. Open a PDF in the workspace to modify its pages. The session is preserved in local AppData after an unexpected exit.

User settings, metadata, logs, and recovery pages are in `%LOCALAPPDATA%\ScaNow`. Managed PDFs default to `%USERPROFILE%\Documents\ScaNow\documents`. Uninstalling the app does not remove either location.

## Build installer

```powershell
uv sync --extra build
uv run flet build windows
.\installer\prepare_naps2.ps1
```

Open `installer\scanow.iss` with Inno Setup 6 and compile. Verify the executable name in the generated `build\windows` folder; update `MyAppExeName` in the installer script if Flet emits a different filename. The preparation script downloads the official NAPS2 8.6.0 Windows x64 portable ZIP and matching source archive at **build time**, verifies their pinned SHA-256 checksums, and stages the entire portable runtime under `installer\payload\naps2`. The installer embeds that runtime under `{app}\tools\naps2` and the source and notices under `{app}\licenses`. Builds and installed scanning do not download dependencies at startup.

The packaged app prefers `{app}\tools\naps2\App\NAPS2.Console.exe`, then a configured external path, then ordinary system locations. NAPS2 is GPL-2.0-or-later; distribute its license, notices, and complete corresponding source archive with every installer. See `installer\NAPS2-NOTICE.txt`. No HP scanner driver is bundled; obtain the manufacturer's driver separately and verify its redistribution terms before any future bundling. Scanned documents and the SQLite Document Library live outside `{app}`, so uninstalling ScaNow does not remove them.

## Current limitations

- Scanner capability detection is limited to driver and device discovery. Source, duplex, resolution, color, page size, and deskew are requested through NAPS2; unsupported combinations are reported by NAPS2. Blank-page removal is not exposed.
- The preview shows the first 20 pages of a library PDF. Imported PDFs are rasterized for editing, so searchable text and vector content are not preserved through Save Changes.
- Crop uses percentage coordinates in a dialog. Side-by-side duplex retake verification, date filters, theme selection, and automated restore are not yet implemented.
- Backup creates a ZIP of the database and managed PDFs. Restore replaces library metadata and managed PDFs after confirmation; make a current backup first.
- A physical scanner and packaged Windows build have not been tested in this environment.
