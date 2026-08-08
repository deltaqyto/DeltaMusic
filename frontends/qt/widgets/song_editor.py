from PyQt6.QtWidgets import QDialogButtonBox, QFormLayout, QLineEdit

from frontends.qt.widgets.app_dialog import AppDialog
from protocol.types.song import Song


class SongEditor(AppDialog):
    """Editor panel to update song details"""

    def __init__(self, song: Song, parent=None):
        super().__init__("Edit song", parent)
        self.setMinimumWidth(380)

        self._name = QLineEdit(song.name)
        self._artist = QLineEdit(song.artist)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self.body)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(10)
        form.addRow("Title", self._name)
        form.addRow("Artist", self._artist)
        form.addRow(buttons)

    def fields(self) -> dict[str, str]:
        return {"name": self._name.text().strip(), "artist": self._artist.text().strip()}
