"""쇼핑몰 이미지 자동 편집 도구 — PySide6 GUI 진입점."""
import sys
import os

# 프로젝트 루트를 sys.path에 추가
from pathlib import Path
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
    app.setStyle("Fusion")  # 크로스 플랫폼 일관된 룩

    # 메인 윈도우 생성
    from gui_pyside.app import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
