"""Compact confirmations and text prompts matching the archive modal."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QVBoxLayout)

from app.ui.components import action, field_label


class PromptDialog(QDialog):
    def __init__(self, parent, title, description, *, choices=None, initial="", confirm="Continue",
                 danger=False, show_cancel=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QDialog { background:transparent; }")
        self.setFixedWidth(440)
        self._overlay = None
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(18, 18, 18, 18)
        card = QFrame()
        card.setObjectName("modalCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(31, 41, 61, 65))
        card.setGraphicsEffect(shadow)
        wrap.addWidget(card)
        body = QVBoxLayout(card)
        body.setContentsMargins(22, 20, 22, 20)
        body.setSpacing(9)
        heading = QLabel(title)
        heading.setObjectName("title")
        body.addWidget(heading)
        explanation = QLabel(description)
        explanation.setObjectName("subtle")
        explanation.setWordWrap(True)
        body.addWidget(explanation)
        self.input = None
        if choices is not None:
            self.input = QComboBox()
            self.input.addItems(choices)
            body.addWidget(self.input)
        elif initial is not None:
            self.input = QLineEdit(initial)
            body.addWidget(self.input)
        controls = QHBoxLayout()
        controls.addStretch()
        if show_cancel:
            controls.addWidget(action("Cancel", self.reject))
        controls.addWidget(action(confirm, self.accept, primary=not danger,
                                  kind="danger" if danger else None))
        body.addLayout(controls)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent and isinstance(parent, QMainWindow):
            self._overlay = QFrame(parent.centralWidget())
            self._overlay.setGeometry(parent.centralWidget().rect())
            self._overlay.setStyleSheet("background:rgba(40,48,70,70);")
            self._overlay.show()
            self._overlay.raise_()
            center = parent.mapToGlobal(parent.rect().center())
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def done(self, result):
        if self._overlay:
            self._overlay.deleteLater()
            self._overlay = None
        super().done(result)


class QMessageBox:
    from PySide6.QtWidgets import QMessageBox as _Native
    StandardButton = _Native.StandardButton

    @staticmethod
    def question(parent, title, description):
        danger = any(word in title.lower() for word in ("delete", "remove", "discard", "restore", "replace"))
        dialog = PromptDialog(parent, title, description, initial=None,
                              confirm="Delete" if "delete" in title.lower() else "Continue", danger=danger)
        return QMessageBox.StandardButton.Yes if dialog.exec() == QDialog.DialogCode.Accepted else QMessageBox.StandardButton.No

    @staticmethod
    def warning(parent, title, description):
        dialog = PromptDialog(parent, title, description, initial=None, confirm="OK", show_cancel=False)
        dialog.exec()


class QInputDialog:
    @staticmethod
    def getText(parent, title, description, *, text=""):
        dialog = PromptDialog(parent, title, description, initial=text, confirm="Apply")
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.input.text() if accepted else text, accepted

    @staticmethod
    def getItem(parent, title, description, choices, current=0, editable=False):
        dialog = PromptDialog(parent, title, description, choices=choices, confirm="Select")
        dialog.input.setCurrentIndex(current)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.input.currentText() if accepted else "", accepted
