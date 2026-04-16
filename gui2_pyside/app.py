"""PySide6 메인 윈도우 - 모던 라이트 스타일"""
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QSpinBox,
    QScrollArea, QProgressBar, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from gui2_pyside.styles import MAIN_STYLESHEET, ACCENT, TEXT_PRIMARY


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("LUXBOY 이미지 자동편집 - v2 (PySide6)")
        self.resize(1200, 850)
        self.setMinimumSize(1000, 700)

        # 중앙 위젯
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 사이드바 ──
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        sidebar.setObjectName("sidebar")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(16, 20, 16, 20)
        sb_layout.setSpacing(4)

        # 로고
        logo = QLabel("LUXBOY")
        logo.setObjectName("logo")
        logo_font = QFont("맑은 고딕", 16, QFont.Bold)
        logo.setFont(logo_font)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("color: white; letter-spacing: 4px;")
        sb_layout.addWidget(logo)
        sb_layout.addSpacing(24)

        # 메뉴
        menus = [
            ("🏠", "대시보드"),
            ("▶", "이미지 처리"),
            ("📝", "프롬프트"),
            ("🌑", "그림자 힌트"),
            ("⚙", "설정"),
        ]

        for icon, label in menus:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setObjectName("menuBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        # 버전
        ver = QLabel("v2.0.0")
        ver.setObjectName("versionLabel")
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet("color: #94a3b8; font-size: 8pt;")
        sb_layout.addWidget(ver)

        # 사이드바 스타일
        sidebar.setStyleSheet(f"""
            #sidebar {{
                background-color: #1e293b;
                border-right: 1px solid #334155;
            }}
            #menuBtn {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
                padding: 10px 14px;
                text-align: left;
                font-size: 9.5pt;
                color: #94a3b8;
                margin-bottom: 2px;
            }}
            #menuBtn:hover {{
                background-color: #334155;
                color: #e2e8f0;
            }}
            #menuBtn:checked {{
                background-color: {ACCENT};
                color: #ffffff;
                font-weight: bold;
            }}
            #versionLabel {{
                color: #475569;
            }}
        """)

        main_layout.addWidget(sidebar)

        # ── 메인 콘텐츠 ──
        content = QWidget()
        content.setObjectName("content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 24, 28, 20)
        cl.setSpacing(20)

        # 헤더
        header = QLabel("이미지 처리")
        header_font = QFont("맑은 고딕", 16, QFont.Bold)
        header.setFont(header_font)
        header.setStyleSheet(f"color: {TEXT_PRIMARY};")
        cl.addWidget(header)

        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("scrollArea")

        scroll_content = QWidget()
        scl = QVBoxLayout(scroll_content)
        scl.setContentsMargins(0, 0, 0, 0)
        scl.setSpacing(20)

        # 카드 1: 입출력
        card1 = self._make_card("📁 입력 / 출력", scl)
        card1_layout = card1.layout()

        input_label = QLabel("입력 경로")
        input_label.setStyleSheet("font-weight: 600; color: #64748b; font-size: 8.5pt;")
        card1_layout.addWidget(input_label)

        input_field = QLineEdit("X:/촬영팀/AI/촬영본/04.06/")
        input_field.setReadOnly(True)
        card1_layout.addWidget(input_field)

        browse_in = QPushButton("폴더 선택")
        browse_in.setProperty("cssClass", "accent")
        card1_layout.addWidget(browse_in)

        output_label = QLabel("출력 경로")
        output_label.setStyleSheet("font-weight: 600; color: #64748b; font-size: 8.5pt; margin-top: 8px;")
        card1_layout.addWidget(output_label)

        output_field = QLineEdit("D:/CLAUDE_CODE_WORK/output")
        output_field.setReadOnly(True)
        card1_layout.addWidget(output_field)

        browse_out = QPushButton("폴더 선택")
        browse_out.setProperty("cssClass", "accent")
        card1_layout.addWidget(browse_out)

        # 카드 2: 프로바이더
        card2 = self._make_card("🔧 AI 프로바이더", scl)
        card2_layout = card2.layout()

        for label, options, selected in [
            ("분석", ["Claude", "ChatGPT", "Gemini", "Grok"], "Gemini"),
            ("배경제거", ["Photoroom", "remove.bg"], "Photoroom"),
            ("보정", ["Claid.ai", "OpenCV"], "Claid.ai"),
            ("그림자", ["Gemini AI", "API", "누끼합성", "없음"], "Gemini AI"),
        ]:
            row_label = QLabel(label)
            row_label.setStyleSheet("font-weight: 600; color: #64748b; font-size: 8.5pt;")
            card2_layout.addWidget(row_label)

            combo = QComboBox()
            combo.addItems(options)
            combo.setCurrentText(selected)
            card2_layout.addWidget(combo)

        # 카드 3: 옵션
        card3 = self._make_card("⚡ 처리 옵션", scl)
        card3_layout = card3.layout()

        for text, checked in [
            ("배경 제거 생략", False),
            ("AI 분석 생략", False),
            ("크롭 완료 이미지", True),
            ("자동 수정 (AI 회의)", False),
        ]:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            card3_layout.addWidget(cb)

        iter_label = QLabel("자동 수정 횟수")
        iter_label.setStyleSheet("font-weight: 600; color: #64748b; font-size: 8.5pt; margin-top: 8px;")
        card3_layout.addWidget(iter_label)

        spin = QSpinBox()
        spin.setRange(1, 10)
        spin.setValue(3)
        card3_layout.addWidget(spin)

        scl.addStretch()
        scroll.setWidget(scroll_content)
        cl.addWidget(scroll)

        # 하단: 실행 바
        action_bar = QWidget()
        action_bar.setObjectName("actionBar")
        ab_layout = QHBoxLayout(action_bar)
        ab_layout.setContentsMargins(16, 12, 16, 12)

        progress = QProgressBar()
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setFormat("준비 중")
        ab_layout.addWidget(progress)

        run_btn = QPushButton("  ▶  처리 시작")
        run_btn.setProperty("cssClass", "accent")
        run_btn.setCursor(Qt.PointingHandCursor)
        ab_layout.addWidget(run_btn)

        stop_btn = QPushButton("  ■  중지")
        stop_btn.setProperty("cssClass", "danger")
        stop_btn.setCursor(Qt.PointingHandCursor)
        ab_layout.addWidget(stop_btn)

        action_bar.setStyleSheet(f"""
            #actionBar {{
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
            }}
        """)

        cl.addWidget(action_bar)

        main_layout.addWidget(content, 1)

        # 스타일 적용
        self.setStyleSheet(MAIN_STYLESHEET)

    def _make_card(self, title, parent_layout):
        """카드 위젯 생성"""
        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet("""
            #card {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 10pt; font-weight: 700; color: #334155;")
        layout.addWidget(title_label)

        parent_layout.addWidget(card)

        return card
