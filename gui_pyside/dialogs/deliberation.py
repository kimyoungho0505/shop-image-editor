"""AI 토론(deliberation) 채팅 윈도우 다이얼로그."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QTextCursor

from gui_pyside.styles import VF_BG, VF_BG_SECONDARY, VF_BORDER, VF_TEXT, VF_TEXT_DIM

SPEAKER_STYLES = {
    "claude": {"icon": "\U0001f7e2", "name_color": "#a6e3a1", "text_color": "#b4e8b4"},
    "chatgpt": {"icon": "\U0001f535", "name_color": "#89b4fa", "text_color": "#a7c8fc"},
    "gemini": {"icon": "\U0001f7e0", "name_color": "#fab387", "text_color": "#fcc8a8"},
    "grok": {"icon": "\U0001f7e3", "name_color": "#a855f7", "text_color": "#c084fc"},
    "mc": {"icon": "\U0001f3a4", "name_color": "#cba6f7", "text_color": "#d8bcf8"},
    "user": {"icon": "\U0001f464", "name_color": "#74c7ec", "text_color": "#74c7ec"},
}

CHAT_BG = "#1e1e2e"


class DeliberationDialog(QDialog):
    user_message_sent = Signal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("AI \ud68c\uc758\uc2e4")
        self.resize(800, 700)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- chat area --
        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setStyleSheet(f"""
            QTextEdit {{
                background-color: {CHAT_BG};
                border: none;
                padding: 12px;
                font-family: 'Consolas', '\ub9d1\uc740 \uace0\ub515';
                font-size: 10pt;
                color: {VF_TEXT};
            }}
        """)
        layout.addWidget(self._chat, 1)

        # -- input bar --
        input_bar = QHBoxLayout()
        input_bar.setContentsMargins(10, 8, 10, 8)
        input_bar.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("\uba54\uc2dc\uc9c0\ub97c \uc785\ub825\ud558\uc138\uc694...")
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {VF_BG_SECONDARY};
                border: 1px solid {VF_BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                color: {VF_TEXT};
                font-size: 10pt;
            }}
            QLineEdit:focus {{
                border-color: #74c7ec;
            }}
        """)
        self._input.returnPressed.connect(self._on_send)
        input_bar.addWidget(self._input, 1)

        self._send_btn = QPushButton("\uc804\uc1a1")
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #74c7ec;
                color: {VF_BG};
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 10pt;
            }}
            QPushButton:hover {{
                background-color: #89dceb;
            }}
            QPushButton:pressed {{
                background-color: #5cb8d6;
            }}
        """)
        self._send_btn.clicked.connect(self._on_send)
        input_bar.addWidget(self._send_btn)

        input_wrapper = QHBoxLayout()
        input_wrapper.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(input_bar)

        self.setStyleSheet(f"QDialog {{ background-color: {VF_BG}; }}")

    def _on_send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.append_message("user", text)
        self.user_message_sent.emit(text)

    def append_message(self, speaker: str, text: str):
        style = SPEAKER_STYLES.get(speaker, SPEAKER_STYLES["mc"])
        icon = style["icon"]
        name_color = style["name_color"]
        text_color = style["text_color"]

        display_name = speaker.capitalize()
        if speaker == "mc":
            display_name = "\uc0ac\ud68c\uc790"
        elif speaker == "user":
            display_name = "\ub098"

        escaped_text = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

        html = (
            f'<div style="margin-bottom: 8px;">'
            f'<span style="font-weight: bold; color: {name_color};">'
            f'{icon} {display_name}</span><br>'
            f'<span style="color: {text_color}; margin-left: 20px;">'
            f'{escaped_text}</span>'
            f'</div>'
        )

        self._chat.append(html)
        # auto-scroll
        sb = self._chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_chat(self):
        self._chat.clear()
