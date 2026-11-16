"""Shared compact controls and a consistent SVG icon family."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton

PATHS = {
    "scan": '<rect x="4" y="8" width="16" height="10" rx="1"/><path d="M7 8V4h10v4M7 14h10M8 18v3h8v-3"/>',
    "archive": '<path d="M6 2h8l4 4v16H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M14 2v5h5M8 12h8M8 16h8"/>',
    "settings": '<path d="M10 2h4l.7 2.3 1.7.7 2.1-1.1 2.8 2.8-1.1 2.1.7 1.7L23 11v4l-2.3.7-.7 1.7 1.1 2.1-2.8 2.8-2.1-1.1-1.7.7L14 24h-4l-.7-2.3-1.7-.7-2.1 1.1-2.8-2.8 1.1-2.1-.7-1.7L1 15v-4l2.3-.7.7-1.7-1.1-2.1 2.8-2.8 2.1 1.1 1.7-.7z" transform="translate(0 -1) scale(.96)"/><circle cx="12" cy="12" r="3"/>',
    "plus": '<path d="M12 4v16M4 12h16"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "left": '<path d="m15 5-7 7 7 7"/>',
    "right": '<path d="m9 5 7 7-7 7"/>',
    "rotate_left": '<path d="M5 9V4h5M5 4a9 9 0 1 1-2 10"/>',
    "rotate_right": '<path d="M19 9V4h-5M19 4a9 9 0 1 0 2 10"/>',
    "crop": '<path d="M7 2v15a2 2 0 0 0 2 2h13M2 7h15a2 2 0 0 1 2 2v13"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7M10 10v8m4-8v8"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
}


def icon(name, color="#647083"):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
           f'stroke-linejoin="round">{PATHS[name]}</svg>')
    pixmap = QPixmap()
    pixmap.loadFromData(svg.encode(), "SVG")
    return QIcon(pixmap)


def action(label, slot, *, primary=False, kind=None, icon_name=None, tip=None):
    control = QPushButton(label)
    control.setProperty("kind", "primary" if primary else (kind or "secondary"))
    if icon_name:
        control.setIcon(icon(icon_name))
    if tip:
        control.setToolTip(tip)
    control.clicked.connect(lambda checked=False: slot())
    return control


def icon_button(name, slot, tip, *, nav=False):
    control = action("", slot, kind="nav" if nav else "icon", icon_name=name, tip=tip)
    control.setFixedSize(40 if nav else 32, 40 if nav else 32)
    if nav:
        control.setIconSize(QSize(28, 28))
    return control


def line():
    divider = QFrame()
    divider.setObjectName("divider")
    divider.setFixedHeight(1)
    return divider


def field_label(text):
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    return label
