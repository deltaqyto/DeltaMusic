from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSlider

from frontends.qt.style import SLIDER_HANDLE_HOVER


class SeekSlider(QSlider):
    """Presses land where the pointer is rather than paging, so the whole bar is a seek target.

    Hover is a property because Qt applies a `:hover::sub-control` rule whether or not the pointer is there.
    """

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.setProperty("hovered", False)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._set_hovered(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._set_hovered(False)

    def mousePressEvent(self, event) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setValue(self._value_at(event.position().x()))
        # Marking the slider down is what emits sliderPressed, and it makes the press flow into a drag.
        self.setSliderDown(True)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self.isSliderDown():
            super().mouseMoveEvent(event)
            return
        self.setValue(self._value_at(event.position().x()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if not self.isSliderDown():
            super().mouseReleaseEvent(event)
            return
        self.setSliderDown(False)
        event.accept()

    def _value_at(self, x: float) -> int:
        """Inset by half a handle at each end, where the handle can no longer travel."""
        span = max(1.0, self.width() - SLIDER_HANDLE_HOVER)
        fraction = min(1.0, max(0.0, (x - SLIDER_HANDLE_HOVER / 2) / span))
        return round(self.minimum() + fraction * (self.maximum() - self.minimum()))

    def _set_hovered(self, hovered: bool) -> None:
        self.setProperty("hovered", hovered)
        self.style().unpolish(self)
        self.style().polish(self)
