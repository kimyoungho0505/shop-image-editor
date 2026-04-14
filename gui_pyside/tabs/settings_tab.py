"""SettingsTab - PySide6 implementation of the settings tab."""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QRadioButton, QButtonGroup, QCheckBox,
    QComboBox, QTextEdit, QScrollArea,
    QTreeWidget, QTreeWidgetItem, QSizePolicy,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer

if TYPE_CHECKING:
    from gui_pyside.app import App

from gui_pyside.utils import (
    SETTINGS_PATH, CATEGORIES_PATH, ENV_PATH,
    load_yaml, save_yaml,
)
from gui_pyside.styles import SUCCESS, DANGER


# ── 기본 프롬프트 상수 ──

GEMINI_MAIN_PROMPT_DEFAULT = (
    "(가장 중요) 제공된 PNG 이미지의 알파 채널과 제품의 모든 픽셀 위치, "
    "스케일(크기)을 0.001%의 변경도 없이 100% 그대로 고정하세요. "
    "제품의 크기를 키우거나 위치를 옮기는 행위를 최우선으로 금지합니다.\n"
    "1. 배경 및 경계 보존: 배경은 결점 없는 순백색(#FFFFFF)을 유지하되, "
    "제품 바닥면과 배경이 만나는 경계선(Edge)이 조명에 의해 날아가지 않도록 "
    "선명하게 보존하세요. 하단 경계가 배경과 동화되는 현상을 엄격히 금지합니다.\n"
    "2. 입체적 조명 처리: 제품의 질감과 색조를 보호하면서, 특히 제품 하단부에 "
    "아주 미세하고 자연스러운 음영(Contact Occlusion)을 남겨 제품이 바닥에 "
    "견고하게 놓여 있는 느낌을 구현하세요.\n"
    "3. 그림자 생성: 이미 정의된 제품 하단 라인을 따라 식별이 가능할 정도의 "
    "아주 연한 투명 그레이 접지 그림자를 추가하세요. 너무 흐릿한 안개 효과보다는 "
    "바닥면을 지지하는 실질적인 그림자 형태여야 합니다.\n"
    "4. 금지 사항: 그림자 생성을 위해 제품을 확대하거나 위치를 옮기는 행위, "
    "경계선을 뭉개는 인공적인 블러(Blur) 처리나 과도한 화이트닝, "
    "그리고 제품의 디테일을 보여주기 위해 스케일을 확대하는 행위를 엄격히 금지합니다."
)

GEMINI_ORIGINAL_PROMPT_DEFAULT = (
    "위 이미지는 원본 제품 사진입니다. 원본에 있는 자연스러운 그림자의 방향, 농도, 부드러움을 참고하세요.\n"
    "원본 사진의 그림자를 최대한 동일하게 재현해주세요. "
    "그림자의 방향이 같도록 해주세요. 피사체의 사이즈는 변경하지 말아주세요."
)

GEMINI_MANNEQUIN_PROMPT_DEFAULT = (
    "위 이미지는 마네킹에 착용된 의류 원본 사진입니다. "
    "다음 작업을 수행해주세요:\n"
    "1. 배경을 완전히 제거하고 깨끗한 흰색(#FFFFFF)으로 교체하세요.\n"
    "2. 마네킹/토르소/스탠드를 완전히 제거하세요.\n"
    "3. 마네킹 제거 후 의류의 자연스러운 마감선(밑단, 소매 등)을 복원하세요.\n"
    "그림자는 추가하지 마세요. 배경은 순백색을 유지하세요.\n"
    "의류 자체(색상, 질감, 로고, 지퍼 등)는 절대 변경하지 마세요."
)

GROK_MAIN_PROMPT_DEFAULT = (
    "위 이미지는 배경이 제거된 누끼 이미지입니다. "
    "이 누끼 이미지의 바닥에 자연스러운 접지 그림자(ground shadow)를 추가해주세요. "
    "제품 자체는 절대 변경하지 마세요. 배경은 깨끗한 흰색을 유지하세요. "
    "그림자는 제품 바로 아래에 부드럽게 퍼지는 형태로, "
    "럭셔리 이커머스 제품 사진처럼 고급스럽게 만들어주세요. "
    "누끼 이미지를 기반으로 결과를 출력하세요."
)

GROK_ORIGINAL_PROMPT_DEFAULT = (
    "위 이미지는 원본 제품 사진입니다. 원본에 있는 자연스러운 그림자의 방향, 농도, 부드러움을 참고하세요.\n"
    "원본 사진의 그림자를 최대한 동일하게 재현해주세요."
)

GROK_MANNEQUIN_PROMPT_DEFAULT = (
    "위 이미지는 마네킹에 착용된 의류 원본 사진입니다. 다음 작업을 수행해주세요:\n"
    "1. 배경을 완전히 제거하고 깨끗한 흰색(#FFFFFF)으로 교체하세요.\n"
    "2. 마네킹/토르소/스탠드를 완전히 제거하세요.\n"
    "3. 마네킹 제거 후 의류의 자연스러운 마감선(밑단, 소매 등)을 복원하세요.\n"
    "4. 의류 하단에 자연스러운 접지 그림자를 추가하세요.\n"
    "의류 자체(색상, 질감, 로고, 지퍼 등)는 절대 변경하지 마세요. "
    "럭셔리 이커머스 제품 사진처럼 고급스럽게 만들어주세요."
)

ENHANCE_DEFAULTS = {
    "full":    {"hdr": "20", "sharpness": "15", "exposure": "0", "saturation": "0", "contrast": "0"},
    "detail":  {"hdr": "15", "sharpness": "10", "exposure": "0", "saturation": "0", "contrast": "0"},
    "worn":    {"hdr": "10", "sharpness": "5",  "exposure": "0", "saturation": "0", "contrast": "0"},
    "package": {"hdr": "20", "sharpness": "15", "exposure": "0", "saturation": "0", "contrast": "0"},
}
ENHANCE_TYPES = ["full", "detail", "worn", "package"]
ENHANCE_FIELDS = ["hdr", "sharpness", "exposure", "saturation", "contrast"]


class SettingsTab(QWidget):

    def __init__(self, app: App):
        super().__init__()
        self.app = app

        self.api_key_edits: dict[str, QLineEdit] = {}
        self.api_key_checks: dict[str, QCheckBox] = {}
        self.claid_vars: dict[tuple[str, str], QLineEdit] = {}
        self.opencv_vars: dict[tuple[str, str], QLineEdit] = {}

        self._gemini_adv_visible = False
        self._grok_adv_visible = False

        self._build_ui()
        self.load_settings()
        self.load_categories()

    # ================================================================
    #  UI Build
    # ================================================================

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(8)

        self._build_api_keys_section()
        self._build_provider_section()
        self._build_output_section()
        self._build_photoroom_section()
        self._build_claid_section()
        self._build_opencv_section()
        self._build_removebg_section()
        self._build_shadow_extract_section()
        self._build_gemini_shadow_section()
        self._build_grok_shadow_section()
        self._build_tts_section()
        self._build_category_section()

        self._layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ── 1. API 키 및 모델 ──

    def _build_api_keys_section(self):
        grp = QGroupBox("API 키 및 모델")
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        api_keys = [
            ("Anthropic (Claude)", "ANTHROPIC_API_KEY"),
            ("Photoroom", "PHOTOROOM_API_KEY"),
            ("Claid.ai", "CLAID_API_KEY"),
            ("remove.bg", "REMOVEBG_API_KEY"),
            ("OpenAI", "OPENAI_API_KEY"),
            ("Gemini", "GEMINI_API_KEY"),
            ("xAI (Grok)", "XAI_API_KEY"),
        ]

        for r, (label, env_key) in enumerate(api_keys):
            grid.addWidget(QLabel(f"{label}:"), r, 0, Qt.AlignLeft)

            edit = QLineEdit(os.environ.get(env_key, ""))
            edit.setEchoMode(QLineEdit.Password)
            self.api_key_edits[env_key] = edit
            grid.addWidget(edit, r, 1)

            cb = QCheckBox("표시")
            self.api_key_checks[env_key] = cb
            cb.toggled.connect(lambda checked, e=edit: (
                e.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            ))
            grid.addWidget(cb, r, 2)

            btn = QPushButton("저장")
            btn.setFixedWidth(48)
            btn.clicked.connect(lambda _, ek=env_key: self.save_api_key(ek))
            grid.addWidget(btn, r, 3)

        # 모델 선택 행
        model_row = len(api_keys)
        model_widget = QWidget()
        mh = QHBoxLayout(model_widget)
        mh.setContentsMargins(0, 4, 0, 0)

        mh.addWidget(QLabel("Claude:"))
        self.cb_model = QComboBox()
        self.cb_model.addItems(["claude-opus-4-20250514", "claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"])
        self.cb_model.setCurrentText("claude-sonnet-4-20250514")
        mh.addWidget(self.cb_model)
        mh.addSpacing(8)

        mh.addWidget(QLabel("OpenAI:"))
        self.cb_openai_model = QComboBox()
        self.cb_openai_model.addItems(["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"])
        mh.addWidget(self.cb_openai_model)
        mh.addSpacing(8)

        mh.addWidget(QLabel("Gemini:"))
        self.cb_gemini_model = QComboBox()
        self.cb_gemini_model.addItems(["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"])
        mh.addWidget(self.cb_gemini_model)
        mh.addSpacing(8)

        mh.addWidget(QLabel("Grok:"))
        self.cb_grok_model = QComboBox()
        self.cb_grok_model.addItems(["grok-4-fast-non-reasoning", "grok-4-fast-reasoning", "grok-4-0709"])
        mh.addWidget(self.cb_grok_model)
        mh.addSpacing(8)

        btn_model_save = QPushButton("모델 저장")
        btn_model_save.clicked.connect(self.save_model_settings)
        mh.addWidget(btn_model_save)
        mh.addStretch()

        grid.addWidget(model_widget, model_row, 0, 1, 4)

        grp.setLayout(grid)
        self._layout.addWidget(grp)

    # ── 2. 처리 프로바이더 ──

    def _build_provider_section(self):
        grp = QGroupBox("처리 프로바이더")
        vbox = QVBoxLayout()

        grid = QGridLayout()

        # 이미지 분석
        grid.addWidget(QLabel("이미지 분석:"), 0, 0, Qt.AlignLeft)
        self.bg_vision = QButtonGroup(self)
        for c, (txt, val) in enumerate([("Claude", "claude"), ("ChatGPT", "chatgpt"),
                                         ("Gemini", "gemini"), ("Grok", "grok")]):
            rb = QRadioButton(txt)
            rb.setProperty("provider_val", val)
            self.bg_vision.addButton(rb)
            grid.addWidget(rb, 0, c + 1)

        # 배경 제거
        grid.addWidget(QLabel("배경 제거:"), 1, 0, Qt.AlignLeft)
        self.bg_removal = QButtonGroup(self)
        for c, (txt, val) in enumerate([("Photoroom", "photoroom"), ("remove.bg", "removebg"), ("복합", "hybrid")]):
            rb = QRadioButton(txt)
            rb.setProperty("provider_val", val)
            self.bg_removal.addButton(rb)
            grid.addWidget(rb, 1, c + 1)

        # 이미지 보정
        grid.addWidget(QLabel("이미지 보정:"), 2, 0, Qt.AlignLeft)
        self.bg_enhance = QButtonGroup(self)
        for c, (txt, val) in enumerate([("Claid.ai", "claid"), ("OpenCV", "opencv")]):
            rb = QRadioButton(txt)
            rb.setProperty("provider_val", val)
            self.bg_enhance.addButton(rb)
            grid.addWidget(rb, 2, c + 1)

        # 그림자
        grid.addWidget(QLabel("그림자:"), 3, 0, Qt.AlignLeft)
        self.bg_shadow = QButtonGroup(self)
        shadow_opts = [
            ("API", "api_shadow"), ("Gemini", "gemini_shadow"),
            ("Grok", "grok_shadow"), ("누끼합성", "opencv_extract"),
            ("SAM-M", "sam_mobile"), ("SAM-CPU", "sam_cpu"),
            ("GPU-B", "sam_gpu_b"), ("GPU-L", "sam_gpu_l"),
            ("GPU-H", "sam_gpu_h"), ("없음", "none"),
        ]
        for c, (txt, val) in enumerate(shadow_opts):
            rb = QRadioButton(txt)
            rb.setProperty("provider_val", val)
            self.bg_shadow.addButton(rb)
            grid.addWidget(rb, 3, c + 1)
            if val.startswith("sam_gpu_"):
                setattr(self, f"rb_{val}_settings", rb)

        # 판단모드
        grid.addWidget(QLabel("판단모드:"), 4, 0, Qt.AlignLeft)
        self.bg_judge = QButtonGroup(self)
        for c, (txt, val) in enumerate([("AI 자동 (권장)", "auto"),
                                         ("항상 생성", "always"),
                                         ("항상 스킵", "never")]):
            rb = QRadioButton(txt)
            rb.setProperty("provider_val", val)
            self.bg_judge.addButton(rb)
            grid.addWidget(rb, 4, c + 1)

        vbox.addLayout(grid)

        # GPU 상태 + 경고
        info_row = QHBoxLayout()
        self.sam_gpu_label = QLabel("")
        info_row.addWidget(self.sam_gpu_label)
        self.prov_warning = QLabel("")
        self.prov_warning.setStyleSheet(f"color: {DANGER};")
        info_row.addWidget(self.prov_warning)
        info_row.addStretch()
        vbox.addLayout(info_row)

        # 저장 버튼
        btn_row = QHBoxLayout()
        btn_save = QPushButton("설정 저장")
        btn_save.setProperty("cssClass", "accent")
        btn_save.clicked.connect(self.save_provider_settings)
        btn_row.addWidget(btn_save)
        self.prov_status = QLabel("")
        btn_row.addWidget(self.prov_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

        self._detect_sam_gpu()

        # 경고 업데이트
        self.bg_removal.buttonClicked.connect(self._update_provider_warning)
        self.bg_shadow.buttonClicked.connect(self._update_provider_warning)

    # ── 3. 출력 이미지 ──

    def _build_output_section(self):
        grp = QGroupBox("출력 이미지")
        vbox = QVBoxLayout()
        row = QHBoxLayout()

        labels = [
            ("가로 (px):", "860"),
            ("세로 (px):", "860"),
            ("최대 용량 (KB):", "2024"),
            ("JPEG 품질:", "95"),
        ]
        self.out_edits: dict[str, QLineEdit] = {}
        keys = ["width", "height", "max_kb", "jpeg_q"]

        for (label, default), key in zip(labels, keys):
            row.addWidget(QLabel(label))
            edit = QLineEdit(default)
            edit.setFixedWidth(60)
            self.out_edits[key] = edit
            row.addWidget(edit)
            row.addSpacing(8)

        row.addStretch()
        vbox.addLayout(row)

        btn = QPushButton("설정 저장")
        btn.setProperty("cssClass", "accent")
        btn.clicked.connect(self.save_output_settings)
        vbox.addWidget(btn, alignment=Qt.AlignLeft)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ── 4. Photoroom API 옵션 ──

    def _build_photoroom_section(self):
        grp = QGroupBox("Photoroom API 옵션")
        vbox = QVBoxLayout()

        # 모드
        mode_row = QHBoxLayout()
        self.bg_pr_mode = QButtonGroup(self)
        rb_manual = QRadioButton("수동 설정")
        rb_manual.setProperty("provider_val", "manual")
        rb_manual.setChecked(True)
        self.bg_pr_mode.addButton(rb_manual)
        mode_row.addWidget(rb_manual)
        rb_ai = QRadioButton("AI 자동")
        rb_ai.setProperty("provider_val", "ai_auto")
        self.bg_pr_mode.addButton(rb_ai)
        mode_row.addWidget(rb_ai)
        mode_row.addStretch()
        vbox.addLayout(mode_row)

        # 옵션
        form = QGridLayout()

        form.addWidget(QLabel("shadow.mode:"), 0, 0, Qt.AlignLeft)
        self.cb_pr_shadow_mode = QComboBox()
        self.cb_pr_shadow_mode.addItems(["none", "ai.soft", "ai.hard", "ai.floating"])
        self.cb_pr_shadow_mode.setCurrentText("ai.soft")
        form.addWidget(self.cb_pr_shadow_mode, 0, 1)

        form.addWidget(QLabel("shadow.opacity:"), 1, 0, Qt.AlignLeft)
        self.edit_pr_shadow_opacity = QLineEdit("0.5")
        self.edit_pr_shadow_opacity.setFixedWidth(80)
        form.addWidget(self.edit_pr_shadow_opacity, 1, 1)

        form.addWidget(QLabel("padding:"), 2, 0, Qt.AlignLeft)
        self.edit_pr_padding = QLineEdit("0.08")
        self.edit_pr_padding.setFixedWidth(80)
        form.addWidget(self.edit_pr_padding, 2, 1)

        form.addWidget(QLabel("outputSize:"), 3, 0, Qt.AlignLeft)
        self.cb_pr_output_size = QComboBox()
        self.cb_pr_output_size.addItems(["originalImage", "1000x1000", "2000x2000"])
        form.addWidget(self.cb_pr_output_size, 3, 1)

        vbox.addLayout(form)

        btn_row = QHBoxLayout()
        btn = QPushButton("설정 저장")
        btn.setProperty("cssClass", "accent")
        btn.clicked.connect(self.save_photoroom_settings)
        btn_row.addWidget(btn)
        self.pr_status = QLabel("")
        btn_row.addWidget(self.pr_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ── 5. Claid.ai 보정 옵션 ──

    def _build_claid_section(self):
        grp = QGroupBox("Claid.ai 보정 옵션")
        vbox = QVBoxLayout()
        self.bg_claid_mode = QButtonGroup(self)
        self._build_enhance_grid(vbox, self.bg_claid_mode, self.claid_vars)
        btn_row = QHBoxLayout()
        btn = QPushButton("설정 저장")
        btn.setProperty("cssClass", "accent")
        btn.clicked.connect(self.save_claid_settings)
        btn_row.addWidget(btn)
        self.cl_status = QLabel("")
        btn_row.addWidget(self.cl_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)
        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ── 5-2. OpenCV 보정 옵션 ──

    def _build_opencv_section(self):
        grp = QGroupBox("OpenCV 보정 옵션")
        vbox = QVBoxLayout()
        self.bg_opencv_mode = QButtonGroup(self)
        self._build_enhance_grid(vbox, self.bg_opencv_mode, self.opencv_vars)
        btn_row = QHBoxLayout()
        btn = QPushButton("설정 저장")
        btn.setProperty("cssClass", "accent")
        btn.clicked.connect(self.save_opencv_settings)
        btn_row.addWidget(btn)
        self.cv_status = QLabel("")
        btn_row.addWidget(self.cv_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)
        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    def _build_enhance_grid(self, parent_layout: QVBoxLayout,
                            mode_group: QButtonGroup,
                            vars_dict: dict):
        mode_row = QHBoxLayout()
        rb_manual = QRadioButton("수동 설정")
        rb_manual.setProperty("provider_val", "manual")
        rb_manual.setChecked(True)
        mode_group.addButton(rb_manual)
        mode_row.addWidget(rb_manual)
        rb_ai = QRadioButton("AI 자동")
        rb_ai.setProperty("provider_val", "ai_auto")
        mode_group.addButton(rb_ai)
        mode_row.addWidget(rb_ai)
        mode_row.addStretch()
        parent_layout.addLayout(mode_row)

        grid = QGridLayout()
        # 헤더
        for ci, t in enumerate(ENHANCE_TYPES):
            lbl = QLabel(t)
            lbl.setStyleSheet("font-weight: bold;")
            lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(lbl, 0, ci + 1)

        for ri, field in enumerate(ENHANCE_FIELDS):
            grid.addWidget(QLabel(field), ri + 1, 0, Qt.AlignLeft)
            for ci, t in enumerate(ENHANCE_TYPES):
                edit = QLineEdit(ENHANCE_DEFAULTS[t][field])
                edit.setFixedWidth(50)
                edit.setAlignment(Qt.AlignCenter)
                vars_dict[(t, field)] = edit
                grid.addWidget(edit, ri + 1, ci + 1, Qt.AlignCenter)

        parent_layout.addLayout(grid)

    # ── 6. remove.bg 옵션 ──

    def _build_removebg_section(self):
        grp = QGroupBox("remove.bg 옵션")
        vbox = QVBoxLayout()
        row = QHBoxLayout()

        row.addWidget(QLabel("size:"))
        self.cb_rb_size = QComboBox()
        self.cb_rb_size.addItems(["auto", "preview", "full"])
        row.addWidget(self.cb_rb_size)
        row.addSpacing(16)

        row.addWidget(QLabel("type:"))
        self.cb_rb_type = QComboBox()
        self.cb_rb_type.addItems(["product", "person", "car"])
        row.addWidget(self.cb_rb_type)
        row.addStretch()
        vbox.addLayout(row)

        btn_row = QHBoxLayout()
        btn = QPushButton("설정 저장")
        btn.setProperty("cssClass", "accent")
        btn.clicked.connect(self.save_removebg_settings)
        btn_row.addWidget(btn)
        self.rb_status = QLabel("")
        btn_row.addWidget(self.rb_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ── 7. 누끼 합성 그림자 ──

    def _build_shadow_extract_section(self):
        grp = QGroupBox("누끼 합성 그림자 (원본 그림자 추출)")
        vbox = QVBoxLayout()

        # 추출 방식 + 파라미터 모드
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("추출 방식:"))
        self.bg_se_method = QButtonGroup(self)
        rb_lv = QRadioButton("레벨보정")
        rb_lv.setProperty("provider_val", "level_correction")
        rb_lv.setChecked(True)
        self.bg_se_method.addButton(rb_lv)
        top_row.addWidget(rb_lv)
        rb_tp = QRadioButton("원본이식")
        rb_tp.setProperty("provider_val", "transplant")
        self.bg_se_method.addButton(rb_tp)
        top_row.addWidget(rb_tp)
        top_row.addSpacing(16)

        top_row.addWidget(QLabel("파라미터:"))
        self.bg_se_param_mode = QButtonGroup(self)
        rb_m = QRadioButton("수동")
        rb_m.setProperty("provider_val", "manual")
        self.bg_se_param_mode.addButton(rb_m)
        top_row.addWidget(rb_m)
        rb_a = QRadioButton("AI 자동")
        rb_a.setProperty("provider_val", "ai_auto")
        rb_a.setChecked(True)
        self.bg_se_param_mode.addButton(rb_a)
        top_row.addWidget(rb_a)
        top_row.addStretch()
        vbox.addLayout(top_row)

        # 8개 파라미터 (2열)
        se_opts = [
            ("opacity:", "se_opacity", "70"),
            ("threshold:", "se_threshold", "8"),
            ("blur:", "se_blur", "3"),
            ("search_top:", "se_search_top", "5"),
            ("search_bottom:", "se_search_bottom", "60"),
            ("search_sides:", "se_search_sides", "30"),
            ("mask_expand:", "se_mask_expand", "2.5"),
            ("distance_falloff:", "se_distance_falloff", "60"),
        ]

        grid = QGridLayout()
        self.se_edits: dict[str, QLineEdit] = {}
        half = len(se_opts) // 2
        for i, (label, key, default) in enumerate(se_opts):
            col_offset = 0 if i < half else 2
            row = i if i < half else i - half
            grid.addWidget(QLabel(label), row, col_offset, Qt.AlignLeft)
            edit = QLineEdit(default)
            edit.setFixedWidth(60)
            self.se_edits[key] = edit
            grid.addWidget(edit, row, col_offset + 1)

        vbox.addLayout(grid)

        btn_row = QHBoxLayout()
        btn = QPushButton("설정 저장")
        btn.setProperty("cssClass", "accent")
        btn.clicked.connect(self.save_shadow_extract_settings)
        btn_row.addWidget(btn)
        self.se_status = QLabel("")
        btn_row.addWidget(self.se_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ── 8. Gemini AI 그림자 프롬프트 ──

    def _build_gemini_shadow_section(self):
        grp = QGroupBox("Gemini AI 그림자 프롬프트")
        vbox = QVBoxLayout()

        # 모델 + 순서
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("이미지 모델:"))
        self.cb_gemini_shadow_model = QComboBox()
        self.cb_gemini_shadow_model.addItems([
            "gemini-3.1-flash-image-preview",
            "gemini-2.5-flash-image",
            "gemini-3-pro-image-preview",
        ])
        top_row.addWidget(self.cb_gemini_shadow_model)
        top_row.addSpacing(12)

        top_row.addWidget(QLabel("순서:"))
        self.bg_gemini_order = QButtonGroup(self)
        rb_after = QRadioButton("보정 후 (권장)")
        rb_after.setProperty("provider_val", "after_enhance")
        rb_after.setChecked(True)
        self.bg_gemini_order.addButton(rb_after)
        top_row.addWidget(rb_after)
        rb_before = QRadioButton("보정 전")
        rb_before.setProperty("provider_val", "before_enhance")
        self.bg_gemini_order.addButton(rb_before)
        top_row.addWidget(rb_before)
        top_row.addStretch()
        vbox.addLayout(top_row)

        # 폴백 모델
        fb_row = QHBoxLayout()
        fb_row.addWidget(QLabel("폴백 모델:"))
        self.cb_gemini_fallback_model = QComboBox()
        self.cb_gemini_fallback_model.addItems([
            "gemini-3-pro-image-preview",
            "gemini-3.1-flash-image-preview",
            "gemini-2.5-flash-image",
        ])
        fb_row.addWidget(self.cb_gemini_fallback_model)
        fb_row.addStretch()
        vbox.addLayout(fb_row)

        # 메인 프롬프트
        vbox.addWidget(QLabel("그림자 생성:"))
        self.txt_gemini_main = QTextEdit()
        self.txt_gemini_main.setPlainText(GEMINI_MAIN_PROMPT_DEFAULT)
        self.txt_gemini_main.setMaximumHeight(160)
        vbox.addWidget(self.txt_gemini_main)

        # 토글 버튼
        self._gemini_adv_btn = QPushButton("\u25b6 상세 프롬프트 (2개)")
        self._gemini_adv_btn.setFlat(True)
        self._gemini_adv_btn.setStyleSheet("text-align: left; color: #6b7280; padding: 2px;")
        self._gemini_adv_btn.setCursor(Qt.PointingHandCursor)
        self._gemini_adv_btn.clicked.connect(self._toggle_gemini_advanced)
        vbox.addWidget(self._gemini_adv_btn)

        # 상세 프롬프트 프레임
        self._gemini_adv_widget = QWidget()
        adv_layout = QVBoxLayout(self._gemini_adv_widget)
        adv_layout.setContentsMargins(0, 0, 0, 0)

        adv_layout.addWidget(QLabel("원본 참고:"))
        self.txt_gemini_original = QTextEdit()
        self.txt_gemini_original.setPlainText(GEMINI_ORIGINAL_PROMPT_DEFAULT)
        self.txt_gemini_original.setMaximumHeight(80)
        adv_layout.addWidget(self.txt_gemini_original)

        adv_layout.addWidget(QLabel("마네킹 제거:"))
        self.txt_gemini_mannequin = QTextEdit()
        self.txt_gemini_mannequin.setPlainText(GEMINI_MANNEQUIN_PROMPT_DEFAULT)
        self.txt_gemini_mannequin.setMaximumHeight(100)
        adv_layout.addWidget(self.txt_gemini_mannequin)

        self._gemini_adv_widget.setVisible(False)
        vbox.addWidget(self._gemini_adv_widget)

        # 버튼
        btn_row = QHBoxLayout()
        btn_save = QPushButton("설정 저장")
        btn_save.setProperty("cssClass", "accent")
        btn_save.clicked.connect(self.save_gemini_shadow_settings)
        btn_row.addWidget(btn_save)
        btn_reset = QPushButton("기본값 복원")
        btn_reset.clicked.connect(self._reset_gemini_shadow_prompts)
        btn_row.addWidget(btn_reset)
        self.gs_status = QLabel("")
        btn_row.addWidget(self.gs_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ── 8-2. Grok AI 그림자 프롬프트 ──

    def _build_grok_shadow_section(self):
        grp = QGroupBox("Grok AI 그림자 프롬프트")
        vbox = QVBoxLayout()

        # 모델 + 순서
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("모델:"))
        self.cb_grok_shadow_model = QComboBox()
        self.cb_grok_shadow_model.addItems(["grok-imagine-image", "grok-imagine-image-pro"])
        top_row.addWidget(self.cb_grok_shadow_model)
        top_row.addSpacing(12)

        top_row.addWidget(QLabel("순서:"))
        self.bg_grok_order = QButtonGroup(self)
        rb_after = QRadioButton("보정 후 (권장)")
        rb_after.setProperty("provider_val", "after_enhance")
        rb_after.setChecked(True)
        self.bg_grok_order.addButton(rb_after)
        top_row.addWidget(rb_after)
        rb_before = QRadioButton("보정 전")
        rb_before.setProperty("provider_val", "before_enhance")
        self.bg_grok_order.addButton(rb_before)
        top_row.addWidget(rb_before)
        top_row.addStretch()
        vbox.addLayout(top_row)

        # 메인 프롬프트
        vbox.addWidget(QLabel("그림자 생성:"))
        self.txt_grok_main = QTextEdit()
        self.txt_grok_main.setPlainText(GROK_MAIN_PROMPT_DEFAULT)
        self.txt_grok_main.setMaximumHeight(160)
        vbox.addWidget(self.txt_grok_main)

        # 토글 버튼
        self._grok_adv_btn = QPushButton("\u25b6 상세 프롬프트 (2개)")
        self._grok_adv_btn.setFlat(True)
        self._grok_adv_btn.setStyleSheet("text-align: left; color: #6b7280; padding: 2px;")
        self._grok_adv_btn.setCursor(Qt.PointingHandCursor)
        self._grok_adv_btn.clicked.connect(self._toggle_grok_advanced)
        vbox.addWidget(self._grok_adv_btn)

        # 상세 프롬프트 프레임
        self._grok_adv_widget = QWidget()
        adv_layout = QVBoxLayout(self._grok_adv_widget)
        adv_layout.setContentsMargins(0, 0, 0, 0)

        adv_layout.addWidget(QLabel("원본 참고:"))
        self.txt_grok_original = QTextEdit()
        self.txt_grok_original.setPlainText(GROK_ORIGINAL_PROMPT_DEFAULT)
        self.txt_grok_original.setMaximumHeight(80)
        adv_layout.addWidget(self.txt_grok_original)

        adv_layout.addWidget(QLabel("마네킹 제거:"))
        self.txt_grok_mannequin = QTextEdit()
        self.txt_grok_mannequin.setPlainText(GROK_MANNEQUIN_PROMPT_DEFAULT)
        self.txt_grok_mannequin.setMaximumHeight(100)
        adv_layout.addWidget(self.txt_grok_mannequin)

        self._grok_adv_widget.setVisible(False)
        vbox.addWidget(self._grok_adv_widget)

        # 버튼
        btn_row = QHBoxLayout()
        btn_save = QPushButton("설정 저장")
        btn_save.setProperty("cssClass", "accent")
        btn_save.clicked.connect(self.save_grok_shadow_settings)
        btn_row.addWidget(btn_save)
        btn_reset = QPushButton("기본값 복원")
        btn_reset.clicked.connect(self._reset_grok_shadow_prompts)
        btn_row.addWidget(btn_reset)
        self.gk_status = QLabel("")
        btn_row.addWidget(self.gk_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ── 9. TTS ──

    def _build_tts_section(self):
        grp = QGroupBox("음성 합성 (TTS)")
        vbox = QVBoxLayout()

        grid = QGridLayout()

        # TTS 모드
        grid.addWidget(QLabel("TTS 모드:"), 0, 0, Qt.AlignLeft)
        mode_w = QWidget()
        mode_h = QHBoxLayout(mode_w)
        mode_h.setContentsMargins(0, 0, 0, 0)
        self.bg_tts_mode = QButtonGroup(self)
        for txt, val in [("끄기", "off"), ("Windows TTS", "windows"), ("OpenAI TTS", "openai")]:
            rb = QRadioButton(txt)
            rb.setProperty("provider_val", val)
            self.bg_tts_mode.addButton(rb)
            mode_h.addWidget(rb)
            if val == "off":
                rb.setChecked(True)
        mode_h.addStretch()
        grid.addWidget(mode_w, 0, 1)

        # OpenAI 모델 + 속도
        grid.addWidget(QLabel("OpenAI 모델:"), 1, 0, Qt.AlignLeft)
        ms_w = QWidget()
        ms_h = QHBoxLayout(ms_w)
        ms_h.setContentsMargins(0, 0, 0, 0)
        self.cb_tts_model = QComboBox()
        self.cb_tts_model.addItems(["tts-1", "tts-1-hd", "gpt-4o-mini-tts"])
        ms_h.addWidget(self.cb_tts_model)
        ms_h.addSpacing(12)
        ms_h.addWidget(QLabel("속도:"))
        self.edit_tts_speed = QLineEdit("1.0")
        self.edit_tts_speed.setFixedWidth(50)
        ms_h.addWidget(self.edit_tts_speed)
        ms_h.addStretch()
        grid.addWidget(ms_w, 1, 1)

        # 발언자 음성
        grid.addWidget(QLabel("발언자 음성:"), 2, 0, Qt.AlignTop)
        oai_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        voice_w = QWidget()
        voice_h = QHBoxLayout(voice_w)
        voice_h.setContentsMargins(0, 0, 0, 0)

        self.cb_voice_claude = QComboBox()
        self.cb_voice_chatgpt = QComboBox()
        self.cb_voice_gemini = QComboBox()
        self.cb_voice_mc = QComboBox()

        for lbl_txt, cb, default in [
            ("Claude:", self.cb_voice_claude, "alloy"),
            ("ChatGPT:", self.cb_voice_chatgpt, "nova"),
            ("Gemini:", self.cb_voice_gemini, "echo"),
            ("사회자:", self.cb_voice_mc, "shimmer"),
        ]:
            voice_h.addWidget(QLabel(lbl_txt))
            cb.addItems(oai_voices)
            cb.setCurrentText(default)
            voice_h.addWidget(cb)
            voice_h.addSpacing(8)

        voice_h.addStretch()
        grid.addWidget(voice_w, 2, 1)

        vbox.addLayout(grid)

        btn_row = QHBoxLayout()
        btn_save = QPushButton("설정 저장")
        btn_save.setProperty("cssClass", "accent")
        btn_save.clicked.connect(self.save_tts_settings)
        btn_row.addWidget(btn_save)
        btn_test = QPushButton("음성 테스트")
        btn_test.clicked.connect(self._test_tts)
        btn_row.addWidget(btn_test)
        self.tts_status = QLabel("")
        btn_row.addWidget(self.tts_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ── 10. 카테고리별 여백 ──

    def _build_category_section(self):
        grp = QGroupBox("카테고리별 여백 규칙 -- % 기준 (더블클릭으로 편집)")
        vbox = QVBoxLayout()

        desc = QLabel(
            "※ 여백은 출력 캔버스 크기 대비 %입니다. "
            "예: 1000px 출력 + 10% = 상하좌우 100px 여백 -> 피사체는 800x800 영역에 맞춤")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #6b7280;")
        vbox.addWidget(desc)

        self.cat_tree = QTreeWidget()
        self.cat_tree.setHeaderLabels(["ID", "이름", "상 %", "하 %", "좌 %", "우 %"])
        self.cat_tree.setColumnWidth(0, 160)
        self.cat_tree.setColumnWidth(1, 120)
        for col in range(2, 6):
            self.cat_tree.setColumnWidth(col, 60)
        self.cat_tree.setAlternatingRowColors(True)
        self.cat_tree.setMinimumHeight(200)
        self.cat_tree.itemDoubleClicked.connect(self._on_cat_double_click)
        vbox.addWidget(self.cat_tree)

        btn_row = QHBoxLayout()
        btn_save = QPushButton("저장")
        btn_save.setProperty("cssClass", "accent")
        btn_save.clicked.connect(self.save_categories)
        btn_row.addWidget(btn_save)
        btn_add = QPushButton("카테고리 추가")
        btn_add.clicked.connect(self.add_category)
        btn_row.addWidget(btn_add)
        btn_del = QPushButton("선택 삭제")
        btn_del.clicked.connect(self.delete_category)
        btn_row.addWidget(btn_del)
        btn_reload = QPushButton("다시 불러오기")
        btn_reload.clicked.connect(self.load_categories)
        btn_row.addWidget(btn_reload)
        self.cat_status = QLabel("")
        btn_row.addWidget(self.cat_status)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        grp.setLayout(vbox)
        self._layout.addWidget(grp)

    # ================================================================
    #  Helpers
    # ================================================================

    def _get_button_group_value(self, group: QButtonGroup) -> str:
        btn = group.checkedButton()
        if btn:
            return btn.property("provider_val")
        return ""

    def _set_button_group_value(self, group: QButtonGroup, value: str):
        for btn in group.buttons():
            if btn.property("provider_val") == value:
                btn.setChecked(True)
                return

    def _show_status(self, label: QLabel, text: str, color: str = SUCCESS, timeout: int = 3000):
        label.setText(text)
        label.setStyleSheet(f"color: {color};")
        if timeout > 0:
            QTimer.singleShot(timeout, lambda: label.setText(""))

    def _now_str(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    # ================================================================
    #  Save Methods
    # ================================================================

    def save_api_key(self, env_key: str):
        edit = self.api_key_edits.get(env_key)
        if not edit:
            return
        value = edit.text().strip()
        if not value:
            QMessageBox.warning(self, "경고", "API 키를 입력하세요.")
            return
        try:
            from dotenv import set_key
            if not ENV_PATH.exists():
                ENV_PATH.write_text("", encoding="utf-8")
            set_key(str(ENV_PATH), env_key, value)
            os.environ[env_key] = value
            QMessageBox.information(self, "저장 완료", f"{env_key} 키가 .env 파일에 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"API 키 저장 실패: {e}")

    def save_model_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            data.setdefault("api", {})["model"] = self.cb_model.currentText()
            data.setdefault("openai", {})["model"] = self.cb_openai_model.currentText()
            data.setdefault("gemini", {})["model"] = self.cb_gemini_model.currentText()
            data.setdefault("grok", {})["model"] = self.cb_grok_model.currentText()
            save_yaml(SETTINGS_PATH, data)
            QMessageBox.information(self, "모델 저장", "모델 설정이 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"모델 저장 실패: {e}")

    def save_provider_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            providers = data.setdefault("providers", {})
            providers["vision"] = self._get_button_group_value(self.bg_vision)
            providers["background_removal"] = self._get_button_group_value(self.bg_removal)
            providers["enhancement"] = self._get_button_group_value(self.bg_enhance)
            providers["shadow"] = self._get_button_group_value(self.bg_shadow)
            data["shadow_judge_mode"] = self._get_button_group_value(self.bg_judge)
            save_yaml(SETTINGS_PATH, data)

            # app.state 동기화
            self.app.state["vision_provider"] = providers["vision"]
            self.app.state["bg_provider"] = providers["background_removal"]
            self.app.state["enhance_provider"] = providers["enhancement"]
            self.app.state["shadow_provider"] = providers["shadow"]
            self.app.state["shadow_judge_mode"] = data["shadow_judge_mode"]

            # 메인탭 라디오 동기화
            main_tab = self.app._tab_widgets.get("MainTab")
            if main_tab and hasattr(main_tab, "sync_providers_from_state"):
                main_tab.sync_providers_from_state()

            self._show_status(self.prov_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.prov_status, f"저장 실패: {e}", DANGER)

    def save_output_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            out = data.setdefault("output", {})
            out["width"] = int(self.out_edits["width"].text())
            out["height"] = int(self.out_edits["height"].text())
            out["max_file_size_kb"] = int(self.out_edits["max_kb"].text())
            out["default_jpeg_quality"] = int(self.out_edits["jpeg_q"].text())
            save_yaml(SETTINGS_PATH, data)
            QMessageBox.information(self, "설정 저장", "출력 설정이 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"설정 저장 실패: {e}")

    def save_photoroom_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            pr_full = data.setdefault("photoroom", {}).setdefault("full", {})
            pr_full["shadow.mode"] = self.cb_pr_shadow_mode.currentText()
            pr_full["shadow.opacity"] = float(self.edit_pr_shadow_opacity.text())
            pr_full["padding"] = float(self.edit_pr_padding.text())
            pr_full["outputSize"] = self.cb_pr_output_size.currentText()

            pr_pkg = data["photoroom"].setdefault("package", {})
            pr_pkg["shadow.mode"] = pr_full["shadow.mode"]
            pr_pkg["shadow.opacity"] = pr_full["shadow.opacity"]

            auto_opts = data.setdefault("auto_options", {})
            auto_opts["photoroom"] = self._get_button_group_value(self.bg_pr_mode)

            save_yaml(SETTINGS_PATH, data)
            self._show_status(self.pr_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.pr_status, f"저장 실패: {e}", DANGER)

    def save_claid_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            cl = data.setdefault("claid", {})
            for img_type in ENHANCE_TYPES:
                type_data = cl.setdefault(img_type, {})
                type_data["hdr"] = int(self.claid_vars[(img_type, "hdr")].text())
                type_data["sharpness"] = int(self.claid_vars[(img_type, "sharpness")].text())
                for field in ["exposure", "saturation", "contrast"]:
                    val = int(self.claid_vars[(img_type, field)].text())
                    if val != 0:
                        type_data[field] = val
                    elif field in type_data:
                        del type_data[field]

            auto_opts = data.setdefault("auto_options", {})
            auto_opts["claid"] = self._get_button_group_value(self.bg_claid_mode)

            save_yaml(SETTINGS_PATH, data)
            self._show_status(self.cl_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.cl_status, f"저장 실패: {e}", DANGER)

    def save_opencv_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            cv = data.setdefault("opencv_enhance", {})
            for img_type in ENHANCE_TYPES:
                type_data = cv.setdefault(img_type, {})
                for field in ENHANCE_FIELDS:
                    key = (img_type, field)
                    if key in self.opencv_vars:
                        type_data[field] = int(self.opencv_vars[key].text())

            auto_opts = data.setdefault("auto_options", {})
            auto_opts["opencv"] = self._get_button_group_value(self.bg_opencv_mode)

            save_yaml(SETTINGS_PATH, data)
            self._show_status(self.cv_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.cv_status, f"저장 실패: {e}", DANGER)

    def save_removebg_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            rb = data.setdefault("removebg", {})
            rb["size"] = self.cb_rb_size.currentText()
            rb["type"] = self.cb_rb_type.currentText()
            save_yaml(SETTINGS_PATH, data)
            self._show_status(self.rb_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.rb_status, f"저장 실패: {e}", DANGER)

    def save_shadow_extract_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            se = data.setdefault("shadow_extract", {})
            se["method"] = self._get_button_group_value(self.bg_se_method)
            se["opacity"] = int(float(self.se_edits["se_opacity"].text()))
            se["threshold"] = int(float(self.se_edits["se_threshold"].text()))
            se["blur"] = float(self.se_edits["se_blur"].text())
            se["search_top"] = int(float(self.se_edits["se_search_top"].text()))
            se["search_bottom"] = int(float(self.se_edits["se_search_bottom"].text()))
            se["search_sides"] = int(float(self.se_edits["se_search_sides"].text()))
            se["mask_expand"] = float(self.se_edits["se_mask_expand"].text())
            se["distance_falloff"] = int(float(self.se_edits["se_distance_falloff"].text()))

            auto_opts = data.setdefault("auto_options", {})
            auto_opts["shadow"] = self._get_button_group_value(self.bg_se_param_mode)

            save_yaml(SETTINGS_PATH, data)
            self._show_status(self.se_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.se_status, f"저장 실패: {e}", DANGER)

    def save_gemini_shadow_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            gs = data.setdefault("gemini_shadow", {})
            gs["model"] = self.cb_gemini_shadow_model.currentText()
            gs["fallback_model"] = self.cb_gemini_fallback_model.currentText()
            gs["order"] = self._get_button_group_value(self.bg_gemini_order)
            gs["main_prompt"] = self.txt_gemini_main.toPlainText().strip()
            gs["original_prompt"] = self.txt_gemini_original.toPlainText().strip()
            gs["mannequin_prompt"] = self.txt_gemini_mannequin.toPlainText().strip()
            for old_key in ("ref_prompt", "orig_insert", "mannequin_full_prompt"):
                gs.pop(old_key, None)
            save_yaml(SETTINGS_PATH, data)
            self._show_status(self.gs_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.gs_status, f"저장 실패: {e}", DANGER)

    def save_grok_shadow_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            gks = data.setdefault("grok_shadow", {})
            gks["model"] = self.cb_grok_shadow_model.currentText()
            gks["order"] = self._get_button_group_value(self.bg_grok_order)
            gks["main_prompt"] = self.txt_grok_main.toPlainText().strip()
            gks["original_prompt"] = self.txt_grok_original.toPlainText().strip()
            gks["mannequin_prompt"] = self.txt_grok_mannequin.toPlainText().strip()
            for old_key in ("ref_prompt", "orig_insert", "mannequin_full_prompt"):
                gks.pop(old_key, None)
            save_yaml(SETTINGS_PATH, data)
            self._show_status(self.gk_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.gk_status, f"저장 실패: {e}", DANGER)

    def save_tts_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            tts = data.setdefault("tts", {})
            tts["provider"] = self._get_button_group_value(self.bg_tts_mode)
            tts["openai_model"] = self.cb_tts_model.currentText()
            tts["speed"] = float(self.edit_tts_speed.text())
            tts["voices"] = {
                "claude": self.cb_voice_claude.currentText(),
                "chatgpt": self.cb_voice_chatgpt.currentText(),
                "gemini": self.cb_voice_gemini.currentText(),
                "mc": self.cb_voice_mc.currentText(),
            }
            save_yaml(SETTINGS_PATH, data)

            if hasattr(self.app, '_tts_engine'):
                self.app._tts_engine.update_config(
                    provider=tts["provider"],
                    openai_model=tts["openai_model"],
                    speed=tts["speed"],
                    voice_map=tts["voices"],
                    openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                )

            self._show_status(self.tts_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.tts_status, f"저장 실패: {e}", DANGER)

    # ── Categories ──

    def save_categories(self):
        try:
            data = load_yaml(CATEGORIES_PATH)
            old_cats = data.get("categories", {})

            new_cats = {}
            root = self.cat_tree.invisibleRootItem()
            for i in range(root.childCount()):
                item = root.child(i)
                cat_id = item.text(0).strip()
                if not cat_id:
                    continue
                base = old_cats.get(cat_id, {})
                base["display_name"] = item.text(1)
                base.pop("padding_860", None)
                base["padding_percent"] = {
                    "top": float(item.text(2)),
                    "bottom": float(item.text(3)),
                    "left": float(item.text(4)),
                    "right": float(item.text(5)),
                }
                if "thumbnail_padding" not in base:
                    base["thumbnail_padding"] = {
                        "top": 359, "bottom": 359, "left": 148, "right": 148
                    }
                new_cats[cat_id] = base

            data["categories"] = new_cats
            save_yaml(CATEGORIES_PATH, data)
            self._show_status(self.cat_status, f"저장 완료 ({self._now_str()})")
        except Exception as e:
            self._show_status(self.cat_status, f"저장 실패: {e}", DANGER)

    def load_categories(self):
        try:
            data = load_yaml(CATEGORIES_PATH)
            cats = data.get("categories", {})

            self.cat_tree.clear()
            for cat_id, cat_data in cats.items():
                p = cat_data.get("padding_percent")
                if not p:
                    p860 = cat_data.get("padding_860", {})
                    if p860:
                        p = {k: round(v / 860.0 * 100, 1) for k, v in p860.items()}
                    else:
                        p = {"top": 10, "bottom": 10, "left": 10, "right": 10}
                item = QTreeWidgetItem([
                    cat_id,
                    cat_data.get("display_name", ""),
                    str(p.get("top", 10)),
                    str(p.get("bottom", 10)),
                    str(p.get("left", 10)),
                    str(p.get("right", 10)),
                ])
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.cat_tree.addTopLevelItem(item)
        except Exception:
            pass

    def add_category(self):
        item = QTreeWidgetItem(["new_category", "새 카테고리", "10", "10", "10", "10"])
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.cat_tree.addTopLevelItem(item)
        self._show_status(self.cat_status, "추가됨 (저장 필요)", "#ca8a04")

    def delete_category(self):
        selected = self.cat_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "선택 필요", "삭제할 카테고리를 선택하세요.")
            return
        for item in selected:
            idx = self.cat_tree.indexOfTopLevelItem(item)
            if idx >= 0:
                self.cat_tree.takeTopLevelItem(idx)
        self._show_status(self.cat_status, "삭제됨 (저장 필요)", "#ca8a04")

    def _on_cat_double_click(self, item: QTreeWidgetItem, column: int):
        self.cat_tree.editItem(item, column)
        self._show_status(self.cat_status, "수정됨 (저장 필요)", "#ca8a04", timeout=0)

    # ================================================================
    #  Load Settings
    # ================================================================

    def load_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
        except Exception:
            data = {}
        if not data:
            data = {}

        # 출력 설정
        out = data.get("output", {})
        self.out_edits["width"].setText(str(out.get("width", 860)))
        self.out_edits["height"].setText(str(out.get("height", 860)))
        self.out_edits["max_kb"].setText(str(out.get("max_file_size_kb", 2024)))
        self.out_edits["jpeg_q"].setText(str(out.get("default_jpeg_quality", 95)))

        # 모델
        api = data.get("api", {})
        self.cb_model.setCurrentText(api.get("model", "claude-sonnet-4-20250514"))
        openai_conf = data.get("openai", {})
        self.cb_openai_model.setCurrentText(openai_conf.get("model", "gpt-4o"))
        gemini_conf = data.get("gemini", {})
        self.cb_gemini_model.setCurrentText(gemini_conf.get("model", "gemini-2.5-flash"))
        grok_conf = data.get("grok", {})
        self.cb_grok_model.setCurrentText(grok_conf.get("model", "grok-4-fast-non-reasoning"))

        # 프로바이더
        providers = data.get("providers", {})
        state = self.app.state
        self._set_button_group_value(self.bg_vision,
            state.get("vision_provider", providers.get("vision", "claude")))
        self._set_button_group_value(self.bg_removal,
            state.get("bg_provider", providers.get("background_removal", "photoroom")))
        self._set_button_group_value(self.bg_enhance,
            state.get("enhance_provider", providers.get("enhancement", "claid")))
        self._set_button_group_value(self.bg_shadow,
            state.get("shadow_provider", providers.get("shadow", "opencv_extract")))
        self._set_button_group_value(self.bg_judge,
            state.get("shadow_judge_mode", data.get("shadow_judge_mode", "auto")))

        # Photoroom
        pr = data.get("photoroom", {}).get("full", {})
        self.cb_pr_shadow_mode.setCurrentText(pr.get("shadow.mode", "ai.soft"))
        self.edit_pr_shadow_opacity.setText(str(pr.get("shadow.opacity", 0.5)))
        self.edit_pr_padding.setText(str(pr.get("padding", 0.08)))
        self.cb_pr_output_size.setCurrentText(pr.get("outputSize", "originalImage"))

        # Claid
        cl = data.get("claid", {})
        for img_type in ENHANCE_TYPES:
            type_data = cl.get(img_type, {})
            for field in ENHANCE_FIELDS:
                key = (img_type, field)
                if key in self.claid_vars:
                    self.claid_vars[key].setText(str(type_data.get(field, ENHANCE_DEFAULTS[img_type][field])))

        # OpenCV
        cv = data.get("opencv_enhance", {})
        for img_type in ENHANCE_TYPES:
            type_data = cv.get(img_type, {})
            for field in ENHANCE_FIELDS:
                key = (img_type, field)
                if key in self.opencv_vars:
                    self.opencv_vars[key].setText(str(type_data.get(field, ENHANCE_DEFAULTS[img_type][field])))

        # remove.bg
        rb = data.get("removebg", {})
        self.cb_rb_size.setCurrentText(rb.get("size", "auto"))
        self.cb_rb_type.setCurrentText(rb.get("type", "product"))

        # 누끼 합성 그림자
        se = data.get("shadow_extract", {})
        self._set_button_group_value(self.bg_se_method, se.get("method", "level_correction"))
        self.se_edits["se_opacity"].setText(str(se.get("opacity", 70)))
        self.se_edits["se_threshold"].setText(str(se.get("threshold", 8)))
        self.se_edits["se_blur"].setText(str(se.get("blur", 3)))
        self.se_edits["se_search_top"].setText(str(se.get("search_top", 5)))
        self.se_edits["se_search_bottom"].setText(str(se.get("search_bottom", 60)))
        self.se_edits["se_search_sides"].setText(str(se.get("search_sides", 30)))
        self.se_edits["se_mask_expand"].setText(str(se.get("mask_expand", 2.5)))
        self.se_edits["se_distance_falloff"].setText(str(se.get("distance_falloff", 60)))

        # Gemini 그림자
        gs = data.get("gemini_shadow", {})
        self.cb_gemini_shadow_model.setCurrentText(gs.get("model", "gemini-3.1-flash-image-preview"))
        self.cb_gemini_fallback_model.setCurrentText(gs.get("fallback_model", "gemini-3-pro-image-preview"))
        self._set_button_group_value(self.bg_gemini_order, gs.get("order", "after_enhance"))
        if gs.get("main_prompt"):
            self.txt_gemini_main.setPlainText(gs["main_prompt"])
        if gs.get("original_prompt"):
            self.txt_gemini_original.setPlainText(gs["original_prompt"])
        elif gs.get("ref_prompt"):
            merged = gs["ref_prompt"] + "\n" + gs.get("orig_insert", "")
            self.txt_gemini_original.setPlainText(merged.strip())
        if gs.get("mannequin_prompt") and "mannequin_full_prompt" not in gs:
            self.txt_gemini_mannequin.setPlainText(gs["mannequin_prompt"])
        elif gs.get("mannequin_full_prompt"):
            self.txt_gemini_mannequin.setPlainText(gs["mannequin_full_prompt"])

        # Grok 그림자
        gks = data.get("grok_shadow", {})
        self.cb_grok_shadow_model.setCurrentText(gks.get("model", "grok-imagine-image"))
        self._set_button_group_value(self.bg_grok_order, gks.get("order", "after_enhance"))
        if gks.get("main_prompt"):
            self.txt_grok_main.setPlainText(gks["main_prompt"])
        if gks.get("original_prompt"):
            self.txt_grok_original.setPlainText(gks["original_prompt"])
        elif gks.get("ref_prompt"):
            merged = gks["ref_prompt"] + "\n" + gks.get("orig_insert", "")
            self.txt_grok_original.setPlainText(merged.strip())
        if gks.get("mannequin_prompt") and "mannequin_full_prompt" not in gks:
            self.txt_grok_mannequin.setPlainText(gks["mannequin_prompt"])
        elif gks.get("mannequin_full_prompt"):
            self.txt_grok_mannequin.setPlainText(gks["mannequin_full_prompt"])

        # TTS
        tts = data.get("tts", {})
        self._set_button_group_value(self.bg_tts_mode, tts.get("provider", "off"))
        self.cb_tts_model.setCurrentText(tts.get("openai_model", "tts-1"))
        self.edit_tts_speed.setText(str(tts.get("speed", 1.0)))
        voices = tts.get("voices", {})
        self.cb_voice_claude.setCurrentText(voices.get("claude", "alloy"))
        self.cb_voice_chatgpt.setCurrentText(voices.get("chatgpt", "nova"))
        self.cb_voice_gemini.setCurrentText(voices.get("gemini", "echo"))
        self.cb_voice_mc.setCurrentText(voices.get("mc", "shimmer"))

        # AI 자동/수동 모드
        auto_opts = data.get("auto_options", {})
        self._set_button_group_value(self.bg_claid_mode, auto_opts.get("claid", "manual"))
        self._set_button_group_value(self.bg_opencv_mode, auto_opts.get("opencv", "manual"))
        self._set_button_group_value(self.bg_pr_mode, auto_opts.get("photoroom", "manual"))
        self._set_button_group_value(self.bg_se_param_mode, auto_opts.get("shadow", "ai_auto"))

    # ================================================================
    #  Toggle / Reset
    # ================================================================

    def _toggle_gemini_advanced(self):
        self._gemini_adv_visible = not self._gemini_adv_visible
        self._gemini_adv_widget.setVisible(self._gemini_adv_visible)
        self._gemini_adv_btn.setText(
            "\u25bc 상세 프롬프트 (2개)" if self._gemini_adv_visible
            else "\u25b6 상세 프롬프트 (2개)")

    def _toggle_grok_advanced(self):
        self._grok_adv_visible = not self._grok_adv_visible
        self._grok_adv_widget.setVisible(self._grok_adv_visible)
        self._grok_adv_btn.setText(
            "\u25bc 상세 프롬프트 (2개)" if self._grok_adv_visible
            else "\u25b6 상세 프롬프트 (2개)")

    def _reset_gemini_shadow_prompts(self):
        self.txt_gemini_main.setPlainText(GEMINI_MAIN_PROMPT_DEFAULT)
        self.txt_gemini_original.setPlainText(GEMINI_ORIGINAL_PROMPT_DEFAULT)
        self.txt_gemini_mannequin.setPlainText(GEMINI_MANNEQUIN_PROMPT_DEFAULT)
        self._show_status(self.gs_status, "기본값 복원됨")

    def _reset_grok_shadow_prompts(self):
        self.txt_grok_main.setPlainText(GROK_MAIN_PROMPT_DEFAULT)
        self.txt_grok_original.setPlainText(GROK_ORIGINAL_PROMPT_DEFAULT)
        self.txt_grok_mannequin.setPlainText(GROK_MANNEQUIN_PROMPT_DEFAULT)
        self._show_status(self.gk_status, "기본값 복원됨")

    # ================================================================
    #  GPU Detection / Provider Warning
    # ================================================================

    def _detect_sam_gpu(self):
        has_gpu = False
        vram_gb = 0
        try:
            from src.sam.client import SamShadowClient
            info = SamShadowClient.detect_gpu_capability()
            has_gpu = info.get("has_gpu", False)
            vram_gb = info.get("vram_gb", 0)
            if has_gpu:
                gpu_text = f"GPU: {info['gpu_name']} ({vram_gb}GB VRAM)"
                avail = []
                if vram_gb >= 2:
                    avail.append("VIT-B")
                if vram_gb >= 4:
                    avail.append("VIT-L")
                if vram_gb >= 6:
                    avail.append("VIT-H")
                gpu_text += f" -- 사용 가능: {', '.join(avail)}"
                self.sam_gpu_label.setText(gpu_text)
                self.sam_gpu_label.setStyleSheet(f"color: {SUCCESS};")
            else:
                self.sam_gpu_label.setText("GPU 없음 -- SAM GPU 비활성")
                self.sam_gpu_label.setStyleSheet("color: #ca8a04;")
        except Exception:
            self.sam_gpu_label.setText("torch 미설치 -- SAM 사용 불가")
            self.sam_gpu_label.setStyleSheet(f"color: {DANGER};")

        gpu_buttons = {
            "b": 2, "l": 4, "h": 6,
        }
        for suffix, min_vram in gpu_buttons.items():
            enabled = has_gpu and vram_gb >= min_vram
            rb = getattr(self, f"rb_sam_gpu_{suffix}_settings", None)
            if rb:
                rb.setEnabled(enabled)

        current = self._get_button_group_value(self.bg_shadow)
        if current.startswith("sam_gpu_"):
            suffix = current.split("_")[-1]
            min_vram = {"b": 2, "l": 4, "h": 6}.get(suffix, 0)
            if not has_gpu or vram_gb < min_vram:
                if has_gpu and vram_gb >= 4:
                    self._set_button_group_value(self.bg_shadow, "sam_gpu_l")
                elif has_gpu and vram_gb >= 2:
                    self._set_button_group_value(self.bg_shadow, "sam_gpu_b")
                else:
                    self._set_button_group_value(self.bg_shadow, "sam_mobile")

    def _update_provider_warning(self, *args):
        bg = self._get_button_group_value(self.bg_removal)
        shadow = self._get_button_group_value(self.bg_shadow)
        warnings_map = {
            ("removebg", "api_shadow"): "* remove.bg는 그림자 API 옵션을 지원하지 않습니다. Photoroom 선택 시 사용 가능",
            (None, "sam_mobile"): "* SAM Mobile: MobileSAM 경량 (models/mobile_sam.pt 40.7MB, CPU 3~5초)",
            (None, "sam_cpu"): "* SAM CPU: VIT-B CPU (models/sam_vit_b_01ec64.pth 375MB, 10~30초)",
            (None, "sam_gpu_b"): "* GPU-B: VIT-B GPU (375MB, VRAM 2GB+, 2~5초)",
            (None, "sam_gpu_l"): "* GPU-L: VIT-L GPU (models/sam_vit_l_0b3195.pth 1.2GB, VRAM 4GB+, 3~8초)",
            (None, "sam_gpu_h"): "* GPU-H: VIT-H GPU (models/sam_vit_h_4b8939.pth 2.5GB, VRAM 6GB+, 5~10초)",
        }

        msg = ""
        if shadow == "api_shadow" and bg == "removebg":
            msg = warnings_map[("removebg", "api_shadow")]
        elif bg == "hybrid":
            extra = ""
            if shadow == "api_shadow":
                extra = " (Photoroom 성공 시만 API 그림자 적용, remove.bg 폴백 시 생략)"
            msg = f"* 복합 모드: Photoroom 우선 → 품질 불량 시 remove.bg 자동 전환{extra}"
        elif (None, shadow) in warnings_map:
            msg = warnings_map[(None, shadow)]

        self.prov_warning.setText(msg)

    # ================================================================
    #  TTS Test
    # ================================================================

    def _test_tts(self):
        provider = self._get_button_group_value(self.bg_tts_mode)
        if provider == "off":
            self._show_status(self.tts_status, "TTS가 꺼져 있습니다.", DANGER)
            return

        self._show_status(self.tts_status, "음성 테스트 중...", "#89b4fa", timeout=0)

        def _do_test():
            try:
                self._ensure_tts_engine()
                self.app._tts_engine.speak_sync("안녕하세요. 음성 테스트입니다.", "claude")
                QTimer.singleShot(0, lambda: self._show_status(
                    self.tts_status, "테스트 완료!"))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._show_status(
                    self.tts_status, f"테스트 실패: {e}", DANGER))

        threading.Thread(target=_do_test, daemon=True).start()

    def _ensure_tts_engine(self):
        gui_provider = self._get_button_group_value(self.bg_tts_mode)
        gui_model = self.cb_tts_model.currentText()
        gui_speed = float(self.edit_tts_speed.text())
        gui_voices = {
            "claude": self.cb_voice_claude.currentText(),
            "chatgpt": self.cb_voice_chatgpt.currentText(),
            "gemini": self.cb_voice_gemini.currentText(),
            "mc": self.cb_voice_mc.currentText(),
        }

        if not hasattr(self.app, '_tts_engine') or self.app._tts_engine is None:
            from src.tts.engine import TTSEngine
            self.app._tts_engine = TTSEngine(
                provider=gui_provider,
                openai_model=gui_model,
                openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                voice_map=gui_voices,
                speed=gui_speed,
            )
        else:
            self.app._tts_engine.update_config(
                provider=gui_provider,
                openai_model=gui_model,
                openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                speed=gui_speed,
                voice_map=gui_voices,
            )
