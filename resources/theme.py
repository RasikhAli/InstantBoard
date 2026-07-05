"""
resources/theme.py

Centralized modern dark-theme stylesheet (Qt Style Sheets) for
InstantBoard, plus a small palette dict other modules can reuse when
drawing custom widgets (e.g. icons).
"""

PALETTE = {
    "bg": "#15151d",
    "bg_alt": "#1c1c26",
    "surface": "#22222e",
    "surface_hover": "#2a2a38",
    "border": "#33333f",
    "accent": "#7c5cff",
    "accent_hover": "#8f73ff",
    "text": "#f2f2f7",
    "text_muted": "#9a9aa5",
    "success": "#3ddc97",
    "danger": "#ff5c7a",
    "warning": "#ffcf4d",
}

DARK_STYLESHEET = f"""
QWidget {{
    background-color: {PALETTE['bg']};
    color: {PALETTE['text']};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {PALETTE['bg']};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QLineEdit {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    padding: 8px 14px;
    color: {PALETTE['text']};
    selection-background-color: {PALETTE['accent']};
}}

QLineEdit:focus {{
    border: 1px solid {PALETTE['accent']};
}}

QPushButton {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    padding: 8px 16px;
    color: {PALETTE['text']};
}}

QPushButton:hover {{
    background-color: {PALETTE['surface_hover']};
    border: 1px solid {PALETTE['accent']};
}}

QPushButton:pressed {{
    background-color: {PALETTE['bg_alt']};
}}

QPushButton#PrimaryButton {{
    background-color: {PALETTE['accent']};
    border: none;
    color: white;
    font-weight: 600;
}}

QPushButton#PrimaryButton:hover {{
    background-color: {PALETTE['accent_hover']};
}}

QPushButton#IconButton {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px;
}}

QPushButton#IconButton:hover {{
    background-color: {PALETTE['surface_hover']};
}}

QFrame#Card {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 14px;
}}

QFrame#Card:hover {{
    border: 1px solid {PALETTE['accent']};
}}

QFrame#TopBar, QFrame#BottomPanel {{
    background-color: {PALETTE['bg_alt']};
    border: none;
}}

QLabel#TitleLabel {{
    font-size: 18px;
    font-weight: 700;
    color: {PALETTE['text']};
}}

QLabel#CardTitle {{
    color: {PALETTE['text']};
    font-size: 11px;
    font-weight: 500;
    line-height: 1.2;
}}

QLabel#MutedLabel {{
    color: {PALETTE['text_muted']};
    font-size: 11px;
}}

QLabel#StatusLabel {{
    color: {PALETTE['success']};
    font-size: 12px;
    font-weight: 600;
}}

QSlider::groove:horizontal {{
    background: {PALETTE['border']};
    height: 5px;
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: {PALETTE['accent']};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}

QSlider::sub-page:horizontal {{
    background: {PALETTE['accent']};
    border-radius: 2px;
}}

QComboBox {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 6px 10px;
    color: {PALETTE['text']};
}}

QComboBox:hover {{
    border: 1px solid {PALETTE['accent']};
}}

QComboBox QAbstractItemView {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    selection-background-color: {PALETTE['accent']};
    outline: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {PALETTE['border']};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {PALETTE['accent']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QDialog {{
    background-color: {PALETTE['bg']};
}}

QTabWidget::pane {{
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
}}

QTabBar::tab {{
    background: {PALETTE['surface']};
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: {PALETTE['text_muted']};
}}

QTabBar::tab:selected {{
    background: {PALETTE['accent']};
    color: white;
}}

QListWidget {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
}}

QListWidget::item {{
    padding: 6px;
}}

QListWidget::item:selected {{
    background-color: {PALETTE['accent']};
    border-radius: 6px;
}}

QToolTip {{
    background-color: {PALETTE['surface_hover']};
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border']};
    padding: 4px;
    border-radius: 4px;
}}
"""
