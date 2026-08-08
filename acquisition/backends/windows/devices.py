"""Input-device discovery and resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Union

from ...errors import DeviceNotFoundError


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    default_samplerate: float

    def __str__(self) -> str:  # pragma: no cover
        return f"[{self.index}] {self.name} ({self.hostapi}, {self.max_input_channels}ch)"


def _sd():
    """Import sounddevice lazily so importing the backend never hard-fails."""
    try:
        import sounddevice  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - environment dependent
        raise DeviceNotFoundError(
            "the 'sounddevice' package is required for audio capture "
            "(pip install sounddevice)"
        ) from exc
    return sounddevice


def list_input_devices() -> List[DeviceInfo]:
    """Return every device exposing at least one input channel."""
    sd = _sd()
    hostapis = sd.query_hostapis()
    out: List[DeviceInfo] = []
    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        api = hostapis[dev["hostapi"]]["name"] if dev["hostapi"] < len(hostapis) else "?"
        out.append(
            DeviceInfo(
                index=index,
                name=dev["name"],
                hostapi=api,
                max_input_channels=int(dev["max_input_channels"]),
                default_samplerate=float(dev["default_samplerate"]),
            )
        )
    return out


def find_device(
    spec: Optional[Union[str, int]],
    hostapi: Optional[str] = None,
) -> DeviceInfo:
    """Resolve `spec` (an index, a case-insensitive name substring, or `None` for the system default) to exactly one input device.
    """
    devices = list_input_devices()
    if not devices:
        raise DeviceNotFoundError("no input devices are available")

    if hostapi:
        needle_api = hostapi.strip().casefold()
        filtered = [d for d in devices if needle_api in d.hostapi.casefold()]
        if not filtered:
            available = sorted({d.hostapi for d in devices})
            raise DeviceNotFoundError(
                f"no input device uses host API {hostapi!r}; available: "
                + ", ".join(available)
            )
        devices = filtered

    if spec is None:
        sd = _sd()
        default_index = sd.default.device[0]
        if default_index is None or default_index < 0:
            raise DeviceNotFoundError("no default input device is configured")
        return _by_index(devices, int(default_index))

    if isinstance(spec, int) or (isinstance(spec, str) and spec.lstrip("-").isdigit()):
        return _by_index(devices, int(spec))

    if not isinstance(spec, str):
        raise DeviceNotFoundError(f"unusable device spec: {spec!r}")

    needle = spec.strip().casefold()
    if not needle:
        raise DeviceNotFoundError("device name is empty")

    exact = [d for d in devices if d.name.casefold() == needle]
    matches = exact or [d for d in devices if needle in d.name.casefold()]

    if not matches:
        raise DeviceNotFoundError(
            f"no input device matches {spec!r}. Available:\n  "
            + "\n  ".join(str(d) for d in devices)
        )
    if len(matches) > 1:
        raise DeviceNotFoundError(
            f"{spec!r} is ambiguous - {len(matches)} devices match:\n  "
            + "\n  ".join(str(d) for d in matches)
            + "\nNarrow it with hostapi= (e.g. 'WASAPI', 'WDM-KS', 'DirectSound')."
        )
    return matches[0]


def _by_index(devices: List[DeviceInfo], index: int) -> DeviceInfo:
    for dev in devices:
        if dev.index == index:
            return dev
    raise DeviceNotFoundError(
        f"device index {index} is not an input device. Available:\n  "
        + "\n  ".join(str(d) for d in devices)
    )
