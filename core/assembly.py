from core.config import Config
from core.event_bus import EventBus
from core.library.library import Library
from core.playback.controller import PlaybackController
from core.playback.engine import PlaybackEngine
from core.playback.sounddevice_engine import SoundDeviceEngine
from core.runtime import Runtime
from core.service import CoreService
from core.session import SessionMemory


def build_core(config: Config, engine: PlaybackEngine | None = None) -> CoreService:
    """Wires core up and hands back the only surface a transport touches."""
    engine = engine or SoundDeviceEngine()

    bus = EventBus()
    memory = SessionMemory()
    library = Library(config.database_path, config.library_path, bus)
    controller = PlaybackController(library, engine, bus, config.initial_volume)
    runtime = Runtime(library, controller, bus, config.audio_extensions, memory)

    # The engine reports on its own thread.
    engine.on_ended(lambda: runtime.post(controller.on_track_ended))
    engine.on_failed(lambda message: runtime.post(lambda: controller.on_track_failed(message)))

    return CoreService(library, controller, runtime, bus, memory)
