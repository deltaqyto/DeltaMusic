import logging
import sys
import threading
from collections.abc import Callable

from core.assembly import build_core
from core.config import CONFIG_FILE, load_or_create
from core.service import CoreService
from frontends.core_client import CoreClient
from frontends.frontend import Frontend
from frontends.settings import SETTINGS_FILE
from entry.paths import adopt

log = logging.getLogger(__name__)

# Qt must own the main thread, so it runs in the foreground and anything else is threaded behind it.
FOREGROUND = "qt"


def _build_frontend(name: str, client: CoreClient) -> Frontend:
    if name == "qt":
        from frontends.qt.app import QtFrontend

        return QtFrontend(client)
    raise ValueError(f"no frontend named '{name}'")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    adopt(CONFIG_FILE, SETTINGS_FILE)
    config = load_or_create()

    service: CoreService = build_core(config)
    service.start()

    names = list(config.frontends)
    if not names:
        log.error("%s lists no frontends", CONFIG_FILE)
        service.stop()
        return 1

    foreground = FOREGROUND if FOREGROUND in names else names[0]
    background = [name for name in names if name != foreground]

    running: list[Frontend] = []
    threads: list[threading.Thread] = []
    try:
        for name in background:
            frontend = _build_frontend(name, CoreClient(service, name))
            running.append(frontend)
            thread = threading.Thread(target=frontend.run, name=f"frontend-{name}", daemon=True)
            thread.start()
            threads.append(thread)

        main_frontend = _build_frontend(foreground, CoreClient(service, foreground))
        running.append(main_frontend)
        return main_frontend.run() or 0
    finally:
        for frontend in running:
            _quietly(frontend.stop)
        service.stop()


def _quietly(work: Callable[[], None]) -> None:
    try:
        work()
    except Exception:
        log.exception("a frontend did not shut down cleanly")


if __name__ == "__main__":
    sys.exit(main())
