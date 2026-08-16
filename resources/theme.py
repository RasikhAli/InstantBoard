"""
resources/theme.py

Centralized modern dark-theme stylesheet (Qt Style Sheets) for InstantBoard.
Includes a rich, harmonious color palette and high-end desktop UI styling.
"""

PALETTE = {
    "bg_root": "#0d0d12",          # Deep obsidian
    "bg": "#12121a",               # Main window background
    "bg_alt": "#171722",           # Panels & top/bottom bars
    "surface": "#1e1e2c",          # Cards & widgets
    "surface_hover": "#262638",    # Hover state for interactive items
    "surface_active": "#2f2f45",   # Pressed / active surface
    "border": "#2c2c3e",           # Subtle border
    "border_light": "#3b3b52",     # Highlight border
    "accent": "#7c5cff",           # Vibrant violet accent
    "accent_hover": "#9377ff",     # Hover accent
    "accent_subtle": "#7c5cff18",  # Accent tint background
    "accent_glow": "#7c5cff33",    # Glow focus
    "text": "#f5f5fa",             # High-contrast primary text
    "text_secondary": "#c2c2d4",   # Secondary readable text
    "text_muted": "#85859e",       # Subtitle / placeholder text
    "success": "#3ddc97",          # Emerald green
    "success_subtle": "#3ddc9718",
    "danger": "#ff5c7a",           # Coral red
    "danger_hover": "#ff758f",
    "danger_subtle": "#ff5c7a18",
    "warning": "#ffb830",          # Amber gold
    "warning_subtle": "#ffb83018",
    "cyan": "#00f2fe",             # Cyan
}

DARK_STYLESHEET = f"""
/* ── Global Defaults ─────────────────────────────────────────────────── */
QWidget {{
    background-color: {PALETTE['bg']};
    color: {PALETTE['text']};
    font-family: "Segoe UI", "Inter", -apple-system, sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {PALETTE['bg_root']};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* ── Typography & Labels ─────────────────────────────────────────────── */
QLabel {{
    color: {PALETTE['text']};
}}

QLabel#TitleLabel {{
    font-size: 19px;
    font-weight: 700;
    color: {PALETTE['text']};
    letter-spacing: -0.3px;
}}

QLabel#BrandSubtitle {{
    font-size: 11px;
    color: {PALETTE['text_muted']};
    font-weight: 500;
}}

QLabel#SectionHeader {{
    font-size: 15px;
    font-weight: 700;
    color: {PALETTE['text']};
    letter-spacing: -0.2px;
}}

QLabel#MutedLabel {{
    color: {PALETTE['text_muted']};
    font-size: 11px;
    font-weight: 500;
}}

QLabel#StatusLabel {{
    color: {PALETTE['success']};
    font-size: 12px;
    font-weight: 600;
}}

QLabel#StatusBadge {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 12px;
    padding: 3px 10px;
    color: {PALETTE['text_secondary']};
    font-size: 11px;
    font-weight: 600;
}}

/* ── Input Fields ────────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    padding: 9px 14px;
    color: {PALETTE['text']};
    font-size: 13px;
    selection-background-color: {PALETTE['accent']};
}}

QLineEdit:hover {{
    border: 1px solid {PALETTE['border_light']};
    background-color: {PALETTE['surface_hover']};
}}

QLineEdit:focus {{
    border: 1px solid {PALETTE['accent']};
    background-color: {PALETTE['surface']};
}}

QLineEdit#UrlInput {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border_light']};
    border-radius: 12px;
    padding: 11px 16px;
    color: {PALETTE['text']};
    font-size: 13px;
    selection-background-color: {PALETTE['accent']};
}}

QLineEdit#UrlInput:focus {{
    border: 1px solid {PALETTE['accent']};
}}

/* ── Buttons ─────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    padding: 8px 16px;
    color: {PALETTE['text']};
    font-size: 13px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: {PALETTE['surface_hover']};
    border: 1px solid {PALETTE['border_light']};
}}

QPushButton:pressed {{
    background-color: {PALETTE['surface_active']};
}}

QPushButton#PrimaryButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {PALETTE['accent']}, stop:1 #9d80ff);
    border: none;
    border-radius: 10px;
    color: #ffffff;
    font-weight: 700;
    padding: 8px 18px;
}}

QPushButton#PrimaryButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {PALETTE['accent_hover']}, stop:1 #ae94ff);
}}

QPushButton#PrimaryButton:pressed {{
    background-color: {PALETTE['accent']};
}}

QPushButton#DangerButton {{
    background-color: {PALETTE['danger_subtle']};
    border: 1px solid {PALETTE['danger']}44;
    color: {PALETTE['danger']};
    border-radius: 10px;
    font-weight: 600;
}}

QPushButton#DangerButton:hover {{
    background-color: {PALETTE['danger']};
    color: #ffffff;
    border: 1px solid {PALETTE['danger']};
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

QPushButton#PillButton {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 16px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
    color: {PALETTE['text_secondary']};
}}

QPushButton#PillButton:hover {{
    background-color: {PALETTE['surface_hover']};
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border_light']};
}}

QPushButton#PillButtonActive {{
    background-color: {PALETTE['accent_subtle']};
    border: 1px solid {PALETTE['accent']};
    border-radius: 16px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 700;
    color: {PALETTE['accent']};
}}

/* ── Cards & Panels ─────────────────────────────────────────────────── */
QFrame#Card {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 14px;
}}

QFrame#Card:hover {{
    border: 1px solid {PALETTE['border_light']};
}}

QFrame#HeroCard {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {PALETTE['surface']}, stop:1 #191924);
    border: 1px solid {PALETTE['border_light']};
    border-radius: 16px;
}}

QFrame#TopBar {{
    background-color: {PALETTE['bg_alt']};
    border-bottom: 1px solid {PALETTE['border']};
}}

QFrame#BottomPanel {{
    background-color: {PALETTE['bg_alt']};
    border-top: 1px solid {PALETTE['border']};
}}

/* ── Sliders ─────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    background: {PALETTE['surface_active']};
    height: 6px;
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: {PALETTE['accent']};
    border: 2px solid #ffffff;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background: {PALETTE['accent_hover']};
    border: 2px solid #ffffff;
}}

QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {PALETTE['accent']}, stop:1 #9d80ff);
    border-radius: 3px;
}}

/* ── Dropdowns ───────────────────────────────────────────────────────── */
QComboBox {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    padding: 7px 12px;
    color: {PALETTE['text']};
    font-size: 12px;
    font-weight: 500;
}}

QComboBox:hover {{
    border: 1px solid {PALETTE['accent']};
    background-color: {PALETTE['surface_hover']};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border_light']};
    border-radius: 8px;
    selection-background-color: {PALETTE['accent']};
    selection-color: #ffffff;
    outline: none;
    padding: 4px;
}}

/* ── Tabs ────────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}

QTabWidget#MainTabs::pane {{
    border: none;
    background: transparent;
}}

QTabBar::tab {{
    background: {PALETTE['surface']};
    padding: 10px 22px;
    margin-right: 4px;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    color: {PALETTE['text_muted']};
    font-size: 13px;
    font-weight: 600;
    min-width: 105px;
}}

QTabBar::tab:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {PALETTE['accent']}, stop:1 #9374ff);
    color: #ffffff;
    font-weight: 700;
}}

QTabBar::tab:hover:!selected {{
    background: {PALETTE['surface_hover']};
    color: {PALETTE['text']};
}}

/* ── Scrollbars ──────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {PALETTE['border_light']};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {PALETTE['accent']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
}}

QScrollBar::handle:horizontal {{
    background: {PALETTE['border_light']};
    border-radius: 4px;
}}

/* ── Dialogs & Lists ─────────────────────────────────────────────────── */
QDialog {{
    background-color: {PALETTE['bg_root']};
}}

QListWidget {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    padding: 4px;
}}

QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
}}

QListWidget::item:hover {{
    background-color: {PALETTE['surface_hover']};
}}

QListWidget::item:selected {{
    background-color: {PALETTE['accent']};
    color: #ffffff;
}}

QToolTip {{
    background-color: #232332;
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border_light']};
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 11px;
}}

/* ── TTS Panel ─────────────────────────────────────────────────────────── */
QTextEdit#TTSTextEdit {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border_light']};
    border-radius: 14px;
    padding: 14px 18px;
    color: {PALETTE['text']};
    font-size: 14px;
    line-height: 1.6;
    selection-background-color: {PALETTE['accent']};
}}

QTextEdit#TTSTextEdit:focus {{
    border: 1px solid {PALETTE['accent']};
}}

QLabel#TTSTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {PALETTE['text']};
    letter-spacing: -0.3px;
}}

QLabel#TTSStatus {{
    color: {PALETTE['text_muted']};
    font-size: 11px;
    font-weight: 500;
}}

QPushButton#TTSPlayBtn {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {PALETTE['accent']}, stop:1 #9d80ff);
    border: none;
    border-radius: 22px;
    color: white;
    font-weight: 700;
}}

QPushButton#TTSPlayBtn:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {PALETTE['accent_hover']}, stop:1 #ae94ff);
}}

QPushButton#TTSPlayBtn:pressed {{
    background-color: {PALETTE['surface_active']};
}}

QComboBox#VoiceCombo {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
    padding: 8px 14px;
    color: {PALETTE['text']};
    font-size: 13px;
    min-height: 38px;
}}

QComboBox#VoiceCombo:hover {{
    border: 1px solid {PALETTE['accent']};
}}

/* ── Link Player & History Panel ──────────────────────────────────────── */
QFrame#HistoryCard {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 14px;
    padding: 4px;
}}

QFrame#HistoryCard:hover {{
    background-color: {PALETTE['surface_hover']};
    border: 1px solid {PALETTE['border_light']};
}}

QLabel#HistoryTitle {{
    color: {PALETTE['text']};
    font-size: 13px;
    font-weight: 600;
}}

QLabel#HistoryMeta {{
    color: {PALETTE['text_muted']};
    font-size: 11px;
}}

QLabel#BadgeInstagram {{
    background-color: #e1306c22;
    color: #ff3377;
    border: 1px solid #e1306c44;
    border-radius: 8px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}

QLabel#BadgeYouTube {{
    background-color: #ff000022;
    color: #ff4d4d;
    border: 1px solid #ff000044;
    border-radius: 8px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}

QLabel#BadgeTwitter {{
    background-color: #1da1f222;
    color: #38bdf8;
    border: 1px solid #1da1f244;
    border-radius: 8px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}

QLabel#BadgeTikTok {{
    background-color: #00f2fe22;
    color: #00f2fe;
    border: 1px solid #00f2fe44;
    border-radius: 8px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}

QLabel#BadgeDefault {{
    background-color: {PALETTE['accent_subtle']};
    color: #a78bfa;
    border: 1px solid {PALETTE['accent']}44;
    border-radius: 8px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
"""
