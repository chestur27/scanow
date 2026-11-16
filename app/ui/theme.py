"""Qt design tokens based on the three-page desktop reference."""

LIGHT = dict(bg="#FFFFFF", rail="#F5F7FA", canvas="#E9EDF2", selected="#E6EBFF",
             surface="#FFFFFF", border="#D9DEE7", soft_border="#E9ECF1", text="#252B36",
             secondary="#647083", accent="#3653DA", danger="#C9362C", hover="#F1F4FC")
DARK = dict(bg="#20242C", rail="#252B35", canvas="#171B22", selected="#313B61",
            surface="#242A34", border="#414959", soft_border="#353D4B", text="#F0F3F8",
            secondary="#ADB6C5", accent="#7388FF", danger="#FF7770", hover="#31394B")


def stylesheet(theme="light"):
    c = DARK if theme == "dark" else LIGHT
    return f"""
    QWidget {{ background: {c['bg']}; color: {c['text']}; font: 10pt Arial; }}
    QMainWindow, QDialog {{ background: {c['surface']}; }}
    QFrame#rail, QFrame#thumbnailPanel, QFrame#libraryPreview {{ background: {c['rail']}; }}
    QFrame#rail {{ border-right: 1px solid {c['soft_border']}; }}
    QFrame#thumbnailPanel {{ border-right: 1px solid {c['soft_border']}; }}
    QFrame#libraryPreview {{ border-left: 1px solid {c['soft_border']}; }}
    QFrame#libraryPreview QLabel {{ background: transparent; }}
    QFrame#topbar {{ background: {c['surface']}; border-bottom: 1px solid {c['soft_border']}; }}
    QFrame#documentCanvas {{ background: {c['canvas']}; }}
    QFrame#actionPanel {{ background: {c['surface']}; border-left: 1px solid {c['soft_border']}; }}
    QFrame#floatingTools {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; }}
    QFrame#modalCard {{ background: {c['surface']}; border-radius: 12px; }}
    QFrame#divider {{ background: {c['soft_border']}; border: 0; }}
    QLabel#title {{ font-size: 13pt; font-weight: 600; }}
    QLabel#subtle, QLabel#fieldLabel, QLabel#meta {{ color: {c['secondary']}; }}
    QLabel#fieldLabel {{ font-size: 9pt; }}
    QLabel#error {{ color: {c['danger']}; font-size: 9pt; }}
    QLabel#paper {{ background: white; }}
    QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 5px;
        padding: 5px 10px; min-height: 22px; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton[kind="primary"] {{ background: {c['accent']}; color: white; border-color: {c['accent']}; font-weight: 600; }}
    QPushButton[kind="primary"]:hover {{ background: {c['accent']}; }}
    QPushButton[kind="nav"], QPushButton[kind="icon"], QPushButton[kind="quiet"] {{ border: 0; background: transparent; padding: 4px; }}
    QPushButton[kind="nav"]:hover, QPushButton[kind="icon"]:hover, QPushButton[kind="quiet"]:hover {{ background: {c['hover']}; }}
    QPushButton[active="true"] {{ background: {c['selected']}; }}
    QPushButton[kind="danger"] {{ color: {c['danger']}; }}
    QPushButton:disabled {{ color: {c['secondary']}; background: {c['rail']}; border-color: {c['soft_border']}; }}
    QLineEdit, QComboBox, QDateEdit, QPlainTextEdit {{ background: {c['surface']}; border: 1px solid {c['border']};
        border-radius: 5px; padding: 5px 9px; min-height: 23px; selection-background-color: {c['selected']}; }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: 0; width: 18px; }}
    QListWidget, QTableView, QScrollArea {{ border: 0; background: {c['surface']}; }}
    QListWidget#thumbnails {{ background: {c['rail']}; outline: none; }}
    QListWidget#thumbnails::item {{ border: 1px solid transparent; border-radius: 5px; padding: 5px; margin: 3px 4px; }}
    QListWidget#thumbnails::item:selected {{ background: {c['selected']}; border-color: {c['accent']}; color: {c['text']}; }}
    QTableView {{ gridline-color: {c['soft_border']}; outline: none; selection-background-color: {c['selected']};
        selection-color: {c['text']}; }}
    QTableView::item {{ border-bottom: 1px solid {c['soft_border']}; padding-left: 6px; }}
    QTableView::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
    QHeaderView::section {{ background: {c['rail']}; color: {c['secondary']}; border: 0;
        border-bottom: 1px solid {c['border']}; padding: 7px 9px; font-weight: 400; text-align: left; }}
    QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; }}
    QMenu::item:selected {{ background: {c['selected']}; }}
    QStatusBar {{ background: {c['rail']}; border-top: 1px solid {c['soft_border']}; color: {c['secondary']}; }}
    QSplitter::handle {{ background: {c['soft_border']}; }}
    QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
    """
