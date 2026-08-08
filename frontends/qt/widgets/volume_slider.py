from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSlider


class VolumeSlider(QSlider):
    """Qt applies a `:hover::sub-page` rule whether or not the pointer is there, so hover is a property instead."""

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.setProperty("hovered", False)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._set_hovered(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._set_hovered(False)

    def _set_hovered(self, hovered: bool) -> None:
        self.setProperty("hovered", hovered)
        self.style().unpolish(self)
        self.style().polish(self)
