from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from frontends.qt.style import ACCENT, DIM

APP_ICON_FILE = Path(__file__).resolve().parent / "assets" / "icon.svg"
# Windows picks a size per surface, and scaling one bitmap to the rest of them looks it.
APP_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Handy icons, drawn from paths
_STROKE = {
    "shuffle": '<path d="M16 3h5v5"/><path d="M4 20 21 3"/><path d="M21 16v5h-5"/><path d="m15 15 6 6"/><path d="M4 4l5 5"/>',
    "repeat": '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    "repeat_one": '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10h1v5"/>',
    "volume": '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a9 9 0 0 1 0 14"/>',
    "muted": '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="m17 9 5 6"/><path d="m22 9-5 6"/>',
    "queue_add": '<path d="M3 6h9"/><path d="M3 12h9"/><path d="M3 18h9"/><path d="m16 8 4 4-4 4"/>',
    "close": '<path d="m6 6 12 12"/><path d="m18 6-12 12"/>',
    "grip": '<path d="M7 10h10"/><path d="M7 14h10"/>',
    "devices": '<rect x="2" y="4" width="13" height="9" rx="1"/><path d="M2 17h13"/><rect x="17" y="8" width="5" height="11" rx="1"/>',
    "settings": '<path d="M21 4h-7"/><path d="M10 4H3"/><path d="M21 12h-9"/><path d="M8 12H3"/><path d="M21 20h-5"/><path d="M12 20H3"/><path d="M14 2v4"/><path d="M8 10v4"/><path d="M16 18v4"/>',
    "chevron_right":'<path d="m9 5 7 7-7 7"/>',
    "chevron_down": '<path d="m5 9 7 7 7-7"/>',
}

_FILLED = {
    "previous": '<path d="M6 5h2v14H6zM20 5v14L9 12z"/>',
    "next": '<path d="M16 5h2v14h-2zM4 5v14l11-7z"/>',
    "play": '<path d="M8 5v14l11-7z"/>',
    "pause": '<path d="M7 4h4v16H7zM13 4h4v16h-4z"/>',
}


def glyph(name: str, colour: str = DIM, size: int = 16) -> QPixmap:
    """The drawn icon itself, for delegates that paint into a cell rather than dress a button."""
    if name in _FILLED:
        body = f'<g fill="{colour}">{_FILLED[name]}</g>'
    else:
        body = (
            f'<g fill="none" stroke="{colour}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round">{_STROKE[name]}</g>'
        )
    markup = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" height="{size}">{body}</svg>'
    renderer = QSvgRenderer(QByteArray(markup.encode("ascii")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def icon(name: str, colour: str = DIM, size: int = 16) -> QIcon:
    return QIcon(glyph(name, colour, size))


def accent_icon(name: str, size: int = 16) -> QIcon:
    return icon(name, ACCENT, size)


def app_glyph(size: int) -> QPixmap:
    """The brand mark at one size, or an empty pixmap if the file has gone missing."""
    renderer = QSvgRenderer(str(APP_ICON_FILE))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    if not renderer.isValid():
        return pixmap
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    built = QIcon()
    for size in APP_ICON_SIZES:
        built.addPixmap(app_glyph(size))
    return built
