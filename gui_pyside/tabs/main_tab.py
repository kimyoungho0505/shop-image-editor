"""MainTab - PySide6 implementation of the main execution tab."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QFrame,
    QRadioButton, QButtonGroup, QCheckBox, QSpinBox,
    QComboBox, QProgressBar, QTextEdit, QFileDialog,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor

if TYPE_CHECKING:
    from gui_pyside.app import App

from gui_pyside.utils import APP_DIR


class MainTab(QWidget):

    def __init__(self, app: App):
        super().__init__()
        self.app = app
        self._build_ui()
        self._sync_state_to_widgets()

    # ── UI 구성 ──

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(0)

        top_area = QVBoxLayout()
        top_area.setSpacing(6)

        self._build_folder_section(top_area)
        self._build_provider_option_section(top_area)
        self._build_action_bar(top_area)

        root.addLayout(top_area)
        self._build_log_area(root)

    # ── 1. Folder section ──

    def _build_folder_section(self, parent_layout: QVBoxLayout):
        card = QFrame()
        card.setFrameShape(QFrame.NoFrame)
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 6, 8, 6)
        grid.setColumnStretch(1, 1)

        self.input_edit = QLineEdit(self.app.state.get("input_folder", ""))
        self.output_edit = QLineEdit(
            self.app.state.get("output_folder", str(APP_DIR / "output")))

        rows = [
            ("입력", self.input_edit, self._browse_input, lambda: self._open_folder(self.input_edit.text())),
            ("출력", self.output_edit, self._browse_output, lambda: self._open_folder(self.output_edit.text())),
        ]

        for r, (label_text, edit, browse_fn, open_fn) in enumerate(rows):
            lbl = QLabel(label_text)
            lbl.setFont(QFont("맑은 고딕", 10, QFont.Bold))
            lbl.setFixedWidth(36)
            grid.addWidget(lbl, r, 0, Qt.AlignLeft)

            grid.addWidget(edit, r, 1)

            btn_browse = QPushButton("...")
            btn_browse.setFixedWidth(32)
            btn_browse.clicked.connect(browse_fn)

            btn_open = QPushButton("열기")
            btn_open.setFixedWidth(42)
            btn_open.clicked.connect(open_fn)

            btn_frame = QHBoxLayout()
            btn_frame.setSpacing(2)
            btn_frame.addWidget(btn_browse)
            btn_frame.addWidget(btn_open)
            grid.addLayout(btn_frame, r, 2)

        self.input_edit.textChanged.connect(
            lambda t: self._update_state("input_folder", t))
        self.output_edit.textChanged.connect(
            lambda t: self._update_state("output_folder", t))

        parent_layout.addWidget(card)

    # ── 2. Provider + Option section ──

    def _build_provider_option_section(self, parent_layout: QVBoxLayout):
        mid_row = QHBoxLayout()
        mid_row.setSpacing(8)

        # Provider card (left, wider)
        prov_card = QGroupBox("프로바이더")
        prov_layout = QVBoxLayout(prov_card)
        prov_layout.setSpacing(4)
        prov_layout.setContentsMargins(8, 8, 8, 4)
        self._build_provider_rows(prov_layout)

        # Option card (right, narrow)
        opt_card = QGroupBox("옵션")
        opt_layout = QVBoxLayout(opt_card)
        opt_layout.setSpacing(2)
        opt_layout.setContentsMargins(8, 8, 8, 4)
        self._build_option_checks(opt_layout)

        mid_row.addWidget(prov_card, 3)
        mid_row.addWidget(opt_card, 1)

        parent_layout.addLayout(mid_row)

    def _build_provider_rows(self, layout: QVBoxLayout):
        # Row 1: Analysis | Background | Enhance
        row1 = QHBoxLayout()
        row1.setSpacing(2)

        # Analysis provider
        row1.addWidget(self._bold_label("분석"))
        self.bg_vision = QButtonGroup(self)
        for txt, val in [("Claude", "claude"), ("ChatGPT", "chatgpt"),
                         ("Gemini", "gemini"), ("Grok", "grok")]:
            rb = QRadioButton(txt)
            self.bg_vision.addButton(rb)
            rb.setProperty("state_value", val)
            row1.addWidget(rb)

        row1.addWidget(self._vsep())

        # Background provider
        row1.addWidget(self._bold_label("배경"))
        self.bg_bg_remove = QButtonGroup(self)
        for txt, val in [("Photoroom", "photoroom"), ("remove.bg", "removebg"), ("복합", "hybrid")]:
            rb = QRadioButton(txt)
            self.bg_bg_remove.addButton(rb)
            rb.setProperty("state_value", val)
            row1.addWidget(rb)

        row1.addWidget(self._vsep())

        # Enhance provider
        row1.addWidget(self._bold_label("보정"))
        self.bg_enhance = QButtonGroup(self)
        for txt, val in [("Claid.ai", "claid"), ("OpenCV", "opencv")]:
            rb = QRadioButton(txt)
            self.bg_enhance.addButton(rb)
            rb.setProperty("state_value", val)
            row1.addWidget(rb)

        row1.addStretch()
        layout.addLayout(row1)

        # Row 2: Shadow
        row2 = QHBoxLayout()
        row2.setSpacing(2)
        row2.addWidget(self._bold_label("그림자"))
        self.bg_shadow = QButtonGroup(self)
        shadow_items = [
            ("API", "api_shadow"), ("Gemini", "gemini_shadow"),
            ("Grok", "grok_shadow"), ("누끼합성", "opencv_extract"),
            ("SAM-M", "sam_mobile"), ("SAM-CPU", "sam_cpu"),
            ("GPU-B", "sam_gpu_b"), ("GPU-L", "sam_gpu_l"),
            ("GPU-H", "sam_gpu_h"), ("없음", "none"),
        ]
        self._shadow_radio_map = {}
        for txt, val in shadow_items:
            rb = QRadioButton(txt)
            self.bg_shadow.addButton(rb)
            rb.setProperty("state_value", val)
            self._shadow_radio_map[val] = rb
            row2.addWidget(rb)
        row2.addStretch()
        layout.addLayout(row2)

        # Row 3: Shadow judge mode
        row3 = QHBoxLayout()
        row3.setSpacing(2)
        lbl_judge = self._bold_label("판단모드")
        lbl_judge.setToolTip(
            "AI 자동: Vision API가 촬영 상황 분석 후 그림자 필요 여부 자동 결정\n"
            "항상 생성: 모든 이미지에 그림자 생성\n"
            "항상 스킵: 그림자 생성 안 함")
        row3.addWidget(lbl_judge)
        self.bg_judge = QButtonGroup(self)
        for txt, val in [("AI 자동", "auto"), ("항상 생성", "always"), ("항상 스킵", "never")]:
            rb = QRadioButton(txt)
            self.bg_judge.addButton(rb)
            rb.setProperty("state_value", val)
            row3.addWidget(rb)
        row3.addStretch()
        layout.addLayout(row3)

        # Row 4: Shadow composite mode
        row4 = QHBoxLayout()
        row4.setSpacing(2)
        lbl_comp = self._bold_label("합성방식")
        lbl_comp.setToolTip(
            "기존(오버레이): AI 결과 위에 원본 누끼를 덮어씌움\n"
            "레이어분리: AI 결과에서 그림자만 추출하여 합성\n"
            "-> 제품 변형 문제가 발생하면 레이어분리 사용 권장")
        row4.addWidget(lbl_comp)
        self.bg_composite = QButtonGroup(self)
        for txt, val in [("기존(오버레이)", "overlay"), ("레이어분리", "layer_extract")]:
            rb = QRadioButton(txt)
            self.bg_composite.addButton(rb)
            rb.setProperty("state_value", val)
            row4.addWidget(rb)
        row4.addStretch()
        layout.addLayout(row4)

        # Connect radio button groups to state
        self.bg_vision.buttonClicked.connect(
            lambda btn: self._update_state("vision_provider", btn.property("state_value")))
        self.bg_bg_remove.buttonClicked.connect(
            lambda btn: self._update_state("bg_provider", btn.property("state_value")))
        self.bg_enhance.buttonClicked.connect(
            lambda btn: self._update_state("enhance_provider", btn.property("state_value")))
        self.bg_shadow.buttonClicked.connect(
            lambda btn: self._update_state("shadow_provider", btn.property("state_value")))
        self.bg_judge.buttonClicked.connect(
            lambda btn: self._update_state("shadow_judge_mode", btn.property("state_value")))
        self.bg_composite.buttonClicked.connect(
            lambda btn: self._update_state("shadow_composite", btn.property("state_value")))

    def _build_option_checks(self, layout: QVBoxLayout):
        self.chk_skip_bg = QCheckBox("배경 제거 생략")
        self.chk_skip_bg.toggled.connect(
            lambda v: self._update_state("skip_bg", v))
        layout.addWidget(self.chk_skip_bg)

        self.chk_skip_analysis = QCheckBox("AI 분석 생략")
        self.chk_skip_analysis.toggled.connect(
            lambda v: self._update_state("skip_analysis", v))
        layout.addWidget(self.chk_skip_analysis)

        self.chk_pre_cropped = QCheckBox("크롭 완료 이미지")
        self.chk_pre_cropped.setToolTip(
            "이미 크롭된 이미지를 입력할 때 사용.\n"
            "크롭/여백/중앙정렬을 건너뛰고\n"
            "누끼 + 보정 + 그림자만 수행합니다.\n"
            "Vision API 참고 이미지도 1장만 사용하여 비용 절감")
        self.chk_pre_cropped.toggled.connect(
            lambda v: self._update_state("pre_cropped", v))
        layout.addWidget(self.chk_pre_cropped)

        refine_row = QHBoxLayout()
        refine_row.setSpacing(4)
        self.chk_auto_refine = QCheckBox("자동 수정")
        self.chk_auto_refine.toggled.connect(
            lambda v: self._update_state("auto_refine", v))
        refine_row.addWidget(self.chk_auto_refine)

        self.spin_iterations = QSpinBox()
        self.spin_iterations.setRange(1, 10)
        self.spin_iterations.setFixedWidth(48)
        self.spin_iterations.valueChanged.connect(
            lambda v: self._update_state("max_iterations", v))
        refine_row.addWidget(self.spin_iterations)
        refine_row.addWidget(QLabel("회"))
        refine_row.addStretch()
        layout.addLayout(refine_row)

        layout.addStretch()

    # ── 3. Action bar ──

    def _build_action_bar(self, parent_layout: QVBoxLayout):
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self.btn_run_single = QPushButton("  파일  ")
        self.btn_run_single.setProperty("cssClass", "accent")
        self.btn_run_single.clicked.connect(lambda: self._on_run("single"))

        self.btn_run_batch = QPushButton("  폴더  ")
        self.btn_run_batch.setProperty("cssClass", "accent")
        self.btn_run_batch.clicked.connect(lambda: self._on_run("batch"))

        self.btn_analyze = QPushButton("분석만")
        self.btn_analyze.clicked.connect(lambda: self._on_run("analyze"))

        self.btn_stop = QPushButton("중지")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self.app.stop())

        self.btn_restart = QPushButton("재시작")
        self.btn_restart.setProperty("cssClass", "success")
        self.btn_restart.clicked.connect(lambda: self.app.restart())

        self.btn_viewfinder = QPushButton("뷰파인더")
        self.btn_viewfinder.setEnabled(False)
        self.btn_viewfinder.clicked.connect(lambda: self.app.open_viewfinder())

        for btn in [self.btn_run_single, self.btn_run_batch, self.btn_analyze,
                     self.btn_stop, self.btn_restart, self.btn_viewfinder]:
            bar.addWidget(btn)

        # Concurrent workers
        bar.addWidget(QLabel("동시:"))
        self.combo_workers = QComboBox()
        self.combo_workers.addItems(["1", "2", "4", "8"])
        self.combo_workers.setFixedWidth(50)
        self.combo_workers.setToolTip(
            "동시 처리 수\n1 = 순차 처리\n4 = 4개 파이프라인 동시 실행\n유료 API 기준 2~4 권장")
        self.combo_workers.currentTextChanged.connect(
            lambda t: self._update_state("concurrent_workers", int(t)))
        bar.addWidget(self.combo_workers)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        bar.addWidget(self.progress_bar, 1)

        self.lbl_progress = QLabel("0%")
        self.lbl_progress.setFixedWidth(40)
        self.lbl_progress.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar.addWidget(self.lbl_progress)

        parent_layout.addLayout(bar)

    # ── 4. Log area ──

    def _build_log_area(self, root_layout: QVBoxLayout):
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e2e; color: #cdd6f4; "
            "border: none; border-radius: 6px; padding: 6px; }")
        root_layout.addWidget(self.log_text, 1)

        self._log_formats = {}
        for tag, color in [("info", "#89b4fa"), ("success", "#a6e3a1"),
                           ("error", "#f38ba8"), ("warn", "#fab387")]:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._log_formats[tag] = fmt

    # ── Helpers ──

    def _bold_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("맑은 고딕", 9, QFont.Bold))
        return lbl

    def _vsep(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setFixedWidth(2)
        sep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        return sep

    def _update_state(self, key: str, value):
        self.app.state[key] = value

    def _select_radio(self, group: QButtonGroup, value: str):
        for btn in group.buttons():
            if btn.property("state_value") == value:
                btn.setChecked(True)
                return

    def _sync_state_to_widgets(self):
        s = self.app.state
        self._select_radio(self.bg_vision, s.get("vision_provider", "claude"))
        self._select_radio(self.bg_bg_remove, s.get("bg_provider", "photoroom"))
        self._select_radio(self.bg_enhance, s.get("enhance_provider", "claid"))
        self._select_radio(self.bg_shadow, s.get("shadow_provider", "opencv_extract"))
        self._select_radio(self.bg_judge, s.get("shadow_judge_mode", "auto"))
        self._select_radio(self.bg_composite, s.get("shadow_composite", "overlay"))

        self.chk_skip_bg.setChecked(s.get("skip_bg", False))
        self.chk_skip_analysis.setChecked(s.get("skip_analysis", False))
        self.chk_pre_cropped.setChecked(s.get("pre_cropped", False))
        self.chk_auto_refine.setChecked(s.get("auto_refine", False))
        self.spin_iterations.setValue(s.get("max_iterations", 3))

        workers = str(s.get("concurrent_workers", 1))
        idx = self.combo_workers.findText(workers)
        if idx >= 0:
            self.combo_workers.setCurrentIndex(idx)

    # ── Public methods (called by app) ──

    def append_log(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        fmt = self._log_formats.get(level, self._log_formats["info"])
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"[{ts}] {msg}\n", fmt)
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()

    def clear_log(self):
        self.log_text.clear()

    def set_progress(self, value: float, text: str = ""):
        v = int(min(max(value, 0), 100))
        self.progress_bar.setValue(v)
        self.lbl_progress.setText(text if text else f"{v}%")

    def set_running(self, is_running: bool):
        for btn in [self.btn_run_single, self.btn_run_batch, self.btn_analyze]:
            btn.setEnabled(not is_running)
        self.btn_stop.setEnabled(is_running)
        self.btn_viewfinder.setEnabled(is_running)

    def on_processing_finished(self, success: int, fail: int):
        self.set_running(False)

    def get_selected_files(self) -> list[str]:
        return []

    # ── Button actions ──

    def _on_run(self, mode: str):
        if mode == "single":
            files = self._browse_single_file()
            if not files:
                return
        self.set_running(True)
        self.app.run(mode)

    def _browse_input(self):
        folder = QFileDialog.getExistingDirectory(self, "입력 폴더 선택")
        if folder:
            self.input_edit.setText(folder)

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if folder:
            self.output_edit.setText(folder)

    def _browse_single_file(self) -> list[str]:
        files, _ = QFileDialog.getOpenFileNames(
            self, "이미지 파일 선택",
            self.app.state.get("input_folder", ""),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)")
        if files:
            self.app.state["_selected_files"] = files
        return files

    def _open_folder(self, path: str):
        if path and os.path.isdir(path):
            os.startfile(path)
