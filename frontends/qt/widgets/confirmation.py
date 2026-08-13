from PyQt6.QtWidgets import QDialogButtonBox, QLabel, QVBoxLayout

from frontends.qt.widgets.app_dialog import AppDialog


class Confirmation(AppDialog):
    """Asks a yes or no question, in place of QMessageBox and its system frame."""

    def __init__(self, title: str, question: str, parent=None):
        super().__init__(title, parent)

        message = QLabel(question)
        message.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        column = QVBoxLayout(self.body)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(14)
        column.addWidget(message)
        column.addWidget(buttons)
        self.fit(380)

    @staticmethod
    def ask(parent, title: str, question: str) -> bool:
        return Confirmation(title, question, parent).exec() == AppDialog.DialogCode.Accepted
