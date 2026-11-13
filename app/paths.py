import os
from pathlib import Path


def app_data() -> Path:
    root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ScaNow"
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_library() -> Path:
    return Path.home() / "Documents" / "ScaNow"
