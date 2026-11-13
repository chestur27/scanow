from pathlib import Path
import threading
from PIL import Image, ImageDraw, ImageFont
import fitz
from app.scanner.base import Scanner, ScanOptions, ScannerBackend, ScannerError


class MockBackend(ScannerBackend):
    def __init__(self):
        self._canceled = threading.Event()

    def discover(self):
        return [Scanner("Sample scanner (mock)", "mock", True)]

    def scan(self, options: ScanOptions, output: Path):
        self._canceled.clear()
        count = options.pages if options.source == "glass" else (2 if options.source == "duplex" and options.pages == 2 else max(4, options.pages))
        if options.source == "duplex" and count % 2:
            count += 1
        document = fitz.open()
        try:
            for index in range(count):
                if self._canceled.is_set():
                    raise ScannerError("Scan canceled.")
                image = Image.new("RGB", (1240, 1754), "#fffdf8")
                draw = ImageDraw.Draw(image)
                draw.rectangle((70, 70, 1170, 1684), outline="#d5dce4", width=3)
                draw.rectangle((70, 70, 1170, 220), fill="#173b57")
                draw.text((110, 115), "ScaNow  /  MOCK SCANNER", fill="white", font=ImageFont.load_default(size=34))
                draw.text((110, 300), f"Sample page {index + 1}", fill="#173b57", font=ImageFont.load_default(size=58))
                draw.text((110, 415), "This sample is generated locally for workflow evaluation.",
                          fill="#4b5d6d", font=ImageFont.load_default(size=28))
                if options.source == "duplex":
                    draw.text((110, 500), f"Sheet {index // 2 + 1}  /  {'Front' if index % 2 == 0 else 'Back'}",
                              fill="#4b5d6d", font=ImageFont.load_default(size=28))
                page = document.new_page(width=595, height=842)
                import io
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                page.insert_image(page.rect, stream=buffer.getvalue())
            if self._canceled.is_set():
                raise ScannerError("Scan canceled.")
            document.save(output)
        finally:
            document.close()
        return output

    def cancel(self):
        self._canceled.set()
