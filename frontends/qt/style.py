## Nightmare everything stylesheet

BG = "#0a0a0b"
PANEL = "#101012"
PANEL_2 = "#151517"
LINE = "#232326"
TEXT = "#e6e6e8"
SUBTLE = "#b4b4bc"
MUTED = "#9a9aa2"
DIM = "#85858c"
DIMMER = "#55555c"
FAINT = "#3b3b41"
ACCENT = "#ff7a18"
ACCENT_DIM = "#b2560f"
WARN = "#ff6b5e"

TITLE_BAR_HEIGHT = 46
DIALOG_TITLE_BAR_HEIGHT = 34
COLUMN_HEAD_HEIGHT = 32
SLIDER_HANDLE = 9
SLIDER_HANDLE_HOVER = 13

STYLESHEET = f"""
QWidget {{
    background: {PANEL};
    color: {TEXT};
    font-family: "Segoe UI";
    font-size: 13px;
}}
QMainWindow, #shell {{ background: {BG}; }}

#titleBar {{ background: {PANEL}; }}
#titleBarBackground {{ background: {PANEL}; }}
#brand {{ background: transparent; font-size: 16px; font-weight: 600; }}
#titleMark {{ background: transparent; }}
#search {{
    background: {PANEL_2};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 6px 10px;
    color: {TEXT};
}}
#search:focus {{ border-color: {ACCENT_DIM}; }}
#status {{ background: transparent; color: {DIM}; font-size: 11px; }}
#headerRule {{ background: {LINE}; border: none; }}

#paneTitle {{
    background: transparent;
    color: {MUTED};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 0px 14px;
}}
#paneHeading {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}

#sidebar {{ border: none; outline: none; }}
#sidebar::item {{ padding: 7px 14px; color: {SUBTLE}; border-left: 2px solid transparent; }}
#sidebar::item:hover {{ background: {PANEL_2}; color: {TEXT}; }}
#sidebar::item:selected {{ background: {PANEL_2}; color: {TEXT}; border-left: 2px solid {ACCENT}; }}

QTableView {{
    background: {PANEL};
    alternate-background-color: {PANEL};
    gridline-color: transparent;
    border: none;
    outline: none;
    selection-background-color: {PANEL_2};
    selection-color: {TEXT};
}}
QTableView::item {{ padding: 4px 6px; border: none; }}
QHeaderView {{ background: {PANEL}; }}
QHeaderView::section {{
    background: {PANEL};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {LINE};
    padding: 0px 8px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
}}

/* The queue's rows are delegate-painted, so no ::item rule may claim their geometry or their background. */
#queue {{ border: none; outline: none; }}

#jobBar {{ background: {PANEL}; border-top: 1px solid {LINE}; }}
#jobRow {{ background: transparent; border-bottom: 1px solid {LINE}; }}
#jobTitle {{ background: transparent; color: {SUBTLE}; font-size: 12px; }}
#jobCount {{ background: transparent; color: {MUTED}; font-size: 11px; }}
#jobDetail {{ background: transparent; color: {DIM}; font-size: 11px; padding-left: 32px; }}

#player {{ background: {PANEL_2}; border-top: 1px solid {LINE}; }}
#npBlock, #transportBlock, #volumeBlock {{ background: transparent; }}
#art {{
    background: #14141a;
    border: 1px solid {LINE};
    border-radius: 3px;
    color: {ACCENT_DIM};
}}
#npTitle {{ background: transparent; font-size: 15px; }}
#npArtist {{ background: transparent; color: {DIM}; font-size: 12px; }}
#clock {{ background: transparent; color: {MUTED}; font-size: 11px; }}

QPushButton#iconButton {{ background: transparent; border: none; padding: 2px; }}
QPushButton#iconButton:hover {{ background: {LINE}; border-radius: 3px; }}
QPushButton#playButton {{
    background: {ACCENT};
    border: none;
    border-radius: 16px;
    min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px;
}}
QPushButton#playButton:hover {{ background: #ff8c38; }}

QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ height: 3px; background: #26262a; border-radius: 2px; }}
QSlider::add-page:horizontal {{ background: #26262a; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: {SLIDER_HANDLE}px; height: {SLIDER_HANDLE}px;
    margin: -{(SLIDER_HANDLE - 3) // 2}px 0;
    border-radius: {SLIDER_HANDLE // 2}px;
}}
QSlider#scrub[hovered="true"]::handle:horizontal {{
    background: #ff9445;
    width: {SLIDER_HANDLE_HOVER}px; height: {SLIDER_HANDLE_HOVER}px;
    margin: -{(SLIDER_HANDLE_HOVER - 3) // 2}px 0;
    border-radius: {SLIDER_HANDLE_HOVER // 2}px;
}}
QSlider#volume::groove:horizontal {{ height: 3px; background: #26262a; border-radius: 2px; }}
QSlider#volume::add-page:horizontal {{ background: #26262a; border-radius: 2px; }}
QSlider#volume::sub-page:horizontal {{ background: #6d6d75; border-radius: 2px; }}
QSlider#volume::handle:horizontal {{ background: #8a8a92; }}
QSlider#volume[hovered="true"]::sub-page:horizontal {{ background: {ACCENT}; }}
QSlider#volume[hovered="true"]::handle:horizontal {{ background: {ACCENT}; }}

QMenu {{ background: {PANEL_2}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; color: {SUBTLE}; }}
QMenu::item:selected {{ background: {LINE}; color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}

QDialog {{ background: {PANEL_2}; }}
#dialogBody {{ background: {PANEL_2}; }}
#dialogTitle {{ background: transparent; color: {SUBTLE}; font-size: 12px; }}
#dialogNote {{ background: transparent; color: {DIM}; font-size: 11px; }}
#dialogError {{ background: transparent; color: {WARN}; font-size: 11px; }}
#code {{ background: transparent; color: {ACCENT}; font-size: 30px; font-weight: 600; letter-spacing: 8px; }}
QLineEdit {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 3px; padding: 5px 8px; color: {TEXT}; }}
QLineEdit:focus {{ border-color: {ACCENT_DIM}; }}
QPushButton {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 3px; padding: 5px 14px; color: {TEXT}; }}
QPushButton:hover {{ background: {LINE}; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #26262a; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""
