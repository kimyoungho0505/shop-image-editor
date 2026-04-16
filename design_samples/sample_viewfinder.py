"""PySide6 뷰파인더 샘플 - 이미지 처리 단계별 비교"""
import sys, os
os.environ['QT_QPA_PLATFORM'] = 'windows'
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *


class ViewfinderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LUXBOY 뷰파인더 — 처리 과정 확인")
        self.resize(1400, 850)
        self.setMinimumSize(1200, 700)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 상단 헤더 ──
        header = QWidget()
        header.setFixedHeight(60)
        header.setObjectName("header")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(24, 0, 24, 0)

        title = QLabel("🔍 뷰파인더 — 처리 단계별 이미지 비교")
        title.setObjectName("headerTitle")
        h_layout.addWidget(title)
        h_layout.addStretch()

        # 파일명
        filename = QLabel("상품_001.jpg")
        filename.setObjectName("filename")
        h_layout.addWidget(filename)

        main_layout.addWidget(header)

        # ── 구분선 ──
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("headerLine")
        main_layout.addWidget(line)

        # ── 메인 콘텐츠 ──
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(16)

        # ── 왼쪽: 단계 선택 ──
        left_panel = QWidget()
        left_panel.setFixedWidth(180)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        step_label = QLabel("📊 처리 단계")
        step_label.setObjectName("sectionLabel")
        left_layout.addWidget(step_label)

        # 단계 버튼들
        self.step_buttons = []
        steps = [
            ("원본", "원본 이미지"),
            ("배경제거", "배경이 제거된 상태"),
            ("그림자", "그림자가 추가됨"),
            ("보정", "밝기/색상 조정"),
            ("센터링", "이미지 중앙 정렬"),
            ("최종", "완성된 이미지"),
        ]

        for i, (name, desc) in enumerate(steps):
            btn = QPushButton(f"  {i+1}. {name}")
            btn.setObjectName("stepBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(desc)
            if i == 0:
                btn.setChecked(True)
            self.step_buttons.append(btn)
            left_layout.addWidget(btn)

        left_layout.addStretch()

        # 점수
        score_card = QWidget()
        score_card.setObjectName("scoreCard")
        sc_layout = QVBoxLayout(score_card)
        sc_layout.setContentsMargins(12, 12, 12, 12)
        sc_layout.setSpacing(8)

        score_title = QLabel("📈 평가점수")
        score_title.setObjectName("cardTitle")
        sc_layout.addWidget(score_title)

        score_num = QLabel("92점")
        score_num.setObjectName("scoreNum")
        score_num.setAlignment(Qt.AlignCenter)
        sc_layout.addWidget(score_num)

        score_bar = QProgressBar()
        score_bar.setValue(92)
        score_bar.setObjectName("scoreBar")
        sc_layout.addWidget(score_bar)

        status = QLabel("✅ 우수")
        status.setObjectName("statusLabel")
        status.setAlignment(Qt.AlignCenter)
        sc_layout.addWidget(status)

        left_layout.addWidget(score_card)

        content_layout.addWidget(left_panel)

        # ── 중앙: 이미지 비교 ──
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(12)

        # 비포/애프터 탭
        tab_widget = QTabWidget()
        tab_widget.setObjectName("viewfinderTabs")

        # 탭 1: 슬라이더 비교
        slider_tab = QWidget()
        st_layout = QVBoxLayout(slider_tab)

        before_label = QLabel("이전 단계")
        before_label.setObjectName("comparisonLabel")
        st_layout.addWidget(before_label)

        before_img = QLabel()
        before_img.setFixedHeight(300)
        before_img.setObjectName("comparisonImage")
        before_img.setText("← 배경제거 전")
        before_img.setAlignment(Qt.AlignCenter)
        st_layout.addWidget(before_img)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(100)
        slider.setValue(50)
        slider.setObjectName("comparisonSlider")
        st_layout.addWidget(slider)

        after_label = QLabel("현재 단계")
        after_label.setObjectName("comparisonLabel")
        st_layout.addWidget(after_label)

        after_img = QLabel()
        after_img.setFixedHeight(300)
        after_img.setObjectName("comparisonImage")
        after_img.setText("배경제거 완료 →")
        after_img.setAlignment(Qt.AlignCenter)
        st_layout.addWidget(after_img)

        tab_widget.addTab(slider_tab, "📊 슬라이더 비교")

        # 탭 2: 좌우 비교
        compare_tab = QWidget()
        ct_layout = QHBoxLayout(compare_tab)
        ct_layout.setSpacing(12)

        before2 = QLabel()
        before2.setObjectName("comparisonImage")
        before2.setText("이전\n단계")
        before2.setAlignment(Qt.AlignCenter)
        ct_layout.addWidget(before2)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setObjectName("divider")
        divider.setFixedWidth(2)
        ct_layout.addWidget(divider)

        after2 = QLabel()
        after2.setObjectName("comparisonImage")
        after2.setText("현재\n단계")
        after2.setAlignment(Qt.AlignCenter)
        ct_layout.addWidget(after2)

        tab_widget.addTab(compare_tab, "🔀 좌우 비교")

        # 탭 3: 단계별 타일
        grid_tab = QWidget()
        gt_layout = QGridLayout(grid_tab)
        gt_layout.setSpacing(12)

        for i in range(6):
            tile = QLabel()
            tile.setObjectName("gridTile")
            tile.setText(f"단계 {i+1}")
            tile.setAlignment(Qt.AlignCenter)
            tile.setMinimumHeight(150)
            gt_layout.addWidget(tile, i // 3, i % 3)

        tab_widget.addTab(grid_tab, "🎯 전체 단계")

        center_layout.addWidget(tab_widget)

        content_layout.addWidget(center_panel, 1)

        # ── 오른쪽: 정보 패널 ──
        right_panel = QWidget()
        right_panel.setFixedWidth(200)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # 세부 정보
        info_card = QWidget()
        info_card.setObjectName("infoCard")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(10)

        info_title = QLabel("📋 세부 정보")
        info_title.setObjectName("cardTitle")
        info_layout.addWidget(info_title)

        # 정보 항목들
        details = [
            ("크기", "1000×1000 px"),
            ("배경", "투명 ✓"),
            ("그림자", "자연스러움"),
            ("밝기", "최적화됨"),
            ("색감", "생생함"),
            ("처리시간", "2분 15초"),
        ]

        for label, value in details:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setObjectName("detailLabel")
            lbl.setFixedWidth(60)
            row.addWidget(lbl)
            val = QLabel(value)
            val.setObjectName("detailValue")
            row.addWidget(val)
            info_layout.addLayout(row)

        right_layout.addWidget(info_card)

        # 버튼
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        approve_btn = QPushButton("✅ 승인")
        approve_btn.setObjectName("approveBtn")
        approve_btn.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(approve_btn)

        reject_btn = QPushButton("❌ 거부")
        reject_btn.setObjectName("rejectBtn")
        reject_btn.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(reject_btn)

        edit_btn = QPushButton("✏️ 편집")
        edit_btn.setObjectName("editBtn")
        edit_btn.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(edit_btn)

        right_layout.addLayout(btn_layout)
        right_layout.addStretch()

        content_layout.addWidget(right_panel)

        main_layout.addWidget(content)

        self.setStyleSheet(STYLESHEET)

    def set_score(self, score):
        """점수 설정"""
        if score >= 85:
            status = "✅ 우수"
            color = "#10b981"
        elif score >= 70:
            status = "⚠️ 보통"
            color = "#f59e0b"
        else:
            status = "❌ 미흡"
            color = "#ef4444"


STYLESHEET = """
/* 전역 */
QMainWindow { background: #f5f5f5; }
QWidget { font-family: '맑은 고딕'; font-size: 9pt; color: #1e293b; }

/* 헤더 */
#header { background: linear-gradient(90deg, #2563eb, #7c3aed); }
#headerTitle { font-size: 14pt; font-weight: 700; color: white; }
#filename { color: rgba(255,255,255,0.8); font-size: 9pt; }
#headerLine { color: #e5e7eb; max-height: 1px; }

/* 왼쪽 패널 */
#sectionLabel { font-size: 10pt; font-weight: 700; color: #2563eb; }
#stepBtn {
    background: white; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 10px 12px; color: #475569; text-align: left;
}
#stepBtn:hover { background: #f0f9ff; border-color: #2563eb; }
#stepBtn:checked { background: #2563eb; color: white; font-weight: bold; }

/* 점수 카드 */
#scoreCard {
    background: white; border: 1px solid #e5e7eb; border-radius: 10px;
}
#cardTitle { font-size: 10pt; font-weight: 700; color: #334155; }
#scoreNum { font-size: 24pt; font-weight: 700; color: #2563eb; }
#scoreBar {
    background: #e5e7eb; border: none; border-radius: 6px;
    text-align: center; min-height: 8px;
}
#scoreBar::chunk { background: linear-gradient(90deg, #10b981, #2563eb); }
#statusLabel { font-size: 9pt; font-weight: 700; color: #10b981; }

/* 탭 */
#viewfinderTabs { background: white; border: 1px solid #e5e7eb; }
QTabWidget::pane { border: 1px solid #e5e7eb; }
QTabBar::tab {
    background: #f9fafb; border: 1px solid #e5e7eb; border-bottom: none;
    padding: 8px 16px; color: #64748b;
}
QTabBar::tab:selected { background: white; color: #2563eb; font-weight: bold; }

/* 비교 이미지 */
#comparisonImage {
    background: #f9fafb; border: 2px dashed #cbd5e1; border-radius: 8px;
    color: #94a3b8; font-size: 10pt;
}
#comparisonLabel { font-size: 9pt; color: #64748b; font-weight: 600; }
#comparisonSlider {
    background: white; border: 1px solid #e5e7eb; border-radius: 6px;
    min-height: 6px;
}
#comparisonSlider::handle { background: #2563eb; border: none; border-radius: 8px; width: 14px; }

/* 그리드 타일 */
#gridTile {
    background: white; border: 1px solid #e5e7eb; border-radius: 8px;
    color: #64748b;
}
#gridTile:hover { border-color: #2563eb; }

/* 분할선 */
#divider { color: #e5e7eb; }

/* 정보 카드 */
#infoCard { background: white; border: 1px solid #e5e7eb; border-radius: 10px; }
#detailLabel { font-size: 8.5pt; color: #64748b; font-weight: 600; }
#detailValue { font-size: 8.5pt; color: #2563eb; font-weight: 700; }

/* 버튼 */
#approveBtn {
    background: #10b981; color: white; border: none; border-radius: 8px;
    padding: 10px; font-weight: 700;
}
#approveBtn:hover { background: #059669; }

#rejectBtn {
    background: #ef4444; color: white; border: none; border-radius: 8px;
    padding: 10px; font-weight: 700;
}
#rejectBtn:hover { background: #dc2626; }

#editBtn {
    background: #f59e0b; color: white; border: none; border-radius: 8px;
    padding: 10px; font-weight: 700;
}
#editBtn:hover { background: #d97706; }
"""


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = ViewfinderApp()
    win.show()

    from PySide6.QtCore import QTimer
    QTimer.singleShot(2000, lambda: (
        win.screen().grabWindow(int(win.winId())).save(
            str(os.path.join(os.path.dirname(__file__), "..", "sample_viewfinder.png"))),
        print("Viewfinder screenshot saved!"),
        app.quit()
    ))
    app.exec()
