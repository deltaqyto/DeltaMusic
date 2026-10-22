"""Where the program keeps its files, and the move of an older layout's config into `config/`."""

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

FROZEN = getattr(sys, "frozen", False)

# A frozen build's code is read-only and may sit in a temporary folder
PROJECT_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def adopt(*files: Path) -> None:
    """Creates `config/` and moves each of `files` there if a copy is still sitting in the project root.

    Each entry point names the files it owns, so running one does not touch another's config.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as failure:
        log.warning("could not create %s: %s", CONFIG_DIR, failure)
        return

    for destination in files:
        legacy = PROJECT_ROOT / destination.name
        if legacy == destination or not legacy.is_file() or destination.exists():
            continue
        try:
            legacy.replace(destination)
        except OSError as failure:
            log.warning("could not move %s into %s: %s", legacy, CONFIG_DIR, failure)
            continue
        log.info("moved %s into %s", legacy.name, CONFIG_DIR)
