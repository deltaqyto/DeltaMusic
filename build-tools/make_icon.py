"""Render the brand mark into a multi-size .ico for the executables
"""

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QBuffer, QByteArray, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

from frontends.qt.icons import APP_ICON_FILE, APP_ICON_SIZES

# Windows reads a 256px entry only as an embedded PNG
HEADER = struct.Struct("<HHH")
ENTRY = struct.Struct("<BBBBHHII")


def render(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def build(sizes: list[int]) -> bytes:
    renderer = QSvgRenderer(str(APP_ICON_FILE))
    if not renderer.isValid():
        raise SystemExit(f"could not read {APP_ICON_FILE}")

    frames = [render(renderer, size) for size in sizes]
    offset = HEADER.size + ENTRY.size * len(frames)

    directory = bytearray(HEADER.pack(0, 1, len(frames)))
    for size, frame in zip(sizes, frames):
        directory += ENTRY.pack(size % 256, size % 256, 0, 0, 1, 32, len(frame), offset)
        offset += len(frame)
    return bytes(directory) + b"".join(frames)


def main(argv: list[str]) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QGuiApplication(argv[:1])

    destination = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent / "icon.ico"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(build(list(APP_ICON_SIZES)))
    print(f"wrote {destination}")

    application.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
