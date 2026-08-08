from __future__ import annotations

import asyncio
import logging

from .config import AcquisitionConfig
from .controller import RecordingController
from .encoding.formats import resolve, validate
from .errors import CaptureError
from .registry import select
from .saver import SaveWorker

log = logging.getLogger(__name__)


async def run(config: AcquisitionConfig) -> int:
    """Run until interrupted. Returns a process exit code."""
    try:
        backend_class = select(config.backend)
        backend = backend_class(config.settings_for(backend_class.name))
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    audio = backend.create_audio_source()
    try:
        source = audio.open()
    except CaptureError as exc:
        log.error("%s", exc)
        if backend.name == "windows":
            log.error("Run 'python -m acquisition.tools.windows_probe' to find the device.")
        return 2

    # The encoder's constraints depend on the rate the source settled on, so this can only be checked now.
    encoding = resolve(config.container, config.subtype)
    try:
        validate(encoding, audio.samplerate, audio.channels)
    except CaptureError as exc:
        log.error("%s", exc)
        audio.close()
        return 2

    save_path = config.save_path
    save_path.mkdir(parents=True, exist_ok=True)

    session = backend.create_session_source(config.app_id)

    log.info("backend %s", backend.name)
    log.info("capturing %s", source)
    log.info("watching %s", session.describe())
    log.info("saving to %s as %s", save_path, encoding)

    saver = SaveWorker()
    saver.start()
    controller = RecordingController(config, audio, saver)

    try:
        while True:
            controller.handle(await session.read())
            await asyncio.sleep(config.poll_interval)
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("stopping")
    finally:
        # Idle the source first, then drain the encoder, then release the device.
        controller.shutdown()
        saver.close()
        await session.close()
        audio.close()
        log.info("%s", controller.stats)
        if audio.xruns:
            log.warning("%d stream dropout(s) during this run", audio.xruns)
    return 0
