"""AI Vision Analysis Prompt Editor Tab (PySide6)."""
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGroupBox, QTextEdit, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer

from gui_pyside.utils import load_yaml, save_yaml, PROMPTS_PATH
from gui_pyside.styles import ACCENT, FONT_FAMILY, SUCCESS, DANGER


class PromptTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._build_ui()
        self.load_prompts()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 8, 12, 8)

        # -- Header --
        header_row = QHBoxLayout()
        title_lbl = QLabel("AI 비전 분석 프롬프트")
        title_lbl.setStyleSheet(f"font-size: 13pt; font-weight: bold; font-family: '{FONT_FAMILY}';")
        header_row.addWidget(title_lbl)
        desc_lbl = QLabel("한글/영어 모두 사용 가능  |  수정 후 [저장] 클릭")
        desc_lbl.setStyleSheet(f"font-size: 9pt; color: #6b7280; font-family: '{FONT_FAMILY}';")
        header_row.addWidget(desc_lbl)
        header_row.addStretch()
        root_layout.addLayout(header_row)

        # -- Button bar --
        btn_row = QHBoxLayout()

        btn_save = QPushButton("  저장  ")
        btn_save.setProperty("cssClass", "accent")
        btn_save.clicked.connect(self.save_prompts)
        btn_row.addWidget(btn_save)

        btn_reset = QPushButton("한글 기본값 복원")
        btn_reset.clicked.connect(self.reset_prompts)
        btn_row.addWidget(btn_reset)

        btn_reload = QPushButton("파일에서 다시 불러오기")
        btn_reload.clicked.connect(self.load_prompts)
        btn_row.addWidget(btn_reload)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"font-family: '{FONT_FAMILY}';")
        btn_row.addWidget(self.lbl_status)
        btn_row.addStretch()
        root_layout.addLayout(btn_row)

        # -- Scroll area --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(scroll_widget)
        root_layout.addWidget(scroll, 1)

        # -- System prompt group --
        grp_sys = QGroupBox("시스템 프롬프트 (AI 역할 정의)")
        grp_sys_layout = QVBoxLayout(grp_sys)

        tip_sys = QLabel("(?) 이 프롬프트의 역할")
        tip_sys.setStyleSheet(f"color: {ACCENT}; font-size: 9pt; font-family: '{FONT_FAMILY}';")
        tip_sys.setCursor(Qt.PointingHandCursor)
        tip_sys.setToolTip(
            "시스템 프롬프트는 AI의 '역할'을 정의합니다.\n\n"
            "여기서 AI에게 '당신은 럭셔리 이커머스 상품 이미지 분류 전문가입니다' 같은\n"
            "역할을 부여합니다. AI가 응답할 때 이 역할에 맞춰 답변합니다.\n\n"
            "이 프롬프트는 모든 이미지 분석 요청에 공통으로 적용됩니다.\n"
            "JSON만 반환하라는 지시도 여기에 포함하세요."
        )
        grp_sys_layout.addWidget(tip_sys)

        self.txt_system = QTextEdit()
        self.txt_system.setStyleSheet("background: #fefce8;")
        self.txt_system.setFixedHeight(self._line_height(7))
        grp_sys_layout.addWidget(self.txt_system)
        scroll_layout.addWidget(grp_sys)

        # -- User prompt group --
        grp_usr = QGroupBox("분석 요청 프롬프트 (이미지별 전송)")
        grp_usr_layout = QVBoxLayout(grp_usr)

        tip_usr = QLabel("(?) 이 프롬프트의 역할")
        tip_usr.setStyleSheet(f"color: {ACCENT}; font-size: 9pt; font-family: '{FONT_FAMILY}';")
        tip_usr.setCursor(Qt.PointingHandCursor)
        tip_usr.setToolTip(
            "분석 요청 프롬프트는 각 이미지를 분석할 때 전송되는 지시문입니다.\n\n"
            "이미지와 함께 이 프롬프트가 AI에게 전달되며,\n"
            "AI는 이 지시에 따라 이미지 유형(full/detail/worn/package),\n"
            "카테고리(bag/shoes/clothing 등), 배경 상태, 그림자 정보 등을\n"
            "JSON 형식으로 분류하여 반환합니다.\n\n"
            "반환 JSON 구조(필드명)를 변경하면 프로그램이 정상 동작하지\n"
            "않을 수 있습니다. 필드명은 유지하고 설명만 수정하세요.\n\n"
            "{{중괄호 2개}}는 변수 치환 방지용입니다. 실제 JSON 예시에 사용하세요."
        )
        grp_usr_layout.addWidget(tip_usr)

        self.txt_user = QTextEdit()
        self.txt_user.setStyleSheet("background: #f0fdf4;")
        self.txt_user.setFixedHeight(self._line_height(14))
        grp_usr_layout.addWidget(self.txt_user)
        scroll_layout.addWidget(grp_usr)

        # -- Validation prompt group --
        grp_val = QGroupBox("검증 프롬프트 (품질 검증 AI 지시)")
        grp_val_layout = QVBoxLayout(grp_val)

        tip_val = QLabel("(?) 이 프롬프트의 역할")
        tip_val.setStyleSheet(f"color: {ACCENT}; font-size: 9pt; font-family: '{FONT_FAMILY}';")
        tip_val.setCursor(Qt.PointingHandCursor)
        tip_val.setToolTip(
            "검증 프롬프트는 처리 완료 후 품질 검수에 사용됩니다.\n\n"
            "Vision API가 원본과 결과물을 비교하여\n"
            "배경 제거, 그림자, 원형 보존 3가지 항목을 판정합니다.\n\n"
            "시스템: AI 역할 정의\n"
            "그림자 필요: 그림자가 있어야 하는 이미지의 판정 기준\n"
            "그림자 불필요: 그림자가 없어도 되는 이미지의 판정 기준\n"
            "검증 요청: 실제 검증 시 전송되는 지시문 ({image_type}, {shadow_context} 변수 사용)"
        )
        grp_val_layout.addWidget(tip_val)

        lbl_val_sys = QLabel("시스템:")
        lbl_val_sys.setStyleSheet(f"font-weight: bold; font-family: '{FONT_FAMILY}';")
        grp_val_layout.addWidget(lbl_val_sys)
        self.txt_val_system = QTextEdit()
        self.txt_val_system.setStyleSheet("background: #fef2f2;")
        self.txt_val_system.setFixedHeight(self._line_height(5))
        grp_val_layout.addWidget(self.txt_val_system)

        lbl_val_sn = QLabel("그림자 필요 시 판정 기준:")
        lbl_val_sn.setStyleSheet(f"font-weight: bold; font-family: '{FONT_FAMILY}';")
        grp_val_layout.addWidget(lbl_val_sn)
        self.txt_val_shadow_needed = QTextEdit()
        self.txt_val_shadow_needed.setStyleSheet("background: #fef2f2;")
        self.txt_val_shadow_needed.setFixedHeight(self._line_height(8))
        grp_val_layout.addWidget(self.txt_val_shadow_needed)

        lbl_val_snn = QLabel("그림자 불필요 시:")
        lbl_val_snn.setStyleSheet(f"font-weight: bold; font-family: '{FONT_FAMILY}';")
        grp_val_layout.addWidget(lbl_val_snn)
        self.txt_val_shadow_not_needed = QTextEdit()
        self.txt_val_shadow_not_needed.setStyleSheet("background: #fef2f2;")
        self.txt_val_shadow_not_needed.setFixedHeight(self._line_height(8))
        grp_val_layout.addWidget(self.txt_val_shadow_not_needed)

        lbl_val_ut = QLabel("검증 요청 템플릿:")
        lbl_val_ut.setStyleSheet(f"font-weight: bold; font-family: '{FONT_FAMILY}';")
        grp_val_layout.addWidget(lbl_val_ut)
        self.txt_val_user = QTextEdit()
        self.txt_val_user.setStyleSheet("background: #fef2f2;")
        self.txt_val_user.setFixedHeight(self._line_height(10))
        grp_val_layout.addWidget(self.txt_val_user)

        scroll_layout.addWidget(grp_val)
        scroll_layout.addStretch()

    def _line_height(self, lines):
        return max(lines * 22, 60)

    # ── Data methods ──

    def load_prompts(self):
        try:
            data = load_yaml(PROMPTS_PATH)
            analysis = data.get("analysis", {})
            self.txt_system.setPlainText(analysis.get("system", "").strip())
            self.txt_user.setPlainText(analysis.get("user_template", "").strip())

            validation = data.get("validation", {})
            self.txt_val_system.setPlainText(validation.get("system", "").strip())
            self.txt_val_shadow_needed.setPlainText(validation.get("shadow_needed", "").strip())
            self.txt_val_shadow_not_needed.setPlainText(validation.get("shadow_not_needed", "").strip())
            self.txt_val_user.setPlainText(validation.get("user_template", "").strip())

            self._show_status("프롬프트 로드 완료", SUCCESS)
        except Exception as e:
            self._show_status(f"로드 실패: {e}", DANGER)

    def save_prompts(self):
        try:
            data = load_yaml(PROMPTS_PATH)
            data["analysis"]["system"] = self.txt_system.toPlainText().strip() + "\n"
            data["analysis"]["user_template"] = self.txt_user.toPlainText().strip() + "\n"

            data.setdefault("validation", {})
            data["validation"]["system"] = self.txt_val_system.toPlainText().strip() + "\n"
            data["validation"]["shadow_needed"] = self.txt_val_shadow_needed.toPlainText().strip() + "\n"
            data["validation"]["shadow_not_needed"] = self.txt_val_shadow_not_needed.toPlainText().strip() + "\n"
            data["validation"]["user_template"] = self.txt_val_user.toPlainText().strip() + "\n"

            save_yaml(PROMPTS_PATH, data)
            self._show_status(
                f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})", SUCCESS)
        except Exception as e:
            self._show_status(f"저장 실패: {e}", DANGER)

    def reset_prompts(self):
        reply = QMessageBox.question(
            self, "기본값 복원",
            "한글 기본값으로 복원하시겠습니까?\n현재 편집 내용이 사라집니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self.txt_system.setPlainText(
            "당신은 LUXBOY 럭셔리 이커머스 플랫폼의 전문 상품 이미지 분류기입니다.\n"
            "제공된 상품 이미지를 분석하고 JSON 객체만 반환하세요.\n"
            "JSON 외의 텍스트는 포함하지 마세요.")
        self.txt_user.setPlainText(
            "이 상품 이미지를 이커머스 처리용으로 분석하세요.\n"
            "여러 이미지가 제공되면 동일 상품의 다른 각도입니다. 첫 번째 이미지가 분류 대상입니다.\n\n"
            "분류 기준:\n"
            "- image_type:\n"
            '  - "full": 상품 전체가 보이는 사진 (가방 전체, 신발 전체 등)\n'
            '  - "detail": 상품 일부분 클로즈업 (로고, 버클, 질감, 내부, 솔, 스티칭 등)\n'
            '  - "worn": 모델 착용 또는 마네킹 착용 사진\n'
            '  - "package": 패키징 요소 (박스, 더스트백, 보증서, 태그 등)\n\n'
            "- background:\n"
            '  - "clean": 단색/무지 배경 (흰색, 회색, 스튜디오 배경)\n'
            '  - "complex": 매장, 야외, 소품이 보이는 배경\n'
            '  - "none": 극단적 클로즈업으로 배경이 거의 없음\n\n'
            "다음 JSON 구조로 반환하세요:\n"
            "{{\n"
            '  "image_type": "<full | detail | worn | package>",\n'
            '  "category": "<bag | shoes | clothing | accessory | watch | jewelry | wallet | belt | scarf | hat | sunglasses | other>",\n'
            '  "category_display": "<카테고리 한글 표시명>",\n'
            '  "background": "<clean | complex | none>",\n'
            '  "subject_position": "<center | left | right | top | bottom>",\n'
            '  "is_detail_cut": <boolean, image_type이 "detail"이면 true>,\n'
            '  "detail_focus_area": <객체 또는 null>,\n'
            '  "needs_shadow": <boolean>,\n'
            '  "shadow_direction": <문자열 또는 null>,\n'
            '  "shadow_params": <객체 또는 null>,\n'
            '  "has_human_hand": <boolean>,\n'
            '  "hand_region": <객체 또는 null>,\n'
            '  "product_only_region": <객체 또는 null>,\n'
            '  "enhance_params": {{\n'
            '    "hdr": <정수 0-50>,\n'
            '    "sharpness": <정수 0-30>,\n'
            '    "exposure": <정수 -30~30>,\n'
            '    "saturation": <정수 -20~20>,\n'
            '    "contrast": <정수 -20~20>\n'
            "  }},\n"
            '  "photoroom_params": <객체 또는 null>,\n'
            '  "confidence": <0~1 실수>,\n'
            '  "notes": "<이미지에 대한 간단한 설명>"\n'
            "}}\n\n"
            "정확하게 분류하세요. image_type과 background 판정이 처리 파이프라인을 결정합니다.")

        self.txt_val_system.setPlainText(
            "당신은 상품 이미지 품질 검수 전문가입니다.\n"
            "원본 이미지와 처리된 결과 이미지를 비교하여 품질을 엄격하게 검증합니다.\n"
            "애매한 경우 FAIL로 판정하세요.\n"
            "반드시 JSON만 출력하세요. 설명 텍스트 없이 순수 JSON만 응답하세요.")
        self.txt_val_shadow_needed.setPlainText(
            "이 이미지는 그림자가 반드시 있어야 하는 이미지입니다.\n"
            "그림자 판정 기준 (엄격 적용):\n"
            "- 원본에 그림자가 있었다면 결과물에도 비슷한 강도의 접지 그림자가 있어야 PASS\n"
            "- 그림자가 없거나 육안으로 식별 불가능할 정도로 약하면 FAIL (detail: '그림자 부족')\n"
            "- 그림자가 원본 대비 과도하게 짙거나 인위적이면 FAIL (detail: '그림자 과다')\n"
            "- 그림자의 방향이 원본과 현저히 다르면 FAIL (detail: '방향 불일치')\n"
            "- 피사체를 정면에서 바라보고 촬영된 이미지라면 그림자는 피사체 하단에만 있어야 PASS. "
            "측면이나 상단에 그림자가 있으면 FAIL (detail: '정면 촬영인데 그림자 위치 부적절')")
        self.txt_val_shadow_not_needed.setPlainText(
            "이 이미지는 그림자가 불필요한 이미지입니다. 그림자 항목은 PASS로 판정하세요.")
        self.txt_val_user.setPlainText(
            "첫 번째 이미지는 원본, 두 번째 이미지는 처리 결과입니다.\n"
            "상품 유형: {image_type}\n"
            "{shadow_context}\n\n"
            "아래 3가지 항목을 검증하고 JSON으로 응답하세요:\n\n"
            "1. background: 배경이 깨끗한 흰색(#FFFFFF)으로 제거되었는가? "
            "원본 배경의 잔여물(색상, 물체, 그라데이션)이 남아있으면 FAIL.\n"
            "2. shadow: 위의 그림자 판정 기준을 엄격히 적용하세요. "
            "원본의 그림자 강도/방향을 기준으로 결과물을 비교 판정하세요.\n"
            "3. integrity: 상품의 원형이 보존되었는가? 원본과 비교하여 상품의 형태, "
            "색상, 디테일(로고, 텍스트, 질감)이 변형되었으면 FAIL. "
            "크롭/센터링으로 인한 위치 변경은 허용.\n\n"
            "응답 형식 (JSON만, 다른 텍스트 없이):\n"
            '{"background": {"pass": true/false, "detail": "한줄 설명"}, '
            '"shadow": {"pass": true/false, "detail": "한줄 설명"}, '
            '"integrity": {"pass": true/false, "detail": "한줄 설명"}}')

        self._show_status("한글 기본값 복원됨 (저장 필요)", "#ca8a04")

    def _show_status(self, msg, color=None):
        style = f"font-family: '{FONT_FAMILY}';"
        if color:
            style += f" color: {color};"
        self.lbl_status.setStyleSheet(style)
        self.lbl_status.setText(msg)
        QTimer.singleShot(3000, lambda: self.lbl_status.setText(""))
