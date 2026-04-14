"""디자인 샘플 1: 사이드바 + 카드 레이아웃 (모던 라이트)"""
import sys, os
os.environ['QT_QPA_PLATFORM'] = 'windows'
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *


class SidebarCardApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LUXBOY Image Editor — Modern Light")
        self.resize(1200, 800)
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
        logo.setAlignment(Qt.AlignCenter)
        sb_layout.addWidget(logo)
        sb_layout.addSpacing(24)

        # 메뉴 항목
        self.menu_buttons = []
        menus = [
            ("🏠", "대시보드"),
            ("▶", "이미지 처리"),
            ("📝", "프롬프트"),
            ("🌑", "그림자 힌트"),
            ("⚙", "설정"),
            ("📊", "처리 이력"),
        ]
        for icon, label in menus:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setObjectName("menuBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            self.menu_buttons.append(btn)
            sb_layout.addWidget(btn)

        self.menu_buttons[1].setChecked(True)  # 이미지 처리 선택

        sb_layout.addStretch()

        # 하단 정보
        ver = QLabel("v2.0.0")
        ver.setObjectName("versionLabel")
        ver.setAlignment(Qt.AlignCenter)
        sb_layout.addWidget(ver)

        main_layout.addWidget(sidebar)

        # ── 메인 콘텐츠 ──
        content = QWidget()
        content.setObjectName("content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 24, 28, 20)
        cl.setSpacing(20)

        # 헤더
        header_row = QHBoxLayout()
        title = QLabel("이미지 처리")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch()

        batch_btn = QPushButton("  배치 처리")
        batch_btn.setObjectName("primaryBtn")
        batch_btn.setCursor(Qt.PointingHandCursor)
        header_row.addWidget(batch_btn)
        cl.addLayout(header_row)

        # 카드 행 1: 입출력
        io_row = QHBoxLayout()
        io_row.setSpacing(16)

        # 입력 카드
        input_card = self._make_card("📁  입력")
        ic_layout = input_card.layout()
        input_path = QLineEdit("X:/촬영팀/AI/촬영본/04.06/")
        input_path.setReadOnly(True)
        input_path.setObjectName("pathInput")
        ic_layout.addWidget(input_path)
        browse_in = QPushButton("폴더 선택")
        browse_in.setObjectName("outlineBtn")
        browse_in.setCursor(Qt.PointingHandCursor)
        ic_layout.addWidget(browse_in)
        io_row.addWidget(input_card)

        # 출력 카드
        output_card = self._make_card("📂  출력")
        oc_layout = output_card.layout()
        output_path = QLineEdit("D:/CLAUDE_CODE_WORK/output")
        output_path.setReadOnly(True)
        output_path.setObjectName("pathInput")
        oc_layout.addWidget(output_path)
        browse_out = QPushButton("폴더 선택")
        browse_out.setObjectName("outlineBtn")
        browse_out.setCursor(Qt.PointingHandCursor)
        oc_layout.addWidget(browse_out)
        io_row.addWidget(output_card)

        cl.addLayout(io_row)

        # 카드 행 2: 프로바이더 설정
        prov_row = QHBoxLayout()
        prov_row.setSpacing(16)

        # 분석 프로바이더
        analysis_card = self._make_card("🔍  AI 분석")
        ac_layout = analysis_card.layout()
        for name in ["Claude", "ChatGPT", "Gemini", "Grok"]:
            rb = QRadioButton(name)
            if name == "Gemini":
                rb.setChecked(True)
            ac_layout.addWidget(rb)
        prov_row.addWidget(analysis_card)

        # 배경 제거
        bg_card = self._make_card("✂  배경 제거")
        bc_layout = bg_card.layout()
        for name in ["Photoroom", "remove.bg", "복합"]:
            rb = QRadioButton(name)
            if name == "Photoroom":
                rb.setChecked(True)
            bc_layout.addWidget(rb)
        prov_row.addWidget(bg_card)

        # 보정
        enh_card = self._make_card("✨  이미지 보정")
        ec_layout = enh_card.layout()
        for name in ["Claid.ai", "OpenCV"]:
            rb = QRadioButton(name)
            if name == "Claid.ai":
                rb.setChecked(True)
            ec_layout.addWidget(rb)
        prov_row.addWidget(enh_card)

        # 그림자
        shadow_card = self._make_card("🌑  그림자")
        sc_layout = shadow_card.layout()
        shadow_combo = QComboBox()
        shadow_combo.addItems(["API", "Gemini", "누끼합성", "SAM-M", "SAM-CPU", "없음"])
        shadow_combo.setCurrentIndex(1)
        sc_layout.addWidget(shadow_combo)
        prov_row.addWidget(shadow_card)

        cl.addLayout(prov_row)

        # 카드 행 3: 옵션 + 미리보기
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(16)

        # 옵션 카드
        opt_card = self._make_card("⚡  처리 옵션")
        opt_layout = opt_card.layout()
        for text, checked in [("배경 제거 생략", False), ("AI 분석 생략", False),
                              ("크롭 완료 이미지", True), ("자동 수정 (AI 회의)", False)]:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            opt_layout.addWidget(cb)

        iter_row = QHBoxLayout()
        iter_row.addWidget(QLabel("자동 수정 횟수:"))
        spin = QSpinBox()
        spin.setRange(1, 10)
        spin.setValue(3)
        iter_row.addWidget(spin)
        iter_row.addStretch()
        opt_layout.addLayout(iter_row)
        bottom_row.addWidget(opt_card, 1)

        # 미리보기 카드
        preview_card = self._make_card("🖼  미리보기")
        pc_layout = preview_card.layout()
        preview_area = QLabel("이미지를 선택하면\n미리보기가 표시됩니다")
        preview_area.setAlignment(Qt.AlignCenter)
        preview_area.setMinimumHeight(160)
        preview_area.setObjectName("previewArea")
        pc_layout.addWidget(preview_area)
        bottom_row.addWidget(preview_card, 2)

        cl.addLayout(bottom_row)

        # 하단: 실행 바
        action_bar = QWidget()
        action_bar.setObjectName("actionBar")
        ab_layout = QHBoxLayout(action_bar)
        ab_layout.setContentsMargins(16, 12, 16, 12)

        progress = QProgressBar()
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setFormat("대기 중")
        ab_layout.addWidget(progress, 1)

        run_btn = QPushButton("  ▶  처리 시작")
        run_btn.setObjectName("runBtn")
        run_btn.setCursor(Qt.PointingHandCursor)
        ab_layout.addWidget(run_btn)

        stop_btn = QPushButton("  ■  중지")
        stop_btn.setObjectName("stopBtn")
        stop_btn.setCursor(Qt.PointingHandCursor)
        ab_layout.addWidget(stop_btn)

        vf_btn = QPushButton("  🔎  뷰파인더")
        vf_btn.setObjectName("outlineBtn")
        vf_btn.setCursor(Qt.PointingHandCursor)
        ab_layout.addWidget(vf_btn)

        cl.addWidget(action_bar)

        main_layout.addWidget(content, 1)

        self.setStyleSheet(STYLESHEET)

    def _make_card(self, title_text):
        card = QWidget()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        title = QLabel(title_text)
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        return card


STYLESHEET = """
/* 전역 */
QMainWindow { background: #f0f2f5; }
QWidget { font-family: '맑은 고딕', 'Segoe UI'; font-size: 9pt; color: #1e293b; }

/* 사이드바 */
#sidebar { background: #1e293b; border-right: 1px solid #334155; }
#logo { font-size: 18pt; font-weight: 800; color: #f8fafc; letter-spacing: 4px; padding: 8px 0; }
#menuBtn {
    background: transparent; border: none; border-radius: 8px;
    padding: 10px 14px; text-align: left; font-size: 9.5pt; color: #94a3b8;
}
#menuBtn:hover { background: #334155; color: #e2e8f0; }
#menuBtn:checked { background: #2563eb; color: #ffffff; font-weight: bold; }
#versionLabel { color: #475569; font-size: 8pt; }

/* 콘텐츠 */
#content { background: #f0f2f5; }
#pageTitle { font-size: 16pt; font-weight: 700; color: #0f172a; }

/* 카드 */
#card {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
}
#card:hover { border-color: #cbd5e1; }
#cardTitle { font-size: 10pt; font-weight: 700; color: #334155; }

/* 입력 */
#pathInput {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 8px 12px; color: #475569; font-size: 8.5pt;
}

/* 버튼 */
#primaryBtn {
    background: #2563eb; color: white; border: none; border-radius: 8px;
    padding: 9px 20px; font-weight: 600; font-size: 9.5pt;
}
#primaryBtn:hover { background: #1d4ed8; }

#outlineBtn {
    background: transparent; border: 1px solid #cbd5e1; border-radius: 8px;
    padding: 7px 16px; color: #475569;
}
#outlineBtn:hover { border-color: #2563eb; color: #2563eb; }

#runBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #7c3aed);
    color: white; border: none; border-radius: 8px;
    padding: 10px 28px; font-weight: 700; font-size: 10pt;
}
#runBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #6d28d9);
}

#stopBtn {
    background: #ef4444; color: white; border: none; border-radius: 8px;
    padding: 10px 20px; font-weight: 600;
}
#stopBtn:hover { background: #dc2626; }

/* 액션 바 */
#actionBar {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
}

/* 프로그레스 바 */
QProgressBar {
    background: #e2e8f0; border: none; border-radius: 7px;
    text-align: center; font-size: 8pt; color: #64748b;
    min-height: 14px; max-height: 14px;
}
QProgressBar::chunk { background: #2563eb; border-radius: 7px; }

/* 미리보기 */
#previewArea {
    background: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 10px;
    color: #94a3b8; font-size: 9pt;
}

/* 라디오/체크박스 */
QRadioButton, QCheckBox { spacing: 8px; padding: 3px 0; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 18px; height: 18px; border: 2px solid #cbd5e1; border-radius: 4px; background: white;
}
QRadioButton::indicator { border-radius: 10px; }
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background: #2563eb; border-color: #2563eb;
}
QRadioButton::indicator:hover, QCheckBox::indicator:hover { border-color: #2563eb; }

/* 콤보박스 */
QComboBox {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 7px 12px; min-height: 20px;
}
QComboBox:hover { border-color: #2563eb; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow {
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 6px solid #64748b; margin-right: 8px;
}

/* 스핀박스 */
QSpinBox {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 4px 8px;
}

/* 스크롤바 */
QScrollBar:vertical { background: transparent; width: 6px; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = SidebarCardApp()
    win.show()

    QTimer.singleShot(2000, lambda: (
        win.screen().grabWindow(int(win.winId())).save(
            str(os.path.join(os.path.dirname(__file__), "..", "sample1_result.png"))),
        print("Sample 1 saved!"),
        app.quit()
    ))
    app.exec()
