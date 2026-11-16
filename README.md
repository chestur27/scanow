# ScaNow 2.0

ScaNow is an offline Windows document scanner and archive. The desktop interface uses PySide6 Qt Widgets and Qt PDF. NAPS2 Console continues to provide TWAIN/WIA scanning; PyMuPDF and Pillow handle page editing and PDF export. SQLite stores document metadata in `%LOCALAPPDATA%\ScaNow\library.db`. Existing settings and records are read in place and extended with new metadata columns. Managed PDFs default to `%USERPROFILE%\Documents\ScaNow\documents`.

## Run and test

Install Python 3.11 or later. From the repository root:

```powershell
uv sync
uv run python main.py
uv run python -m unittest discover -s tests -v
uv run python tests/smoke_qt.py
```

On a computer without NAPS2 or a physical scanner, select **Sample scanner (mock)**. Flatbed produces one page; ADF and duplex generate multiple sample pages. The real scanner requires NAPS2 Console and a manufacturer TWAIN or WIA driver. Use Settings to choose an external NAPS2 Console executable, then refresh devices.

## Daily workflow

1. Choose a scanner, source, resolution, color, and paper size. Scan runs in a background worker. Cancel stops the active scanner job while keeping earlier pages.
2. Select page thumbnails to rotate, crop, delete, or retake. Drag one page to reorder. Undo and redo cover page edits. Add PDF imports pages into the same recoverable session.
3. Click **Save to archive**, enter a name and category, and optionally add a date, reference, related person or company, notes, and tags. ScaNow validates the PDF and indexes it only after the file is written. A failed save keeps the pages in the session.
4. Use Archive library to search, filter, preview, open, export, relink, or edit documents. Removing an index entry leaves the PDF on disk. Deleting a managed PDF moves it into the archive's `documents\recovery` folder.
   Saving edits to an existing archived PDF also keeps its prior version in a recovery folder.
5. Use Settings to check database integrity, manage categories, and create or restore backups.

Unfinished pages are kept in `%LOCALAPPDATA%\ScaNow\sessions\active`. The archive and application data are outside the installation folder and are not removed by uninstalling ScaNow.

## Data compatibility and migration inventory

| Existing component | Migration action |
|---|---|
| Flet shell, scan workspace, library, settings, dialogs | Replaced by Qt Widgets and Qt PDF |
| NAPS2 discovery and scan backend | Preserved; called from Qt workers |
| Mock scanner | Preserved |
| Page session, recovery, edits, PDF export | Preserved and connected to Qt |
| JSON settings | Preserved at the same path |
| SQLite archive and categories | Preserved; added reference, entity, document date, OCR text, and checksum columns |
| Flet Windows build | Replaced with PyInstaller onedir build |

The database schema adds columns in place; it does not remove existing records. Before first use on the employee's machine, copy `%LOCALAPPDATA%\ScaNow` and the configured managed PDF folder as a separate precaution. The application does not silently move or delete either location.

## Backup and restore

**Create backup** writes a ZIP with a SQLite snapshot, referenced managed PDFs, and settings. It refuses to overwrite an existing ZIP and fails if a referenced managed PDF is missing. External PDF paths are retained in metadata but their files are not copied into the ZIP. **Restore backup** validates the ZIP and database, moves current managed PDFs into a timestamped recovery folder, saves the prior database as `library.before-restore-*.db`, and then installs the restored snapshot. The configured archive directory remains the target; paths from the backup's managed directory are remapped to it. Keep external documents separately backed up.

## Build the Windows installer

```powershell
.\installer\build.ps1
.\installer\prepare_naps2.ps1
```

Compile `installer\scanow.iss` with Inno Setup 6. The PyInstaller build creates `build\windows\scanow\scanow.exe`; the installer places the bundled NAPS2 runtime under `{app}\tools\naps2`. `prepare_naps2.ps1` downloads NAPS2 8.6.0 and its matching source archive at build time, verifies pinned SHA-256 hashes, and stages license notices. No download is needed at application startup. The installer uses a per-user directory and does not need administrator privileges for ordinary installation or use. NAPS2 is GPL-2.0-or-later; distribute its license, notices, and matching source archive with every installer. See `installer\NAPS2-NOTICE.txt`.

## Verification on the employee's Windows computer

Run the automated tests above, then verify a clean installer launch on Windows 10 or 11, NAPS2 discovery, physical flatbed and ADF/duplex scans, cancellation, PDF preview, write permissions, archive persistence after restart, and backup restore. Test TWAIN/WIA behavior with the actual scanner and manufacturer driver. Confirm the bundled NAPS2 executable is found in the installed folder. This repository's automated tests use the mock scanner and do not establish physical scanner or installer behavior.

## Current limitations

- Existing OCR was absent; ScaNow does not claim content search for scanned image PDFs. The database has an OCR text field for a future optional offline OCR service.
- Opening an archived PDF in the workspace rasterizes it for editing. Saving edits can remove searchable text and vector content in the original. Export a copy first when those matter.
- Search uses SQLite FTS5 for indexed text matches when available, with `LIKE` for substring and date/category matches.
- The preview focuses on one page at a time. Feeder and duplex options rely on capabilities supported by the selected NAPS2 driver.
