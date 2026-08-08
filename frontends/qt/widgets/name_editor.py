from PyQt6.QtWidgets import QDialogButtonBox, QFormLayout, QLineEdit

from frontends.qt.widgets.app_dialog import AppDialog


class NameEditor(AppDialog):
    """Asks for a single name, in place of QInputDialog and its system frame."""

    def __init__(self, title: str, label: str, text: str = "", parent=None):
        super().__init__(title, parent)
        self.setMinimumWidth(340)

        self._field = QLineEdit(text)
        self._field.selectAll()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self.body)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(10)
        form.addRow(label, self._field)
        form.addRow(buttons)

    def name(self) -> str:
        return self._field.text().strip()

    @staticmethod
    def ask(parent, title: str, label: str, text: str = "") -> str | None:
        """The chosen name, or None if it was cancelled or left empty."""
        editor = NameEditor(title, label, text, parent)
        if editor.exec() != AppDialog.DialogCode.Accepted:
            return None
        return editor.name() or None
