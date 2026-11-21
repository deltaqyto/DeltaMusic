from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget
from qframelesswindow import TitleBar

from frontends.qt.icons import app_glyph, icon
from frontends.qt.style import ACCENT, DIALOG_TITLE_BAR_HEIGHT, LINE, PANEL, PANEL_2, TEXT, TITLE_BAR_HEIGHT

CAPTION_BUTTON_SIZE = QSize(46, 32)
DIALOG_BUTTON_SIZE = QSize(38, 26)
BRAND_MARK_SIZE = 22
BRAND_CLEARANCE = 64
DIALOG_MARK_SIZE = 14
DEVICES_ICON_SIZE = 17
CLOSE_HOVER = "#c42b1c"
CLOSE_PRESS = "#a52216"


class _ThemedTitleBar(TitleBar):
    """A backdrop to paint on, themed caption buttons."""

    def __init__(self, parent, height: int, button_size: QSize):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(height)
        self._button_size = button_size

        # The title bar floats above the window's own widget, so it needs to paint its own backdrop.
        self._backdrop = QWidget(self)
        self._backdrop.setObjectName("titleBarBackground")
        self._backdrop.lower()

    def _add_content(self, content: QWidget) -> None:
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hBoxLayout.insertWidget(0, content, 1, Qt.AlignmentFlag.AlignVCenter)
        # The base title bar keeps a stretch of its own, which would leave the content half a bar wide.
        for position in range(self.hBoxLayout.count()):
            if self.hBoxLayout.itemAt(position).spacerItem() is not None:
                self.hBoxLayout.setStretch(position, 0)

    @staticmethod
    def _mark(size: int) -> QLabel:
        """The brand mark, since a frameless title bar draws none of the window's own chrome."""
        mark = QLabel()
        mark.setObjectName("titleMark")
        mark.setPixmap(app_glyph(size))
        mark.setFixedSize(size, size)
        mark.setCursor(Qt.CursorShape.ArrowCursor)
        return mark

    def _paint_buttons(self) -> None:
        """Caption buttons keep their own size"""
        for button in (self.minBtn, self.maxBtn, self.closeBtn):
            button.setFixedSize(self._button_size)
            button.setIconSize(self._button_size)
            self.hBoxLayout.setAlignment(button, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for button in (self.minBtn, self.maxBtn):
            button.setNormalColor(QColor(TEXT))
            button.setNormalBackgroundColor(QColor(0, 0, 0, 0))
            button.setHoverColor(QColor(TEXT))
            button.setHoverBackgroundColor(QColor(PANEL_2))
            button.setPressedColor(QColor(TEXT))
            button.setPressedBackgroundColor(QColor(LINE))

        self.closeBtn.setNormalColor(QColor(TEXT))
        self.closeBtn.setNormalBackgroundColor(QColor(0, 0, 0, 0))
        self.closeBtn.setHoverColor(QColor(PANEL))
        self.closeBtn.setHoverBackgroundColor(QColor(CLOSE_HOVER))
        self.closeBtn.setPressedColor(QColor(PANEL))
        self.closeBtn.setPressedBackgroundColor(QColor(CLOSE_PRESS))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._backdrop.setGeometry(0, 0, self.width(), self.height())


class ApplicationTitleBar(_ThemedTitleBar):
    """Carries the brand, the search box, and the caption buttons."""

    def __init__(self, parent):
        super().__init__(parent, TITLE_BAR_HEIGHT, CAPTION_BUTTON_SIZE)

        brand = QLabel(f'Delta<span style="color: {ACCENT}">Music</span>')
        brand.setObjectName("brand")
        brand.setTextFormat(Qt.TextFormat.RichText)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search songs, artists, playlists")
        self.search.setFixedWidth(420)

        self.devices = QPushButton()
        self.devices.setObjectName("iconButton")
        self.devices.setIcon(icon("devices", TEXT, DEVICES_ICON_SIZE))
        self.devices.setToolTip("Devices")
        self.devices.setFixedSize(30, 26)
        self.devices.setCursor(Qt.CursorShape.PointingHandCursor)

        self.settings = QPushButton()
        self.settings.setObjectName("iconButton")
        self.settings.setIcon(icon("settings", TEXT, DEVICES_ICON_SIZE))
        self.settings.setToolTip("Settings")
        self.settings.setFixedSize(30, 26)
        self.settings.setCursor(Qt.CursorShape.PointingHandCursor)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        content = QWidget(self)
        row = QHBoxLayout(content)
        row.setContentsMargins(16, 0, 12, 0)
        row.setSpacing(16)
        row.addWidget(self._mark(BRAND_MARK_SIZE))
        row.addWidget(brand)
        row.addSpacing(BRAND_CLEARANCE)
        row.addWidget(self.search)
        row.addWidget(self.devices)
        row.addWidget(self.settings)
        row.addStretch(1)
        row.addWidget(self.status)

        self._add_content(content)
        self._paint_buttons()
        # The brand and the status line are labels on a draggable bar, and would otherwise take its cursor.
        for label in (brand, self.status):
            label.setCursor(Qt.CursorShape.ArrowCursor)


class DialogTitleBar(_ThemedTitleBar):
    """The window title and a close button"""

    def __init__(self, parent):
        super().__init__(parent, DIALOG_TITLE_BAR_HEIGHT, DIALOG_BUTTON_SIZE)
        self.setDoubleClickEnabled(False)
        self.minBtn.hide()
        self.maxBtn.hide()

        self._title = QLabel(parent.windowTitle())
        self._title.setObjectName("dialogTitle")

        content = QWidget(self)
        row = QHBoxLayout(content)
        row.setContentsMargins(14, 0, 10, 0)
        row.setSpacing(8)
        row.addWidget(self._mark(DIALOG_MARK_SIZE))
        row.addWidget(self._title)
        row.addStretch(1)

        self._add_content(content)
        self._paint_buttons()
        self._title.setCursor(Qt.CursorShape.ArrowCursor)

    def setTitle(self, title: str) -> None:
        self._title.setText(title)
