# 프로젝트 규칙

## 코드 수정 필수 규칙
- **파일을 Edit하기 전에 반드시 Read로 해당 파일의 현재 상태를 먼저 확인할 것**
- old_string은 반드시 방금 Read한 현재 파일 내용에서 복사할 것 (기억에 의존 금지)
- 한 파일에 여러 곳을 수정할 때, 첫 번째 Edit 후 다시 Read하고 두 번째 Edit 진행
- 이전 대화에서 수정한 내용이 현재 파일에 반영되어 있는지 Read로 확인 후 작업

## 프로젝트 구조
- GUI: tkinter (gui.py) / PySide6 (gui_pyside.py) 라이트 테마 (customtkinter 사용 금지)
- 설정: config/settings.yaml, config/prompts.yaml, config/categories.yaml
- 파이프라인: src/pipeline.py (핵심 오케스트레이터)
- Vision 클라이언트: src/analyzer/ (claude, openai, gemini, grok)
- API 키: .env 파일 (dotenv)

## PySide6 GUI 구조 (gui_pyside/)
- 진입점: gui_pyside.py → gui_pyside/app.py (MainWindow)
- 탭: gui_pyside/tabs/ (main_tab, prompt_tab, hints_tab, settings_tab)
- 다이얼로그: gui_pyside/dialogs/ (viewfinder, deliberation, prompt_preview)
- 워커: gui_pyside/workers.py (QThread 기반)
- 스타일: gui_pyside/styles.py (QSS)
- 유틸: gui_pyside/utils.py (경로, YAML, 상태 관리)
