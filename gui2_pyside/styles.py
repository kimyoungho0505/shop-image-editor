"""PySide6 QSS 스타일시트 - 모던 라이트 테마 (개선된 버전)"""

# 색상 상수
BG_COLOR = "#f5f5f5"
ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
ACCENT_LIGHT = "#dbeafe"
DANGER = "#dc2626"
DANGER_HOVER = "#b91c1c"
SUCCESS = "#10b981"
SUCCESS_HOVER = "#059669"
CARD_BG = "#ffffff"
BORDER_COLOR = "#e2e8f0"
BORDER_FOCUS = ACCENT
TEXT_PRIMARY = "#1e293b"
TEXT_SECONDARY = "#64748b"
TEXT_DISABLED = "#94a3b8"
SIDEBAR_BG = "#1e293b"
SIDEBAR_TEXT = "#f8fafc"
FONT_FAMILY = "맑은 고딕"
FONT_SIZE = 9

# 메인 라이트 테마 QSS
MAIN_STYLESHEET = f"""
/* ── 전역 ── */
QMainWindow {{
    background-color: {BG_COLOR};
    font-family: '{FONT_FAMILY}';
    font-size: {FONT_SIZE}pt;
    color: {TEXT_PRIMARY};
}}

QWidget {{
    font-family: '{FONT_FAMILY}';
    font-size: {FONT_SIZE}pt;
    color: {TEXT_PRIMARY};
}}

/* ── 탭 위젯 ── */
QTabWidget::pane {{
    border: 1px solid {BORDER_COLOR};
    border-top: 2px solid {ACCENT};
    background: {BG_COLOR};
    border-radius: 0 0 4px 4px;
}}

QTabBar::tab {{
    background: {CARD_BG};
    border: 1px solid {BORDER_COLOR};
    border-bottom: none;
    padding: 8px 18px;
    margin-right: 2px;
    border-radius: 4px 4px 0 0;
    font-size: {FONT_SIZE}pt;
    color: {TEXT_SECONDARY};
    min-width: 80px;
}}

QTabBar::tab:selected {{
    background: {BG_COLOR};
    color: {ACCENT};
    font-weight: bold;
    border-bottom: 2px solid {ACCENT};
}}

QTabBar::tab:hover:!selected {{
    background: {ACCENT_LIGHT};
    color: {ACCENT};
}}

/* ── 버튼 ── */
QPushButton {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 6px 16px;
    font-size: {FONT_SIZE}pt;
    color: {TEXT_PRIMARY};
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {BG_COLOR};
    border-color: {ACCENT};
    color: {ACCENT};
}}

QPushButton:pressed {{
    background-color: {ACCENT_LIGHT};
}}

QPushButton:disabled {{
    background-color: {BG_COLOR};
    color: {TEXT_DISABLED};
    border-color: {BORDER_COLOR};
}}

QPushButton[cssClass="accent"] {{
    background-color: {ACCENT};
    color: #ffffff;
    border: none;
    font-weight: bold;
}}

QPushButton[cssClass="accent"]:hover {{
    background-color: {ACCENT_HOVER};
    color: #ffffff;
}}

QPushButton[cssClass="danger"] {{
    background-color: {DANGER};
    color: #ffffff;
    border: none;
}}

QPushButton[cssClass="danger"]:hover {{
    background-color: {DANGER_HOVER};
    color: #ffffff;
}}

QPushButton[cssClass="success"] {{
    background-color: {SUCCESS};
    color: #ffffff;
    border: none;
}}

QPushButton[cssClass="success"]:hover {{
    background-color: {SUCCESS_HOVER};
    color: #ffffff;
}}

/* ── 입력 필드 ── */
QLineEdit {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: {FONT_SIZE}pt;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_LIGHT};
}}

QLineEdit:focus {{
    border-color: {ACCENT};
}}

QLineEdit:disabled {{
    background-color: {BG_COLOR};
    color: {TEXT_DISABLED};
}}

/* ── 콤보박스 ── */
QComboBox {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: {FONT_SIZE}pt;
    color: {TEXT_PRIMARY};
    min-height: 20px;
}}

QComboBox:hover {{
    border-color: {ACCENT};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {TEXT_SECONDARY};
    margin-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    selection-background-color: {ACCENT_LIGHT};
    selection-color: {ACCENT};
    padding: 4px;
}}

/* ── 체크박스 ── */
QCheckBox {{
    spacing: 8px;
    font-size: {FONT_SIZE}pt;
    color: {TEXT_PRIMARY};
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid {BORDER_COLOR};
    border-radius: 4px;
    background: {CARD_BG};
}}

QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QCheckBox::indicator:disabled {{
    background-color: {BG_COLOR};
    border-color: {BORDER_COLOR};
}}

/* ── 라디오 버튼 ── */
QRadioButton {{
    spacing: 8px;
    font-size: {FONT_SIZE}pt;
    color: {TEXT_PRIMARY};
}}

QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid {BORDER_COLOR};
    border-radius: 10px;
    background: {CARD_BG};
}}

QRadioButton::indicator:hover {{
    border-color: {ACCENT};
}}

QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ── 텍스트 편집 ── */
QTextEdit, QPlainTextEdit {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 6px;
    font-family: 'Consolas', '{FONT_FAMILY}';
    font-size: {FONT_SIZE}pt;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_LIGHT};
}}

QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}

/* ── 프로그레스 바 ── */
QProgressBar {{
    background-color: {BORDER_COLOR};
    border: none;
    border-radius: 6px;
    text-align: center;
    font-size: 8pt;
    color: {TEXT_PRIMARY};
    min-height: 14px;
    max-height: 14px;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 6px;
}}

/* ── 그룹박스 ── */
QGroupBox {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-size: {FONT_SIZE}pt;
    font-weight: bold;
    color: {TEXT_PRIMARY};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px;
    color: {ACCENT};
    font-weight: bold;
}}

/* ── 스크롤바 ── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {BORDER_COLOR};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {TEXT_DISABLED};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER_COLOR};
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {TEXT_DISABLED};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── 라벨 ── */
QLabel {{
    color: {TEXT_PRIMARY};
    font-size: {FONT_SIZE}pt;
}}

/* ── 스크롤 영역 ── */
QScrollArea {{
    border: none;
    background: transparent;
}}

/* ── 상태바 ── */
QStatusBar {{
    background-color: {CARD_BG};
    border-top: 1px solid {BORDER_COLOR};
    color: {TEXT_SECONDARY};
}}
"""
