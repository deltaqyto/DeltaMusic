import logging
import socket
import threading
from collections.abc import Callable

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from core.peer.identity import CoreIdentity
from protocol.types.pairing_candidate import PairingCandidate
from protocol.version import PEER_PROTOCOL_VERSION

log = logging.getLogger(__name__)

SERVICE_TYPE = "_deltamusic-peer._tcp.local."
RESOLVE_TIMEOUT_MS = 3000

# Connecting a datagram socket sends nothing, and picks the interface the network is reached over.
ROUTE_PROBE = ("192.0.2.1", 9)


class Discovery(ServiceListener):
    """Advertises this core's peer service and browses for others. Owns the TXT record and the visibility flag."""

    def __init__(self, identity: CoreIdentity, port: int, on_change: Callable[[], None] | None = None):
        self._identity = identity
        self._port = port
        self._on_change = on_change or (lambda: None)

        self._lock = threading.Lock()
        self._advertising = threading.Lock()
        self._found: dict[str, PairingCandidate] = {}
        self._names: dict[str, str] = {}
        self._pairing = False

        self._zeroconf: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self._info: ServiceInfo | None = None

    # Lifecycle

    def start(self) -> None:
        if self._zeroconf is not None:
            return
        self._zeroconf = Zeroconf()
        self._info = self._service_info()
        if self._info is not None:
            try:
                self._zeroconf.register_service(self._info, allow_name_change=True)
            except Exception:
                log.exception("could not advertise the peer service")
                self._info = None
        self._browser = ServiceBrowser(self._zeroconf, SERVICE_TYPE, self)

    def stop(self) -> None:
        # Waits out a flip that is mid-flight, so the goodbye is the last thing this core puts on the wire.
        with self._advertising:
            zeroconf, browser, info = self._zeroconf, self._browser, self._info
            self._zeroconf, self._browser, self._info = None, None, None
            if zeroconf is None:
                return
            try:
                if browser is not None:
                    browser.cancel()
                if info is not None:
                    zeroconf.unregister_service(info)
            except Exception:
                log.exception("could not withdraw the peer service")
            zeroconf.close()

    def watch(self, on_change: Callable[[], None]) -> None:
        """Whoever draws the candidate list is called whenever what was found changes."""
        self._on_change = on_change

    # Advertising

    @property
    def pairing(self) -> bool:
        return self._pairing

    def set_pairing(self, open_window: bool) -> None:
        if open_window == self._pairing:
            return
        self._pairing = open_window
        self._readvertise()

    # Browsing

    def candidates(self) -> list[PairingCandidate]:
        with self._lock:
            return sorted(self._found.values(), key=lambda candidate: (candidate.name, candidate.id))

    def find(self, core_id: str) -> PairingCandidate | None:
        with self._lock:
            return self._found.get(core_id)

    def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        self._take(zeroconf, type_, name)

    def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        self._take(zeroconf, type_, name)

    def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        with self._lock:
            core_id = self._names.pop(name, None)
            if core_id is None:
                return
            self._found.pop(core_id, None)
        self._on_change()

    # Internals

    def _take(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        info = zeroconf.get_service_info(type_, name, RESOLVE_TIMEOUT_MS)
        candidate = _candidate_in(info) if info is not None else None
        if candidate is None or candidate.id == self._identity.uuid:
            return
        with self._lock:
            self._names[name] = candidate.id
            if self._found.get(candidate.id) == candidate:
                return
            self._found[candidate.id] = candidate
        self._on_change()

    def _readvertise(self) -> None:
        """Off the caller's thread, since probing and announcing take seconds and the runtime thread is behind a flip."""
        threading.Thread(target=self._reannounce, name="peer-advertise", daemon=True).start()

    def _reannounce(self) -> None:
        with self._advertising:
            zeroconf, held = self._zeroconf, self._info
            if zeroconf is None or held is None:
                return
            # The properties are read here, so a flip queued behind another one announces the state the core is in now.
            info = self._service_info(held.name)
            if info is None:
                return
            try:
                # A TXT record updated in place reaches a responder that only reports an instance appearing and going away, and it never re-resolves. So the instance is withdrawn and announced again.
                zeroconf.unregister_service(held)
                zeroconf.register_service(info, allow_name_change=True)
                self._info = info
            except Exception:
                log.exception("could not announce the peer service again")

    def _service_info(self, name: str | None = None) -> ServiceInfo | None:
        addresses = _local_addresses()
        if not addresses:
            log.warning("this machine has no address to advertise the peer service on")
            return None
        return ServiceInfo(
            SERVICE_TYPE,
            name or f"{self._identity.uuid}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(address) for address in addresses],
            port=self._port,
            properties=self._properties(),
            server=f"{self._identity.uuid}.local.",
        )

    def _properties(self) -> dict[str, str]:
        return {
            "id": self._identity.uuid,
            "name": self._identity.name,
            "fp": self._identity.fingerprint,
            "pairing": "open" if self._pairing else "closed",
            "v": str(PEER_PROTOCOL_VERSION),
        }


def _candidate_in(info: ServiceInfo) -> PairingCandidate | None:
    properties = {_text(key): _text(value) for key, value in (info.properties or {}).items()}
    addresses = info.parsed_addresses()
    core_id = properties.get("id")
    if not core_id or not addresses or not info.port:
        return None
    try:
        version = int(properties.get("v") or PEER_PROTOCOL_VERSION)
    except ValueError:
        return None
    return PairingCandidate(
        id=core_id,
        name=properties.get("name") or core_id,
        fingerprint=properties.get("fp") or "",
        address=addresses[0],
        port=info.port,
        pairing=properties.get("pairing") == "open",
        version=version,
    )


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value is None else str(value)


def _local_addresses() -> list[str]:
    """The IPv4 addresses this core is reachable at, the one carrying the default route first."""
    found: list[str] = []
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(ROUTE_PROBE)
        found.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    try:
        found.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass

    addresses: list[str] = []
    for address in found:
        if address not in addresses and not address.startswith(("127.", "169.254.")):
            addresses.append(address)
    return addresses
