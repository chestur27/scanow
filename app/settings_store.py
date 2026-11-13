import json
from pathlib import Path
from app.paths import app_data, default_library


DEFAULTS = {
    "library_dir": str(default_library()), "driver": "auto", "source": "duplex",
    "dpi": 300, "color": "color", "paper": "a4", "deskew": False,
    "last_save_dir": str(default_library()), "theme": "light", "recover_sessions": True,
    "naps2_path": "", "default_scanner": "",
}


class SettingsStore:
    def __init__(self):
        self.path = app_data() / "settings.json"
        try:
            self.values = DEFAULTS | json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.values = DEFAULTS.copy()

    def get(self, key):
        return self.values[key]

    def set(self, **values):
        self.values.update(values)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.values, indent=2), encoding="utf-8")
        temporary.replace(self.path)
