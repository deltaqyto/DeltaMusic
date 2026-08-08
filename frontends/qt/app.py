import ctypes
import logging
import sys

from PyQt6.QtWidgets import QApplication

from frontends.core_client import CoreClient
from frontends.qt.icons import app_icon
from frontends.qt.main_window import MainWindow

log = logging.getLogger(__name__)

APP_ID = "DeltaMusic.Player"


class QtFrontend:
    """A bundled desktop app"""

    def __init__(self, client: CoreClient):
        self._client = client
        self._app: QApplication | None = None
        self._window: MainWindow | None = None

    def run(self) -> int:
        _claim_taskbar_identity()
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("DeltaMusic")
        self._app.setWindowIcon(app_icon())
        self._window = MainWindow(self._client)
        self._window.show()
        return self._app.exec()

    def stop(self) -> None:
        if self._app is not None:
            self._app.quit()


def _claim_taskbar_identity() -> None:
    """Without an explicit app id, Windows groups the window under the host python and shows its icon on the taskbar."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError) as failure:
        log.debug("could not claim a taskbar identity: %s", failure)
