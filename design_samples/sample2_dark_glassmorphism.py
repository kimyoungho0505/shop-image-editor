"""디자인 샘플 2: 다크 글래스모피즘 (프리미엄 느낌)"""
import sys, os
os.environ['QT_QPA_PLATFORM'] = 'windows'
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *


class DarkGlassApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LUXBOY Image Editor — Dark Premium")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 700)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 사이드바 (좁은 아이콘 바) ──
        icon_bar = QWidget()
        icon_bar.setFixedWidth(64)
        icon_bar.setObjectName("iconBar")
        ib_layout = QVBoxLayout(icon_bar)
        ib_layout.setContentsMargins(0, 16, 0, 16)
        ib_layout.setSpacing(4)

        # 로고
        logo = QLabel("L")
        logo.setObjectName("logoIcon")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedHeight(48)
        ib_layout.addWidget(logo)
        ib_layout.addSpacing(16)

        icons = ["🏠", "▶", "📝", "🌑", "⚙", "📊"]
        self.icon_btns = []
        for i, icon in enumerate(icons):
            btn = QPushButton(icon)
            btn.setObjectName("iconBtn")
            btn.setFixedSize(48, 48)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            if i == 1:
                btn.setChecked(True)
            self.icon_btns.append(btn)
            ib_layout.addWidget(btn, 0, Qt.AlignCenter)

        ib_layout.addStretch()
        main_layout.addWidget(icon_bar)

        # ── 메인 영역 ──
        content = QWidget()
        content.setObjectName("content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 28, 32, 20)
        cl.setSpacing(20)

        # 헤더
        header = QHBoxLayout()
        title = QLabel("이미지 처리")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        status_label = QLabel("● 준비 완료")
        status_label.setObjectName("statusBadge")
        header.addWidget(status_label)
        cl.addLayout(header)

        # 상단 카드 행
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        # 입출력 카드 (세로)
        io_card = self._glass_card("파일 설정")
        io_l = io_card.layout()

        lbl1 = QLabel("입력 경로")
        lbl1.setObjectName("fieldLabel")
        io_l.addWidget(lbl1)
        inp = QLineEdit("X:/촬영팀/AI/촬영본/04.06/")
        inp.setObjectName("glassInput")
        io_l.addWidget(inp)

        lbl2 = QLabel("출력 경로")
        lbl2.setObjectName("fieldLabel")
        io_l.addWidget(lbl2)
        out = QLineEdit("D:/CLAUDE_CODE_WORK/output")
        out.setObjectName("glassInput")
        io_l.addWidget(out)

        btn_row = QHBoxLayout()
        for text in ["파일 선택", "폴더 선택"]:
            b = QPushButton(text)
            b.setObjectName("glassBtn")
            b.setCursor(Qt.PointingHandCursor)
            btn_row.addWidget(b)
        io_l.addLayout(btn_row)
        top_row.addWidget(io_card, 1)

        # 프로바이더 카드
        prov_card = self._glass_card("AI 프로바이더")
        pl = prov_card.layout()

        for section, items, selected in [
            ("분석", ["Claude", "ChatGPT", "Gemini", "Grok"], "Gemini"),
            ("배경 제거", ["Photoroom", "remove.bg"], "Photoroom"),
            ("보정", ["Claid.ai", "OpenCV"], "Claid.ai"),
        ]:
            sl = QLabel(section)
            sl.setObjectName("sectionLabel")
            pl.addWidget(sl)
            row = QHBoxLayout()
            row.setSpacing(6)
            for name in items:
                btn = QPushButton(name)
                btn.setObjectName("chipBtn")
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                if name == selected:
                    btn.setChecked(True)
                row.addWidget(btn)
            row.addStretch()
            pl.addLayout(row)

        top_row.addWidget(prov_card, 1)
        cl.addLayout(top_row)

        # 하단 행: 그림자 + 옵션 + 미리보기
        bot_row = QHBoxLayout()
        bot_row.setSpacing(16)

        # 그림자 카드
        sh_card = self._glass_card("그림자 처리")
        shl = sh_card.layout()
        shadow_combo = QComboBox()
        shadow_combo.addItems(["Gemini AI", "API Shadow", "누끼합성", "SAM-M", "없음"])
        shadow_combo.setObjectName("glassCombo")
        shl.addWidget(shadow_combo)

        order_label = QLabel("처리 순서")
        order_label.setObjectName("sectionLabel")
        shl.addWidget(order_label)
        for text, checked in [("보정 후 그림자 (권장)", True), ("보정 전 그림자", False)]:
            rb = QRadioButton(text)
            rb.setChecked(checked)
            shl.addWidget(rb)
        shl.addStretch()
        bot_row.addWidget(sh_card, 1)

        # 옵션 카드
        opt_card = self._glass_card("처리 옵션")
        ol = opt_card.layout()
        for text, checked in [
            ("배경 제거 생략", False), ("AI 분석 생략", False),
            ("크롭 완료 이미지", True), ("자동 수정 (AI 회의)", False)
        ]:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            ol.addWidget(cb)
        ol.addStretch()
        bot_row.addWidget(opt_card, 1)

        # 미리보기 카드
        prev_card = self._glass_card("미리보기")
        pvl = prev_card.layout()
        preview = QLabel("드래그 앤 드롭\n또는 파일을 선택하세요")
        preview.setAlignment(Qt.AlignCenter)
        preview.setObjectName("previewDark")
        preview.setMinimumHeight(140)
        pvl.addWidget(preview)
        bot_row.addWidget(prev_card, 2)

        cl.addLayout(bot_row)

        # 실행 바
        action_bar = QWidget()
        action_bar.setObjectName("actionBarDark")
        ab = QHBoxLayout(action_bar)
        ab.setContentsMargins(20, 14, 20, 14)

        progress = QProgressBar()
        progress.setValue(35)
        progress.setFormat("처리 중... 35%")
        ab.addWidget(progress, 1)

        run = QPushButton("▶  처리 시작")
        run.setObjectName("runBtnDark")
        run.setCursor(Qt.PointingHandCursor)
        ab.addWidget(run)

        stop = QPushButton("■  중지")
        stop.setObjectName("stopBtnDark")
        stop.setCursor(Qt.PointingHandCursor)
        ab.addWidget(stop)

        cl.addWidget(action_bar)

        main_layout.addWidget(content, 1)
        self.setStyleSheet(STYLESHEET)

    def _glass_card(self, title):
        card = QWidget()
        card.setObjectName("glassCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        t = QLabel(title)
        t.setObjectName("glassCardTitle")
        layout.addWidget(t)
        return card


STYLESHEET = """
QMainWindow { background: #0f0f1a; }
QWidget { font-family: '맑은 고딕', 'Segoe UI'; font-size: 9pt; color: #e2e8f0; }

/* 아이콘 바 */
#iconBar { background: #0a0a14; border-right: 1px solid #1e1e3a; }
#logoIcon {
    font-size: 20pt; font-weight: 900; color: #a78bfa;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7c3aed22, stop:1 #2563eb22);
    border-radius: 8px;
}
#iconBtn {
    background: transparent; border: none; border-radius: 12px;
    font-size: 16pt; color: #64748b;
}
#iconBtn:hover { background: #1e1e3a; color: #a78bfa; }
#iconBtn:checked { background: #7c3aed33; color: #a78bfa; }

/* 콘텐츠 */
#content { background: #0f0f1a; }
#pageTitle { font-size: 18pt; font-weight: 700; color: #f1f5f9; }
#statusBadge {
    color: #4ade80; font-size: 8.5pt; font-weight: 600;
    background: #4ade8015; border: 1px solid #4ade8030;
    border-radius: 12px; padding: 4px 14px;
}

/* 글래스 카드 */
#glassCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1a1a2e, stop:1 #16162a);
    border: 1px solid #2a2a4a; border-radius: 14px;
}
#glassCard:hover { border-color: #3a3a5a; }
#glassCardTitle { font-size: 10pt; font-weight: 700; color: #a78bfa; }

/* 필드 */
#fieldLabel { font-size: 8pt; color: #64748b; font-weight: 600; margin-top: 4px; }
#sectionLabel { font-size: 8.5pt; color: #94a3b8; font-weight: 600; margin-top: 2px; }

#glassInput {
    background: #0f0f1a; border: 1px solid #2a2a4a; border-radius: 8px;
    padding: 8px 12px; color: #94a3b8; font-size: 8.5pt;
}
#glassInput:focus { border-color: #7c3aed; }

/* 버튼 */
#glassBtn {
    background: #1e1e3a; border: 1px solid #2a2a4a; border-radius: 8px;
    padding: 8px 16px; color: #a78bfa;
}
#glassBtn:hover { background: #2a2a4a; border-color: #7c3aed; }

/* 칩 버튼 */
#chipBtn {
    background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 16px;
    padding: 5px 14px; color: #94a3b8; font-size: 8.5pt;
}
#chipBtn:hover { border-color: #7c3aed; color: #a78bfa; }
#chipBtn:checked { background: #7c3aed; color: #ffffff; border-color: #7c3aed; font-weight: 600; }

/* 실행 바 */
#actionBarDark {
    background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 14px;
}

#runBtnDark {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:1 #2563eb);
    color: white; border: none; border-radius: 10px;
    padding: 11px 32px; font-weight: 700; font-size: 10pt;
}
#runBtnDark:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6d28d9, stop:1 #1d4ed8);
}
#stopBtnDark {
    background: #dc262630; color: #f87171; border: 1px solid #dc262650;
    border-radius: 10px; padding: 11px 20px; font-weight: 600;
}
#stopBtnDark:hover { background: #dc262650; }

/* 프로그레스 */
QProgressBar {
    background: #1e1e3a; border: none; border-radius: 7px;
    text-align: center; font-size: 8pt; color: #a78bfa;
    min-height: 14px; max-height: 14px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:1 #2563eb);
    border-radius: 7px;
}

/* 콤보 */
#glassCombo {
    background: #0f0f1a; border: 1px solid #2a2a4a; border-radius: 8px;
    padding: 8px 12px; color: #e2e8f0;
}
#glassCombo:hover { border-color: #7c3aed; }
#glassCombo::drop-down { border: none; width: 24px; }
#glassCombo::down-arrow {
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 6px solid #64748b; margin-right: 8px;
}
#glassCombo QAbstractItemView {
    background: #1a1a2e; border: 1px solid #2a2a4a;
    selection-background-color: #7c3aed; selection-color: white;
}

/* 미리보기 */
#previewDark {
    background: #0a0a14; border: 2px dashed #2a2a4a; border-radius: 12px;
    color: #475569; font-size: 9pt;
}

/* 라디오/체크박스 */
QRadioButton, QCheckBox { spacing: 8px; padding: 3px 0; color: #cbd5e1; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 18px; height: 18px; border: 2px solid #3a3a5a; border-radius: 4px; background: #0f0f1a;
}
QRadioButton::indicator { border-radius: 10px; }
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background: #7c3aed; border-color: #7c3aed;
}

/* 스크롤바 */
QScrollBar:vertical { background: transparent; width: 6px; }
QScrollBar::handle:vertical { background: #2a2a4a; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DarkGlassApp()
    win.show()
    QTimer.singleShot(2000, lambda: (
        win.screen().grabWindow(int(win.winId())).save(
            str(os.path.join(os.path.dirname(__file__), "..", "sample2_result.png"))),
        print("Sample 2 saved!"),
        app.quit()
    ))
    app.exec()
