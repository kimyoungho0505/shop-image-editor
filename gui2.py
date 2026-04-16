"""LUXBOY 이미지 자동편집 프로그램 - PySide6 향상된 GUI v2"""
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
APP_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP_DIR))

# 환경변수 로드
from dotenv import load_dotenv
load_dotenv(str(APP_DIR / ".env"))

# PySide6 앱 생성
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


def main():
    # High DPI 지원
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 메인 윈도우 생성
    from gui2_pyside.app import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
