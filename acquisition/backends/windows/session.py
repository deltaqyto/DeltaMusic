"""Reading the Windows media session (SMTC)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)

from ...interfaces import SessionSource
from ...types import TrackInfo

log = logging.getLogger(__name__)


class SessionWatcher(SessionSource):
    """Polls one app's media session and hands back TrackInfo.
    """

    def __init__(self, app_id: str) -> None:
        if not app_id or not app_id.strip():
            raise ValueError("app_id must not be empty")
        self._app_id = app_id.strip()
        self._manager = None
        self._warned_missing = False

    @property
    def app_id(self) -> str:
        return self._app_id

    def describe(self) -> str:
        return f"Windows media session (SMTC) from {self._app_id!r}"

    async def _get_manager(self):
        if self._manager is None:
            self._manager = await SessionManager.request_async()
        return self._manager

    async def read(self) -> Optional[TrackInfo]:
        """Return the current track, or None if the app has no session."""
        try:
            manager = await self._get_manager()
            session = self._find_session(manager)
            if session is None:
                if not self._warned_missing:
                    log.info("waiting for a media session from %r", self._app_id)
                    self._warned_missing = True
                return None
            self._warned_missing = False

            properties = await session.try_get_media_properties_async()
            status = session.get_playback_info().playback_status
            timeline = session.get_timeline_properties()
        except OSError as exc:
            # The manager itself can go away (an audio service restart, say).
            log.warning("media session read failed, will retry: %s", exc)
            self._manager = None
            return None
        except Exception as exc:  # pragma: no cover
            log.warning("unexpected media session error, will retry: %s", exc)
            self._manager = None
            return None

        # SMTC hands back nulls while a session is being torn down or has not published its properties yet.
        if properties is None or timeline is None:
            return None

        return TrackInfo(
            title=(properties.title or "").strip(),
            artist=(properties.artist or "").strip(),
            is_playing=status == PlaybackStatus.PLAYING,
            duration=timeline.end_time - timeline.start_time,
            position=timeline.position - timeline.start_time,
            last_updated=timeline.last_updated_time,
            observed_at=datetime.now(timezone.utc),
        )

    def _find_session(self, manager):
        for session in manager.get_sessions():
            if session.source_app_user_model_id == self._app_id:
                return session
        return None
