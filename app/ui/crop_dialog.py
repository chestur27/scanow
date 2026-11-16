"""Drag-to-crop editor for one scanned page."""

from PySide6.QtCore import Qt, QRect, QPoint, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.components import action


class CropCanvas(QWidget):
    changed = Signal(bool)

    def __init__(self, pixmap):
        super().__init__()
        self.pixmap = pixmap
        self.setMinimumSize(500, 360)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start = None
        self.end = None

    def image_rect(self):
        size = self.pixmap.size().scaled(QSize(max(1, self.width() - 24), max(1, self.height() - 24)),
                                         Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width() - size.width()) // 2, (self.height() - size.height()) // 2,
                     size.width(), size.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#E9EDF2"))
        target = self.image_rect()
        painter.drawPixmap(target, self.pixmap)
        if self.start and self.end:
            selection = QRect(self.start, self.end).normalized().intersected(target)
            painter.fillRect(target, QColor(32, 42, 62, 75))
            painter.drawPixmap(selection, self.pixmap, self._source_rect(selection, target))
            painter.setPen(QPen(QColor("#3653DA"), 2))
            painter.drawRect(selection)
            for corner in (selection.topLeft(), selection.topRight(), selection.bottomLeft(), selection.bottomRight()):
                painter.fillRect(QRect(corner.x() - 4, corner.y() - 4, 8, 8), QColor("#3653DA"))

    def _source_rect(self, selection, target):
        return QRect(round((selection.x() - target.x()) * self.pixmap.width() / target.width()),
                     round((selection.y() - target.y()) * self.pixmap.height() / target.height()),
                     round(selection.width() * self.pixmap.width() / target.width()),
                     round(selection.height() * self.pixmap.height() / target.height()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(event.position().toPoint()):
            self.start = event.position().toPoint()
            self.end = self.start
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            target = self.image_rect()
            point = event.position().toPoint()
            self.end = QPoint(max(target.left(), min(target.right(), point.x())),
                              max(target.top(), min(target.bottom(), point.y())))
            self.changed.emit(self.bounds() is not None)
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start is not None:
            self.mouseMoveEvent(event)

    def bounds(self):
        if self.start is None or self.end is None:
            return None
        target = self.image_rect()
        selection = QRect(self.start, self.end).normalized().intersected(target)
        if selection.width() < 12 or selection.height() < 12:
            return None
        return ((selection.left() - target.left()) / target.width(),
                (selection.top() - target.top()) / target.height(),
                (selection.right() - target.left()) / target.width(),
                (selection.bottom() - target.top()) / target.height())


class CropDialog(QDialog):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crop page")
        self.resize(640, 510)
        layout = QVBoxLayout(self)
        title = QLabel("Drag over the page to choose the area to keep.")
        title.setObjectName("subtle")
        layout.addWidget(title)
        self.canvas = CropCanvas(pixmap)
        layout.addWidget(self.canvas, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(action("Cancel", self.reject))
        apply = action("Apply crop", self.accept, primary=True)
        apply.setEnabled(False)
        self.canvas.changed.connect(apply.setEnabled)
        buttons.addWidget(apply)
        layout.addLayout(buttons)

    def bounds(self):
        return self.canvas.bounds()
