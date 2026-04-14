"""prompt preview / validation preview dialogs for viewfinder."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap

from gui_pyside.styles import (
    VIEWFINDER_STYLESHEET,
    VF_BG, VF_BG_SECONDARY, VF_ACCENT, VF_TEXT, VF_TEXT_DIM,
    VF_BORDER, VF_SUCCESS, VF_WARN,
)


class PromptPreviewDialog(QDialog):
    preview_requested = Signal(str)
    apply_requested = Signal(str)

    def __init__(self, title: str, prompt_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 620)
        self.setStyleSheet(VIEWFINDER_STYLESHEET)
        self._has_preview = False
        self._build_ui(title, prompt_text)

    def _build_ui(self, title: str, prompt_text: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # header
        lbl_header = QLabel(f"AI \ucd94\ucc9c \ud504\ub86c\ud504\ud2b8:")
        lbl_header.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {VF_ACCENT};")
        layout.addWidget(lbl_header)

        # editable prompt
        self._text_edit = QTextEdit()
        self._text_edit.setPlainText(prompt_text)
        self._text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: #1a2a1a;
                color: #c0e0c0;
                border: 1px solid {VF_BORDER};
                border-radius: 6px;
                padding: 8px;
                font-size: 10pt;
            }}
            QTextEdit:focus {{
                border-color: {VF_ACCENT};
            }}
        """)
        layout.addWidget(self._text_edit, 1)

        # preview image (hidden initially)
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setVisible(False)
        layout.addWidget(self._preview_label)

        # buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_preview = QPushButton("\U0001f441 \uacb0\uacfc \ubbf8\ub9ac\ubcf4\uae30")
        self._btn_preview.setProperty("cssClass", "accent")
        self._btn_preview.setStyleSheet(f"""
            QPushButton {{
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #1d4ed8; }}
        """)
        self._btn_preview.clicked.connect(
            lambda: self.preview_requested.emit(self.get_prompt()))
        btn_row.addWidget(self._btn_preview)

        self._btn_apply = QPushButton("\u2705 \uc801\uc6a9 (\ud504\ub86c\ud504\ud2b8 \uc800\uc7a5)")
        self._btn_apply.setStyleSheet(f"""
            QPushButton {{
                background-color: {VF_SUCCESS};
                color: {VF_BG};
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 10pt;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #8dd98d; }}
        """)
        self._btn_apply.clicked.connect(
            lambda: self.apply_requested.emit(self.get_prompt()))
        btn_row.addWidget(self._btn_apply)

        btn_cancel = QPushButton("\ucde8\uc18c")
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {VF_BG_SECONDARY};
                color: {VF_TEXT};
                border: 1px solid {VF_BORDER};
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 10pt;
            }}
            QPushButton:hover {{ border-color: {VF_ACCENT}; }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def get_prompt(self) -> str:
        return self._text_edit.toPlainText().strip()

    def set_preview_image(self, pixmap: QPixmap):
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            660, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._preview_label.setPixmap(scaled)
        self._preview_label.setVisible(True)
        self._has_preview = True
        self._btn_apply.setText("\u2705 \uc801\uc6a9 (\ubbf8\ub9ac\ubcf4\uae30 \uacb0\uacfc \uc0ac\uc6a9)")


class ValidationPreviewDialog(QDialog):
    save_and_pass = Signal(str)
    save_only = Signal(str)
    force_pass = Signal()

    def __init__(self, title: str, suggestion: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(750, 650)
        self.setStyleSheet(VIEWFINDER_STYLESHEET)
        self._suggestion = suggestion
        self._build_ui(title, suggestion)

    def _build_ui(self, title: str, suggestion: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        agreed = suggestion.get("agreed", suggestion.get("agree", False))
        reason = suggestion.get("reason", "")
        modified_prompt = suggestion.get("modified_prompt", "")
        new_shadow = suggestion.get("updated_shadow_needed", "")
        new_template = suggestion.get("updated_user_template", "")

        # header: agree / disagree
        if agreed:
            header_text = "\u2705 AI\uac00 \uc0ac\uc6a9\uc790 \uc758\uacac\uc5d0 \ub3d9\uc758\ud569\ub2c8\ub2e4"
            header_color = VF_SUCCESS
        else:
            header_text = "\u26a0\ufe0f AI\uac00 \uc0ac\uc6a9\uc790 \uc758\uacac\uc5d0 \ub3d9\uc758\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4"
            header_color = VF_WARN

        lbl_header = QLabel(header_text)
        lbl_header.setStyleSheet(
            f"font-size: 13pt; font-weight: bold; color: {header_color};")
        layout.addWidget(lbl_header)

        if reason:
            lbl_reason = QLabel(f"\ud310\ub2e8 \uadfc\uac70: {reason}")
            lbl_reason.setWordWrap(True)
            lbl_reason.setStyleSheet(f"color: {VF_TEXT_DIM}; font-size: 9pt;")
            layout.addWidget(lbl_reason)

        has_changes = bool(new_shadow or new_template or modified_prompt)

        # editable text areas
        self._shadow_edit = None
        self._template_edit = None

        prompt_source = new_shadow or modified_prompt
        if has_changes and prompt_source:
            lbl_s = QLabel("\u25b6 \uc218\uc815\ub41c \ud504\ub86c\ud504\ud2b8 (\ud3b8\uc9d1 \uac00\ub2a5):")
            lbl_s.setStyleSheet(
                f"font-size: 10pt; font-weight: bold; color: {VF_SUCCESS};")
            layout.addWidget(lbl_s)
            self._shadow_edit = QTextEdit()
            self._shadow_edit.setPlainText(prompt_source)
            self._shadow_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: #1a2a1a;
                    color: #c0e0c0;
                    border: 1px solid {VF_BORDER};
                    border-radius: 6px;
                    padding: 8px;
                    font-size: 9pt;
                }}
            """)
            layout.addWidget(self._shadow_edit, 1)

        if has_changes and new_template:
            lbl_t = QLabel("\u25b6 \uc218\uc815\ub41c \uac80\uc99d \ud15c\ud50c\ub9bf (\ud3b8\uc9d1 \uac00\ub2a5):")
            lbl_t.setStyleSheet(
                f"font-size: 10pt; font-weight: bold; color: {VF_SUCCESS};")
            layout.addWidget(lbl_t)
            self._template_edit = QTextEdit()
            self._template_edit.setPlainText(new_template)
            self._template_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: #1a2a1a;
                    color: #c0e0c0;
                    border: 1px solid {VF_BORDER};
                    border-radius: 6px;
                    padding: 8px;
                    font-size: 9pt;
                }}
            """)
            layout.addWidget(self._template_edit, 1)

        if not has_changes:
            lbl_no = QLabel("\ud504\ub86c\ud504\ud2b8 \ubcc0\uacbd \ubd88\ud544\uc694 (AI \ud310\ub2e8)")
            lbl_no.setStyleSheet(f"color: {VF_TEXT_DIM}; font-size: 10pt;")
            layout.addWidget(lbl_no)

        # buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if has_changes:
            btn_save_pass = QPushButton("\ud504\ub86c\ud504\ud2b8 \uc800\uc7a5 + \uac15\uc81c \ud569\uaca9")
            btn_save_pass.setStyleSheet(f"""
                QPushButton {{
                    background-color: #16a34a;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 11pt;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #15803d; }}
            """)
            btn_save_pass.clicked.connect(
                lambda: self.save_and_pass.emit(self._get_combined_prompt()))
            btn_row.addWidget(btn_save_pass)

            btn_save = QPushButton("\ud504\ub86c\ud504\ud2b8\ub9cc \uc800\uc7a5")
            btn_save.setStyleSheet(f"""
                QPushButton {{
                    background-color: #2563eb;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 10pt;
                }}
                QPushButton:hover {{ background-color: #1d4ed8; }}
            """)
            btn_save.clicked.connect(
                lambda: self.save_only.emit(self._get_combined_prompt()))
            btn_row.addWidget(btn_save)
        else:
            btn_force = QPushButton("\uac15\uc81c \ud569\uaca9 \ucc98\ub9ac")
            btn_force.setStyleSheet(f"""
                QPushButton {{
                    background-color: #d97706;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 11pt;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #b45309; }}
            """)
            btn_force.clicked.connect(self.force_pass.emit)
            btn_row.addWidget(btn_force)

        btn_cancel = QPushButton("\ucde8\uc18c")
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {VF_BG_SECONDARY};
                color: {VF_TEXT};
                border: 1px solid {VF_BORDER};
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 10pt;
            }}
            QPushButton:hover {{ border-color: {VF_ACCENT}; }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _get_combined_prompt(self) -> str:
        parts = []
        if self._shadow_edit:
            parts.append(self._shadow_edit.toPlainText().strip())
        if self._template_edit:
            parts.append(self._template_edit.toPlainText().strip())
        return "\n---\n".join(p for p in parts if p)

    def get_shadow_text(self) -> str | None:
        if self._shadow_edit:
            return self._shadow_edit.toPlainText().strip() or None
        return None

    def get_template_text(self) -> str | None:
        if self._template_edit:
            return self._template_edit.toPlainText().strip() or None
        return None
