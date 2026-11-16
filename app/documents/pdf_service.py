import io
import os
import tempfile
from pathlib import Path
import pymupdf as fitz
from app.documents.session import DocumentSession


def export_pdf(session: DocumentSession, destination: Path):
    if not session.pages:
        raise ValueError("There are no pages to save.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        for item in session.pages:
            image = session.image(item)
            width, height = image.size
            page = doc.new_page(width=width * 72 / 150, height=height * 72 / 150)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            page.insert_image(page.rect, stream=buffer.getvalue())
        fd, name = tempfile.mkstemp(prefix=".scanow-", suffix=".pdf", dir=destination.parent)
        os.close(fd)
        try:
            Path(name).unlink()
            doc.save(name, garbage=4, deflate=True)
            os.replace(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)
    finally:
        doc.close()
    return destination
