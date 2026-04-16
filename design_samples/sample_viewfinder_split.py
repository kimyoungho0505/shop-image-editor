"""PySide6 뷰파인더 샘플 - 좌우 분할 비교"""
import sys, os
os.environ['QT_QPA_PLATFORM'] = 'windows'
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *


class SplitViewfinderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LUXBOY 뷰파인더 — 좌우 비교")
        self.resize(1400, 900)
        self.setMinimumSize(1200, 700)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 헤더 ──
        header = QWidget()
        header.setFixedHeight(70)
        header.setObjectName("header")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(28, 0, 28, 0)
        h_layout.setSpacing(20)

        title = QLabel("🔍 좌우 비교 뷰파인더")
        title.setObjectName("headerTitle")
        h_layout.addWidget(title)

        # 단계 표시
        step_label = QLabel("단계 선택:")
        step_label.setObjectName("stepLabel")
        h_layout.addWidget(step_label)

        step_combo = QComboBox()
        step_combo.addItems(["원본 ↔ 배경제거", "배경제거 ↔ 그림자", "그림자 ↔ 보정",
                             "보정 ↔ 센터링", "센터링 ↔ 최종"])
        step_combo.setObjectName("stepCombo")
        step_combo.setFixedWidth(180)
        h_layout.addWidget(step_combo)

        h_layout.addStretch()

        # 파일명
        filename = QLabel("상품_신발_001.jpg")
        filename.setObjectName("filename")
        h_layout.addWidget(filename)

        main_layout.addWidget(header)

        # 구분선
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("headerLine")
        main_layout.addWidget(line)

        # ── 메인 콘텐츠 ──
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(0)

        # ── 왼쪽 이미지 ──
        left_container = QWidget()
        left_container.setObjectName("imageContainer")
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)

        left_title = QLabel("이전 단계")
        left_title.setObjectName("sideTitle")
        left_layout.addWidget(left_title)

        left_img = QLabel()
        left_img.setObjectName("imageArea")
        left_img.setText("📷\n\n배경제거 전\n원본 이미지")
        left_img.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(left_img)

        left_info = QLabel("해상도: 2000×2000px\n파일크기: 2.5MB\n촬영일: 2026-04-17")
        left_info.setObjectName("imageInfo")
        left_layout.addWidget(left_info)

        content_layout.addWidget(left_container, 1)

        # ── 중앙 분할선 ──
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setObjectName("divider")
        divider.setFixedWidth(2)
        content_layout.addWidget(divider)

        # ── 오른쪽 이미지 ──
        right_container = QWidget()
        right_container.setObjectName("imageContainer")
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)

        right_title = QLabel("현재 단계")
        right_title.setObjectName("sideTitle")
        right_layout.addWidget(right_title)

        right_img = QLabel()
        right_img.setObjectName("imageArea")
        right_img.setText("✨\n\n배경제거 완료\n깨끗한 누끼")
        right_img.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(right_img)

        right_info = QLabel("배경: 제거됨 ✓\n그림자: 미처리\n처리시간: 45초")
        right_info.setObjectName("imageInfo")
        right_layout.addWidget(right_info)

        content_layout.addWidget(right_container, 1)

        main_layout.addWidget(content, 1)

        # ── 하단 액션 바 ──
        footer = QWidget()
        footer.setFixedHeight(70)
        footer.setObjectName("footer")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(28, 0, 28, 0)
        f_layout.setSpacing(16)

        # 점수
        score_box = QWidget()
        score_box.setObjectName("scoreBox")
        sb_layout = QHBoxLayout(score_box)
        sb_layout.setContentsMargins(16, 0, 16, 0)
        sb_layout.setSpacing(12)

        score_label = QLabel("평가 점수")
        score_label.setObjectName("scoreLabel")
        sb_layout.addWidget(score_label)

        score_num = QLabel("92")
        score_num.setObjectName("scoreNumber")
        sb_layout.addWidget(score_num)

        score_text = QLabel("점 / 100점")
        score_text.setObjectName("scoreText")
        sb_layout.addWidget(score_text)

        f_layout.addWidget(score_box)

        # 상태
        status = QLabel("✅ 우수 — 이 결과물을 사용 가능합니다")
        status.setObjectName("status")
        f_layout.addWidget(status)

        f_layout.addStretch()

        # 버튼들
        prev_btn = QPushButton("◀ 이전")
        prev_btn.setObjectName("navBtn")
        prev_btn.setCursor(Qt.PointingHandCursor)
        f_layout.addWidget(prev_btn)

        next_btn = QPushButton("다음 ▶")
        next_btn.setObjectName("navBtn")
        next_btn.setCursor(Qt.PointingHandCursor)
        f_layout.addWidget(next_btn)

        reject_btn = QPushButton("❌ 거부")
        reject_btn.setObjectName("rejectBtn")
        reject_btn.setCursor(Qt.PointingHandCursor)
        f_layout.addWidget(reject_btn)

        approve_btn = QPushButton("✅ 승인")
        approve_btn.setObjectName("approveBtn")
        approve_btn.setCursor(Qt.PointingHandCursor)
        f_layout.addWidget(approve_btn)

        main_layout.addWidget(footer)

        self.setStyleSheet(STYLESHEET)


STYLESHEET = """
/* 전역 */
QMainWindow { background: #f0f0f0; }
QWidget { font-family: '맑은 고딕', 'Segoe UI'; font-size: 9pt; color: #1e293b; }

/* 헤더 */
#header { background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%); }
#headerTitle { font-size: 16pt; font-weight: 800; color: white; letter-spacing: 1px; }
#stepLabel { color: rgba(255,255,255,0.9); font-weight: 600; }
#stepCombo {
    background: rgba(255,255,255,0.15); color: white; border: 1px solid rgba(255,255,255,0.3);
    border-radius: 6px; padding: 6px 12px; font-weight: 600;
}
#stepCombo::drop-down { border: none; }
#stepCombo::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 6px solid white; }
#stepCombo QAbstractItemView { background: #1e293b; color: white; selection-background-color: #2563eb; }
#filename { color: rgba(255,255,255,0.85); font-size: 9.5pt; }
#headerLine { color: rgba(0,0,0,0.05); max-height: 1px; }

/* 컨테이너 */
#imageContainer { background: white; border-radius: 12px; padding: 20px; }

/* 제목 */
#sideTitle { font-size: 12pt; font-weight: 700; color: #0f172a; margin-bottom: 8px; }

/* 이미지 영역 */
#imageArea {
    background: linear-gradient(135deg, #f0f9ff 0%, #fdf2f8 100%);
    border: 2px dashed #cbd5e1; border-radius: 10px;
    color: #64748b; font-size: 11pt; font-weight: 600;
    min-height: 300px; max-height: 500px;
}

/* 이미지 정보 */
#imageInfo {
    background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 12px 14px; color: #64748b; font-size: 8.5pt; line-height: 1.6;
}

/* 분할선 */
#divider { background: #e5e7eb; }

/* 푸터 */
#footer { background: white; border-top: 1px solid #e5e7eb; }

/* 점수 박스 */
#scoreBox { background: #dbeafe; border-radius: 8px; border: 1px solid #bfdbfe; }
#scoreLabel { color: #1e40af; font-weight: 700; font-size: 9.5pt; }
#scoreNumber { font-size: 18pt; font-weight: 800; color: #2563eb; }
#scoreText { color: #3b82f6; font-weight: 600; }

/* 상태 */
#status { color: #10b981; font-weight: 700; font-size: 10pt; }

/* 네비게이션 버튼 */
#navBtn {
    background: #f9fafb; border: 1px solid #cbd5e1; border-radius: 8px;
    padding: 10px 20px; color: #475569; font-weight: 600;
}
#navBtn:hover { background: #f0f9ff; border-color: #2563eb; color: #2563eb; }

/* 승인/거부 버튼 */
#approveBtn {
    background: #10b981; color: white; border: none; border-radius: 8px;
    padding: 10px 24px; font-weight: 700;
}
#approveBtn:hover { background: #059669; }

#rejectBtn {
    background: #ef4444; color: white; border: none; border-radius: 8px;
    padding: 10px 24px; font-weight: 700;
}
#rejectBtn:hover { background: #dc2626; }
"""


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = SplitViewfinderApp()
    win.show()

    from PySide6.QtCore import QTimer
    QTimer.singleShot(2000, lambda: (
        win.screen().grabWindow(int(win.winId())).save(
            str(os.path.join(os.path.dirname(__file__), "..", "sample_viewfinder_split.png"))),
        print("Split viewfinder screenshot saved!"),
        app.quit()
    ))
    app.exec()
