import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.paths import app_data
from app.ui.main_window import ScaNowWindow


def main() -> int:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ScaNow.Desktop.2")
    logging.basicConfig(filename=app_data() / "scanow.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("ScaNow")
    app.setOrganizationName("ScaNow")
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app_icon = QIcon(str(resource_root / "app" / "assets" / "scanow.ico"))
    app.setWindowIcon(app_icon)
    window = ScaNowWindow()
    window.setWindowIcon(app_icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
