from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qframelesswindow import FramelessDialog

from frontends.qt.icons import app_icon
from frontends.qt.style import DIALOG_TITLE_BAR_HEIGHT
from frontends.qt.widgets.title_bar import DialogTitleBar


class AppDialog(FramelessDialog):
    """A modal panel wearing the same title bar as the main window."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.setTitleBar(DialogTitleBar(self))
        self.titleBar.setTitle(title)

        self.body = QWidget(self)
        self.body.setObjectName("dialogBody")
        self.body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        frame = QVBoxLayout(self)
        frame.setContentsMargins(0, DIALOG_TITLE_BAR_HEIGHT, 0, 0)
        frame.setSpacing(0)
        frame.addWidget(self.body)

        self.titleBar.raise_()

    def fit(self, width: int) -> None:
        """A frameless dialog takes no size from what it holds, so it is given one. Call it once the body is filled."""
        self.setFixedWidth(width)
        self.adjustSize()
        self.setFixedHeight(self.height())
