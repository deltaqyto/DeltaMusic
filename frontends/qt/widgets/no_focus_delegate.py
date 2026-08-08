from PyQt6.QtCore import QModelIndex
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem, QStyledItemDelegate


class NoFocusDelegate(QStyledItemDelegate):
    """Drops the focus state, which is the only way to be rid of the dotted rect the Windows style draws."""

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        option.state &= ~QStyle.StateFlag.State_HasFocus
