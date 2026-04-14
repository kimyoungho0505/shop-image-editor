"""PySide6 GUI 유틸리티 - 경로 상수, YAML 헬퍼, 의존성 검사."""
import os
import sys
import json
import subprocess
import re
import warnings
import importlib.util
from pathlib import Path

import yaml

APP_DIR = Path(__file__).parent.parent.resolve()
CONFIG_DIR = APP_DIR / "config"
PROMPTS_PATH = CONFIG_DIR / "prompts.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
CATEGORIES_PATH = CONFIG_DIR / "categories.yaml"
SHADOW_HINTS_PATH = CONFIG_DIR / "shadow_hints.yaml"
ENV_PATH = APP_DIR / ".env"
GUI_STATE_PATH = APP_DIR / "gui_state.json"

WINDOW_TITLE = "LUXBOY 이미지 자동 편집 도구"


def load_yaml(path):
    with open(str(path), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path, data):
    with open(str(path), "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_state() -> dict:
    if GUI_STATE_PATH.exists():
        try:
            with open(str(GUI_STATE_PATH), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    try:
        with open(str(GUI_STATE_PATH), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _detect_cuda_version():
    """nvidia-smi에서 CUDA 버전을 감지하여 (available, version_str, whl_tag) 반환."""
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False, None, None
        m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", result.stdout)
        if not m:
            return True, "unknown", "cu118"
        major, minor = int(m.group(1)), int(m.group(2))
        ver_str = f"{major}.{minor}"
        if major >= 13 or (major == 12 and minor >= 6):
            whl = "cu126"
        elif major == 12 and minor >= 4:
            whl = "cu124"
        elif major == 12 and minor >= 1:
            whl = "cu121"
        elif major == 12:
            whl = "cu121"
        elif major == 11 and minor >= 8:
            whl = "cu118"
        else:
            whl = "cu118"
        return True, ver_str, whl
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, None, None


def _is_installed(module_name: str) -> bool:
    try:
        top = module_name.split(".")[0]
        if importlib.util.find_spec(top) is not None:
            return True
    except (ModuleNotFoundError, ValueError):
        pass
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            __import__(module_name)
            return True
        except ImportError:
            return False


def _check_and_install_deps():
    """필수/선택 패키지 누락 시 PySide6 QDialog 기반 설치 다이얼로그 표시."""
    required = {
        "dotenv": "python-dotenv",
        "yaml": "pyyaml",
        "PIL": "Pillow",
        "numpy": "numpy",
        "cv2": "opencv-python",
        "requests": "requests",
        "loguru": "loguru",
        "click": "click",
    }
    optional_api = {
        "anthropic": ("anthropic", "Claude Vision API"),
        "openai": ("openai", "ChatGPT / OpenAI TTS"),
        "google.genai": ("google-genai", "Gemini Vision API"),
        "tenacity": ("tenacity", "API 재시도 로직"),
        "pyttsx3": ("pyttsx3", "Windows TTS 음성 합성"),
    }
    sam_packages = {
        "torch": {"check": "torch", "label": "PyTorch (SAM 공통 엔진)"},
        "segment_anything": {"check": "segment_anything", "pip": "segment-anything",
                             "label": "segment-anything (SAM VIT-B/L/H)"},
        "mobile_sam": {"check": "mobile_sam",
                       "git": "git+https://github.com/ChaoningZhang/MobileSAM.git",
                       "label": "MobileSAM (경량 모바일 버전)"},
        "timm": {"check": "timm", "pip": "timm",
                 "label": "timm (SAM 의존 라이브러리)"},
    }
    audio_packages = {}
    if sys.version_info < (3, 14):
        audio_packages["pygame"] = ("pygame", "오디오 재생 엔진 (OpenAI TTS 재생용)")

    missing_required = []
    for module, package in required.items():
        if not _is_installed(module):
            missing_required.append(package)

    missing_api = {}
    for module, (package, desc) in optional_api.items():
        if not _is_installed(module):
            missing_api[module] = (package, desc)

    missing_sam = {}
    installed_sam = {}
    for name, info in sam_packages.items():
        if _is_installed(info["check"]):
            installed_sam[name] = info
        else:
            missing_sam[name] = info

    missing_audio = {}
    for module, (package, desc) in audio_packages.items():
        if not _is_installed(module):
            missing_audio[module] = (package, desc)

    torch_gpu_info = None
    if "torch" in installed_sam:
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_properties(0).name
                vram_gb = torch.cuda.get_device_properties(0).total_mem / (1024**3)
                torch_gpu_info = f"{gpu_name} ({vram_gb:.1f}GB VRAM)"
            else:
                torch_gpu_info = "CPU 전용 (CUDA 미지원)"
        except Exception:
            pass

    if not missing_required and not missing_api and not missing_sam and not missing_audio:
        print("[의존성 검사] 모든 패키지 설치 확인 완료 (OK)")
        sam_names = [info["label"] for info in installed_sam.values()]
        if sam_names:
            print(f"  SAM: {', '.join(sam_names)}")
        if torch_gpu_info:
            print(f"  GPU: {torch_gpu_info}")
        return

    from PySide6.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QScrollArea, QWidget, QCheckBox, QFrame,
    )
    from PySide6.QtCore import Qt

    app_created = False
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app_created = True

    dlg = QDialog()
    dlg.setWindowTitle("패키지 설치 관리자")
    dlg.setFixedSize(620, 560)
    dlg.setStyleSheet("""
        QDialog { background: #1e1e2e; }
        QLabel { color: #cdd6f4; }
        QCheckBox { color: #cdd6f4; spacing: 6px; }
        QCheckBox::indicator { width: 16px; height: 16px; }
        QCheckBox::indicator:unchecked { background: #313244; border: 1px solid #45475a; border-radius: 3px; }
        QCheckBox::indicator:checked { background: #89b4fa; border: 1px solid #89b4fa; border-radius: 3px; }
        QPushButton { border: none; border-radius: 4px; padding: 6px 12px; font-family: '맑은 고딕'; }
    """)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(15, 15, 15, 15)

    title_lbl = QLabel("패키지 설치 관리자")
    title_lbl.setStyleSheet("font-size: 14pt; font-weight: bold; font-family: '맑은 고딕';")
    title_lbl.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_lbl)

    sub_lbl = QLabel("설치할 패키지를 선택하세요. 필수 패키지는 자동 선택됩니다.")
    sub_lbl.setStyleSheet("font-size: 9pt; color: #a6adc8; font-family: '맑은 고딕';")
    sub_lbl.setAlignment(Qt.AlignCenter)
    layout.addWidget(sub_lbl)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e2e; }")
    scroll_widget = QWidget()
    scroll_layout = QVBoxLayout(scroll_widget)
    scroll_layout.setContentsMargins(0, 0, 0, 0)
    scroll.setWidget(scroll_widget)
    layout.addWidget(scroll, 1)

    check_vars: dict[str, QCheckBox] = {}

    def _add_section(title, color="#89b4fa"):
        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size: 10pt; font-weight: bold; color: {color}; font-family: '맑은 고딕'; margin-top: 8px;")
        scroll_layout.addWidget(lbl)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #45475a;")
        scroll_layout.addWidget(sep)

    def _add_check(key, text, desc, checked=True, disabled=False):
        cb = QCheckBox(f"  {text}  --  {desc}")
        cb.setStyleSheet("font-family: '맑은 고딕'; font-size: 9pt;")
        cb.setChecked(checked)
        if disabled:
            cb.setEnabled(False)
            cb.setChecked(True)
        scroll_layout.addWidget(cb)
        check_vars[key] = cb

    if missing_required:
        _add_section(f"필수 패키지 ({len(missing_required)}개 미설치)", color="#f38ba8")
        for pkg in missing_required:
            _add_check(f"req_{pkg}", pkg, "프로그램 실행에 필수", checked=True, disabled=True)

    if missing_api:
        _add_section(f"API 패키지 ({len(missing_api)}개 미설치)", color="#89b4fa")
        for module, (package, desc) in missing_api.items():
            _add_check(f"api_{module}", package, desc, checked=True)

    if missing_audio:
        _add_section(f"오디오 패키지 ({len(missing_audio)}개 미설치)", color="#cba6f7")
        for module, (package, desc) in missing_audio.items():
            _add_check(f"audio_{module}", package, desc, checked=False)

    if missing_sam:
        _add_section(f"SAM 그림자 추출 ({len(missing_sam)}개 미설치)", color="#fab387")
        note = QLabel("    * SAM 미설치 시 API/OpenCV 그림자만 사용 가능")
        note.setStyleSheet("font-size: 8pt; color: #a6adc8; font-family: '맑은 고딕';")
        scroll_layout.addWidget(note)
        for name, info in missing_sam.items():
            checked = name in ("timm",)
            _add_check(f"sam_{name}", info["label"], "SAM 그림자 추출", checked=checked)

    if installed_sam:
        _add_section("이미 설치된 SAM 패키지", color="#a6e3a1")
        for name, info in installed_sam.items():
            lbl = QLabel(f"  (OK) {info['label']}")
            lbl.setStyleSheet("font-size: 9pt; color: #a6e3a1; font-family: '맑은 고딕';")
            scroll_layout.addWidget(lbl)
        if torch_gpu_info:
            gpu_lbl = QLabel(f"  GPU: {torch_gpu_info}")
            gpu_lbl.setStyleSheet("font-size: 9pt; color: #89b4fa; font-family: '맑은 고딕';")
            scroll_layout.addWidget(gpu_lbl)

    scroll_layout.addStretch()

    sep_bottom = QFrame()
    sep_bottom.setFrameShape(QFrame.HLine)
    sep_bottom.setStyleSheet("color: #45475a;")
    layout.addWidget(sep_bottom)

    result = {"action": "skip"}

    btn_row = QHBoxLayout()

    btn_all = QPushButton("전체 선택")
    btn_all.setStyleSheet("background: #313244; color: #cdd6f4; font-size: 9pt;")
    btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb in check_vars.values() if cb.isEnabled()])
    btn_row.addWidget(btn_all)

    btn_none = QPushButton("선택 해제")
    btn_none.setStyleSheet("background: #313244; color: #cdd6f4; font-size: 9pt;")
    btn_none.clicked.connect(lambda: [cb.setChecked(False) for k, cb in check_vars.items() if cb.isEnabled() and not k.startswith("req_")])
    btn_row.addWidget(btn_none)

    btn_row.addStretch()

    btn_skip = QPushButton("건너뛰기")
    btn_skip.setStyleSheet("background: #45475a; color: #cdd6f4; font-size: 9pt;")
    def _on_skip():
        result["action"] = "skip"
        dlg.accept()
    btn_skip.clicked.connect(_on_skip)
    btn_row.addWidget(btn_skip)

    btn_install = QPushButton("  선택 항목 설치  ")
    btn_install.setStyleSheet("background: #89b4fa; color: #11111b; font-size: 10pt; font-weight: bold;")
    def _on_install():
        result["action"] = "install"
        dlg.accept()
    btn_install.clicked.connect(_on_install)
    btn_row.addWidget(btn_install)

    layout.addLayout(btn_row)

    dlg.exec()

    if result["action"] != "install":
        if missing_required:
            print("\n[경고] 필수 패키지가 없어 프로그램이 정상 동작하지 않을 수 있습니다.")
        print("[건너뜀] 패키지 설치를 건너뜁니다.\n")
        return

    print("\n" + "=" * 60)
    print("  선택된 패키지 설치 시작")
    print("=" * 60)

    def _is_checked(key, default=False):
        cb = check_vars.get(key)
        if cb is None:
            return default
        try:
            return cb.isChecked()
        except RuntimeError:
            return default

    if missing_required:
        install_req = [pkg for pkg in missing_required if _is_checked(f"req_{pkg}", True)]
        if install_req:
            print(f"\n[설치 중] 필수: {', '.join(install_req)}")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + install_req)
                print("[완료] 필수 패키지 설치 완료 (OK)")
            except subprocess.CalledProcessError as e:
                print(f"[오류] 필수 패키지 설치 실패: {e}")

    install_api = []
    for module, (package, desc) in missing_api.items():
        if _is_checked(f"api_{module}"):
            install_api.append(package)
    if install_api:
        print(f"\n[설치 중] API: {', '.join(install_api)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + install_api)
            print("[완료] API 패키지 설치 완료 (OK)")
        except subprocess.CalledProcessError as e:
            print(f"[오류] API 패키지 설치 실패: {e}")

    install_audio = []
    for module, (package, desc) in missing_audio.items():
        if _is_checked(f"audio_{module}"):
            install_audio.append(package)
    if install_audio:
        print(f"\n[설치 중] 오디오: {', '.join(install_audio)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + install_audio)
            print("[완료] 오디오 패키지 설치 완료 (OK)")
        except subprocess.CalledProcessError:
            print(f"[경고] 오디오 패키지 설치 실패 (Python {sys.version.split()[0]}에서 "
                  f"미지원 가능). TTS 오디오 재생이 비활성화됩니다.")

    if "torch" in missing_sam and _is_checked("sam_torch"):
        cuda_available, cuda_ver, whl_tag = _detect_cuda_version()
        if cuda_available and whl_tag:
            print(f"\n[설치 중] PyTorch (CUDA {cuda_ver} -> {whl_tag})")
            cmd = (f"{sys.executable} -m pip install torch torchvision "
                   f"--index-url https://download.pytorch.org/whl/{whl_tag}")
        else:
            print("\n[설치 중] PyTorch (CPU)")
            cmd = (f"{sys.executable} -m pip install torch torchvision "
                   f"--index-url https://download.pytorch.org/whl/cpu")
        try:
            subprocess.check_call(cmd, shell=True)
            print("[완료] PyTorch 설치 완료 (OK)")
        except subprocess.CalledProcessError as e:
            print(f"[오류] PyTorch 설치 실패: {e}")

    pip_sam = []
    for name in ("timm", "segment_anything"):
        if name in missing_sam and _is_checked(f"sam_{name}"):
            if "pip" in missing_sam[name]:
                pip_sam.append(missing_sam[name]["pip"])
    if pip_sam:
        print(f"\n[설치 중] SAM: {', '.join(pip_sam)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + pip_sam)
            print("[완료] SAM 패키지 설치 완료 (OK)")
        except subprocess.CalledProcessError as e:
            print(f"[오류] SAM 패키지 설치 실패: {e}")

    if "mobile_sam" in missing_sam and _is_checked("sam_mobile_sam"):
        print("\n[설치 중] MobileSAM (git)")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--quiet",
                missing_sam["mobile_sam"]["git"]
            ])
            print("[완료] MobileSAM 설치 완료 (OK)")
        except subprocess.CalledProcessError as e:
            print(f"[오류] MobileSAM 설치 실패: {e}")

    print("\n" + "=" * 60)
    print("  패키지 설치 완료 — 프로그램을 시작합니다")
    print("=" * 60 + "\n")
