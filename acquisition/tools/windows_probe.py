"""Scan all audio devices to work out which one is playing audio

For windows only.

Run it with audio playing (only the app that is being targeted):
    python -m acquisition.tools.windows_probe                # every input device
    python -m acquisition.tools.windows_probe --match CABLE  # only matching names
"""

from __future__ import annotations

import argparse
import sys
import threading
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from ..backends.windows.devices import DeviceInfo, list_input_devices

# Host APIs in descending order of preference for capture work.
#   WASAPI is shared-mode and rate-matched
#   DirectSound resamples
#   MME is 16-bit and slow
#   WDM-KS is the lowest latency but refuses to open if the pin is busy.
HOSTAPI_PREFERENCE = ("WASAPI", "WDM-KS", "DirectSound", "MME")


@dataclass(frozen=True)
class ProbeResult:
    device: DeviceInfo
    ok: bool
    peak: float = 0.0
    rms: float = 0.0
    error: Optional[str] = None

    @property
    def peak_dbfs(self) -> float:
        return 20.0 * np.log10(self.peak) if self.peak > 0 else -np.inf

    @property
    def has_signal(self) -> bool:
        # -60 dBFS is comfortably above a dithered digital-silence floor
        return self.ok and self.peak > 10 ** (-60 / 20)

    def describe(self) -> str:
        if not self.ok:
            return f"  FAILED   {self.device}\n           {self.error}"
        level = "SIGNAL " if self.has_signal else "silence"
        return (
            f"  {level}  {self.device}\n"
            f"           peak {self.peak_dbfs:6.1f} dBFS   rms {self.rms:.6f}"
        )


def probe_device(device: DeviceInfo, seconds: float = 1.0) -> ProbeResult:
    """Open ``device`` briefly and measure the level it delivers."""
    try:
        import sounddevice as sd
    except Exception as exc:  # pragma: no cover
        return ProbeResult(device, ok=False, error=f"sounddevice unavailable: {exc}")

    channels = min(2, device.max_input_channels)
    samplerate = int(round(device.default_samplerate))
    frames_wanted = max(1, int(seconds * samplerate))
    collected: List[np.ndarray] = []
    done = threading.Event()

    def callback(indata, frames, time_info, status):  # noqa: ANN001, ARG001
        collected.append(np.array(indata, dtype=np.float32, copy=True))
        if sum(block.shape[0] for block in collected) >= frames_wanted:
            done.set()

    try:
        with sd.InputStream(
            device=device.index,
            samplerate=samplerate,
            channels=channels,
            dtype="float32",
            latency="high",
            callback=callback,
        ):
            done.wait(timeout=seconds + 2.0)
    except Exception as exc:
        return ProbeResult(device, ok=False, error=str(exc))

    if not collected:
        return ProbeResult(device, ok=False, error="device delivered no audio")
    audio = np.concatenate(collected, axis=0)[:frames_wanted]
    if audio.size == 0:
        return ProbeResult(device, ok=False, error="device returned no frames")
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    return ProbeResult(
        device=device,
        ok=True,
        peak=float(np.max(np.abs(audio))),
        rms=float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))),
    )


def probe_all(match: Optional[str] = None, seconds: float = 1.0) -> List[ProbeResult]:
    """Probe every input device, optionally filtered by name substring. Ignores microphones (obviously)"""
    devices = [d for d in list_input_devices() if "microphone" not in d.name.casefold()]
    if match:
        needle = match.casefold()
        devices = [d for d in devices if needle in d.name.casefold()]
    return [probe_device(d, seconds) for d in devices]


def rank(results: List[ProbeResult]) -> List[ProbeResult]:
    """Order live devices best-first: loudest signal, then host API quality."""

    def key(result: ProbeResult):
        try:
            api_rank = next(
                i
                for i, name in enumerate(HOSTAPI_PREFERENCE)
                if name.casefold() in result.device.hostapi.casefold()
            )
        except StopIteration:
            api_rank = len(HOSTAPI_PREFERENCE)
        return not result.has_signal, api_rank, -result.rms

    return sorted(results, key=key)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--match", help="only probe devices whose name contains this")
    parser.add_argument(
        "--seconds", type=float, default=1.0, help="listen time per device"
    )
    args = parser.parse_args(argv)

    if args.seconds <= 0 or args.seconds > 30:
        parser.error("--seconds must be in (0, 30]")

    print("Probing input devices - make sure audio is playing.\n")
    results = rank(probe_all(args.match, args.seconds))
    if not results:
        print("No input devices matched.")
        return 1

    for result in results:
        print(result.describe())

    live = [r for r in results if r.has_signal]
    print()
    if not live:
        print("Nothing carrying audio. Is the player actually routed to a cable?")
        return 1

    best = live[0]
    print(f"Best candidate: {best.device.name!r} on {best.device.hostapi}")
    print("Put that in config/acquisition_config.json as device / hostapi.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
