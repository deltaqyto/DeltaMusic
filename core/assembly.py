import logging

from core.config import Config
from core.event_bus import EventBus
from core.library.library import Library
from core.peer.discovery import Discovery
from core.peer.identity import CoreIdentity
from core.peer.jobs import PeerJobs
from core.peer.pairing import Pairing
from core.peer.registry import PeerRegistry
from core.peer.server import PeerServer
from core.peer.transfers import Transfers
from core.peer.types.peer_side import PeerSide
from core.playback.controller import PlaybackController
from core.playback.engine import PlaybackEngine
from core.playback.sounddevice_engine import SoundDeviceEngine
from core.runtime import Runtime
from core.service import CoreService
from core.session import SessionMemory
from entry.paths import CONFIG_DIR
from protocol.types.shuffle_method import ShuffleMethod

log = logging.getLogger(__name__)


def build_core(config: Config, engine: PlaybackEngine | None = None) -> CoreService:
    """Wires core up and hands back the only surface a transport touches."""
    engine = engine or SoundDeviceEngine()

    bus = EventBus()
    memory = SessionMemory()
    library = Library(config.database_path, config.library_path, bus, config.private_library)
    controller = PlaybackController(library, engine, bus, config.initial_volume, ShuffleMethod(config.shuffle_method))
    runtime = Runtime(library, controller, bus, config.audio_extensions, memory)

    # The engine reports on its own thread.
    engine.on_ended(lambda: runtime.post(controller.on_track_ended))
    engine.on_failed(lambda message: runtime.post(lambda: controller.on_track_failed(message)))

    peer = _build_peer(config, bus, library, runtime)
    service = CoreService(library, controller, runtime, bus, memory, config, peer, _features(config))
    if peer is not None:
        server = PeerServer(service, peer.identity, peer.registry, peer.discovery, peer.pairing, config.peer_port)
        service.use_peer_server(server)
    return service


def _features(config: Config) -> list[str]:
    """What `get_state` names as true of this core."""
    return ["private_library"] if config.private_library else []


def _build_peer(config: Config, bus: EventBus, library: Library, runtime: Runtime) -> PeerSide | None:
    if not config.peer_enabled:
        return None
    try:
        identity = CoreIdentity(CONFIG_DIR, config.core_name)
        registry = PeerRegistry(CONFIG_DIR, identity, bus)
        discovery = Discovery(identity, config.peer_port)
        pairing = Pairing(identity, registry, discovery, bus, config.peer_port, config.visibility_seconds)
        discovery.watch(pairing.discovered)
        transfers = Transfers(library, runtime, config.max_concurrent_transfers)
        jobs = PeerJobs(library, runtime, identity, registry, discovery, transfers, bus, config.transfer_space_reserve_bytes)
        return PeerSide(identity, registry, discovery, pairing, transfers, jobs)
    except Exception:
        # A core with no usable identity still plays music.
        log.exception("peer support is off")
        return None
