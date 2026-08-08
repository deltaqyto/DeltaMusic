from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from frontends.qt.formatting import clock
from frontends.qt.icons import accent_icon, icon
from frontends.qt.widgets.elided_label import ElidedLabel
from frontends.qt.widgets.seek_slider import SeekSlider
from frontends.qt.widgets.volume_slider import VolumeSlider
from protocol.types.playback_state import PlaybackState
from protocol.types.playback_status import PlaybackStatus
from protocol.types.repeat_mode import RepeatMode

SCRUB_STEPS = 1000
SLIDER_HEIGHT = 18
PLAY_GLYPH_SIZE = 19
PLAY_GLYPH_COLOUR = "#0a0a0b"
_REPEAT_ORDER = [RepeatMode.PLAYLIST, RepeatMode.SONG, RepeatMode.NONE]


class PlayerBar(QWidget):
    play_pressed = pyqtSignal()
    pause_pressed = pyqtSignal()
    next_pressed = pyqtSignal()
    previous_pressed = pyqtSignal()
    seeked = pyqtSignal(float)
    volume_set = pyqtSignal(float)
    shuffle_set = pyqtSignal(bool)
    repeat_set = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("player")
        self.setFixedHeight(78)

        self._status = PlaybackStatus.IDLE
        self._duration = 0.0
        self._repeat = RepeatMode.PLAYLIST
        self._shuffle = False
        self._muted_from: float | None = None
        self._scrubbing = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(20)
        layout.addWidget(self._build_now_playing(), 1)
        layout.addWidget(self._build_transport(), 0)
        layout.addWidget(self._build_volume(), 1)

        # None of the bar's text is clickable, so none of it may inherit the hand cursor from a parent.
        for label in self.findChildren(QLabel):
            label.setCursor(Qt.CursorShape.ArrowCursor)

    # Building

    def _build_now_playing(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("npBlock")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self._art = QLabel("~")
        self._art.setObjectName("art")
        self._art.setFixedSize(46, 46)
        self._art.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title = ElidedLabel("Nothing playing")
        self._title.setObjectName("npTitle")
        self._artist = ElidedLabel("")
        self._artist.setObjectName("npArtist")

        # Without the stretches the spare height is split between the two labels rather than around them.
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        text.addStretch(1)
        text.addWidget(self._title)
        text.addWidget(self._artist)
        text.addStretch(1)

        row.addWidget(self._art)
        row.addLayout(text, 1)
        return holder

    def _build_transport(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("transportBlock")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 7, 0, 7)
        column.setSpacing(4)

        self._shuffle_button = self._icon_button("shuffle", "Shuffle", self._toggle_shuffle)
        self._previous_button = self._icon_button("previous", "Previous", self.previous_pressed.emit, size=17)
        self._next_button = self._icon_button("next", "Next", self.next_pressed.emit, size=17)
        self._repeat_button = self._icon_button("repeat", "Repeat", self._cycle_repeat)

        self._play_button = QPushButton()
        self._play_button.setObjectName("playButton")
        self._play_button.setIcon(icon("play", PLAY_GLYPH_COLOUR, PLAY_GLYPH_SIZE))
        # A button's icon size caps what it will draw, and the default is smaller than the glyph.
        self._play_button.setIconSize(QSize(PLAY_GLYPH_SIZE, PLAY_GLYPH_SIZE))
        self._play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_button.clicked.connect(self._toggle_play)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(14)
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons.addWidget(self._shuffle_button)
        buttons.addWidget(self._previous_button)
        buttons.addWidget(self._play_button)
        buttons.addWidget(self._next_button)
        buttons.addWidget(self._repeat_button)

        self._elapsed = QLabel("0:00")
        self._elapsed.setObjectName("clock")
        self._total = QLabel("0:00")
        self._total.setObjectName("clock")

        self._scrub = SeekSlider()
        self._scrub.setObjectName("scrub")
        self._scrub.setFixedSize(340, SLIDER_HEIGHT)
        self._scrub.setRange(0, SCRUB_STEPS)
        self._scrub.sliderPressed.connect(self._start_scrub)
        self._scrub.sliderReleased.connect(self._finish_scrub)

        scrubbing = QHBoxLayout()
        scrubbing.setContentsMargins(0, 0, 0, 0)
        scrubbing.setSpacing(9)
        scrubbing.addWidget(self._elapsed)
        scrubbing.addWidget(self._scrub)
        scrubbing.addWidget(self._total)

        column.addLayout(buttons)
        column.addLayout(scrubbing)
        return holder

    def _build_volume(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("volumeBlock")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)

        self._mute_button = self._icon_button("volume", "Mute", self._toggle_mute)

        self._volume = VolumeSlider()
        self._volume.setObjectName("volume")
        self._volume.setFixedSize(90, SLIDER_HEIGHT)
        self._volume.setRange(0, 100)
        self._volume.valueChanged.connect(self._on_volume)

        self._volume_label = QLabel("0%")
        self._volume_label.setObjectName("clock")
        self._volume_label.setFixedWidth(30)
        self._volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addStretch(1)
        row.addWidget(self._mute_button)
        row.addWidget(self._volume)
        row.addWidget(self._volume_label)
        return holder

    def _icon_button(self, name: str, tip: str, slot, size: int = 16) -> QPushButton:
        button = QPushButton()
        button.setObjectName("iconButton")
        button.setIcon(icon(name, size=size))
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    # Updating

    def show_playback(self, playback: PlaybackState) -> None:
        self._status = playback.status
        self._duration = playback.duration
        playing = playback.status is PlaybackStatus.PLAYING
        self._play_button.setIcon(icon("pause" if playing else "play", PLAY_GLYPH_COLOUR, PLAY_GLYPH_SIZE))
        self._total.setText(clock(playback.duration))
        self.show_position(playback.position)

        if playback.repeat is not self._repeat:
            self._repeat = playback.repeat
            self._paint_repeat()
        if playback.shuffle != self._shuffle:
            self._shuffle = playback.shuffle
            self._paint_shuffle()

        percent = int(round(playback.volume * 100))
        if percent != self._volume.value() and not self._volume.isSliderDown():
            self._volume.blockSignals(True)
            self._volume.setValue(percent)
            self._volume.blockSignals(False)
        self._volume_label.setText(f"{percent}%")
        self._mute_button.setIcon(icon("muted" if percent == 0 else "volume"))

    def show_position(self, seconds: float) -> None:
        self._elapsed.setText(clock(seconds))
        if self._scrubbing:
            return
        fraction = seconds / self._duration if self._duration > 0 else 0.0
        self._scrub.blockSignals(True)
        self._scrub.setValue(int(min(1.0, max(0.0, fraction)) * SCRUB_STEPS))
        self._scrub.blockSignals(False)

    def show_track(self, name: str, artist: str) -> None:
        self._title.setText(name)
        self._artist.setText(artist)

    # Reacting

    def _toggle_play(self) -> None:
        if self._status is PlaybackStatus.PLAYING:
            self.pause_pressed.emit()
        else:
            self.play_pressed.emit()

    def _start_scrub(self) -> None:
        self._scrubbing = True

    def _finish_scrub(self) -> None:
        self._scrubbing = False
        if self._duration > 0:
            self.seeked.emit(self._scrub.value() / SCRUB_STEPS * self._duration)

    def _on_volume(self, percent: int) -> None:
        self._muted_from = None
        self.volume_set.emit(percent / 100.0)

    def _toggle_mute(self) -> None:
        if self._volume.value() > 0:
            self._muted_from = self._volume.value() / 100.0
            self.volume_set.emit(0.0)
        else:
            self.volume_set.emit(self._muted_from or 0.5)

    def _toggle_shuffle(self) -> None:
        self.shuffle_set.emit(not self._shuffle)

    def _cycle_repeat(self) -> None:
        position = _REPEAT_ORDER.index(self._repeat) if self._repeat in _REPEAT_ORDER else 0
        self.repeat_set.emit(_REPEAT_ORDER[(position + 1) % len(_REPEAT_ORDER)].value)

    def _paint_shuffle(self) -> None:
        self._shuffle_button.setIcon(accent_icon("shuffle") if self._shuffle else icon("shuffle"))

    def _paint_repeat(self) -> None:
        name = "repeat_one" if self._repeat is RepeatMode.SONG else "repeat"
        self._repeat_button.setIcon(icon(name) if self._repeat is RepeatMode.NONE else accent_icon(name))
        self._repeat_button.setToolTip(f"Repeat {self._repeat.value}")
