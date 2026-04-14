"""디자인 샘플 3: 미니멀 클린 (Apple 스타일)"""
import sys, os
os.environ['QT_QPA_PLATFORM'] = 'windows'
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *


class MinimalCleanApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LUXBOY Image Editor — Minimal Clean")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 700)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 상단 네비게이션 바 ──
        navbar = QWidget()
        navbar.setFixedHeight(56)
        navbar.setObjectName("navbar")
        nb_layout = QHBoxLayout(navbar)
        nb_layout.setContentsMargins(24, 0, 24, 0)

        logo = QLabel("LUXBOY")
        logo.setObjectName("navLogo")
        nb_layout.addWidget(logo)
        nb_layout.addSpacing(32)

        self.nav_btns = []
        for text in ["처리", "프롬프트", "그림자", "설정"]:
            btn = QPushButton(text)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self.nav_btns.append(btn)
            nb_layout.addWidget(btn)

        self.nav_btns[0].setChecked(True)
        nb_layout.addStretch()

        status = QLabel("GPU: RTX 3060 Ti")
        status.setObjectName("navStatus")
        nb_layout.addWidget(status)

        main_layout.addWidget(navbar)

        # 구분선
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("navLine")
        main_layout.addWidget(line)

        # ── 콘텐츠 영역 ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("scrollArea")

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(48, 32, 48, 32)
        cl.setSpacing(32)

        # 페이지 헤더
        header = QVBoxLayout()
        title = QLabel("이미지 처리")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        subtitle = QLabel("원본 이미지를 선택하고 AI 기반 자동 편집을 실행합니다")
        subtitle.setObjectName("pageSubtitle")
        header.addWidget(subtitle)
        cl.addLayout(header)

        # 섹션 1: 파일
        cl.addWidget(self._section_title("파일"))
        file_section = QWidget()
        file_section.setObjectName("section")
        fl = QGridLayout(file_section)
        fl.setContentsMargins(24, 20, 24, 20)
        fl.setHorizontalSpacing(16)
        fl.setVerticalSpacing(14)

        fl.addWidget(self._field_label("입력"), 0, 0)
        inp = QLineEdit("X:/촬영팀/AI/촬영본/04.06/26-04-06_015.jpg")
        inp.setObjectName("cleanInput")
        fl.addWidget(inp, 0, 1)
        b1 = QPushButton("찾아보기")
        b1.setObjectName("softBtn")
        b1.setCursor(Qt.PointingHandCursor)
        fl.addWidget(b1, 0, 2)

        fl.addWidget(self._field_label("출력"), 1, 0)
        out = QLineEdit("D:/CLAUDE_CODE_WORK/output")
        out.setObjectName("cleanInput")
        fl.addWidget(out, 1, 1)
        b2 = QPushButton("찾아보기")
        b2.setObjectName("softBtn")
        b2.setCursor(Qt.PointingHandCursor)
        fl.addWidget(b2, 1, 2)

        cl.addWidget(file_section)

        # 섹션 2: AI 프로바이더
        cl.addWidget(self._section_title("AI 프로바이더"))
        prov_section = QWidget()
        prov_section.setObjectName("section")
        pl = QVBoxLayout(prov_section)
        pl.setContentsMargins(24, 20, 24, 20)
        pl.setSpacing(16)

        for label, items, selected in [
            ("이미지 분석", ["Claude", "ChatGPT", "Gemini", "Grok"], "Gemini"),
            ("배경 제거", ["Photoroom", "remove.bg", "복합"], "Photoroom"),
            ("이미지 보정", ["Claid.ai", "OpenCV"], "Claid.ai"),
            ("그림자", ["Gemini AI", "API", "누끼합성", "SAM-Mobile", "없음"], "Gemini AI"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel(label)
            lbl.setFixedWidth(90)
            lbl.setObjectName("fieldLabelClean")
            row.addWidget(lbl)

            for name in items:
                btn = QPushButton(name)
                btn.setObjectName("segmentBtn")
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                if name == selected:
                    btn.setChecked(True)
                row.addWidget(btn)
            row.addStretch()
            pl.addLayout(row)

        cl.addWidget(prov_section)

        # 섹션 3: 옵션
        cl.addWidget(self._section_title("옵션"))
        opt_section = QWidget()
        opt_section.setObjectName("section")
        ol = QHBoxLayout(opt_section)
        ol.setContentsMargins(24, 20, 24, 20)
        ol.setSpacing(32)

        left_opts = QVBoxLayout()
        left_opts.setSpacing(12)
        for text, checked in [("배경 제거 생략", False), ("AI 분석 생략", False)]:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            left_opts.addWidget(cb)
        ol.addLayout(left_opts)

        right_opts = QVBoxLayout()
        right_opts.setSpacing(12)
        for text, checked in [("크롭 완료 이미지", True), ("자동 수정 (AI 회의)", False)]:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            right_opts.addWidget(cb)
        ol.addLayout(right_opts)

        # 자동 수정 횟수
        iter_col = QVBoxLayout()
        iter_col.setSpacing(4)
        iter_label = QLabel("자동 수정 횟수")
        iter_label.setObjectName("fieldLabelClean")
        iter_col.addWidget(iter_label)
        spin = QSpinBox()
        spin.setRange(1, 10)
        spin.setValue(3)
        spin.setObjectName("cleanSpin")
        iter_col.addWidget(spin)
        ol.addLayout(iter_col)
        ol.addStretch()

        cl.addWidget(opt_section)
        cl.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll, 1)

        # ── 하단 실행 바 ──
        footer = QWidget()
        footer.setFixedHeight(72)
        footer.setObjectName("footer")
        ft_layout = QHBoxLayout(footer)
        ft_layout.setContentsMargins(48, 0, 48, 0)

        progress = QProgressBar()
        progress.setValue(0)
        progress.setFormat("대기 중")
        ft_layout.addWidget(progress, 1)
        ft_layout.addSpacing(16)

        vf = QPushButton("뷰파인더")
        vf.setObjectName("softBtn")
        vf.setCursor(Qt.PointingHandCursor)
        ft_layout.addWidget(vf)

        stop = QPushButton("중지")
        stop.setObjectName("dangerBtn")
        stop.setCursor(Qt.PointingHandCursor)
        ft_layout.addWidget(stop)

        run = QPushButton("처리 시작")
        run.setObjectName("accentBtn")
        run.setCursor(Qt.PointingHandCursor)
        ft_layout.addWidget(run)

        main_layout.addWidget(footer)

        self.setStyleSheet(STYLESHEET)

    def _section_title(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("sectionTitle")
        return lbl

    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabelClean")
        lbl.setFixedWidth(40)
        return lbl


STYLESHEET = """
QMainWindow { background: #ffffff; }
QWidget { font-family: '맑은 고딕', 'Segoe UI'; font-size: 9pt; color: #1d1d1f; }

/* 네비게이션 */
#navbar { background: #ffffff; }
#navLogo { font-size: 14pt; font-weight: 800; color: #1d1d1f; letter-spacing: 3px; }
#navBtn {
    background: transparent; border: none; border-radius: 6px;
    padding: 8px 16px; color: #86868b; font-size: 9pt; font-weight: 500;
}
#navBtn:hover { color: #1d1d1f; }
#navBtn:checked { color: #0071e3; font-weight: 700; }
#navStatus { color: #86868b; font-size: 8pt; }
#navLine { color: #d2d2d7; max-height: 1px; }

/* 스크롤 */
#scrollArea { background: #f5f5f7; border: none; }

/* 페이지 */
#pageTitle { font-size: 22pt; font-weight: 700; color: #1d1d1f; }
#pageSubtitle { font-size: 9.5pt; color: #86868b; margin-top: 2px; }

/* 섹션 */
#sectionTitle { font-size: 10pt; font-weight: 700; color: #1d1d1f; padding-left: 4px; }
#section {
    background: #ffffff; border: 1px solid #d2d2d7; border-radius: 12px;
}

/* 필드 */
#fieldLabelClean { font-size: 9pt; color: #86868b; font-weight: 500; }

#cleanInput {
    background: #f5f5f7; border: 1px solid #d2d2d7; border-radius: 8px;
    padding: 9px 14px; color: #1d1d1f; font-size: 9pt;
}
#cleanInput:focus { border-color: #0071e3; background: #ffffff; }

/* 버튼 */
#softBtn {
    background: #f5f5f7; border: none; border-radius: 8px;
    padding: 9px 18px; color: #0071e3; font-weight: 500;
}
#softBtn:hover { background: #e8e8ed; }

#accentBtn {
    background: #0071e3; color: white; border: none; border-radius: 8px;
    padding: 10px 28px; font-weight: 700; font-size: 10pt;
}
#accentBtn:hover { background: #0077ED; }

#dangerBtn {
    background: transparent; color: #ff3b30; border: 1px solid #ff3b3040;
    border-radius: 8px; padding: 9px 18px; font-weight: 500;
}
#dangerBtn:hover { background: #ff3b3010; }

/* 세그먼트 버튼 (프로바이더 선택) */
#segmentBtn {
    background: #f5f5f7; border: 1px solid #d2d2d7; border-radius: 8px;
    padding: 7px 16px; color: #3a3a3c; font-size: 8.5pt;
}
#segmentBtn:hover { border-color: #0071e3; color: #0071e3; }
#segmentBtn:checked {
    background: #0071e3; color: white; border-color: #0071e3; font-weight: 600;
}

/* 체크박스 */
QCheckBox { spacing: 10px; color: #3a3a3c; }
QCheckBox::indicator {
    width: 20px; height: 20px; border: 2px solid #d2d2d7;
    border-radius: 6px; background: white;
}
QCheckBox::indicator:hover { border-color: #0071e3; }
QCheckBox::indicator:checked { background: #0071e3; border-color: #0071e3; }

/* 스핀박스 */
#cleanSpin {
    background: #f5f5f7; border: 1px solid #d2d2d7; border-radius: 8px;
    padding: 6px 10px; min-width: 60px;
}

/* 프로그레스 */
QProgressBar {
    background: #e8e8ed; border: none; border-radius: 5px;
    text-align: center; font-size: 8pt; color: #86868b;
    min-height: 10px; max-height: 10px;
}
QProgressBar::chunk { background: #0071e3; border-radius: 5px; }

/* 푸터 */
#footer { background: #ffffff; border-top: 1px solid #d2d2d7; }

/* 스크롤바 */
QScrollBar:vertical { background: transparent; width: 6px; }
QScrollBar::handle:vertical { background: #c7c7cc; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #8e8e93; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MinimalCleanApp()
    win.show()
    QTimer.singleShot(2000, lambda: (
        win.screen().grabWindow(int(win.winId())).save(
            str(os.path.join(os.path.dirname(__file__), "..", "sample3_result.png"))),
        print("Sample 3 saved!"),
        app.quit()
    ))
    app.exec()
