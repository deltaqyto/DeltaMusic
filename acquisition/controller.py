"""The state machine tying the media session to the recorder.

Because it's not guaranteed for a media session to refresh its name and its timeline at once,
a single observation can mix the new track's title with the old track's timeline, or the reverse.

A reading is therefore identified by title, artist and duration together,
acted on only after a second consecutive poll reports the same triple,
and held back entirely while only one of the two halves has moved on.
(with a bound, since two adjacent tracks may actually share a duration)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from .analysis import silent_fraction
from .config import AcquisitionConfig
from .errors import CaptureError
from .interfaces import AudioSource
from .saver import SaveJob, SaveWorker
from .types import TrackInfo, TrackMetadata

log = logging.getLogger(__name__)

# Title, artist and duration. It is extremely rare to have two adjacent tracks be the same length to the subsecond.
Identity = Tuple[str, str, timedelta]


@dataclass
class Stats:
    started: int = 0
    saved: int = 0
    rejected: int = 0
    missed: int = 0

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"{self.saved} saved, {self.rejected} rejected, "
            f"{self.missed} missed, {self.started} started"
        )


def _mmss(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def _identity(track: TrackInfo) -> Identity:
    return track.title, track.artist, track.duration


class RecordingController:
    """Drives one AudioSource from a stream of TrackInfo."""

    def __init__(
        self,
        config: AcquisitionConfig,
        audio: AudioSource,
        saver: SaveWorker,
    ) -> None:
        self._config = config
        self._audio = audio
        self._saver = saver
        self.stats = Stats()

        # The reading accepted as coherent, and the latest snapshot of it.
        self._committed: Optional[Identity] = None
        self._current: Optional[TrackInfo] = None

        # A candidate awaiting its confirming poll.
        self._pending: Optional[Identity] = None
        self._pending_polls = 0

        # Polls spent holding a reading whose halves disagree, capped at about a second's worth.
        self._mixed_polls = 0
        self._mixed_limit = max(2, int(round(1.0 / config.poll_interval)))

        # Where the audio now being recorded begins, back-dated by the pre-roll granted. The captured length is judged against this.
        self._recording_started_at: Optional[datetime] = None

        # Track given up on until the player moves off it.
        self._blocked: Optional[Identity] = None
        self._seen_any = False

        # The source's real reach-back, less a margin so a request never lands on the buffer edge.
        self._prebuffer_ms = audio.prebuffer_ms
        self._max_offset_ms = self._prebuffer_ms - 50.0

    def handle(self, track: Optional[TrackInfo]) -> None:
        """Feed one observation into the state machine. Never raises."""
        try:
            self._handle(track)
        except CaptureError:
            log.exception("capture error; dropping the current recording")
            self._reject("internal capture error")
        except Exception:
            log.exception("controller error; dropping the current recording")
            self._reject("internal error")

    def _handle(self, track: Optional[TrackInfo]) -> None:
        if track is None:
            self._reject("media session ended")
            self._forget()
            return

        # Sessions briefly report blank properties mid-transition.
        if not track.is_identified:
            return

        identity = _identity(track)

        # Detect and handle partially stale polls
        if self._committed is not None and identity != self._committed:
            name_moved = identity[:2] != self._committed[:2]
            duration_moved = identity[2] != self._committed[2]
            if name_moved != duration_moved and self._mixed_polls < self._mixed_limit:
                self._mixed_polls += 1
                log.debug(
                    "half-refreshed reading %r dur=%.3fs; waiting for the other half",
                    track.title,
                    track.duration.total_seconds(),
                )
                return
        self._mixed_polls = 0

        if identity == self._committed:
            self._pending = None
            self._pending_polls = 0
            self._continue(track)
            return

        # Anything else is a candidate, and needs a confirming poll before it is believed.
        if identity != self._pending:
            self._pending = identity
            self._pending_polls = 1
            log.debug(
                "unconfirmed reading %r dur=%.3fs; awaiting a second poll",
                track.title,
                track.duration.total_seconds(),
            )
            return

        self._pending_polls += 1
        if self._pending_polls < 2:
            return

        self._pending = None
        self._pending_polls = 0
        self._commit(track, identity)

    def _commit(self, track: TrackInfo, identity: Identity) -> None:
        """Act on a valid reading"""
        log.info(
            "TRACK CHANGE  %s - %s  pos=%.3fs dur=%.3fs reported_pos=%.3fs",
            track.artist,
            track.title,
            track.effective_position().total_seconds(),
            track.duration.total_seconds(),
            track.position.total_seconds(),
        )

        previous_committed = self._committed
        self._committed = identity

        # Whatever is playing at startup has potentially dirty audio or incomplete capture.
        # Ignore it
        if not self._seen_any:
            self._seen_any = True
            self._blocked = identity
            log.info(
                "joined %s - %s already in progress; waiting for the next track",
                track.artist,
                track.title,
            )
            return

        if self._current is not None and previous_committed is not None:
            self._changeover(track)
        else:
            self._maybe_start(track)

    def _continue(self, track: TrackInfo) -> None:
        """The committed track, observed again."""
        if self._current is None:
            return
        if not track.is_playing:
            position = track.effective_position().total_seconds()
            duration = track.duration.total_seconds()
            self._reject(f"paused at {_mmss(position)} of {_mmss(duration)}")
            self._blocked = self._committed
            return
        self._current = track

    def _changeover(self, track: TrackInfo) -> None:
        """A confirmed different track, while one was being recorded."""
        previous = self._current
        assert previous is not None
        now = datetime.now(timezone.utc)

        # The new track's position says how long ago the change happened. Use it to backdate to the correct start moment (~400ms ago, usually)
        elapsed = track.effective_position(now).total_seconds()
        changed_at = now - timedelta(seconds=elapsed)
        remaining = previous.remaining(changed_at).total_seconds()
        duration = previous.duration.total_seconds()

        # There is no session event for 'the track finished', so completion is inferred from how close to its own duration the outgoing track got.
        completed = duration > 0 and remaining <= self._config.completion_tolerance_seconds

        # Reaching the end is different from having played the whole way there: a discrepancy in actual and expected durations means an unannounced seek in the middle.
        played = (
            (changed_at - self._recording_started_at).total_seconds()
            if self._recording_started_at is not None
            else None
        )
        drift = abs(played - duration) if played is not None and duration > 0 else 0.0

        if completed and drift > self._config.end_tolerance_seconds:
            self._reject(
                f"{_mmss(played)} of audio for a {_mmss(duration)} track; "
                "a skip or a seek happened inside it"
            )
        elif completed:
            self._finish(previous, track, now)
        else:
            reason = (
                f"skipped at {_mmss(duration - remaining)} of {_mmss(duration)}"
                if duration > 0
                else "no duration reported"
            )
            self._reject(reason)

        self._current = None
        self._blocked = None
        self._maybe_start(track)

    def _finish(self, previous: TrackInfo, track: TrackInfo, now: datetime) -> None:
        """Close out a completed track and hand it to the saver."""
        # Everything captured since the changeover belongs to the new track. The position is wall-clock, the capture trails real time by the input latency, so correct before trimming.
        latency_ms = self._audio.input_latency_ms
        self._recording_started_at = None

        bleed_ms = track.effective_position(now).total_seconds() * 1000.0
        trim_ms = max(0.0, bleed_ms - latency_ms)

        try:
            capture = self._audio.stop_capture(trim_ms)
        except ValueError as exc:
            self.stats.rejected += 1
            log.warning("could not close %r: %s", previous.title, exc)
            return
        except CaptureError as exc:
            self.stats.rejected += 1
            log.warning("dropped %r: %s", previous.title, exc)
            return

        silence = silent_fraction(
            capture.audio, capture.samplerate, self._config.silence_threshold
        )
        if silence > self._config.max_silence_fraction:
            self.stats.rejected += 1
            log.warning(
                "dropped %r: %.0f%% of it is silence (the audio device was not carrying it)",
                previous.title,
                silence * 100,
            )
            return

        metadata = TrackMetadata(
            artist=previous.artist or "Unknown Artist",
            title=previous.title,
        )
        job = SaveJob(
            capture=capture,
            metadata=metadata,
            destination=self._config.save_path,
            filename_template=self._config.filename_template,
            container=self._config.container,
            subtype=self._config.subtype,
            overwrite=self._config.overwrite,
            dither=self._config.dither,
        )
        if self._saver.submit(job):
            self.stats.saved += 1
            log.info(
                "%s - %s complete (%.1fs captured, trimmed %.0f ms of bleed)",
                metadata.artist,
                metadata.title,
                capture.duration_seconds,
                trim_ms,
            )

    def _maybe_start(self, track: TrackInfo) -> None:
        """Start recording ``track`` if it is playing and recoverable."""
        if not track.is_playing:
            return
        if self._committed == self._blocked:
            return

        position_ms = track.effective_position().total_seconds() * 1000.0
        # The lead covers jitter the extrapolation cannot see.
        offset_ms = position_ms + self._config.start_lead_ms

        if offset_ms > self._max_offset_ms:
            self.stats.missed += 1
            self._blocked = self._committed
            log.warning(
                "missed the start of %s - %s (already %.0f ms in, buffer holds %.0f ms)",
                track.artist,
                track.title,
                position_ms,
                self._prebuffer_ms,
            )
            return

        try:
            at = datetime.now(timezone.utc)
            granted = self._audio.start_recording(offset_ms)
        except CaptureError as exc:
            self.stats.missed += 1
            self._blocked = self._committed
            log.error("could not start recording %r: %s", track.title, exc)
            return

        self._current = track
        # Where the captured audio actually begins, not where we noticed.
        self._recording_started_at = at - timedelta(milliseconds=granted)
        self.stats.started += 1
        log.info(
            "recording %s - %s (from %.0f ms ago%s)",
            track.artist,
            track.title,
            granted,
            "" if granted + 0.5 >= offset_ms else f", {offset_ms - granted:.0f} ms short",
        )

    def _reject(self, reason: str) -> None:
        if self._audio.abort_recording(reason):
            self.stats.rejected += 1
        self._current = None
        self._recording_started_at = None

    def _forget(self) -> None:
        """Reset to the startup state, so a session that comes back is treated as another mid-track join."""
        self._committed = None
        self._pending = None
        self._pending_polls = 0
        self._mixed_polls = 0
        self._blocked = None
        self._seen_any = False

    def shutdown(self) -> None:
        """Reject anything in flight. An interrupted track is incomplete."""
        self._reject("shutting down")
