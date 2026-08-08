"""Acquire tracks: watch a media session, record from an audio source.

    python acquire.py  # run with config/acquisition_config.json
    python acquire.py --list-devices  # show input devices and exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Optional, Sequence

from acquisition import DEFAULT_CONFIG_PATH, AcquisitionConfig, run, select
from paths import adopt

log = logging.getLogger("acquisition")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def show_devices(backend_name: Optional[str]) -> int:
    try:
        backend = select(backend_name)
        devices = backend.describe_devices()
    except ValueError as exc:
        print(f"could not enumerate devices: {exc}", file=sys.stderr)
        return 2

    if not devices:
        print(f"the {backend.name} backend reports no selectable input devices")
        return 0
    for device in devices:
        print(f"  {device}")
    if backend.name == "windows":
        print("\nProbe them with audio playing: python -m acquisition.tools.windows_probe")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--backend",
        default=None,
        help="force an acquisition backend instead of detecting one",
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="list input devices and exit"
    )
    args = parser.parse_args(argv)

    if args.list_devices:
        configure_logging("WARNING")
        return show_devices(args.backend)

    adopt(DEFAULT_CONFIG_PATH)
    try:
        config = AcquisitionConfig.load(DEFAULT_CONFIG_PATH)
    except (ValueError, OSError) as exc:
        configure_logging("INFO")
        log.error("bad config: %s", exc)
        return 2

    if args.backend:
        config.backend = args.backend

    configure_logging(config.log_level)
    log.debug("config loaded from %s", DEFAULT_CONFIG_PATH)

    try:
        return asyncio.run(run(config))
    except KeyboardInterrupt:  # raised before the loop is established
        return 130


if __name__ == "__main__":
    sys.exit(main())
