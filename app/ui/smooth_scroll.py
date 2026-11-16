"""Animated wheel scrolling for page thumbnails and the document canvas."""

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt
from PySide6.QtWidgets import QListWidget, QScrollArea


class SmoothWheel:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QEvent.Type.Wheel:
            return self._wheel(event)
        return super().eventFilter(watched, event)

    def _wheel(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            return False
        bar = self.verticalScrollBar()
        if bar.maximum() <= bar.minimum():
            return False
        pixel = event.pixelDelta().y()
        distance = -pixel if pixel else -event.angleDelta().y() * 0.55
        if not distance:
            return False
        animation = getattr(self, "_wheel_animation", None)
        start = bar.value()
        if animation is not None and animation.state() == QPropertyAnimation.State.Running:
            start = int(animation.endValue())
            animation.stop()
        target = max(bar.minimum(), min(bar.maximum(), round(start + distance)))
        if animation is None:
            animation = QPropertyAnimation(bar, b"value", self)
            animation.setDuration(180)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._wheel_animation = animation
        animation.setStartValue(bar.value())
        animation.setEndValue(target)
        animation.start()
        event.accept()
        return True


class SmoothPageList(SmoothWheel, QListWidget):
    pass


class SmoothPaperScroll(SmoothWheel, QScrollArea):
    pass
