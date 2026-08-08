from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """A label that shortens its text with an ellipsis instead of demanding room for all of it."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._full = ""
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text
        self._elide()

    def text(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        available = self.contentsRect().width()
        metrics = self.fontMetrics()
        if 0 < available < metrics.horizontalAdvance(self._full):
            super().setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, available))
            self.setToolTip(self._full)
        else:
            super().setText(self._full)
            self.setToolTip("")
