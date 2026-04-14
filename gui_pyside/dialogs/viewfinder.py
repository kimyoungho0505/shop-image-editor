"""PySide6 ViewfinderDialog - 처리 결과 비교 뷰파인더."""
from __future__ import annotations

import io
import ctypes
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton,
    QScrollArea, QFrame, QLineEdit, QSizePolicy, QTextEdit, QApplication,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QKeyEvent

from gui_pyside.styles import (
    VIEWFINDER_STYLESHEET, VF_BG, VF_ACCENT, VF_TEXT, VF_TEXT_DIM, VF_BORDER,
)
from gui_pyside.utils import CONFIG_DIR, PROMPTS_PATH, load_yaml, save_yaml, SETTINGS_PATH


VF_PURPLE = "#cba6f7"
VF_GREEN = "#a6e3a1"
VF_RED = "#f38ba8"
VF_YELLOW = "#f9e2af"
VF_TEXT_FAINT = "#555"
VF_PIP_BG = "#2a2a3a"
VF_PIP_SKIP = "#45475a"
VF_IMG_BG = "#f5f5f5"
VF_CARD = "#313244"
VF_SURFACE = "#2b2b3d"
VF_TITLEBAR_BG = "#181825"

VF_STAGES = ["분석", "누끼", "보정", "그림자", "크롭", "저장", "검증"]
STAGE_TABS = ["비교", "원본", "누끼", "보정", "그림자", "최종"]


class _PipBlock(QFrame):
    """10x4 색상 블록 (PIP 바 한 칸)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self.setMinimumWidth(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(f"background: {VF_PIP_BG}; border: none; border-radius: 1px;")

    def set_color(self, color: str):
        self.setStyleSheet(f"background: {color}; border: none; border-radius: 1px;")


class _FileRow(QFrame):
    """좌측 패널의 파일 행 위젯."""

    clicked = Signal(int)

    def __init__(self, idx: int, fname: str, parent=None):
        super().__init__(parent)
        self.idx = idx
        self.fname = fname
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)

        self.sel_bar = QFrame()
        self.sel_bar.setFixedWidth(3)
        self.sel_bar.setStyleSheet(f"background: {VF_BG};")
        layout.addWidget(self.sel_bar)

        content = QVBoxLayout()
        content.setContentsMargins(4, 3, 2, 3)
        content.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self.lbl_icon = QLabel("\u2b1c")
        self.lbl_icon.setFixedWidth(20)
        self.lbl_icon.setStyleSheet(f"font-size: 10pt; background: transparent;")
        top_row.addWidget(self.lbl_icon)

        self.lbl_name = QLabel(fname)
        self.lbl_name.setStyleSheet(
            f"color: {VF_TEXT}; font-size: 9pt; background: transparent;")
        self.lbl_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top_row.addWidget(self.lbl_name, 1)

        content.addLayout(top_row)

        pip_layout = QHBoxLayout()
        pip_layout.setContentsMargins(20, 0, 2, 0)
        pip_layout.setSpacing(1)
        self.pips: list[_PipBlock] = []
        for _ in VF_STAGES:
            pip = _PipBlock()
            pip_layout.addWidget(pip)
            self.pips.append(pip)
        content.addLayout(pip_layout)

        self.lbl_stage_text = QLabel("")
        self.lbl_stage_text.setStyleSheet(
            f"color: {VF_TEXT_FAINT}; font-size: 8pt; background: transparent;")
        self.lbl_stage_text.setContentsMargins(20, 0, 2, 0)
        content.addWidget(self.lbl_stage_text)

        self.val_labels: dict[str, QLabel] = {}
        self.val_row = QHBoxLayout()
        self.val_row.setContentsMargins(20, 0, 2, 0)
        self.val_row.setSpacing(6)
        for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형")]:
            lbl = QLabel(f"  {label}")
            lbl.setStyleSheet(f"color: {VF_TEXT_FAINT}; font-size: 8pt; background: transparent;")
            lbl.hide()
            self.val_row.addWidget(lbl)
            self.val_labels[key] = lbl
        self.val_row.addStretch()
        content.addLayout(self.val_row)

        layout.addLayout(content, 1)

        self._apply_bg(VF_BG)

    def set_selected(self, selected: bool):
        self._selected = selected
        if selected:
            self.sel_bar.setStyleSheet(f"background: {VF_ACCENT};")
            self._apply_bg(VF_CARD)
        else:
            self.sel_bar.setStyleSheet(f"background: {VF_BG};")
            self._apply_bg(VF_BG)

    def _apply_bg(self, color: str):
        self.setStyleSheet(
            f"_FileRow {{ background: {color}; border: none; }}")

    def mousePressEvent(self, event):
        self.clicked.emit(self.idx)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.fname)
            self.lbl_name.setStyleSheet(
                f"color: {VF_GREEN}; font-size: 9pt; background: transparent;")
            QTimer.singleShot(500, lambda: self.lbl_name.setStyleSheet(
                f"color: {VF_TEXT}; font-size: 9pt; background: transparent;"))
        super().mouseDoubleClickEvent(event)


class _ImageCanvas(QLabel):
    """종횡비 유지 이미지 표시 라벨."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"background: {VF_IMG_BG}; border: none;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(100, 100)
        self._source_pixmap: QPixmap | None = None

    def set_image(self, pixmap: QPixmap):
        self._source_pixmap = pixmap
        self._fit_display()

    def clear_image(self):
        self._source_pixmap = None
        self.clear()

    def show_placeholder(self, text: str, icon: str = ""):
        self._source_pixmap = None
        display = f"{icon}\n{text}" if icon else text
        self.setText(display)
        self.setStyleSheet(
            f"background: {VF_IMG_BG}; color: #999; font-size: 11pt; border: none;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._source_pixmap:
            self._fit_display()

    def _fit_display(self):
        if not self._source_pixmap or self._source_pixmap.isNull():
            return
        cw = max(self.width(), 100)
        ch = max(self.height(), 100)
        scaled = self._source_pixmap.scaled(
            cw - 10, ch - 10, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(scaled)
        self.setStyleSheet(f"background: {VF_IMG_BG}; border: none;")


class _VFPromptPreviewDialog(QDialog):
    """프롬프트 변경 미리보기 팝업."""

    def __init__(self, preview: dict, pair: dict, app, parent=None):
        super().__init__(parent)
        self.preview = preview
        self.pair = pair
        self.app = app
        self._preview_result_bytes: bytes | None = None

        self.setWindowTitle("프롬프트 변경 미리보기")
        self.resize(700, 620)
        self.setStyleSheet(f"QWidget {{ background: {VF_BG}; color: {VF_TEXT}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        prov_name = preview.get("provider_name", "")
        hint_key = preview.get("hint_key", "")
        current = preview.get("current_hint", "")
        suggested = preview.get("suggested_hint", "")

        header = QLabel(f"{prov_name} AI 추천 프롬프트")
        header.setStyleSheet(f"color: {VF_ACCENT}; font-size: 13pt; font-weight: bold;")
        layout.addWidget(header)

        key_lbl = QLabel(f"저장 키: {hint_key}")
        key_lbl.setStyleSheet(f"color: {VF_TEXT_DIM}; font-size: 9pt;")
        layout.addWidget(key_lbl)

        layout.addWidget(QLabel("현재 프롬프트:"))
        self.cur_text = QTextEdit()
        self.cur_text.setPlainText(current or "(없음)")
        self.cur_text.setReadOnly(True)
        self.cur_text.setMaximumHeight(100)
        self.cur_text.setStyleSheet(
            f"background: #2a2a3a; color: #a0a0b0; border: 1px solid {VF_BORDER};")
        layout.addWidget(self.cur_text)

        layout.addWidget(QLabel(f"{prov_name} 추천 프롬프트 (편집 가능):"))
        self.new_text = QTextEdit()
        self.new_text.setPlainText(suggested)
        self.new_text.setMaximumHeight(160)
        self.new_text.setStyleSheet(
            "background: #1a2a1a; color: #c0e0c0; border: 1px solid #2a4a2a;")
        layout.addWidget(self.new_text)

        prob_desc = preview.get("problem_description", "")
        if prob_desc:
            prob_lbl = QLabel(f"문제 설명: {prob_desc}")
            prob_lbl.setWordWrap(True)
            prob_lbl.setStyleSheet(f"color: {VF_TEXT_FAINT}; font-size: 8pt;")
            layout.addWidget(prob_lbl)

        self.lbl_preview_status = QLabel("")
        self.lbl_preview_status.setStyleSheet(f"color: {VF_TEXT_DIM}; font-size: 9pt;")
        layout.addWidget(self.lbl_preview_status)

        self.lbl_preview_img = QLabel()
        self.lbl_preview_img.setAlignment(Qt.AlignCenter)
        self.lbl_preview_img.hide()
        layout.addWidget(self.lbl_preview_img)

        btn_row = QHBoxLayout()
        self.btn_preview = QPushButton("결과 미리보기")
        self.btn_preview.setStyleSheet(
            "background: #2563eb; color: white; font-weight: bold; padding: 8px 16px;")
        self.btn_preview.clicked.connect(self._on_preview)
        btn_row.addWidget(self.btn_preview)

        self.btn_apply = QPushButton("적용 (프롬프트 저장)")
        self.btn_apply.setStyleSheet(
            "background: #16a34a; color: white; font-weight: bold; padding: 8px 16px;")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(self.btn_apply)

        btn_cancel = QPushButton("취소")
        btn_cancel.setStyleSheet(f"background: {VF_CARD}; color: {VF_TEXT}; padding: 8px 16px;")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.result_data: dict = {"action": "cancel", "hint": "", "bytes": None}

    def _on_preview(self):
        from gui_pyside.workers import ShadowPreviewWorker

        final_hint = self.new_text.toPlainText().strip()
        if not final_hint:
            self.lbl_preview_status.setText("프롬프트를 입력하세요")
            self.lbl_preview_status.setStyleSheet(f"color: {VF_YELLOW};")
            return

        self.btn_preview.setEnabled(False)
        self.btn_preview.setText("생성 중...")
        self.lbl_preview_status.setText("그림자 생성 중... (프롬프트 미저장)")
        self.lbl_preview_status.setStyleSheet(f"color: {VF_ACCENT};")

        vi = self.pair.get("vision_info", {})
        input_path = self.pair.get("input_path", "")
        fname = Path(input_path).name
        stage_data = self.app._vf_file_stages.get(fname, {}).get("stage_images", {})

        enhance_path = stage_data.get("보정")
        nukki_path = stage_data.get("누끼")

        pre_shadow_bytes = b""
        original_bytes = b""
        nukki_bytes = None

        if enhance_path and Path(enhance_path).exists():
            pre_shadow_bytes = Path(enhance_path).read_bytes()
        if input_path and Path(input_path).exists():
            original_bytes = Path(input_path).read_bytes()
        if nukki_path and Path(nukki_path).exists():
            nukki_bytes = Path(nukki_path).read_bytes()

        self._shadow_worker = ShadowPreviewWorker(
            pre_shadow_bytes=pre_shadow_bytes,
            original_bytes=original_bytes,
            nukki_png_bytes=nukki_bytes,
            temp_hint=final_hint,
            image_type=vi.get("image_type", "full"),
            category=vi.get("category", ""),
            shooting_angle=vi.get("shooting_angle", "front"),
            has_mannequin=vi.get("has_mannequin", False),
            parent=self,
        )
        self._shadow_worker.finished.connect(self._on_preview_done)
        self._shadow_worker.error.connect(self._on_preview_error)
        self._shadow_worker.start()

    def _on_preview_done(self, result_bytes: bytes):
        self._preview_result_bytes = result_bytes
        pixmap = QPixmap()
        pixmap.loadFromData(result_bytes)
        if not pixmap.isNull():
            scaled = pixmap.scaledToWidth(660, Qt.SmoothTransformation)
            if scaled.height() > 350:
                scaled = pixmap.scaledToHeight(350, Qt.SmoothTransformation)
            self.lbl_preview_img.setPixmap(scaled)
            self.lbl_preview_img.show()

        self.lbl_preview_status.setText("미리보기 생성 완료 - 만족하면 '적용' 클릭")
        self.lbl_preview_status.setStyleSheet(f"color: {VF_GREEN};")
        self.btn_apply.setEnabled(True)
        self.btn_preview.setEnabled(True)
        self.btn_preview.setText("결과 미리보기")

    def _on_preview_error(self, msg: str):
        self.lbl_preview_status.setText(f"오류: {msg}")
        self.lbl_preview_status.setStyleSheet(f"color: {VF_RED};")
        self.btn_preview.setEnabled(True)
        self.btn_preview.setText("결과 미리보기")

    def _on_apply(self):
        self.result_data = {
            "action": "apply",
            "hint": self.new_text.toPlainText().strip(),
            "hint_key": self.preview.get("hint_key", ""),
            "bytes": self._preview_result_bytes,
        }
        self.accept()


class ValidationFixDialog(QDialog):
    """검증 프롬프트 수정 미리보기 팝업."""

    def __init__(self, suggestion: dict, parent=None):
        super().__init__(parent)
        self.suggestion = suggestion
        self.setWindowTitle("검증 프롬프트 수정 미리보기")
        self.resize(750, 650)
        self.setStyleSheet(f"QWidget {{ background: {VF_BG}; color: {VF_TEXT}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        agree = suggestion.get("agree", False)
        reason = suggestion.get("reason", "")
        self.new_shadow = suggestion.get("updated_shadow_needed", "")
        self.new_template = suggestion.get("updated_user_template", "")

        if agree:
            header = QLabel("AI가 사용자 의견에 동의합니다")
            header.setStyleSheet(f"color: {VF_GREEN}; font-size: 13pt; font-weight: bold;")
        else:
            header = QLabel("AI가 사용자 의견에 동의하지 않습니다")
            header.setStyleSheet(f"color: {VF_YELLOW}; font-size: 13pt; font-weight: bold;")
        layout.addWidget(header)

        reason_lbl = QLabel(f"판단 근거: {reason}")
        reason_lbl.setWordWrap(True)
        reason_lbl.setStyleSheet(f"color: {VF_TEXT_DIM}; font-size: 9pt;")
        layout.addWidget(reason_lbl)

        has_changes = bool(self.new_shadow or self.new_template)

        self.shadow_text: QTextEdit | None = None
        self.template_text: QTextEdit | None = None

        if has_changes and self.new_shadow:
            layout.addWidget(QLabel("수정된 그림자 판정 기준 (편집 가능):"))
            self.shadow_text = QTextEdit()
            self.shadow_text.setPlainText(self.new_shadow)
            self.shadow_text.setMaximumHeight(150)
            self.shadow_text.setStyleSheet(
                "background: #1a2a1a; color: #c0e0c0; border: 1px solid #2a4a2a;")
            layout.addWidget(self.shadow_text)

        if has_changes and self.new_template:
            layout.addWidget(QLabel("수정된 검증 템플릿 (편집 가능):"))
            self.template_text = QTextEdit()
            self.template_text.setPlainText(self.new_template)
            self.template_text.setMaximumHeight(150)
            self.template_text.setStyleSheet(
                "background: #1a2a1a; color: #c0e0c0; border: 1px solid #2a4a2a;")
            layout.addWidget(self.template_text)

        if not has_changes:
            no_change = QLabel("프롬프트 변경 불필요 (AI 판단)")
            no_change.setStyleSheet(f"color: {VF_TEXT_DIM}; font-size: 10pt;")
            layout.addWidget(no_change)

        layout.addStretch()

        btn_row = QHBoxLayout()
        if has_changes:
            btn_force = QPushButton("프롬프트 저장 + 강제 합격")
            btn_force.setStyleSheet(
                "background: #16a34a; color: white; font-weight: bold; padding: 8px 16px;")
            btn_force.clicked.connect(lambda: self._finish("force_pass"))
            btn_row.addWidget(btn_force)

            btn_save = QPushButton("프롬프트만 저장")
            btn_save.setStyleSheet(
                "background: #2563eb; color: white; padding: 8px 16px;")
            btn_save.clicked.connect(lambda: self._finish("save_only"))
            btn_row.addWidget(btn_save)
        else:
            btn_force = QPushButton("강제 합격 처리")
            btn_force.setStyleSheet(
                "background: #d97706; color: white; font-weight: bold; padding: 8px 16px;")
            btn_force.clicked.connect(lambda: self._finish("force_pass"))
            btn_row.addWidget(btn_force)

        btn_cancel = QPushButton("취소")
        btn_cancel.setStyleSheet(f"background: {VF_CARD}; color: {VF_TEXT}; padding: 8px 16px;")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.result_data: dict = {"action": "cancel"}

    def _finish(self, action: str):
        self.result_data = {
            "action": action,
            "shadow_text": self.shadow_text.toPlainText().strip() if self.shadow_text else "",
            "template_text": self.template_text.toPlainText().strip() if self.template_text else "",
        }
        self.accept()


class ViewfinderDialog(QDialog):
    """뷰파인더 - 처리 결과 비교 다이얼로그."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("뷰파인더 - 처리 결과 비교")
        self.setStyleSheet(VIEWFINDER_STYLESHEET)

        self._current_idx = 0
        self._out_idx = 0
        self._stage_mode: str | None = None  # None=비교
        self._file_rows: dict[str, _FileRow] = {}
        self._prev_count = 0
        self._feedback_has_focus = False
        self._autofix_worker = None
        self._val_fix_worker = None

        self._setup_geometry()
        self._build_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(500)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._on_resize_done)

        self._initial_build()

    def _setup_geometry(self):
        try:
            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            rect = _RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0)
            work_x, work_y = rect.left, rect.top
            work_w = rect.right - rect.left
            work_h = rect.bottom - rect.top
        except Exception:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                work_x, work_y = geo.x(), geo.y()
                work_w, work_h = geo.width(), geo.height()
            else:
                work_x, work_y = 0, 0
                work_w, work_h = 1920, 1080

        dlg_h = work_h
        dlg_w = min(work_w, max(1500, int(dlg_h * 1.6)))
        dlg_x = work_x + max(0, (work_w - dlg_w) // 2)
        dlg_y = work_y
        self.setGeometry(dlg_x, dlg_y, dlg_w, dlg_h)
        self.setMinimumSize(1000, 650)

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._build_titlebar(root_layout)

        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_left_panel(main_layout)

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {VF_BORDER};")
        main_layout.addWidget(sep)

        self._build_right_panel(main_layout)

        root_layout.addWidget(main_widget, 1)

    def _build_titlebar(self, parent_layout: QVBoxLayout):
        titlebar = QFrame()
        titlebar.setFixedHeight(32)
        titlebar.setStyleSheet(f"background: {VF_TITLEBAR_BG};")
        tb_layout = QHBoxLayout(titlebar)
        tb_layout.setContentsMargins(10, 0, 12, 0)
        tb_layout.setSpacing(8)

        for c in [VF_RED, VF_YELLOW, VF_GREEN]:
            dot = QLabel("\u25cf")
            dot.setStyleSheet(f"color: {c}; font-size: 10pt; background: transparent;")
            tb_layout.addWidget(dot)

        title_lbl = QLabel("뷰파인더 - 처리 결과 비교")
        title_lbl.setStyleSheet(
            f"color: {VF_PURPLE}; font-size: 10pt; font-weight: bold; background: transparent;")
        tb_layout.addWidget(title_lbl)
        tb_layout.addStretch()

        esc_lbl = QLabel("ESC로 닫기")
        esc_lbl.setStyleSheet(
            f"color: {VF_TEXT_FAINT}; font-size: 9pt; background: transparent;")
        tb_layout.addWidget(esc_lbl)

        parent_layout.addWidget(titlebar)

    def _build_left_panel(self, parent_layout: QHBoxLayout):
        left = QWidget()
        left.setFixedWidth(280)
        left.setStyleSheet(f"background: {VF_BG};")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        header_frame = QWidget()
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 10, 10, 6)
        self.lbl_header = QLabel("처리 현황")
        self.lbl_header.setStyleSheet(
            f"color: {VF_TEXT_DIM}; font-size: 10pt; font-weight: bold; background: transparent;")
        header_layout.addWidget(self.lbl_header)
        header_layout.addStretch()
        left_layout.addWidget(header_frame)

        self.file_scroll = QScrollArea()
        self.file_scroll.setWidgetResizable(True)
        self.file_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_scroll.setStyleSheet(f"background: {VF_BG}; border: none;")

        self.file_list_widget = QWidget()
        self.file_list_layout = QVBoxLayout(self.file_list_widget)
        self.file_list_layout.setContentsMargins(4, 0, 4, 0)
        self.file_list_layout.setSpacing(2)
        self.file_list_layout.addStretch()

        self.file_scroll.setWidget(self.file_list_widget)
        left_layout.addWidget(self.file_scroll, 1)

        nav_frame = QWidget()
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(8, 6, 8, 8)
        nav_layout.setSpacing(6)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {VF_BORDER};")
        nav_layout.addWidget(sep)

        btn_nav_row = QHBoxLayout()
        self.btn_prev = QPushButton("\u25c0 이전")
        self.btn_prev.setStyleSheet(
            f"background: {VF_CARD}; color: {VF_TEXT}; padding: 3px 10px; border: none;")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(lambda: self._go(-1))
        btn_nav_row.addWidget(self.btn_prev)

        self.lbl_count = QLabel("0 / 0")
        self.lbl_count.setStyleSheet(
            f"color: {VF_TEXT_DIM}; font-size: 9pt; background: transparent;")
        self.lbl_count.setAlignment(Qt.AlignCenter)
        btn_nav_row.addWidget(self.lbl_count)

        self.btn_next = QPushButton("다음 \u25b6")
        self.btn_next.setStyleSheet(
            f"background: {VF_CARD}; color: {VF_TEXT}; padding: 3px 10px; border: none;")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(lambda: self._go(1))
        btn_nav_row.addWidget(self.btn_next)

        nav_layout.addLayout(btn_nav_row)
        left_layout.addWidget(nav_frame)

        parent_layout.addWidget(left)

    def _build_right_panel(self, parent_layout: QHBoxLayout):
        right = QWidget()
        right.setStyleSheet(f"background: {VF_BG};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # -- 라벨 행 --
        lbl_row = QHBoxLayout()
        lbl_row.setContentsMargins(12, 8, 12, 0)
        self.lbl_left_title = QLabel("원본")
        self.lbl_left_title.setStyleSheet(
            f"color: #bac2de; font-size: 11pt; font-weight: bold; background: transparent;")
        self.lbl_left_title.setAlignment(Qt.AlignCenter)
        lbl_row.addWidget(self.lbl_left_title, 1)
        self.lbl_right_title = QLabel("처리 결과")
        self.lbl_right_title.setStyleSheet(
            f"color: #bac2de; font-size: 11pt; font-weight: bold; background: transparent;")
        self.lbl_right_title.setAlignment(Qt.AlignCenter)
        lbl_row.addWidget(self.lbl_right_title, 1)
        right_layout.addLayout(lbl_row)

        # -- 탭 바 --
        tab_frame = QWidget()
        tab_layout = QHBoxLayout(tab_frame)
        tab_layout.setContentsMargins(12, 4, 12, 4)
        tab_layout.setSpacing(2)

        self.stage_tab_btns: dict[str, QPushButton] = {}
        for tab in STAGE_TABS:
            btn = QPushButton(tab)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"background: {VF_CARD}; color: {VF_TEXT}; padding: 2px 8px; border: none;")
            btn.clicked.connect(lambda checked=False, t=tab: self._select_stage_tab(t))
            tab_layout.addWidget(btn)
            self.stage_tab_btns[tab] = btn
        tab_layout.addStretch()
        self.stage_tab_btns["비교"].setStyleSheet(
            f"background: {VF_ACCENT}; color: {VF_BG}; padding: 2px 8px; border: none;")

        right_layout.addWidget(tab_frame)

        # -- 캔버스 영역 --
        canvas_widget = QWidget()
        canvas_layout = QHBoxLayout(canvas_widget)
        canvas_layout.setContentsMargins(8, 0, 8, 4)
        canvas_layout.setSpacing(0)

        self.cv_orig = _ImageCanvas()
        canvas_layout.addWidget(self.cv_orig, 1)

        self.sep_canvas = QFrame()
        self.sep_canvas.setFixedWidth(2)
        self.sep_canvas.setStyleSheet(f"background: {VF_PURPLE};")
        canvas_layout.addWidget(self.sep_canvas)

        self.cv_proc = _ImageCanvas()
        canvas_layout.addWidget(self.cv_proc, 1)

        right_layout.addWidget(canvas_widget, 1)

        # -- 정보 행 --
        info_row = QHBoxLayout()
        info_row.setContentsMargins(12, 4, 12, 0)
        self.lbl_orig_info = QLabel("")
        self.lbl_orig_info.setStyleSheet(
            f"color: {VF_TEXT_DIM}; font-size: 9pt; background: transparent;")
        info_row.addWidget(self.lbl_orig_info, 1)
        self.lbl_out_sel = QLabel("")
        self.lbl_out_sel.setStyleSheet(
            f"color: {VF_PURPLE}; font-size: 9pt; background: transparent;")
        info_row.addWidget(self.lbl_out_sel)
        self.lbl_proc_info = QLabel("")
        self.lbl_proc_info.setStyleSheet(
            f"color: {VF_TEXT_DIM}; font-size: 9pt; background: transparent;")
        info_row.addWidget(self.lbl_proc_info, 1)
        right_layout.addLayout(info_row)

        # -- 검증 결과 행 --
        val_row = QHBoxLayout()
        val_row.setContentsMargins(12, 4, 12, 0)
        self.lbl_val = QLabel("")
        self.lbl_val.setStyleSheet(
            f"color: {VF_TEXT_DIM}; font-size: 9pt; background: transparent;")
        val_row.addWidget(self.lbl_val, 1)
        right_layout.addLayout(val_row)

        # -- Vision 판단 행 --
        vision_row = QHBoxLayout()
        vision_row.setContentsMargins(12, 2, 12, 0)
        self.lbl_vision = QLabel("")
        self.lbl_vision.setStyleSheet(
            f"color: {VF_TEXT_DIM}; font-size: 9pt; background: transparent;")
        self.lbl_vision.setWordWrap(True)
        vision_row.addWidget(self.lbl_vision, 1)
        right_layout.addLayout(vision_row)

        # -- 독립 평가 패널 --
        self._build_eval_panel(right_layout)

        # -- 키보드 힌트 --
        hint_widget = QWidget()
        hint_layout = QVBoxLayout(hint_widget)
        hint_layout.setContentsMargins(12, 4, 12, 8)
        hint_sep = QFrame()
        hint_sep.setFixedHeight(1)
        hint_sep.setStyleSheet(f"background: {VF_BORDER};")
        hint_layout.addWidget(hint_sep)
        hint_text = QLabel(
            "\u2191\u2193 파일이동  \u2190\u2192 출력전환  1~6 단계보기  ESC 닫기")
        hint_text.setStyleSheet(
            f"color: {VF_TEXT_FAINT}; font-size: 9pt; background: transparent;")
        hint_text.setAlignment(Qt.AlignCenter)
        hint_layout.addWidget(hint_text)
        right_layout.addWidget(hint_widget)

        parent_layout.addWidget(right, 1)

    def _build_eval_panel(self, parent_layout: QVBoxLayout):
        eval_widget = QWidget()
        eval_layout = QVBoxLayout(eval_widget)
        eval_layout.setContentsMargins(12, 4, 12, 0)
        eval_layout.setSpacing(2)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {VF_BORDER};")
        eval_layout.addWidget(sep)

        # 점수 행
        score_row = QHBoxLayout()
        self.lbl_eval_title = QLabel("")
        self.lbl_eval_title.setStyleSheet(
            f"color: {VF_PURPLE}; font-size: 9pt; font-weight: bold; background: transparent;")
        score_row.addWidget(self.lbl_eval_title)

        self.eval_score_labels: dict[str, QLabel] = {}
        for cat_key in ["shadow_natural", "background_clean", "edge_quality",
                        "product_integrity", "commercial_quality"]:
            lbl = QLabel("")
            lbl.setStyleSheet(
                f"color: {VF_TEXT_DIM}; font-size: 8pt; background: transparent;")
            score_row.addWidget(lbl)
            self.eval_score_labels[cat_key] = lbl

        score_row.addStretch()
        eval_layout.addLayout(score_row)

        # 이슈 행
        self.lbl_eval_issues = QLabel("")
        self.lbl_eval_issues.setStyleSheet(
            f"color: {VF_YELLOW}; font-size: 8pt; background: transparent;")
        self.lbl_eval_issues.setWordWrap(True)
        eval_layout.addWidget(self.lbl_eval_issues)

        # 피드백 행
        fb_row = QHBoxLayout()
        fb_lbl = QLabel("의견:")
        fb_lbl.setStyleSheet(
            f"color: {VF_TEXT_DIM}; font-size: 9pt; background: transparent;")
        fb_row.addWidget(fb_lbl)

        self.eval_feedback_entry = QLineEdit()
        self.eval_feedback_entry.setStyleSheet(
            f"background: {VF_CARD}; color: {VF_TEXT}; border: none; padding: 3px 6px;")
        self.eval_feedback_entry.setPlaceholderText("수정 의견 입력...")
        self.eval_feedback_entry.installEventFilter(self)
        fb_row.addWidget(self.eval_feedback_entry, 1)
        eval_layout.addLayout(fb_row)

        # 버튼 행
        btn_row = QHBoxLayout()

        self.lbl_autofix_status = QLabel("")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_TEXT_DIM}; font-size: 8pt; background: transparent;")
        btn_row.addWidget(self.lbl_autofix_status, 1)

        self.btn_claude = QPushButton("클로드 복사")
        self.btn_claude.setStyleSheet(
            f"background: #45475a; color: {VF_TEXT}; padding: 3px 10px; border: none;")
        self.btn_claude.setCursor(Qt.PointingHandCursor)
        self.btn_claude.setEnabled(False)
        self.btn_claude.clicked.connect(self._on_claude_copy)
        btn_row.addWidget(self.btn_claude)

        self.btn_val_feedback = QPushButton("검증수정")
        self.btn_val_feedback.setStyleSheet(
            f"background: #45475a; color: {VF_TEXT}; padding: 3px 10px; border: none;")
        self.btn_val_feedback.setCursor(Qt.PointingHandCursor)
        self.btn_val_feedback.setEnabled(False)
        self.btn_val_feedback.clicked.connect(self._on_val_feedback)
        btn_row.addWidget(self.btn_val_feedback)

        self.btn_autofix = QPushButton("자동수정 (프롬프트)")
        self.btn_autofix.setStyleSheet(
            f"background: #45475a; color: {VF_TEXT}; padding: 3px 10px; border: none;")
        self.btn_autofix.setCursor(Qt.PointingHandCursor)
        self.btn_autofix.setEnabled(False)
        self.btn_autofix.clicked.connect(self._on_autofix)
        btn_row.addWidget(self.btn_autofix)

        eval_layout.addLayout(btn_row)
        parent_layout.addWidget(eval_widget)

    # ─── 이벤트 필터 (피드백 입력 포커스 감지) ───

    def eventFilter(self, obj, event):
        if obj is self.eval_feedback_entry:
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.FocusIn:
                self._feedback_has_focus = True
            elif event.type() == QEvent.FocusOut:
                self._feedback_has_focus = False
        return super().eventFilter(obj, event)

    # ─── 초기 빌드 ───

    def _initial_build(self):
        pairs = self._get_pairs()
        for i, p in enumerate(pairs):
            fname = Path(p["input_path"]).name
            self._add_file_row(i, fname, p)
            if p.get("success"):
                if fname not in self._get_stages():
                    self._get_stages()[fname] = {"stages": {}, "status": "done"}
                for s in VF_STAGES:
                    self._get_stages()[fname]["stages"][s] = "done"
            self._update_row_stages(fname)
        self._prev_count = len(pairs)

        if pairs:
            QTimer.singleShot(100, lambda: self.show_file(0))

    def _add_file_row(self, idx: int, fname: str, pair: dict):
        row = _FileRow(idx, fname)
        row.clicked.connect(self.show_file)
        self.file_list_layout.insertWidget(
            self.file_list_layout.count() - 1, row)
        self._file_rows[fname] = row

    # ─── 데이터 접근 ───

    def _get_pairs(self) -> list[dict]:
        return getattr(self.app, '_viewfinder_pairs', [])

    def _get_stages(self) -> dict:
        return getattr(self.app, '_vf_file_stages', {})

    # ─── 행 업데이트 ───

    def _update_row_stages(self, fname: str):
        row = self._file_rows.get(fname)
        if not row:
            return

        file_stage = self._get_stages().get(fname, {})
        stage_data = file_stage.get("stages", {})
        status = file_stage.get("status", "pending")
        validation = file_stage.get("validation")

        active_stage_name = ""
        for i, s in enumerate(VF_STAGES):
            st = stage_data.get(s, "")
            if st == "done":
                row.pips[i].set_color(VF_GREEN)
            elif st == "fail":
                row.pips[i].set_color(VF_RED)
            elif st == "active":
                row.pips[i].set_color(VF_ACCENT)
                active_stage_name = s
            elif st == "skip":
                row.pips[i].set_color(VF_PIP_SKIP)
            else:
                row.pips[i].set_color(VF_PIP_BG)

        if status == "processing" and active_stage_name:
            row.lbl_stage_text.setText(f"{active_stage_name} 중...")
            row.lbl_stage_text.setStyleSheet(
                f"color: {VF_ACCENT}; font-size: 8pt; background: transparent;")
            row.lbl_stage_text.show()
            for lbl in row.val_labels.values():
                lbl.hide()
        elif status == "done" and validation:
            row.lbl_stage_text.hide()
            for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형")]:
                lbl = row.val_labels.get(key)
                if not lbl:
                    continue
                item = validation.get(key, {})
                is_pass = item.get("pass", True)
                mark = "\u2705" if is_pass else "\u274c"
                color = VF_GREEN if is_pass else VF_RED
                lbl.setText(f"{mark}{label}")
                lbl.setStyleSheet(
                    f"color: {color}; font-size: 8pt; background: transparent;")
                lbl.show()
        elif status == "done":
            row.lbl_stage_text.setText("완료")
            row.lbl_stage_text.setStyleSheet(
                f"color: {VF_GREEN}; font-size: 8pt; background: transparent;")
            row.lbl_stage_text.show()
            for lbl in row.val_labels.values():
                lbl.hide()
        elif status == "fail":
            row.lbl_stage_text.setText("실패")
            row.lbl_stage_text.setStyleSheet(
                f"color: {VF_RED}; font-size: 8pt; background: transparent;")
            row.lbl_stage_text.show()
            for lbl in row.val_labels.values():
                lbl.hide()
        else:
            row.lbl_stage_text.setText("")
            for lbl in row.val_labels.values():
                lbl.hide()

        # 아이콘
        if validation and not validation.get("overall", True):
            icon = "\u26a0\ufe0f"
        else:
            icon = {"done": "\u2705", "processing": "\u23f3", "fail": "\u274c"}.get(
                status, "\u2b1c")
        row.lbl_icon.setText(icon)

        opacity_fg = VF_TEXT if status != "pending" else VF_TEXT_FAINT
        row.lbl_name.setStyleSheet(
            f"color: {opacity_fg}; font-size: 9pt; background: transparent;")

    def _highlight_row(self, idx: int):
        for fname, row in self._file_rows.items():
            row.set_selected(row.idx == idx)

    # ─── 탭 전환 ───

    def _select_stage_tab(self, tab_name: str):
        self._stage_mode = None if tab_name == "비교" else tab_name
        for name, btn in self.stage_tab_btns.items():
            if name == tab_name:
                btn.setStyleSheet(
                    f"background: {VF_ACCENT}; color: {VF_BG}; padding: 2px 8px; border: none;")
            else:
                btn.setStyleSheet(
                    f"background: {VF_CARD}; color: {VF_TEXT}; padding: 2px 8px; border: none;")
        self.show_file(self._current_idx, self._out_idx)

    # ─── 이미지 로드 헬퍼 ───

    def _load_pixmap_from_path(self, path: str) -> QPixmap | None:
        if path and Path(path).exists():
            pm = QPixmap(path)
            if not pm.isNull():
                return pm
        return None

    def _load_stage_image(self, fname: str, stage_name: str) -> QPixmap | None:
        si = self._get_stages().get(fname, {}).get("stage_images", {})
        path = si.get(stage_name)
        return self._load_pixmap_from_path(path)

    # ─── show_file: 메인 표시 ───

    def show_file(self, idx: int, out_sub: int = 0):
        pairs = self._get_pairs()
        if not pairs or idx < 0 or idx >= len(pairs):
            return
        self._current_idx = idx
        self._out_idx = out_sub
        pair = pairs[idx]
        self._highlight_row(idx)

        total = len(pairs)
        done_count = sum(1 for p in pairs if p.get("success"))
        self.lbl_count.setText(f"{idx + 1} / {total}")
        self.lbl_header.setText(f"처리 현황 ({done_count}/{total} 완료)")

        inp = pair["input_path"]
        fname = Path(inp).name
        sm = self._stage_mode

        if sm is not None:
            self._show_stage_mode(pair, fname, inp, sm)
        else:
            self._show_compare_mode(pair, inp)

        self._update_validation_display(pair)
        self._update_vision_display(pair)
        self._update_eval_panel(pair)

    def _show_stage_mode(self, pair: dict, fname: str, inp: str, sm: str):
        stage_order = ["원본", "누끼", "보정", "그림자", "최종"]
        si_idx = stage_order.index(sm) if sm in stage_order else 0

        prev_stage = stage_order[si_idx - 1] if si_idx > 0 else None
        self.lbl_left_title.setText(f"  {prev_stage or '원본'}")
        self.lbl_right_title.setText(f"  {sm}")

        if prev_stage:
            prev_pm = self._load_stage_image(fname, prev_stage)
        else:
            prev_pm = None
        if prev_pm:
            self.cv_orig.set_image(prev_pm)
            w, h = prev_pm.width(), prev_pm.height()
            self.lbl_orig_info.setText(f"{prev_stage}  \u00b7  {w}\u00d7{h}")
        else:
            pm = self._load_pixmap_from_path(inp)
            if pm:
                self.cv_orig.set_image(pm)
                self.lbl_orig_info.setText(
                    f"원본  \u00b7  {pm.width()}\u00d7{pm.height()}")
            else:
                self.cv_orig.show_placeholder("로드 실패", "\U0001f5bc\ufe0f")
                self.lbl_orig_info.setText("")

        cur_pm = self._load_stage_image(fname, sm)
        if cur_pm:
            self.cv_proc.set_image(cur_pm)
            self.lbl_proc_info.setText(
                f"{sm}  \u00b7  {cur_pm.width()}\u00d7{cur_pm.height()}")
        else:
            self.cv_proc.show_placeholder(f"{sm} 이미지 없음", "\U0001f4ad")
            self.lbl_proc_info.setText("")
        self.lbl_out_sel.setText("")

    def _show_compare_mode(self, pair: dict, inp: str):
        self.lbl_left_title.setText("  원본")
        self.lbl_right_title.setText("  처리 결과")

        pm_orig = self._load_pixmap_from_path(inp)
        if pm_orig:
            w, h = pm_orig.width(), pm_orig.height()
            sz = Path(inp).stat().st_size // 1024
            self.lbl_orig_info.setText(
                f"{Path(inp).name}  \u00b7  {w}\u00d7{h}  \u00b7  {sz}KB")
            self.cv_orig.set_image(pm_orig)
        else:
            self.cv_orig.show_placeholder("로드 실패", "\U0001f5bc\ufe0f")
            self.lbl_orig_info.setText(Path(inp).name)

        out_files = pair.get("output_files", [])
        out_sub = self._out_idx
        if out_files and out_sub < len(out_files):
            out_path = out_files[out_sub]["path"]
            pm_proc = self._load_pixmap_from_path(out_path)
            if pm_proc:
                pw, ph = pm_proc.width(), pm_proc.height()
                pkb = out_files[out_sub].get("size_kb",
                          Path(out_path).stat().st_size // 1024)
                self.lbl_proc_info.setText(
                    f"{Path(out_path).name}  \u00b7  {pw}\u00d7{ph}  \u00b7  {pkb}KB")
                self.cv_proc.set_image(pm_proc)
            else:
                self.cv_proc.show_placeholder("로드 실패", "\U0001f5bc\ufe0f")
                self.lbl_proc_info.setText("")
            if len(out_files) > 1:
                self.lbl_out_sel.setText(
                    f"  출력 {out_sub + 1}/{len(out_files)} (\u2190 \u2192 전환)  ")
            else:
                self.lbl_out_sel.setText("")
        elif pair.get("status") == "processing":
            self.cv_proc.show_placeholder("처리 중...", "\u23f3")
            self.lbl_proc_info.setText("")
            self.lbl_out_sel.setText("")
        else:
            self.cv_proc.show_placeholder("출력 없음", "\u2716")
            if not pair.get("success"):
                self.lbl_proc_info.setText("처리 실패")
                self.lbl_proc_info.setStyleSheet(
                    f"color: {VF_RED}; font-size: 9pt; background: transparent;")
            else:
                self.lbl_proc_info.setText("")
            self.lbl_out_sel.setText("")

    # ─── 정보 표시 업데이트 ───

    def _update_validation_display(self, pair: dict):
        validation = pair.get("validation")
        if not validation or validation.get("overall") is None:
            self.lbl_val.setText("")
            return

        parts = []
        for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형")]:
            item = validation.get(key, {})
            is_pass = item.get("pass", True)
            mark = "\u2705" if is_pass else "\u274c"
            parts.append(f"{mark}{label}")

        overall = validation.get("overall", True)
        color = VF_GREEN if overall else VF_RED
        text = "  ".join(parts)

        fails = []
        for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형")]:
            item = validation.get(key, {})
            if not item.get("pass", True):
                detail = item.get("detail", "")
                if detail:
                    fails.append(f"{label}: {detail}")
        if fails:
            text += "  |  " + " / ".join(fails)

        self.lbl_val.setText(text)
        self.lbl_val.setStyleSheet(
            f"color: {color}; font-size: 9pt; background: transparent;")

    def _update_vision_display(self, pair: dict):
        vi = pair.get("vision_info")
        if not vi:
            self.lbl_vision.setText("")
            return

        angle = vi.get("shooting_angle", "?")
        floor = "\u2705" if vi.get("floor_visible") else "\u274c"
        shadow = "\u2705" if vi.get("needs_shadow") else "\u274c"
        conf = vi.get("shadow_confidence", 0)
        reason = vi.get("shadow_reason", "")
        cat = vi.get("category", "")
        hand = "\u270b" if vi.get("has_human_hand") else ""
        mannequin = "\U0001f9cd" if vi.get("has_mannequin") else ""
        angle_kr = {
            "front": "정면", "top_down": "탑다운", "side": "측면",
            "detail": "디테일", "held": "손잡이", "worn": "착용",
        }.get(angle, angle)
        full_body = vi.get("is_full_body")
        full_tag = ""
        if angle == "worn" and full_body is not None:
            full_tag = "\U0001f455풀샷" if full_body else "\U0001f455반신"

        parts = [
            f"\U0001f3af {cat}" if cat else "",
            f"\U0001f4d0 {angle_kr}",
            full_tag,
            f"\U0001f6b6 바닥{floor}",
            f"\U0001f4a1 그림자{shadow}({conf:.0%})",
            hand, mannequin,
            f"\u2192 {reason}" if reason else "",
        ]
        text = "  ".join(p for p in parts if p)
        shadow_on = vi.get("needs_shadow", False)
        color = VF_ACCENT if shadow_on else VF_TEXT_DIM
        self.lbl_vision.setText(text)
        self.lbl_vision.setStyleSheet(
            f"color: {color}; font-size: 9pt; background: transparent;")

    def _update_eval_panel(self, pair: dict):
        ind_eval = pair.get("independent_eval")
        validation = pair.get("validation")

        has_val_fail = (validation and not validation.get("overall", True))
        self.btn_val_feedback.setEnabled(bool(has_val_fail))

        if not ind_eval or not ind_eval.get("overall_score"):
            self.lbl_eval_title.setText("")
            for lbl in self.eval_score_labels.values():
                lbl.setText("")
            self.lbl_eval_issues.setText("")
            self.btn_autofix.setEnabled(False)
            self.btn_claude.setEnabled(False)
            self.lbl_autofix_status.setText("")
            return

        overall = ind_eval.get("overall_score", 0)
        if overall >= 8:
            score_color = VF_GREEN
        elif overall >= 5:
            score_color = VF_YELLOW
        else:
            score_color = VF_RED
        self.lbl_eval_title.setText(f"독립평가 {overall}/10")
        self.lbl_eval_title.setStyleSheet(
            f"color: {score_color}; font-size: 9pt; font-weight: bold; background: transparent;")

        label_map = {
            "shadow_natural": "그림자",
            "background_clean": "배경",
            "edge_quality": "경계선",
            "product_integrity": "보존",
            "commercial_quality": "상업성",
        }
        for cat_key, lbl in self.eval_score_labels.items():
            item = ind_eval.get(cat_key, {})
            score = item.get("score", 0)
            label_text = label_map.get(cat_key, cat_key)
            if score >= 8:
                color = VF_GREEN
            elif score >= 7:
                color = VF_TEXT_DIM
            elif score >= 5:
                color = VF_YELLOW
            else:
                color = VF_RED
            lbl.setText(f"{label_text}{score}")
            lbl.setStyleSheet(
                f"color: {color}; font-size: 8pt; background: transparent;")

        critical = ind_eval.get("critical_issues", [])
        rec = ind_eval.get("recommendation", "")
        issue_parts = list(critical) if critical else []
        if rec:
            issue_parts.append(f"\U0001f4a1 {rec}")
        self.lbl_eval_issues.setText(" | ".join(issue_parts) if issue_parts else "")

        self.btn_autofix.setEnabled(True)
        self.btn_claude.setEnabled(True)

    # ─── 네비게이션 ───

    def _go(self, delta: int):
        self.show_file(self._current_idx + delta, 0)

    # ─── 키보드 ───

    def keyPressEvent(self, event: QKeyEvent):
        if self._feedback_has_focus:
            if event.key() == Qt.Key_Escape:
                self.setFocus()
            else:
                super().keyPressEvent(event)
            return

        key = event.key()
        if key == Qt.Key_Up:
            self._go(-1)
        elif key == Qt.Key_Down:
            self._go(1)
        elif key == Qt.Key_Left:
            if self._out_idx > 0:
                self.show_file(self._current_idx, self._out_idx - 1)
        elif key == Qt.Key_Right:
            pairs = self._get_pairs()
            if pairs and self._current_idx < len(pairs):
                out_files = pairs[self._current_idx].get("output_files", [])
                if self._out_idx < len(out_files) - 1:
                    self.show_file(self._current_idx, self._out_idx + 1)
        elif key == Qt.Key_Escape:
            self.close()
        elif event.text() in ("1", "2", "3", "4", "5", "6"):
            tab_idx = int(event.text()) - 1
            if tab_idx < len(STAGE_TABS):
                self._select_stage_tab(STAGE_TABS[tab_idx])
        else:
            super().keyPressEvent(event)

    # ─── 리사이즈 ───

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start(150)

    def _on_resize_done(self):
        self.show_file(self._current_idx, self._out_idx)

    # ─── 실시간 갱신 ───

    def _refresh(self):
        try:
            pairs = self._get_pairs()

            if len(pairs) > self._prev_count:
                for i in range(self._prev_count, len(pairs)):
                    p = pairs[i]
                    fname = Path(p["input_path"]).name
                    self._add_file_row(i, fname, p)
                    self._update_row_stages(fname)
                self._prev_count = len(pairs)

            for fname in list(self._get_stages().keys()):
                self._update_row_stages(fname)
        except (RuntimeError, AttributeError):
            # 앱 종료 중 위젯 접근 시 발생 — 타이머 정지
            if hasattr(self, '_refresh_timer'):
                self._refresh_timer.stop()

    # ─── 자동수정 ───

    def _on_autofix(self):
        from gui_pyside.workers import AutoFixWorker

        pairs = self._get_pairs()
        if not pairs or self._current_idx >= len(pairs):
            return
        pair = pairs[self._current_idx]
        ind_eval = pair.get("independent_eval")
        if not ind_eval:
            return

        user_fb = self.eval_feedback_entry.text().strip()
        vi = pair.get("vision_info", {})
        input_path = pair.get("input_path", "")
        fname = Path(input_path).name
        stage_data = self._get_stages().get(fname, {}).get("stage_images", {})

        enhance_path = stage_data.get("보정")
        if not enhance_path or not Path(enhance_path).exists():
            self.lbl_autofix_status.setText("보정 단계 이미지 없음")
            self.lbl_autofix_status.setStyleSheet(
                f"color: {VF_RED}; font-size: 8pt; background: transparent;")
            return

        self.btn_autofix.setEnabled(False)
        self.btn_autofix.setText("AI 질문 중...")
        self.lbl_autofix_status.setText("AI에게 프롬프트 추천 요청 중...")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_ACCENT}; font-size: 8pt; background: transparent;")

        self._autofix_worker = AutoFixWorker(
            mode="preview",
            evaluation=ind_eval,
            user_feedback=user_fb,
            image_type=vi.get("image_type", "full"),
            category=vi.get("category", ""),
            shooting_angle=vi.get("shooting_angle", "front"),
            parent=self,
        )
        self._autofix_worker.prompt_ready.connect(
            lambda result: self._show_prompt_preview(result, pair))
        self._autofix_worker.error.connect(self._on_autofix_error)
        self._autofix_worker.start()

    def _show_prompt_preview(self, preview: dict, pair: dict):
        suggested = preview.get("suggested_hint", "")
        if not suggested:
            self.lbl_autofix_status.setText("AI 추천 프롬프트 없음")
            self.lbl_autofix_status.setStyleSheet(
                f"color: {VF_YELLOW}; font-size: 8pt; background: transparent;")
            self._reset_autofix_btn()
            return

        dlg = _VFPromptPreviewDialog(preview, pair, self.app, parent=self)
        result_code = dlg.exec()

        if result_code == QDialog.Accepted and dlg.result_data.get("action") == "apply":
            self._apply_autofix_result(
                pair, dlg.result_data["hint"],
                dlg.result_data.get("hint_key", ""),
                dlg.result_data.get("bytes"))
        else:
            self.lbl_autofix_status.setText("사용자 취소")
            self.lbl_autofix_status.setStyleSheet(
                f"color: {VF_TEXT_DIM}; font-size: 8pt; background: transparent;")

        self._reset_autofix_btn()

    def _apply_autofix_result(self, pair: dict, final_hint: str, hint_key: str,
                              result_bytes: bytes | None):
        if result_bytes:
            self._apply_preview_bytes(pair, final_hint, hint_key, result_bytes)
        else:
            self._regenerate_shadow(pair, final_hint, hint_key)

    def _apply_preview_bytes(self, pair: dict, final_hint: str, hint_key: str,
                             result_bytes: bytes):
        self.btn_autofix.setEnabled(False)
        self.btn_autofix.setText("적용 중...")
        self.lbl_autofix_status.setText("프롬프트 저장 + 결과 적용 중...")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_ACCENT}; font-size: 8pt; background: transparent;")

        try:
            from src.pipeline import ImageEditPipeline
            pipe = ImageEditPipeline(config_dir=str(CONFIG_DIR))
            pipe._save_shadow_hint(hint_key, final_hint)
        except Exception as e:
            self.lbl_autofix_status.setText(f"프롬프트 저장 오류: {str(e)[:50]}")
            self.lbl_autofix_status.setStyleSheet(
                f"color: {VF_RED}; font-size: 8pt; background: transparent;")
            self._reset_autofix_btn()
            return

        out_files = pair.get("output_files", [])
        if out_files:
            out_path = out_files[0]["path"]
            try:
                from PIL import Image as _PILImage
                _img = _PILImage.open(io.BytesIO(result_bytes))
                _img.save(out_path, format="JPEG", quality=95)
                fsize = Path(out_path).stat().st_size
                pair["output_files"][0]["size"] = fsize
            except Exception as e:
                self.lbl_autofix_status.setText(f"이미지 저장 오류: {str(e)[:50]}")
                self.lbl_autofix_status.setStyleSheet(
                    f"color: {VF_RED}; font-size: 8pt; background: transparent;")
                self._reset_autofix_btn()
                return

        self.lbl_autofix_status.setText("프롬프트 저장 + 결과 적용 완료")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_GREEN}; font-size: 8pt; background: transparent;")

        input_path = pair.get("input_path", "")
        fname = Path(input_path).name
        self._mark_shadow_done(fname)
        self._reset_autofix_btn()
        self.show_file(self._current_idx, self._out_idx)
        self._update_eval_panel(pair)

    def _regenerate_shadow(self, pair: dict, final_hint: str, hint_key: str):
        from gui_pyside.workers import AutoFixWorker

        self.btn_autofix.setEnabled(False)
        self.btn_autofix.setText("그림자 재생성 중...")
        self.lbl_autofix_status.setText("변경된 프롬프트로 그림자 재생성 중...")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_ACCENT}; font-size: 8pt; background: transparent;")

        input_path = pair.get("input_path", "")
        fname = Path(input_path).name
        vi = pair.get("vision_info", {})
        ind_eval = pair.get("independent_eval", {})
        stage_data = self._get_stages().get(fname, {}).get("stage_images", {})
        enhance_path = stage_data.get("보정")
        nukki_path = stage_data.get("누끼")

        pre_shadow_bytes = b""
        original_bytes = b""
        nukki_bytes = None
        if enhance_path and Path(enhance_path).exists():
            pre_shadow_bytes = Path(enhance_path).read_bytes()
        if input_path and Path(input_path).exists():
            original_bytes = Path(input_path).read_bytes()
        if nukki_path and Path(nukki_path).exists():
            nukki_bytes = Path(nukki_path).read_bytes()

        self._mark_shadow_active(fname)

        self._regen_worker = AutoFixWorker(
            mode="regenerate",
            evaluation=ind_eval,
            pre_shadow_bytes=pre_shadow_bytes,
            original_bytes=original_bytes,
            nukki_png_bytes=nukki_bytes,
            suggested_hint=final_hint,
            hint_key=hint_key,
            image_type=vi.get("image_type", "full"),
            category=vi.get("category", ""),
            shooting_angle=vi.get("shooting_angle", "front"),
            has_mannequin=vi.get("has_mannequin", False),
            needs_shadow=vi.get("needs_shadow", True),
            parent=self,
        )
        self._regen_worker.regenerated.connect(
            lambda rb, ne: self._on_regen_done(pair, rb, ne, fname, ind_eval))
        self._regen_worker.error.connect(
            lambda msg: self._on_regen_error(msg, fname))
        self._regen_worker.start()

    def _on_regen_done(self, pair: dict, result_bytes: bytes, new_eval: dict,
                       fname: str, old_eval: dict):
        out_files = pair.get("output_files", [])
        if out_files:
            out_path = out_files[0]["path"]
            try:
                from PIL import Image as _PILImage
                _img = _PILImage.open(io.BytesIO(result_bytes))
                _img.save(out_path, format="JPEG", quality=95)
                fsize = Path(out_path).stat().st_size
                pair["output_files"][0]["size"] = fsize
            except Exception:
                pass

        pair["independent_eval"] = new_eval
        score_before = old_eval.get("overall_score", 0)
        score_after = new_eval.get("overall_score", 0)
        self.lbl_autofix_status.setText(
            f"그림자 재생성 {score_before:.0f}\u2192{score_after:.0f}/10")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_GREEN}; font-size: 8pt; background: transparent;")

        self._mark_shadow_done(fname)
        self._reset_autofix_btn()
        self.show_file(self._current_idx, self._out_idx)
        self._update_eval_panel(pair)

    def _on_regen_error(self, msg: str, fname: str):
        self.lbl_autofix_status.setText(f"오류: {msg[:50]}")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_RED}; font-size: 8pt; background: transparent;")
        self._mark_shadow_fail(fname)
        self._reset_autofix_btn()

    def _on_autofix_error(self, msg: str):
        self.lbl_autofix_status.setText(f"오류: {msg[:50]}")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_RED}; font-size: 8pt; background: transparent;")
        self._reset_autofix_btn()

    def _reset_autofix_btn(self):
        self.btn_autofix.setEnabled(True)
        self.btn_autofix.setText("자동수정 (프롬프트)")

    # ─── 그림자 단계 마킹 ───

    def _mark_shadow_active(self, fname: str):
        stages_dict = self._get_stages()
        if fname in stages_dict:
            stages_dict[fname]["status"] = "processing"
            s = stages_dict[fname].get("stages", {})
            s["그림자"] = "active"
            stages_dict[fname]["stages"] = s
        self._update_row_stages(fname)

    def _mark_shadow_done(self, fname: str):
        stages_dict = self._get_stages()
        if fname in stages_dict:
            s = stages_dict[fname].get("stages", {})
            s["그림자"] = "done"
            stages_dict[fname]["status"] = "done"
        row = self._file_rows.get(fname)
        if row:
            row.lbl_stage_text.setText("적용 완료")
            row.lbl_stage_text.setStyleSheet(
                f"color: {VF_GREEN}; font-size: 8pt; background: transparent;")
            row.lbl_stage_text.show()
            for lbl in row.val_labels.values():
                lbl.hide()
        self._update_row_stages(fname)

    def _mark_shadow_fail(self, fname: str):
        stages_dict = self._get_stages()
        if fname in stages_dict:
            s = stages_dict[fname].get("stages", {})
            s["그림자"] = "fail"
            stages_dict[fname]["status"] = "done"
        self._update_row_stages(fname)

    # ─── 클로드 복사 ───

    def _on_claude_copy(self):
        pairs = self._get_pairs()
        if not pairs or self._current_idx >= len(pairs):
            return
        pair = pairs[self._current_idx]
        ind_eval = pair.get("independent_eval", {})
        validation = pair.get("validation", {})

        input_path = pair.get("input_path", "")
        out_files = pair.get("output_files", [])
        output_path = out_files[0]["path"] if out_files else ""

        user_fb = self.eval_feedback_entry.text().strip()

        log_text = ""
        try:
            log_widget = self.app.log_text
            log_text = log_widget.toPlainText()
            log_lines = log_text.strip().split("\n")
            if len(log_lines) > 100:
                log_text = "\n".join(log_lines[-100:])
        except Exception:
            pass

        settings_snap = {}
        try:
            _s = load_yaml(SETTINGS_PATH)
            settings_snap = {
                "shadow_provider": _s.get("providers", {}).get("shadow", ""),
                "shadow_composite_method": _s.get("shadow_composite_method", ""),
                "gemini_shadow.model": _s.get("gemini_shadow", {}).get("model", ""),
                "gemini_shadow.main_prompt": _s.get("gemini_shadow", {}).get(
                    "main_prompt", "")[:300],
            }
        except Exception:
            pass

        autofix_result = {"attempts": pair.get("autofix_attempts", [])}

        try:
            from src.pipeline import ImageEditPipeline
            report = ImageEditPipeline._build_claude_report(
                input_path=input_path,
                output_path=output_path,
                evaluation=ind_eval,
                validation=validation,
                auto_fix_result=autofix_result,
                user_feedback=user_fb,
                log_text=log_text,
                settings_snapshot=settings_snap,
            )
        except Exception as e:
            report = f"리포트 생성 실패: {e}"

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(report)

        self.btn_claude.setText("복사됨!")
        self.btn_claude.setStyleSheet(
            f"background: #45475a; color: {VF_GREEN}; padding: 3px 10px; border: none;")
        QTimer.singleShot(2000, lambda: (
            self.btn_claude.setText("클로드 복사"),
            self.btn_claude.setStyleSheet(
                f"background: #45475a; color: {VF_TEXT}; padding: 3px 10px; border: none;"),
        ))

    # ─── 검증수정 ───

    def _on_val_feedback(self):
        from gui_pyside.workers import ValidationFixWorker

        pairs = self._get_pairs()
        if not pairs or self._current_idx >= len(pairs):
            return
        pair = pairs[self._current_idx]
        validation = pair.get("validation", {})
        if not validation:
            return

        user_fb = self.eval_feedback_entry.text().strip()
        if not user_fb:
            self.lbl_autofix_status.setText("의견을 입력해주세요 (예: 이 그림자는 합격이다)")
            self.lbl_autofix_status.setStyleSheet(
                f"color: {VF_YELLOW}; font-size: 8pt; background: transparent;")
            return

        fail_items = []
        label_map = {"background": "배경", "shadow": "그림자", "integrity": "원형보존"}
        for key in ["background", "shadow", "integrity"]:
            item = validation.get(key, {})
            if not item.get("pass", True):
                fail_items.append({
                    "key": key,
                    "label": label_map.get(key, key),
                    "detail": item.get("detail", ""),
                })

        if not fail_items:
            self.lbl_autofix_status.setText("불합격 항목 없음")
            self.lbl_autofix_status.setStyleSheet(
                f"color: {VF_TEXT_DIM}; font-size: 8pt; background: transparent;")
            return

        self.btn_val_feedback.setEnabled(False)
        self.btn_val_feedback.setText("AI 분석 중...")
        self.lbl_autofix_status.setText("검증 프롬프트 개선안 생성 중...")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_ACCENT}; font-size: 8pt; background: transparent;")

        vi = pair.get("vision_info", {})
        self._val_fix_worker = ValidationFixWorker(
            evaluation=pair.get("independent_eval", {}),
            user_feedback=user_fb,
            image_type=vi.get("image_type", "full"),
            category=vi.get("category", ""),
            shooting_angle=vi.get("shooting_angle", "front"),
            parent=self,
        )
        self._val_fix_worker.suggestion_ready.connect(
            lambda suggestion: self._show_val_preview(suggestion, pair))
        self._val_fix_worker.error.connect(self._on_val_fix_error)
        self._val_fix_worker.start()

    def _show_val_preview(self, suggestion: dict, pair: dict):
        dlg = ValidationFixDialog(suggestion, parent=self)
        result_code = dlg.exec()

        if result_code == QDialog.Accepted:
            action = dlg.result_data.get("action", "cancel")
            shadow_text = dlg.result_data.get("shadow_text", "")
            template_text = dlg.result_data.get("template_text", "")

            if action in ("save_only", "force_pass"):
                self._save_val_prompts(PROMPTS_PATH, shadow_text, template_text)

            if action == "force_pass":
                self._force_pass_validation(pair)

        self.btn_val_feedback.setEnabled(True)
        self.btn_val_feedback.setText("검증수정")

    def _save_val_prompts(self, prompts_path: Path, shadow_text: str, template_text: str):
        try:
            all_prompts = load_yaml(prompts_path)
            changed = False
            if shadow_text:
                all_prompts.setdefault("validation", {})["shadow_needed"] = shadow_text
                changed = True
            if template_text:
                all_prompts.setdefault("validation", {})["user_template"] = template_text
                changed = True
            if changed:
                save_yaml(prompts_path, all_prompts)
                self.lbl_autofix_status.setText("검증 프롬프트 저장 완료 (다음 처리부터 적용)")
                self.lbl_autofix_status.setStyleSheet(
                    f"color: {VF_GREEN}; font-size: 8pt; background: transparent;")
            else:
                self.lbl_autofix_status.setText("변경 없음")
                self.lbl_autofix_status.setStyleSheet(
                    f"color: {VF_TEXT_DIM}; font-size: 8pt; background: transparent;")
        except Exception as e:
            self.lbl_autofix_status.setText(f"저장 오류: {str(e)[:50]}")
            self.lbl_autofix_status.setStyleSheet(
                f"color: {VF_RED}; font-size: 8pt; background: transparent;")

    def _force_pass_validation(self, pair: dict):
        for key in ["background", "shadow", "integrity"]:
            if key in pair.get("validation", {}):
                pair["validation"][key]["pass"] = True
        pair["validation"]["overall"] = True

        fname = Path(pair.get("input_path", "")).name
        stages_dict = self._get_stages()
        if fname in stages_dict:
            stages_dict[fname]["validation"] = pair["validation"]
        self._update_row_stages(fname)

        self.lbl_autofix_status.setText("강제 합격 + 프롬프트 저장 완료")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_GREEN}; font-size: 8pt; background: transparent;")
        self._update_eval_panel(pair)
        self.show_file(self._current_idx, self._out_idx)

    def _on_val_fix_error(self, msg: str):
        self.lbl_autofix_status.setText(f"오류: {msg[:60]}")
        self.lbl_autofix_status.setStyleSheet(
            f"color: {VF_RED}; font-size: 8pt; background: transparent;")
        self.btn_val_feedback.setEnabled(True)
        self.btn_val_feedback.setText("검증수정")

    # ─── 닫기 ───

    def closeEvent(self, event):
        self._refresh_timer.stop()
        self._resize_timer.stop()
        if hasattr(self.app, '_vf_dlg'):
            self.app._vf_dlg = None
        super().closeEvent(event)
