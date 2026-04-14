"""PySide6 메인 윈도우 - 공유 상태 관리 및 탭 구성."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QStatusBar,
)
from PySide6.QtCore import Qt

from dotenv import load_dotenv

from gui_pyside.utils import (
    APP_DIR, CONFIG_DIR, WINDOW_TITLE,
    load_yaml, save_yaml, load_state, save_state,
    PROMPTS_PATH, SETTINGS_PATH, CATEGORIES_PATH, SHADOW_HINTS_PATH, ENV_PATH,
)
from gui_pyside.styles import MAIN_STYLESHEET
from gui_pyside.workers import ProcessWorker

load_dotenv(str(ENV_PATH))

DEFAULT_STATE = {
    "input_folder": "",
    "output_folder": str(APP_DIR / "output"),
    "vision_provider": "claude",
    "bg_provider": "photoroom",
    "enhance_provider": "claid",
    "shadow_provider": "opencv_extract",
    "shadow_judge_mode": "auto",
    "shadow_composite": "overlay",
    "skip_bg": False,
    "skip_analysis": False,
    "pre_cropped": False,
    "auto_refine": False,
    "max_iterations": 3,
    "concurrent_workers": 1,
}


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1100, 850)
        self.setMinimumSize(900, 700)
        self.setStyleSheet(MAIN_STYLESHEET)

        # 공유 상태
        saved = load_state()
        self.state: dict = {**DEFAULT_STATE, **saved}

        # 설정 데이터 (각 탭에서 참조)
        self.settings: dict = {}
        self.prompts: dict = {}
        self.categories: dict = {}
        self.shadow_hints: dict = {}

        # 처리 관련 플래그
        self._processing = False
        self._viewfinder_pairs: list = []
        self._vf_file_stages: dict = {}
        self._vf_dlg = None
        self._worker: ProcessWorker | None = None

        # 설정 로드
        self.load_configs()

        # UI 구성
        self._build_ui()

        # 상태바 초기 메시지
        self.statusBar().showMessage("준비 완료")

    def _build_ui(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)

        tab_defs = [
            ("  실행  ", "gui_pyside.tabs.main_tab", "MainTab"),
            ("  프롬프트 편집  ", "gui_pyside.tabs.prompt_tab", "PromptTab"),
            ("  그림자 힌트  ", "gui_pyside.tabs.hints_tab", "HintsTab"),
            ("  설정  ", "gui_pyside.tabs.settings_tab", "SettingsTab"),
        ]

        self._tab_widgets: dict[str, QWidget] = {}

        for label, module_path, class_name in tab_defs:
            widget = self._try_load_tab(module_path, class_name)
            self.tabs.addTab(widget, label)
            self._tab_widgets[class_name] = widget

        self.setCentralWidget(self.tabs)

    def _try_load_tab(self, module_path: str, class_name: str) -> QWidget:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            return cls(self)
        except Exception:
            placeholder = QWidget()
            return placeholder

    # ── 설정 로드/저장 ──

    def load_configs(self):
        try:
            self.settings = load_yaml(SETTINGS_PATH) or {}
        except Exception:
            self.settings = {}

        try:
            self.prompts = load_yaml(PROMPTS_PATH) or {}
        except Exception:
            self.prompts = {}

        try:
            self.categories = load_yaml(CATEGORIES_PATH) or {}
        except Exception:
            self.categories = {}

        try:
            self.shadow_hints = load_yaml(SHADOW_HINTS_PATH) or {}
        except Exception:
            self.shadow_hints = {}

    def save_configs(self):
        save_yaml(SETTINGS_PATH, self.settings)
        save_yaml(PROMPTS_PATH, self.prompts)
        save_yaml(CATEGORIES_PATH, self.categories)
        save_yaml(SHADOW_HINTS_PATH, self.shadow_hints)

    def _save_state(self):
        save_state(self.state)

    def closeEvent(self, event):
        self._save_state()
        # 뷰파인더 타이머 정리
        if hasattr(self, '_vf_dlg') and self._vf_dlg is not None:
            try:
                if hasattr(self._vf_dlg, '_refresh_timer'):
                    self._vf_dlg._refresh_timer.stop()
                self._vf_dlg.close()
            except RuntimeError:
                pass
        if self._processing and self._worker:
            self._worker.stop()
            self._worker.wait(3000)
        event.accept()

    # ── 핵심 액션 메서드 ──

    def run(self, mode: str = "single"):
        if self._processing:
            return

        self._processing = True

        worker = ProcessWorker(
            mode=mode,
            files=self._collect_files(),
            input_dir=self.state.get("input_folder", ""),
            output_dir=self.state.get("output_folder", ""),
            category=self.state.get("category", ""),
            skip_analysis=self.state.get("skip_analysis", False),
            skip_photoroom=self.state.get("skip_bg", False),
            pre_cropped=self.state.get("pre_cropped", False),
            num_workers=self.state.get("concurrent_workers", 1),
            auto_refine=self.state.get("auto_refine", False),
            max_iterations=self.state.get("max_iterations", 3),
            parent=self,
        )

        worker.log.connect(self._on_worker_log)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        worker.file_started.connect(self._on_file_started)
        worker.file_completed.connect(self._on_file_completed)
        worker.stage_image.connect(self._on_stage_image)

        self._worker = worker
        worker.start()

    def stop(self):
        if self._worker and self._processing:
            self._worker.stop()
            self.log("처리 중지 요청...", "warn")

    def restart(self):
        self._save_state()
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv)
        self.close()

    def open_viewfinder(self):
        pass

    def log(self, msg: str, level: str = "info"):
        main_tab = self._tab_widgets.get("MainTab")
        if main_tab and hasattr(main_tab, "append_log"):
            main_tab.append_log(msg, level)

    # ── Worker 시그널 핸들러 ──

    def _on_worker_log(self, msg: str, tag: str):
        self.log(msg, tag)

    def _on_worker_progress(self, value: float):
        main_tab = self._tab_widgets.get("MainTab")
        if main_tab and hasattr(main_tab, "set_progress"):
            main_tab.set_progress(value)

    def _on_worker_finished(self, success: int, fail: int):
        self._processing = False
        self._worker = None
        self.log(f"완료: 성공 {success}, 실패 {fail}", "info")
        self.statusBar().showMessage(f"완료 - 성공: {success}, 실패: {fail}")
        main_tab = self._tab_widgets.get("MainTab")
        if main_tab and hasattr(main_tab, "on_processing_finished"):
            main_tab.on_processing_finished(success, fail)

    def _on_worker_error(self, msg: str):
        self._processing = False
        self._worker = None
        self.log(msg, "error")
        self.statusBar().showMessage("오류 발생")
        main_tab = self._tab_widgets.get("MainTab")
        if main_tab and hasattr(main_tab, "on_processing_finished"):
            main_tab.on_processing_finished(0, 1)

    def _on_file_started(self, filename: str):
        self.statusBar().showMessage(f"처리 중: {filename}")

    def _on_file_completed(self, filename: str, result: dict):
        self.log(f"[{filename}] 처리 완료", "info")

    def _on_stage_image(self, filename: str, stage: str, data: bytes):
        self._vf_file_stages.setdefault(filename, {})[stage] = data
        if self._vf_dlg and hasattr(self._vf_dlg, "on_stage_image"):
            self._vf_dlg.on_stage_image(filename, stage, data)

    # ── 유틸리티 ──

    def _collect_files(self) -> list[str]:
        main_tab = self._tab_widgets.get("MainTab")
        if main_tab and hasattr(main_tab, "get_selected_files"):
            return main_tab.get_selected_files()
        return []
