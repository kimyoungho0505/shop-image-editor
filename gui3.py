"""쇼핑몰 이미지 자동 편집 도구 - Windows GUI."""
import os
import sys
import json
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False
from pathlib import Path
from datetime import datetime

APP_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP_DIR))


def _detect_cuda_version():
    """nvidia-smi에서 CUDA 버전을 감지하여 (available, version_str, whl_tag) 반환."""
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False, None, None
        import re as _re
        m = _re.search(r"CUDA Version:\s*(\d+)\.(\d+)", result.stdout)
        if not m:
            return True, "unknown", "cu118"
        major, minor = int(m.group(1)), int(m.group(2))
        ver_str = f"{major}.{minor}"
        # PyTorch 공식 whl 태그 매핑
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


def _check_and_install_deps():
    """필수/선택 패키지 누락 시 선택 설치 다이얼로그 표시."""
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
    # 오디오 재생 패키지 (OpenAI TTS용)
    # pygame은 Python 3.14+에서 빌드 불가 — 해당 버전에서는 os.startfile fallback 사용
    audio_packages = {}
    if sys.version_info < (3, 14):
        audio_packages["pygame"] = ("pygame", "오디오 재생 엔진 (OpenAI TTS 재생용)")

    # ── 1. 누락 패키지 수집 (경고 억제) ──
    import warnings as _warnings
    import importlib.util as _imp_util

    def _is_installed(module_name: str) -> bool:
        """모듈 설치 여부만 확인 (import 실행 없이)."""
        # 1차: importlib.util.find_spec (가장 가벼움)
        try:
            top = module_name.split(".")[0]
            if _imp_util.find_spec(top) is not None:
                return True
        except (ModuleNotFoundError, ValueError):
            pass
        # 2차: 경고 억제 후 __import__ (find_spec 실패 시 폴백)
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            try:
                __import__(module_name)
                return True
            except ImportError:
                return False

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

    # PyTorch GPU 상태 확인
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

    # ── 2. 누락 없으면 바로 리턴 ──
    if not missing_required and not missing_api and not missing_sam and not missing_audio:
        print("[의존성 검사] 모든 패키지 설치 확인 완료 (OK)")
        sam_names = [info["label"] for info in installed_sam.values()]
        if sam_names:
            print(f"  SAM: {', '.join(sam_names)}")
        if torch_gpu_info:
            print(f"  GPU: {torch_gpu_info}")
        return

    # ── 3. 선택 설치 다이얼로그 (tkinter) ──
    import tkinter as _tk
    from tkinter import ttk as _ttk

    dlg = _tk.Tk()
    dlg.title("패키지 설치 관리자")
    dlg.geometry("620x560")
    dlg.resizable(False, False)
    try:
        dlg.iconbitmap(default="")
    except Exception:
        pass

    # 스타일
    bg = "#1e1e2e"
    fg = "#cdd6f4"
    accent = "#89b4fa"
    success = "#a6e3a1"
    warn = "#fab387"
    danger = "#f38ba8"
    dlg.configure(bg=bg)

    _tk.Label(dlg, text="📦 패키지 설치 관리자", font=("맑은 고딕", 14, "bold"),
              bg=bg, fg=fg).pack(pady=(15, 5))
    _tk.Label(dlg, text="설치할 패키지를 선택하세요. 필수 패키지는 자동 선택됩니다.",
              font=("맑은 고딕", 9), bg=bg, fg="#a6adc8").pack(pady=(0, 10))

    # ── 하단 버튼 (먼저 pack — 항상 보이도록) ──
    result = {"action": "skip"}

    def _on_install():
        result["action"] = "install"
        dlg.destroy()

    def _on_skip():
        result["action"] = "skip"
        dlg.destroy()

    btn_f = _tk.Frame(dlg, bg=bg)
    btn_f.pack(side="bottom", fill="x", pady=(5, 15), padx=15)

    _tk.Button(btn_f, text="전체 선택", command=lambda: [v.set(True) for v in check_vars.values()],
               bg="#313244", fg=fg, font=("맑은 고딕", 9),
               relief="flat", padx=10, pady=4).pack(side="left", padx=(0, 5))
    _tk.Button(btn_f, text="선택 해제", command=lambda: [v.set(False) for k, v in check_vars.items() if not k.startswith("req_")],
               bg="#313244", fg=fg, font=("맑은 고딕", 9),
               relief="flat", padx=10, pady=4).pack(side="left", padx=(0, 5))

    _tk.Button(btn_f, text="  선택 항목 설치  ", command=_on_install,
               bg="#89b4fa", fg="#11111b", font=("맑은 고딕", 10, "bold"),
               relief="flat", padx=15, pady=6).pack(side="right", padx=(5, 0))
    _tk.Button(btn_f, text="건너뛰기", command=_on_skip,
               bg="#45475a", fg=fg, font=("맑은 고딕", 9),
               relief="flat", padx=10, pady=4).pack(side="right", padx=(0, 5))

    # 구분선
    _tk.Frame(dlg, height=1, bg="#45475a").pack(side="bottom", fill="x", padx=15)

    # 스크롤 프레임 (버튼 위 나머지 공간)
    list_f = _tk.Frame(dlg, bg=bg)
    list_f.pack(side="top", fill="both", expand=True, padx=15, pady=5)
    canvas = _tk.Canvas(list_f, bg=bg, highlightthickness=0)
    scrollbar = _tk.Scrollbar(list_f, orient="vertical", command=canvas.yview)
    scroll_frame = _tk.Frame(canvas, bg=bg)
    scroll_frame.bind("<Configure>",
                      lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=560)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    # 마우스 휠 스크롤
    canvas.bind_all("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

    check_vars = {}  # key → (BooleanVar, install_info)

    def _add_section(parent, title, color=accent):
        f = _tk.Frame(parent, bg=bg)
        f.pack(fill="x", pady=(8, 2))
        _tk.Label(f, text=title, font=("맑은 고딕", 10, "bold"),
                  bg=bg, fg=color).pack(anchor="w")
        sep = _tk.Frame(f, height=1, bg="#45475a")
        sep.pack(fill="x", pady=(2, 0))
        return f

    def _add_check(parent, key, text, desc, checked=True, disabled=False):
        var = _tk.BooleanVar(value=checked)
        f = _tk.Frame(parent, bg=bg)
        f.pack(fill="x", padx=(15, 0), pady=1)
        cb = _tk.Checkbutton(f, variable=var, bg=bg, fg=fg,
                              selectcolor="#313244", activebackground=bg,
                              activeforeground=fg, highlightthickness=0)
        if disabled:
            cb.config(state="disabled")
            var.set(True)
        cb.pack(side="left")
        _tk.Label(f, text=text, font=("맑은 고딕", 9, "bold"),
                  bg=bg, fg=fg).pack(side="left")
        _tk.Label(f, text=f"  — {desc}", font=("맑은 고딕", 8),
                  bg=bg, fg="#a6adc8").pack(side="left")
        check_vars[key] = var
        return var

    # ── 필수 패키지 ──
    if missing_required:
        _add_section(scroll_frame, f"🔴 필수 패키지 ({len(missing_required)}개 미설치)",
                     color=danger)
        for pkg in missing_required:
            _add_check(scroll_frame, f"req_{pkg}", pkg,
                       "프로그램 실행에 필수", checked=True, disabled=True)

    # ── API 패키지 ──
    if missing_api:
        _add_section(scroll_frame, f"🔵 API 패키지 ({len(missing_api)}개 미설치)",
                     color=accent)
        for module, (package, desc) in missing_api.items():
            _add_check(scroll_frame, f"api_{module}", package, desc, checked=True)

    # ── 오디오 패키지 ──
    if missing_audio:
        _add_section(scroll_frame, f"🎵 오디오 패키지 ({len(missing_audio)}개 미설치)",
                     color="#cba6f7")
        for module, (package, desc) in missing_audio.items():
            _add_check(scroll_frame, f"audio_{module}", package, desc, checked=False)

    # ── SAM 패키지 ──
    if missing_sam:
        _add_section(scroll_frame, f"🟠 SAM 그림자 추출 ({len(missing_sam)}개 미설치)",
                     color=warn)
        _tk.Label(scroll_frame, text="    ※ SAM 미설치 시 API/OpenCV 그림자만 사용 가능",
                  font=("맑은 고딕", 8), bg=bg, fg="#a6adc8").pack(anchor="w", padx=15)
        for name, info in missing_sam.items():
            checked = name in ("timm",)  # timm은 기본 체크
            _add_check(scroll_frame, f"sam_{name}", info["label"],
                       "SAM 그림자 추출", checked=checked)

    # ── 설치됨 표시 ──
    if installed_sam:
        _add_section(scroll_frame, "✅ 이미 설치된 SAM 패키지", color=success)
        for name, info in installed_sam.items():
            f = _tk.Frame(scroll_frame, bg=bg)
            f.pack(fill="x", padx=(15, 0), pady=1)
            _tk.Label(f, text=f"  (OK) {info['label']}", font=("맑은 고딕", 9),
                      bg=bg, fg=success).pack(side="left")
        if torch_gpu_info:
            f = _tk.Frame(scroll_frame, bg=bg)
            f.pack(fill="x", padx=(15, 0), pady=1)
            _tk.Label(f, text=f"  🖥 GPU: {torch_gpu_info}",
                      font=("맑은 고딕", 9), bg=bg, fg=accent).pack(side="left")

    # 다이얼로그 중앙 배치
    dlg.update_idletasks()
    x = (dlg.winfo_screenwidth() - 620) // 2
    y = (dlg.winfo_screenheight() - 560) // 2
    dlg.geometry(f"+{x}+{y}")

    dlg.mainloop()

    # ── 4. 설치 실행 ──
    if result["action"] != "install":
        if missing_required:
            print("\n[경고] 필수 패키지가 없어 프로그램이 정상 동작하지 않을 수 있습니다.")
        print("[건너뜀] 패키지 설치를 건너뜁니다.\n")
        return

    print("\n" + "=" * 60)
    print("  선택된 패키지 설치 시작")
    print("=" * 60)

    # 다이얼로그 종료 후 check_vars에서 값을 꺼내는 헬퍼
    # (dlg.destroy() 이후 tkinter 루트가 없으므로 BooleanVar 생성 불가)
    def _is_checked(key, default=False):
        var = check_vars.get(key)
        if var is None:
            return default
        try:
            return var.get()
        except Exception:
            return default

    # 필수 패키지
    if missing_required:
        install_req = [pkg for pkg in missing_required
                       if _is_checked(f"req_{pkg}", True)]
        if install_req:
            print(f"\n[설치 중] 필수: {', '.join(install_req)}")
            try:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", "--quiet"
                ] + install_req)
                print("[완료] 필수 패키지 설치 완료 (OK)")
            except subprocess.CalledProcessError as e:
                print(f"[오류] 필수 패키지 설치 실패: {e}")

    # API 패키지
    install_api = []
    for module, (package, desc) in missing_api.items():
        if _is_checked(f"api_{module}"):
            install_api.append(package)
    if install_api:
        print(f"\n[설치 중] API: {', '.join(install_api)}")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--quiet"
            ] + install_api)
            print("[완료] API 패키지 설치 완료 (OK)")
        except subprocess.CalledProcessError as e:
            print(f"[오류] API 패키지 설치 실패: {e}")

    # 오디오 패키지
    install_audio = []
    for module, (package, desc) in missing_audio.items():
        if _is_checked(f"audio_{module}"):
            install_audio.append(package)
    if install_audio:
        print(f"\n[설치 중] 오디오: {', '.join(install_audio)}")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--quiet"
            ] + install_audio)
            print("[완료] 오디오 패키지 설치 완료 (OK)")
        except subprocess.CalledProcessError:
            print(f"[경고] 오디오 패키지 설치 실패 (Python {sys.version.split()[0]}에서 "
                  f"미지원 가능). TTS 오디오 재생이 비활성화됩니다.")

    # PyTorch
    if "torch" in missing_sam and _is_checked("sam_torch"):
        cuda_available, cuda_ver, whl_tag = _detect_cuda_version()
        if cuda_available and whl_tag:
            print(f"\n[설치 중] PyTorch (CUDA {cuda_ver} → {whl_tag})")
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

    # pip SAM 패키지 (timm, segment-anything)
    pip_sam = []
    for name in ("timm", "segment_anything"):
        if name in missing_sam and _is_checked(f"sam_{name}"):
            if "pip" in missing_sam[name]:
                pip_sam.append(missing_sam[name]["pip"])
    if pip_sam:
        print(f"\n[설치 중] SAM: {', '.join(pip_sam)}")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--quiet"
            ] + pip_sam)
            print("[완료] SAM 패키지 설치 완료 (OK)")
        except subprocess.CalledProcessError as e:
            print(f"[오류] SAM 패키지 설치 실패: {e}")

    # MobileSAM (git)
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


_check_and_install_deps()

from dotenv import load_dotenv, set_key
load_dotenv(str(APP_DIR / ".env"))

import yaml

CONFIG_DIR = APP_DIR / "config"
PROMPTS_PATH = CONFIG_DIR / "prompts.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
CATEGORIES_PATH = CONFIG_DIR / "categories.yaml"
SHADOW_HINTS_PATH = CONFIG_DIR / "shadow_hints.yaml"
ENV_PATH = APP_DIR / ".env"
GUI_STATE_PATH = APP_DIR / "gui_state.json"

WINDOW_TITLE = "LUXBOY 이미지 자동 편집 도구"
WINDOW_SIZE = "1100x850"
BG_COLOR = "#f5f5f5"
ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
DANGER = "#dc2626"
SUCCESS = "#16a34a"
CARD_BG = "#ffffff"
FONT_FAMILY = "맑은 고딕"


class ToolTip:
    """위젯에 마우스를 올리면 툴팁을 표시."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event=None):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 2
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tip, text=self.text, background="#fffde7",
                         foreground="#333", font=(FONT_FAMILY, 9),
                         relief="solid", borderwidth=1, wraplength=350,
                         justify="left", padx=6, pady=4)
        label.pack()

    def _hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def load_yaml(path):
    with open(str(path), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path, data):
    with open(str(path), "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


class App(TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LUXBOY 메인 - gui3")
        self.geometry("1100x850")
        self.configure(bg=BG_COLOR)
        self.minsize(900, 700)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

        self._processing = False
        self._viewfinder_pairs = []
        self._vf_file_stages = {}
        self._vf_dlg = None
        self._unified_processing = False
        self._load_state()
        self._build_ui()
        self._load_configs()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _restart_app(self):
        self._save_state()
        self.destroy()
        import subprocess as _sp
        _sp.Popen([sys.executable, __file__])

    def _load_state(self):
        self._state = {}
        if GUI_STATE_PATH.exists():
            try:
                with open(str(GUI_STATE_PATH), "r", encoding="utf-8") as f:
                    self._state = json.load(f)
            except Exception:
                pass

    def _save_state(self):
        try:
            with open(str(GUI_STATE_PATH), "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self._save_state()
        self.destroy()

    # 안 UI 빌드 ――
    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG_COLOR)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("TLabel", background=BG_COLOR, font=(FONT_FAMILY, 10))
        style.configure("Card.TLabel", background=CARD_BG, font=(FONT_FAMILY, 10))
        style.configure("Header.TLabel", background=BG_COLOR, font=(FONT_FAMILY, 14, "bold"))
        style.configure("Section.TLabel", background=CARD_BG, font=(FONT_FAMILY, 11, "bold"))
        style.configure("TButton", font=(FONT_FAMILY, 10))
        style.configure("Accent.TButton", font=(FONT_FAMILY, 11, "bold"),
                        foreground="white", background=ACCENT)
        style.map("Accent.TButton",
                  background=[("active", ACCENT_HOVER), ("disabled", "#94a3b8")])
        style.configure("Restart.TButton", font=(FONT_FAMILY, 10),
                        foreground="white", background="#16a34a")
        style.map("Restart.TButton",
                  background=[("active", "#15803d"), ("disabled", "#94a3b8")])
        style.configure("Viewfinder.TButton", font=(FONT_FAMILY, 10, "bold"),
                        foreground="white", background="#7c3aed")
        style.map("Viewfinder.TButton",
                  background=[("active", "#6d28d9"), ("disabled", "#94a3b8")])
        style.configure("TCheckbutton", background=CARD_BG, font=(FONT_FAMILY, 10))
        style.configure("TCombobox", font=(FONT_FAMILY, 10))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        # 프로바이더 변수 (설정탭에서 공유)
        self.var_vision_provider = tk.StringVar(value="claude")
        self.var_bg_provider = tk.StringVar(value="photoroom")
        self.var_enhance_provider = tk.StringVar(value="claid")

        self.tab_temp_options = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_temp_options, text="  메인  ")
        self._build_temp_options_tab()

        self.tab_conditions = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_conditions, text="  조건  ")
        self._build_conditions_tab()

        self.tab_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_settings, text="  설정  ")
        self._build_settings_tab()

        bottom_bar = tk.Frame(self, bg=BG_COLOR)
        bottom_bar.pack(fill="x", padx=10, pady=(5, 10))
        self.status_bar = ttk.Label(bottom_bar, text="준비 완료", relief="sunken", anchor="w",
                                    font=(FONT_FAMILY, 9))
        self.status_bar.pack(side="left", fill="x", expand=True)
        ttk.Button(bottom_bar, text="🔄 재시작", width=8,
                   command=self._restart_app).pack(side="right", padx=(6, 0))

    # ── 조건 탭 ──
    # ── 조건 탭 ──
    def _build_conditions_tab(self):
        parent = self.tab_conditions

        # 상단 툴바
        toolbar = tk.Frame(parent, bg=BG_COLOR)
        toolbar.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Button(toolbar, text="+ 조건 추가",
                   command=self._add_routing_rule).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="저장", style="Accent.TButton",
                   command=self._save_routing_rules).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="기본값 복원",
                   command=self._reset_routing_rules).pack(side="left", padx=(0, 6))
        self.cond_status = ttk.Label(toolbar, text="", font=(FONT_FAMILY, 9))
        self.cond_status.pack(side="left", padx=8)

        # 설명
        tk.Label(parent,
                 text="조건은 위에서부터 순서대로 평가되며, 처음 일치하는 규칙이 적용됩니다. 조건을 비워두면 나머지 모든 이미지에 적용됩니다.",
                 bg=BG_COLOR, fg="#6b7280", font=(FONT_FAMILY, 9), justify="left"
                 ).pack(fill="x", padx=14, pady=(0, 6))

        # 스크롤 영역
        outer = tk.Frame(parent, bg=BG_COLOR)
        outer.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        canvas = tk.Canvas(outer, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self._cond_inner = tk.Frame(canvas, bg=BG_COLOR)
        self._cond_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._cond_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>",
            lambda ev: canvas.yview_scroll(int(-1*(ev.delta/120)), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._cond_canvas = canvas

        # 규칙 로드 후 렌더링
        self._routing_rules_data = self._load_routing_rules()
        self._render_routing_rules()

    def _load_routing_rules(self):
        """config/routing_rules.yaml 로드. 없으면 기본값 반환."""
        import yaml as _yaml
        rules_path = CONFIG_DIR / "routing_rules.yaml"
        if rules_path.exists():
            try:
                with open(rules_path, encoding="utf-8") as f:
                    data = _yaml.safe_load(f)
                    return data.get("rules", self._default_routing_rules())
            except Exception:
                pass
        return self._default_routing_rules()

    def _default_routing_rules(self):
        return [
            {"id": "label_skip",       "name": "라벨/바코드컷",
             "conditions": {"is_label_cut": True},
             "processing": {"nukki": False, "shadow": False, "enhance": False}},
            {"id": "top_down_only",    "name": "수직촬영(탑다운)",
             "conditions": {"shooting_angle": "top_down"},
             "processing": {"nukki": False, "shadow": False, "enhance": True}},
            {"id": "detail_clean_bg",  "name": "디테일컷 (흰/깨끗한 배경)",
             "conditions": {"image_type": "detail", "background_type": "clean"},
             "processing": {"nukki": True, "shadow": False, "enhance": True}},
            {"id": "detail_colored_bg","name": "디테일컷 (유색 배경)",
             "conditions": {"image_type": "detail", "background_type": "colored"},
             "processing": {"nukki": False, "shadow": False, "enhance": True}},
            {"id": "full_shot",        "name": "전체컷 (기본)",
             "conditions": {},
             "processing": {"nukki": True, "shadow": True, "enhance": True}},
        ]

    def _save_routing_rules(self):
        """현재 UI 상태를 routing_rules.yaml에 저장."""
        import yaml as _yaml
        rules = self._collect_routing_rules_from_ui()
        self._routing_rules_data = rules
        rules_path = CONFIG_DIR / "routing_rules.yaml"
        try:
            with open(rules_path, "w", encoding="utf-8") as f:
                _yaml.dump({"rules": rules}, f, allow_unicode=True, default_flow_style=False)
            self.cond_status.config(text="✓ 저장됨", foreground="#16a34a")
            self.after(2000, lambda: self.cond_status.config(text=""))
        except Exception as e:
            self.cond_status.config(text=f"저장 실패: {e}", foreground="red")

    def _reset_routing_rules(self):
        self._routing_rules_data = self._default_routing_rules()
        self._render_routing_rules()
        self.cond_status.config(text="기본값 복원됨", foreground="#6b7280")
        self.after(2000, lambda: self.cond_status.config(text=""))

    def _add_routing_rule(self):
        rules = self._collect_routing_rules_from_ui()
        rules.append({
            "id": f"rule_{len(rules)+1}",
            "name": "새 조건",
            "conditions": {},
            "processing": {"nukki": True, "shadow": False, "enhance": True}
        })
        self._routing_rules_data = rules
        self._render_routing_rules()
        # 스크롤 맨 아래로
        self._cond_canvas.after(50, lambda: self._cond_canvas.yview_moveto(1.0))

    def _collect_routing_rules_from_ui(self):
        """현재 카드 UI에서 규칙 데이터 수집."""
        rules = []
        for card_data in self._cond_cards:
            rule = {"id": card_data["id"]}
            rule["name"] = card_data["var_name"].get().strip() or "규칙"
            cond = {}
            lc = card_data["var_is_label_cut"].get()
            if lc == "예":   cond["is_label_cut"] = True
            elif lc == "아니오": cond["is_label_cut"] = False
            sa = card_data["var_shooting_angle"].get()
            if sa != "any":  cond["shooting_angle"] = sa
            it = card_data["var_image_type"].get()
            if it != "any":  cond["image_type"] = it
            bt = card_data["var_background_type"].get()
            if bt != "any":  cond["background_type"] = bt
            rule["conditions"] = cond
            rule["processing"] = {
                "nukki":   card_data["var_nukki"].get(),
                "shadow":  card_data["var_shadow"].get(),
                "enhance": card_data["var_enhance"].get(),
            }
            rules.append(rule)
        return rules

    def _render_routing_rules(self):
        """_cond_inner 프레임을 지우고 현재 _routing_rules_data로 카드 재렌더링."""
        for w in self._cond_inner.winfo_children():
            w.destroy()
        self._cond_cards = []

        COLORS = ["#3b82f6","#7c3aed","#16a34a","#d97706","#6b7280",
                  "#ef4444","#0891b2","#db2777","#ca8a04","#059669"]

        for idx, rule in enumerate(self._routing_rules_data):
            color = COLORS[idx % len(COLORS)]
            card = tk.Frame(self._cond_inner, bg=CARD_BG, relief="solid", bd=1)
            card.pack(fill="x", padx=4, pady=(0, 8))

            # 상단 컬러 바 + 헤더 행
            tk.Frame(card, bg=color, height=3).pack(fill="x")
            header = tk.Frame(card, bg=CARD_BG, padx=10, pady=6)
            header.pack(fill="x")

            tk.Label(header, text=f"우선순위 {idx+1}", bg=CARD_BG, fg=color,
                     font=(FONT_FAMILY, 8, "bold"), width=8, anchor="w").pack(side="left")
            tk.Label(header, text="이름:", bg=CARD_BG, fg="#374151",
                     font=(FONT_FAMILY, 9)).pack(side="left", padx=(4, 2))
            var_name = tk.StringVar(value=rule.get("name", "규칙"))
            ttk.Entry(header, textvariable=var_name, width=22,
                      font=(FONT_FAMILY, 9)).pack(side="left")

            # ↑ ↓ 삭제 버튼
            def _make_move(i, d): return lambda: self._move_routing_rule(i, d)
            def _make_del(i):     return lambda: self._delete_routing_rule(i)
            ttk.Button(header, text="↑", width=2,
                       command=_make_move(idx, -1)).pack(side="right", padx=(2,0))
            ttk.Button(header, text="↓", width=2,
                       command=_make_move(idx, 1)).pack(side="right", padx=(2,0))
            ttk.Button(header, text="✕", width=2,
                       command=_make_del(idx)).pack(side="right", padx=(8,0))

            body = tk.Frame(card, bg=CARD_BG, padx=12, pady=4)
            body.pack(fill="x")

            # ── 조건 행 ──
            cond_lf = tk.LabelFrame(body, text=" 조건 (모두 일치해야 함) ",
                                    bg=CARD_BG, fg="#6b7280",
                                    font=(FONT_FAMILY, 8, "bold"), padx=8, pady=4)
            cond_lf.pack(fill="x", pady=(0, 6))
            cond_row = tk.Frame(cond_lf, bg=CARD_BG)
            cond_row.pack(fill="x")

            conds = rule.get("conditions", {})

            # is_label_cut
            var_lc = tk.StringVar()
            if conds.get("is_label_cut") is True: var_lc.set("예")
            elif conds.get("is_label_cut") is False: var_lc.set("아니오")
            else: var_lc.set("any")
            tk.Label(cond_row, text="라벨컷:", bg=CARD_BG, fg="#374151",
                     font=(FONT_FAMILY, 9)).grid(row=0, column=0, sticky="w", padx=(0,4), pady=2)
            ttk.Combobox(cond_row, textvariable=var_lc,
                         values=["any", "예", "아니오"],
                         width=7, state="readonly", font=(FONT_FAMILY, 9)
                         ).grid(row=0, column=1, sticky="w", padx=(0,16), pady=2)

            # shooting_angle
            var_sa = tk.StringVar(value=conds.get("shooting_angle", "any"))
            tk.Label(cond_row, text="촬영각도:", bg=CARD_BG, fg="#374151",
                     font=(FONT_FAMILY, 9)).grid(row=0, column=2, sticky="w", padx=(0,4), pady=2)
            ttk.Combobox(cond_row, textvariable=var_sa,
                         values=["any", "top_down", "front", "side"],
                         width=9, state="readonly", font=(FONT_FAMILY, 9)
                         ).grid(row=0, column=3, sticky="w", padx=(0,16), pady=2)

            # image_type
            var_it = tk.StringVar(value=conds.get("image_type", "any"))
            tk.Label(cond_row, text="이미지종류:", bg=CARD_BG, fg="#374151",
                     font=(FONT_FAMILY, 9)).grid(row=1, column=0, sticky="w", padx=(0,4), pady=2)
            ttk.Combobox(cond_row, textvariable=var_it,
                         values=["any", "full", "detail", "worn", "package"],
                         width=7, state="readonly", font=(FONT_FAMILY, 9)
                         ).grid(row=1, column=1, sticky="w", padx=(0,16), pady=2)

            # background_type
            var_bt = tk.StringVar(value=conds.get("background_type", "any"))
            tk.Label(cond_row, text="배경:", bg=CARD_BG, fg="#374151",
                     font=(FONT_FAMILY, 9)).grid(row=1, column=2, sticky="w", padx=(0,4), pady=2)
            ttk.Combobox(cond_row, textvariable=var_bt,
                         values=["any", "clean", "colored"],
                         width=9, state="readonly", font=(FONT_FAMILY, 9)
                         ).grid(row=1, column=3, sticky="w", padx=(0,16), pady=2)

            # ── 처리 행 ──
            proc_lf = tk.LabelFrame(body, text=" 처리 ",
                                    bg=CARD_BG, fg="#6b7280",
                                    font=(FONT_FAMILY, 8, "bold"), padx=8, pady=4)
            proc_lf.pack(fill="x", pady=(0, 4))
            proc_row = tk.Frame(proc_lf, bg=CARD_BG)
            proc_row.pack(anchor="w")

            proc = rule.get("processing", {})
            var_nukki  = tk.BooleanVar(value=proc.get("nukki",   True))
            var_shadow = tk.BooleanVar(value=proc.get("shadow",  False))
            var_enhance= tk.BooleanVar(value=proc.get("enhance", True))

            for col, (txt, var) in enumerate([
                ("누끼 (배경제거)", var_nukki),
                ("그림자",          var_shadow),
                ("보정 (Claid)",    var_enhance),
            ]):
                cb = ttk.Checkbutton(proc_row, text=txt, variable=var)
                cb.grid(row=0, column=col, padx=(0, 20), pady=2, sticky="w")

            # 카드 데이터 저장
            self._cond_cards.append({
                "id": rule.get("id", f"rule_{idx}"),
                "var_name": var_name,
                "var_is_label_cut": var_lc,
                "var_shooting_angle": var_sa,
                "var_image_type": var_it,
                "var_background_type": var_bt,
                "var_nukki": var_nukki,
                "var_shadow": var_shadow,
                "var_enhance": var_enhance,
            })

        self._cond_inner.update_idletasks()
        self._cond_canvas.configure(scrollregion=self._cond_canvas.bbox("all"))

    def _move_routing_rule(self, idx, direction):
        rules = self._collect_routing_rules_from_ui()
        new_idx = idx + direction
        if 0 <= new_idx < len(rules):
            rules[idx], rules[new_idx] = rules[new_idx], rules[idx]
        self._routing_rules_data = rules
        self._render_routing_rules()

    def _delete_routing_rule(self, idx):
        rules = self._collect_routing_rules_from_ui()
        if len(rules) > 1:
            rules.pop(idx)
        self._routing_rules_data = rules
        self._render_routing_rules()

    def _build_settings_tab(self):
        parent = self.tab_settings
        canvas = tk.Canvas(parent, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y", pady=10)
        # 마우스 휠 — 설정 탭 위에서만 동작
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._settings_canvas = canvas

        sf = scroll_frame

        # ══════════════════════════════════════
        #  1. API 키 관리
        # ══════════════════════════════════════
        api_lf = tk.LabelFrame(sf, text=" API 키 및 모델 ", font=(FONT_FAMILY, 11, "bold"),
                               bg=CARD_BG, fg="#374151", padx=10, pady=6)
        api_lf.pack(fill="x", pady=(0, 8))

        # API 키 데이터 정의
        api_keys = [
            ("Anthropic (Claude)", "ANTHROPIC_API_KEY", "var_api_key", "entry_api_key",
             "var_show_key", "_toggle_key_visibility", "_save_api_key"),
            ("Photoroom", "PHOTOROOM_API_KEY", "var_photoroom_key", "entry_photoroom_key",
             "var_show_photoroom_key", "_toggle_photoroom_key_visibility", "_save_photoroom_key"),
            ("Claid.ai", "CLAID_API_KEY", "var_claid_key", "entry_claid_key",
             "var_show_claid_key", "_toggle_claid_key_visibility", "_save_claid_key"),
            ("remove.bg", "REMOVEBG_API_KEY", "var_removebg_key", "entry_removebg_key",
             "var_show_removebg_key", "_toggle_removebg_key_visibility", "_save_removebg_key"),
            ("OpenAI", "OPENAI_API_KEY", "var_openai_key", "entry_openai_key",
             "var_show_openai_key", "_toggle_openai_key_visibility", "_save_openai_key"),
            ("Gemini", "GEMINI_API_KEY", "var_gemini_key", "entry_gemini_key",
             "var_show_gemini_key", "_toggle_gemini_key_visibility", "_save_gemini_key"),
            ("xAI (Grok)", "XAI_API_KEY", "var_xai_key", "entry_xai_key",
             "var_show_xai_key", "_toggle_xai_key_visibility", "_save_xai_key"),
        ]

        for r, (label, env_key, var_name, entry_name, show_var_name, toggle_cmd, save_cmd) in enumerate(api_keys):
            ttk.Label(api_lf, text=f"{label}:", style="Card.TLabel",
                      font=(FONT_FAMILY, 9)).grid(row=r, column=0, sticky="w", padx=(2, 8), pady=3)
            var = tk.StringVar(value=os.environ.get(env_key, ""))
            setattr(self, var_name, var)
            entry = ttk.Entry(api_lf, textvariable=var, show="*", width=55, font=(FONT_FAMILY, 9))
            entry.grid(row=r, column=1, padx=0, pady=3, sticky="ew")
            setattr(self, entry_name, entry)
            show_var = tk.BooleanVar(value=False)
            setattr(self, show_var_name, show_var)
            ttk.Checkbutton(api_lf, text="표시", variable=show_var,
                            command=getattr(self, toggle_cmd)).grid(row=r, column=2, padx=4)
            ttk.Button(api_lf, text="저장", width=4,
                       command=getattr(self, save_cmd)).grid(row=r, column=3, padx=(2, 0), pady=3)
            if env_key == "PHOTOROOM_API_KEY":
                self.lbl_photoroom_credits = ttk.Label(
                    api_lf, text="", style="Card.TLabel", font=(FONT_FAMILY, 9))
                self.lbl_photoroom_credits.grid(row=r, column=5, padx=(4, 0), pady=3, sticky="w")
                ttk.Button(api_lf, text="크레딧 확인", width=9,
                           command=self._check_photoroom_credits).grid(
                    row=r, column=4, padx=(4, 0), pady=3)

        api_lf.columnconfigure(1, weight=1)

        # 모델 선택 행
        model_f = ttk.Frame(api_lf, style="Card.TFrame")
        model_f.grid(row=len(api_keys), column=0, columnspan=4, sticky="ew", pady=(6, 2))

        ttk.Label(model_f, text="Claude:", style="Card.TLabel",
                  font=(FONT_FAMILY, 9)).pack(side="left", padx=(2, 4))
        self.var_model = tk.StringVar(value="claude-sonnet-4-20250514")
        ttk.Combobox(model_f, textvariable=self.var_model, width=28,
            values=["claude-opus-4-20250514", "claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
            font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 12))

        ttk.Label(model_f, text="OpenAI:", style="Card.TLabel",
                  font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 4))
        self.var_openai_model = tk.StringVar(value="gpt-4o")
        ttk.Combobox(model_f, textvariable=self.var_openai_model, width=14,
            values=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 12))

        ttk.Label(model_f, text="Gemini:", style="Card.TLabel",
                  font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 4))
        self.var_gemini_model = tk.StringVar(value="gemini-2.5-flash")
        ttk.Combobox(model_f, textvariable=self.var_gemini_model, width=18,
            values=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"],
            font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 12))

        ttk.Label(model_f, text="Grok:", style="Card.TLabel",
                  font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 4))
        self.var_grok_model = tk.StringVar(value="grok-4-fast-non-reasoning")
        ttk.Combobox(model_f, textvariable=self.var_grok_model, width=24,
            values=["grok-4-fast-non-reasoning", "grok-4-fast-reasoning", "grok-4-0709"],
            font=(FONT_FAMILY, 9)).pack(side="left")

        ttk.Button(model_f, text="모델 저장", width=8,
                   command=self._save_model_settings).pack(side="left", padx=(12, 0))

        # ══════════════════════════════════════
        #  3. 출력 이미지 설정
        # ══════════════════════════════════════
        out_lf = tk.LabelFrame(sf, text=" 출력 이미지 ", font=(FONT_FAMILY, 11, "bold"),
                               bg=CARD_BG, fg="#374151", padx=10, pady=6)
        out_lf.pack(fill="x", pady=(0, 8))

        out_grid = ttk.Frame(out_lf, style="Card.TFrame")
        out_grid.pack(fill="x")
        labels = [
            ("가로 (px):", "var_out_w", "860"),
            ("세로 (px):", "var_out_h", "860"),
            ("최대 용량 (KB):", "var_max_kb", "2024"),
            ("JPEG 품질:", "var_jpeg_q", "95"),
        ]
        for i, (label, var_name, default) in enumerate(labels):
            ttk.Label(out_grid, text=label, style="Card.TLabel").grid(
                row=0, column=i*2, sticky="w", padx=(2 if i==0 else 12, 4), pady=4)
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            ttk.Entry(out_grid, textvariable=var, width=7, font=(FONT_FAMILY, 10)).grid(
                row=0, column=i*2+1, sticky="w", padx=0, pady=4)

        ttk.Button(out_lf, text="설정 저장", command=self._save_settings,
                   style="Accent.TButton").pack(anchor="w", padx=2, pady=(6, 2))

        # ══════════════════════════════════════
        #  4. Photoroom API 옵션
        # ══════════════════════════════════════
        pr_lf = tk.LabelFrame(sf, text=" Photoroom API 옵션 ", font=(FONT_FAMILY, 11, "bold"),
                              bg=CARD_BG, fg="#374151", padx=10, pady=6)
        pr_lf.pack(fill="x", pady=(0, 8))

        self.var_photoroom_mode = tk.StringVar(value="manual")
        pr_mode_f = ttk.Frame(pr_lf, style="Card.TFrame")
        pr_mode_f.pack(fill="x", pady=(0, 4))
        rb1 = ttk.Radiobutton(pr_mode_f, text="수동 설정", variable=self.var_photoroom_mode, value="manual")
        rb1.pack(side="left", padx=(2, 8))
        ToolTip(rb1, "아래 입력값을 그대로 사용합니다")
        rb2 = ttk.Radiobutton(pr_mode_f, text="AI 자동", variable=self.var_photoroom_mode, value="ai_auto")
        rb2.pack(side="left")
        ToolTip(rb2, "Vision API가 최적 값을 자동 설정. 아래 값은 AI 실패 시 기본값")

        pr_f = ttk.Frame(pr_lf, style="Card.TFrame")
        pr_f.pack(fill="x")

        pr_labels = [
            ("shadow.mode:", "var_pr_shadow_mode", "combobox",
             ["none", "ai.soft", "ai.hard", "ai.floating"], "ai.soft",
             "그림자 유형.\nnone: 없음 / ai.soft: 부드러움 / ai.hard: 선명 / ai.floating: 떠있는 느낌"),
            ("shadow.opacity:", "var_pr_shadow_opacity", "entry", None, "0.5",
             "그림자 투명도 (0~1). 0.3~0.5가 자연스러움"),
            ("padding:", "var_pr_padding", "entry", None, "0.08",
             "제품 주변 여백 비율. 0.05~0.10 권장"),
            ("outputSize:", "var_pr_output_size", "combobox",
             ["originalImage", "1000x1000", "2000x2000"], "originalImage",
             "출력 해상도. originalImage 권장"),
        ]
        for i, (label, var_name, wtype, values, default, tooltip) in enumerate(pr_labels):
            lbl = ttk.Label(pr_f, text=label, style="Card.TLabel")
            lbl.grid(row=i, column=0, sticky="w", padx=(2, 8), pady=3)
            ToolTip(lbl, tooltip)
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            if wtype == "combobox":
                w = ttk.Combobox(pr_f, textvariable=var, values=values,
                             width=16, font=(FONT_FAMILY, 10), state="readonly")
            else:
                w = ttk.Entry(pr_f, textvariable=var, width=10, font=(FONT_FAMILY, 10))
            w.grid(row=i, column=1, sticky="w", padx=0, pady=3)
            ToolTip(w, tooltip)

        pr_btn_f = ttk.Frame(pr_lf, style="Card.TFrame")
        pr_btn_f.pack(fill="x", pady=(4, 0))
        ttk.Button(pr_btn_f, text="설정 저장", command=self._save_photoroom_settings,
                   style="Accent.TButton").pack(side="left", padx=(2, 10))
        self.pr_status = ttk.Label(pr_btn_f, text="", style="Card.TLabel")
        self.pr_status.pack(side="left")

        # ══════════════════════════════════════
        #  5. Claid.ai / OpenCV 보정 옵션 (공통 빌더)
        # ══════════════════════════════════════
        enhance_types = ["full", "detail", "worn", "package"]
        enhance_fields = ["hdr", "sharpness", "exposure", "saturation", "contrast"]
        field_tooltips = {
            "hdr": "HDR 보정 강도 (0~100). 15~25 권장",
            "sharpness": "선명도 (0~100). 10~20 자연스러움",
            "exposure": "노출 (-100~100). 0=변경 없음",
            "saturation": "채도 (-100~100). 0=변경 없음",
            "contrast": "대비 (-100~100). 0=변경 없음",
        }
        type_tooltips = {
            "full": "전체 상품 사진", "detail": "디테일컷 (클로즈업)",
            "worn": "착용/모델 사진", "package": "패키지/박스",
        }
        enhance_defaults = {
            "full":    {"hdr": "20", "sharpness": "15", "exposure": "0", "saturation": "0", "contrast": "0"},
            "detail":  {"hdr": "15", "sharpness": "10", "exposure": "0", "saturation": "0", "contrast": "0"},
            "worn":    {"hdr": "10", "sharpness": "5",  "exposure": "0", "saturation": "0", "contrast": "0"},
            "package": {"hdr": "20", "sharpness": "15", "exposure": "0", "saturation": "0", "contrast": "0"},
        }

        def _build_enhance_grid(parent_lf, mode_var, vars_dict, mode_val_manual, save_cmd, status_attr):
            """Claid/OpenCV 공통 보정 그리드 빌더."""
            mode_f = ttk.Frame(parent_lf, style="Card.TFrame")
            mode_f.pack(fill="x", pady=(0, 4))
            rb1 = ttk.Radiobutton(mode_f, text="수동 설정", variable=mode_var, value="manual")
            rb1.pack(side="left", padx=(2, 8))
            ToolTip(rb1, "아래 입력값을 그대로 사용")
            rb2 = ttk.Radiobutton(mode_f, text="AI 자동", variable=mode_var, value="ai_auto")
            rb2.pack(side="left")
            ToolTip(rb2, "Vision API가 최적 값 자동 설정. 아래 값은 기본값")

            grid = ttk.Frame(parent_lf, style="Card.TFrame")
            grid.pack(fill="x")

            # 헤더 행
            ttk.Label(grid, text="", style="Card.TLabel").grid(row=0, column=0)
            for ci, t in enumerate(enhance_types):
                lbl = ttk.Label(grid, text=t, style="Card.TLabel", font=(FONT_FAMILY, 9, "bold"))
                lbl.grid(row=0, column=ci*2+1, columnspan=2, padx=6, pady=(0, 2))
                ToolTip(lbl, type_tooltips[t])

            for ri, field in enumerate(enhance_fields):
                lbl = ttk.Label(grid, text=field, style="Card.TLabel", font=(FONT_FAMILY, 9))
                lbl.grid(row=ri+1, column=0, sticky="w", padx=(2, 6), pady=2)
                ToolTip(lbl, field_tooltips[field])
                for ci, t in enumerate(enhance_types):
                    var = tk.StringVar(value=enhance_defaults[t][field])
                    vars_dict[(t, field)] = var
                    ttk.Entry(grid, textvariable=var, width=5, font=(FONT_FAMILY, 9)).grid(
                        row=ri+1, column=ci*2+1, columnspan=2, padx=6, pady=2)

            btn_f = ttk.Frame(parent_lf, style="Card.TFrame")
            btn_f.pack(fill="x", pady=(4, 0))
            ttk.Button(btn_f, text="설정 저장", command=save_cmd,
                       style="Accent.TButton").pack(side="left", padx=(2, 10))
            status = ttk.Label(btn_f, text="", style="Card.TLabel")
            status.pack(side="left")
            setattr(self, status_attr, status)

        # Claid.ai
        cl_lf = tk.LabelFrame(sf, text=" Claid.ai 보정 옵션 ", font=(FONT_FAMILY, 11, "bold"),
                              bg=CARD_BG, fg="#374151", padx=10, pady=6)
        cl_lf.pack(fill="x", pady=(0, 8))
        self.var_claid_mode = tk.StringVar(value="manual")
        self.claid_vars = {}
        _build_enhance_grid(cl_lf, self.var_claid_mode, self.claid_vars,
                            "manual", self._save_claid_settings, "cl_status")

        # ══════════════════════════════════════
        #  10. 카테고리별 여백
        # ══════════════════════════════════════
        cat_lf = tk.LabelFrame(sf, text=" 카테고리별 여백 규칙 — % 기준 (더블클릭으로 편집) ",
                               font=(FONT_FAMILY, 11, "bold"),
                               bg=CARD_BG, fg="#374151", padx=10, pady=6)
        cat_lf.pack(fill="x", pady=(0, 8))

        # 설명 라벨
        cat_desc = ttk.Label(cat_lf, text="※ 여백은 출력 캔버스 크기 대비 %입니다. "
                             "예: 1000px 출력 + 10% = 상하좌우 100px 여백 → 피사체는 800×800 영역에 맞춤",
                             style="Card.TLabel", wraplength=620,
                             font=(FONT_FAMILY, 9), foreground="#6b7280")
        cat_desc.pack(fill="x", pady=(0, 4))

        tree_frame = ttk.Frame(cat_lf)
        tree_frame.pack(fill="x")

        cols = ("display", "top", "bottom", "left", "right")
        self.cat_tree = ttk.Treeview(tree_frame, columns=cols, height=10)
        self.cat_tree.heading("#0", text="ID")
        self.cat_tree.heading("display", text="이름")
        self.cat_tree.heading("top", text="상 %")
        self.cat_tree.heading("bottom", text="하 %")
        self.cat_tree.heading("left", text="좌 %")
        self.cat_tree.heading("right", text="우 %")
        self.cat_tree.column("#0", width=160)
        self.cat_tree.column("display", width=120)
        self.cat_tree.column("top", width=60)
        self.cat_tree.column("bottom", width=60)
        self.cat_tree.column("left", width=60)
        self.cat_tree.column("right", width=60)
        self.cat_tree.pack(fill="x")
        self.cat_tree.bind("<Double-1>", self._on_cat_double_click)

        cat_btn = ttk.Frame(cat_lf, style="Card.TFrame")
        cat_btn.pack(fill="x", pady=(6, 0))
        ttk.Button(cat_btn, text="저장", command=self._save_categories,
                   style="Accent.TButton").pack(side="left", padx=(2, 8), ipady=2)
        ttk.Button(cat_btn, text="카테고리 추가",
                   command=self._add_category).pack(side="left", padx=(0, 8), ipady=2)
        ttk.Button(cat_btn, text="선택 삭제",
                   command=self._delete_category).pack(side="left", padx=(0, 8), ipady=2)
        ttk.Button(cat_btn, text="다시 불러오기",
                   command=self._load_categories).pack(side="left", ipady=2)
        self.cat_status = ttk.Label(cat_btn, text="", style="TLabel")
        self.cat_status.pack(side="left", padx=15)

    # ── 임시 옵션 탭 ──
    def _build_temp_options_tab(self):
        parent = self.tab_temp_options

        # ── 입력/출력 폴더 ──
        folder_card = tk.LabelFrame(parent, text=" 폴더 ", font=(FONT_FAMILY, 9, "bold"),
                                    bg=CARD_BG, fg="#555", padx=10, pady=6)
        folder_card.pack(fill="x", padx=12, pady=(0, 6))
        folder_card.columnconfigure(1, weight=1)

        _init_input = self._state.get("input_folder", "")
        _init_output = (str(Path(_init_input) / "OUTPUT") if _init_input
                        else self._state.get("output_folder", str(APP_DIR / "output")))
        self.var_unified_input = tk.StringVar(value=_init_input)
        self.var_unified_output = tk.StringVar(value=_init_output)

        for r, (lbl, var, browse_cmd, open_cmd, is_inp) in enumerate([
            ("입력", self.var_unified_input,
             self._browse_unified_input, self._open_unified_input_folder, True),
            ("출력", self.var_unified_output,
             self._browse_unified_output, self._open_unified_output_folder, False),
        ]):
            ttk.Label(folder_card, text=lbl, style="Card.TLabel",
                      font=(FONT_FAMILY, 10, "bold"), width=4).grid(
                row=r, column=0, sticky="w", padx=(12, 4), pady=6)
            e = ttk.Entry(folder_card, textvariable=var, font=(FONT_FAMILY, 10))
            e.grid(row=r, column=1, sticky="ew", padx=0, pady=6)
            self._register_drop(e, var, is_input=is_inp)
            bf = ttk.Frame(folder_card, style="Card.TFrame")
            bf.grid(row=r, column=2, padx=(4, 8), pady=6)
            ttk.Button(bf, text="...", width=3, command=browse_cmd).pack(side="left", padx=(0, 2))
            ttk.Button(bf, text="열기", width=4, command=open_cmd).pack(side="left")

        # ── 포토룸 배경+그림자 통합방식 ──
        opt_frame = tk.LabelFrame(parent, text=" 포토룸 배경+그림자 통합방식 ",
                                  font=(FONT_FAMILY, 9, "bold"),
                                  bg=CARD_BG, fg="#1a6bb0", padx=10, pady=8)
        opt_frame.pack(fill="x", padx=12, pady=(0, 8))

        # Vision 프로바이더
        vision_row = ttk.Frame(opt_frame, style="Card.TFrame")
        vision_row.pack(fill="x", pady=(0, 6))
        ttk.Label(vision_row, text="Vision 분류", style="Card.TLabel",
                  font=(FONT_FAMILY, 9, "bold")).pack(side="left", padx=(0, 12))
        self.var_unified_vision = tk.StringVar(
            value=self._state.get("vision_provider", "gemini"))
        for txt, val in [("Claude", "claude"), ("ChatGPT", "chatgpt"),
                          ("Gemini", "gemini"), ("Grok", "grok")]:
            ttk.Radiobutton(vision_row, text=txt,
                            variable=self.var_unified_vision,
                            value=val).pack(side="left", padx=4)
        ttk.Label(vision_row, text="  ※ full→그림자/detail+흰배경→배경만/detail+유색배경→Claid만",
                  style="Card.TLabel", font=(FONT_FAMILY, 8),
                  foreground="#888").pack(side="left", padx=(8, 0))

        # 그림자 모드 (full shot 적용)
        shadow_row = ttk.Frame(opt_frame, style="Card.TFrame")
        shadow_row.pack(fill="x", pady=(0, 6))
        ttk.Label(shadow_row, text="그림자 모드", style="Card.TLabel",
                  font=(FONT_FAMILY, 9, "bold")).pack(side="left", padx=(0, 12))
        self.var_unified_shadow_mode = tk.StringVar(value="ai.soft")
        for txt, val in [("ai.soft (자연스러운)", "ai.soft"),
                          ("ai.hard (선명한)", "ai.hard"),
                          ("ai.floating (부유효과)", "ai.floating")]:
            ttk.Radiobutton(shadow_row, text=txt,
                            variable=self.var_unified_shadow_mode,
                            value=val).pack(side="left", padx=4)

        # 그림자 강도 + 배경색
        detail_row = ttk.Frame(opt_frame, style="Card.TFrame")
        detail_row.pack(fill="x", pady=(0, 6))
        ttk.Label(detail_row, text="그림자 강도", style="Card.TLabel",
                  font=(FONT_FAMILY, 9, "bold")).pack(side="left", padx=(0, 6))
        self.var_unified_opacity = tk.IntVar(value=20)
        ttk.Spinbox(detail_row, from_=10, to=100, increment=5,
                    textvariable=self.var_unified_opacity,
                    width=4, font=(FONT_FAMILY, 9)).pack(side="left")
        ttk.Label(detail_row, text="%", style="Card.TLabel",
                  font=(FONT_FAMILY, 9)).pack(side="left", padx=(2, 20))
        ttk.Label(detail_row, text="배경색(HEX)", style="Card.TLabel",
                  font=(FONT_FAMILY, 9, "bold")).pack(side="left", padx=(0, 6))
        self.var_unified_bg_color = tk.StringVar(value="FFFFFF")
        ttk.Entry(detail_row, textvariable=self.var_unified_bg_color,
                  width=8, font=(FONT_FAMILY, 9)).pack(side="left")

        # 실행 버튼 + 프로그레스
        action_row = ttk.Frame(opt_frame, style="Card.TFrame")
        action_row.pack(fill="x", pady=(4, 0))
        self.btn_unified_file = ttk.Button(
            action_row, text="  파일 실행  ",
            command=lambda: self._run_unified_photoroom("file"), style="Accent.TButton")
        self.btn_unified_file.pack(side="left", padx=(0, 6), ipady=3)
        self.btn_unified_run = ttk.Button(
            action_row, text="  폴더 실행  ",
            command=lambda: self._run_unified_photoroom("batch"), style="Accent.TButton")
        self.btn_unified_run.pack(side="left", padx=(0, 6), ipady=3)
        self.btn_unified_stop = ttk.Button(
            action_row, text="중지",
            command=self._stop_unified_photoroom, state="disabled")
        self.btn_unified_stop.pack(side="left", padx=(0, 6), ipady=3)
        self.btn_unified_vf = ttk.Button(
            action_row, text="뷰파인더",
            command=self._open_viewfinder, state="disabled",
            style="Viewfinder.TButton")
        self.btn_unified_vf.pack(side="left", padx=(0, 12), ipady=3)
        self.var_unified_progress = tk.DoubleVar(value=0)
        self.unified_progress = ttk.Progressbar(
            action_row, mode="determinate",
            variable=self.var_unified_progress, maximum=100)
        self.unified_progress.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.lbl_unified_progress = ttk.Label(action_row, text="0%", width=5, anchor="e",
                                               font=(FONT_FAMILY, 9))
        self.lbl_unified_progress.pack(side="left")

        # 로그
        self.unified_log = scrolledtext.ScrolledText(
            parent, height=16, font=("Consolas", 9),
            bg="#1e1e2e", fg="#cdd6f4", insertbackground="white",
            wrap="word", state="disabled", relief="flat", borderwidth=0)
        self.unified_log.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.unified_log.tag_config("info", foreground="#89b4fa")
        self.unified_log.tag_config("success", foreground="#a6e3a1")
        self.unified_log.tag_config("error", foreground="#f38ba8")
        self.unified_log.tag_config("warn", foreground="#fab387")

        self._unified_processing = False

    def _log_unified(self, msg, tag="info"):
        def _do():
            self.unified_log.config(state="normal")
            self.unified_log.insert("end", msg + "\n", tag)
            self.unified_log.see("end")
            self.unified_log.config(state="disabled")
        self.after(0, _do)

    def _set_unified_progress(self, current, total):
        def _do():
            pct = (current / total * 100) if total > 0 else 0
            self.var_unified_progress.set(pct)
            self.lbl_unified_progress.config(text=f"{pct:.0f}%")
        self.after(0, _do)

    def _run_unified_photoroom(self, mode="batch"):
        output_dir = self.var_unified_output.get().strip() or str(APP_DIR / "output")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if mode == "file":
            filetypes = [("이미지 파일", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp"),
                         ("모든 파일", "*.*")]
            current = self.var_unified_input.get().strip()
            initial_dir = str(Path(current).parent) if current and Path(current).is_file() \
                          else (current if current and Path(current).is_dir() else "")
            filepaths = filedialog.askopenfilenames(
                title="처리할 이미지 파일 선택 (여러 장 가능)",
                filetypes=filetypes, initialdir=initial_dir or None, parent=self)
            if not filepaths:
                return
            file_list = list(filepaths)
        else:
            input_path = self.var_unified_input.get().strip()
            if not input_path:
                messagebox.showwarning("경고", "입력 폴더를 선택하세요.")
                return
            if not Path(input_path).is_dir():
                messagebox.showerror("오류", f"입력 폴더가 존재하지 않습니다:\n{input_path}")
                return
            from src.utils.image_io import get_image_files
            file_list = get_image_files(input_path)
            if not file_list:
                messagebox.showwarning("경고", "폴더에 이미지 파일이 없습니다.")
                return

        # UI 초기화
        self._unified_processing = True
        self.btn_unified_file.config(state="disabled")
        self.btn_unified_run.config(state="disabled")
        self.btn_unified_stop.config(state="normal")
        self.var_unified_progress.set(0)
        self.lbl_unified_progress.config(text="0%")
        self.unified_log.config(state="normal")
        self.unified_log.delete("1.0", "end")
        self.unified_log.config(state="disabled")

        # 뷰파인더 초기화 후 즉시 활성화 + 자동 오픈
        self._viewfinder_pairs = []
        self._vf_file_stages = {}
        self.btn_unified_vf.config(state="normal")
        self.after(100, self._open_viewfinder)

        shadow_mode = self.var_unified_shadow_mode.get()
        bg_color = self.var_unified_bg_color.get().strip().lstrip("#") or "FFFFFF"
        shadow_opacity = self.var_unified_opacity.get()
        vision_provider = self.var_unified_vision.get()
        total = len(file_list)

        completed = [0]
        lock = threading.Lock()

        def _process_one(idx, img_path):
            fname = Path(img_path).name
            if not self._unified_processing:
                return
            self._log_unified(f"-- [{idx}/{total}] {fname} 시작 --")
            with lock:
                vf_idx = self._vf_register_file(img_path)
            try:
                from src.pipeline import ImageEditPipeline
                pl = ImageEditPipeline(config_dir=str(CONFIG_DIR))
                pl._vision_provider = vision_provider
                result = pl.process_single_unified_photoroom(
                    image_path=img_path,
                    output_dir=output_dir,
                    shadow_mode=shadow_mode,
                    bg_color=bg_color,
                    shadow_opacity=shadow_opacity,
                    on_log=self._log_unified,
                    idx=idx,
                    routing_rules=self._routing_rules_data,
                )
            except Exception as e:
                import traceback
                self._log_unified(f"[{fname}] 오류: {e}", "error")
                self._log_unified(traceback.format_exc(), "error")
                result = {"success": False, "error": str(e), "path": img_path}
            with lock:
                self._vf_complete_file(vf_idx, result)
                # 라우팅 정보 저장 (뷰파인더 표시용)
                img_type = result.get("image_type", "")
                bg = result.get("background", "")
                shooting_angle = result.get("shooting_angle", "")
                is_label_cut = result.get("is_label_cut", False)
                if is_label_cut:
                    route = "label_skip"
                elif shooting_angle == "top_down":
                    route = "top_down_only"
                elif img_type == "detail" and bg not in ("clean", "white", ""):
                    route = "claid_only"
                elif img_type == "detail":
                    route = "detail_bg_only"
                else:
                    route = "full_shadow"
                _performed_map = {
                    "full_shadow":    ["누끼", "그림자"],
                    "detail_bg_only": ["누끼"],
                    "claid_only":     [],
                    "top_down_only":  [],
                    "label_skip":     [],
                }
                performed = _performed_map.get(route, [])
                routing_info = {
                    "route": route, "image_type": img_type, "background": bg,
                    "shooting_angle": shooting_angle, "performed": performed,
                }
                if 0 <= vf_idx < len(self._viewfinder_pairs):
                    self._viewfinder_pairs[vf_idx]["routing_info"] = routing_info
                if fname in self._vf_file_stages:
                    self._vf_file_stages[fname]["routing_info"] = routing_info
                completed[0] += 1
                self._set_unified_progress(completed[0], total)
            if result.get("success"):
                self._log_unified(f"[{fname}] ✓ 완료 ({completed[0]}/{total})", "success")
            else:
                self._log_unified(f"[{fname}] ✗ 실패: {result.get('error','')} ({completed[0]}/{total})", "error")

        def _worker():
            try:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {
                        executor.submit(_process_one, idx, img_path): img_path
                        for idx, img_path in enumerate(file_list, 1)
                    }
                    for future in as_completed(futures):
                        if not self._unified_processing:
                            executor.shutdown(wait=False, cancel_futures=True)
                            self._log_unified("중지됨.", "warn")
                            break
                        try:
                            future.result()
                        except Exception:
                            pass
            except Exception as e:
                self._log_unified(f"오류 발생: {e}", "error")
            finally:
                self.after(0, self._on_unified_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_unified_photoroom(self):
        self._unified_processing = False
    def _on_unified_done(self):
        self._unified_processing = False
        self.btn_unified_file.config(state="normal")
        self.btn_unified_run.config(state="normal")
        self.btn_unified_stop.config(state="disabled")
        self.var_unified_progress.set(100)
        self.lbl_unified_progress.config(text="완료")
        if self._viewfinder_pairs:
            self.btn_unified_vf.config(state="normal")

    def _on_cat_double_click(self, event):
        item = self.cat_tree.identify_row(event.y)
        col = self.cat_tree.identify_column(event.x)
        if not item or not col:
            return

        # #0 = ID 열, #1~#5 = display, top, bottom, left, right
        is_id_col = (col == "#0")

        if is_id_col:
            bbox = self.cat_tree.bbox(item, column="#0")
            current = self.cat_tree.item(item, "text")
        else:
            col_idx = int(col.replace("#", "")) - 1
            col_names = ["display", "top", "bottom", "left", "right"]
            col_name = col_names[col_idx]
            bbox = self.cat_tree.bbox(item, col)
            current = self.cat_tree.set(item, col_name)

        if not bbox:
            return
        x, y, w, h = bbox

        entry = ttk.Entry(self.cat_tree, font=(FONT_FAMILY, 10))
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, current)
        entry.select_range(0, "end")
        entry.focus()

        def _save_edit(e=None):
            new_val = entry.get().strip()
            if is_id_col:
                if new_val:
                    self.cat_tree.item(item, text=new_val)
            else:
                self.cat_tree.set(item, col_name, new_val)
            entry.destroy()
            self.cat_status.config(text="수정됨 (저장 필요)", foreground="#ca8a04")

        entry.bind("<Return>", _save_edit)
        entry.bind("<FocusOut>", _save_edit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    # ── 카테고리 추가 ──
    def _add_category(self):
        self.cat_tree.insert("", "end", text="new_category", values=(
            "새 카테고리", 10, 10, 10, 10))
        self.cat_status.config(text="추가됨 (저장 필요)", foreground="#ca8a04")

    # ── 카테고리 삭제 ──
    def _delete_category(self):
        selected = self.cat_tree.selection()
        if not selected:
            messagebox.showwarning("선택 필요", "삭제할 카테고리를 선택하세요.")
            return
        for item in selected:
            cat_id = self.cat_tree.item(item, "text")
            self.cat_tree.delete(item)
        self.cat_status.config(text="삭제됨 (저장 필요)", foreground="#ca8a04")

    # ── 카테고리 저장 ──
    def _save_categories(self):
        try:
            data = load_yaml(CATEGORIES_PATH)
            old_cats = data.get("categories", {})

            new_cats = {}
            for item in self.cat_tree.get_children():
                cat_id = self.cat_tree.item(item, "text").strip()
                vals = self.cat_tree.item(item, "values")
                if not cat_id:
                    continue
                # 기존 데이터 유지 (thumbnail_padding 등)
                base = old_cats.get(cat_id, {})
                base["display_name"] = vals[0]
                # 구 형식 제거, 새 형식으로 저장
                base.pop("padding_860", None)
                base["padding_percent"] = {
                    "top": float(vals[1]),
                    "bottom": float(vals[2]),
                    "left": float(vals[3]),
                    "right": float(vals[4]),
                }
                if "thumbnail_padding" not in base:
                    base["thumbnail_padding"] = {
                        "top": 359, "bottom": 359, "left": 148, "right": 148
                    }
                new_cats[cat_id] = base

            data["categories"] = new_cats
            save_yaml(CATEGORIES_PATH, data)

            self.cat_status.config(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                foreground=SUCCESS)
        except Exception as e:
            self.cat_status.config(text=f"저장 실패: {e}", foreground=DANGER)

    # 안 설정 로드 ――
    def _load_configs(self):
        self._load_settings()
        self._load_categories()

    def _load_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            out = data.get("output", {})
            self.var_out_w.set(str(out.get("width", 860)))
            self.var_out_h.set(str(out.get("height", 860)))
            self.var_max_kb.set(str(out.get("max_file_size_kb", 2024)))
            self.var_jpeg_q.set(str(out.get("default_jpeg_quality", 95)))
            api = data.get("api", {})
            self.var_model.set(api.get("model", "claude-sonnet-4-20250514"))

            # Photoroom 설정 로드
            pr = data.get("photoroom", {}).get("full", {})
            self.var_pr_shadow_mode.set(pr.get("shadow.mode", "ai.soft"))
            self.var_pr_shadow_opacity.set(str(pr.get("shadow.opacity", 0.5)))
            self.var_pr_padding.set(str(pr.get("padding", 0.08)))
            self.var_pr_output_size.set(pr.get("outputSize", "originalImage"))

            # Claid 설정 로드
            cl = data.get("claid", {})
            for img_type in ["full", "detail", "worn", "package"]:
                type_data = cl.get(img_type, {})
                for field in ["hdr", "sharpness", "exposure", "saturation", "contrast"]:
                    key = (img_type, field)
                    if key in self.claid_vars:
                        val = type_data.get(field, 0)
                        self.claid_vars[key].set(str(val))

            # 프로바이더 설정 로드
            providers = data.get("providers", {})
            self.var_vision_provider.set(providers.get("vision", "claude"))
            self.var_bg_provider.set(providers.get("background_removal", "photoroom"))
            self.var_enhance_provider.set(providers.get("enhancement", "claid"))

            # OpenAI/Gemini 설정 로드
            openai_config = data.get("openai", {})
            self.var_openai_model.set(openai_config.get("model", "gpt-4o"))
            gemini_config = data.get("gemini", {})
            self.var_gemini_model.set(gemini_config.get("model", "gemini-2.5-flash"))
            grok_config = data.get("grok", {})
            self.var_grok_model.set(grok_config.get("model", "grok-4-fast-non-reasoning"))

            # AI 자동/수동 모드 설정 로드
            auto_opts = data.get("auto_options", {})
            self.var_claid_mode.set(auto_opts.get("claid", "manual"))
            self.var_photoroom_mode.set(auto_opts.get("photoroom", "manual"))

            # gui_state에서 마지막 사용한 프로바이더 복원 (settings.yaml 기본값보다 우선)
            if "vision_provider" in self._state:
                self.var_vision_provider.set(self._state["vision_provider"])
            if "bg_provider" in self._state:
                self.var_bg_provider.set(self._state["bg_provider"])
            if "enhance_provider" in self._state:
                self.var_enhance_provider.set(self._state["enhance_provider"])
        except Exception:
            pass

    def _load_categories(self):
        try:
            data = load_yaml(CATEGORIES_PATH)
            cats = data.get("categories", {})

            for item in self.cat_tree.get_children():
                self.cat_tree.delete(item)

            for cat_id, cat_data in cats.items():
                # 새 형식(padding_percent) 우선, 구 형식(padding_860) fallback
                p = cat_data.get("padding_percent")
                if not p:
                    p860 = cat_data.get("padding_860", {})
                    if p860:
                        p = {k: round(v / 860.0 * 100, 1) for k, v in p860.items()}
                    else:
                        p = {"top": 10, "bottom": 10, "left": 10, "right": 10}
                self.cat_tree.insert("", "end", text=cat_id, values=(
                    cat_data.get("display_name", ""),
                    p.get("top", 10), p.get("bottom", 10),
                    p.get("left", 10), p.get("right", 10),
                ))
            self.cat_status.config(text="", foreground=SUCCESS)
        except Exception:
            pass

    def _save_model_settings(self):
        """Claude/OpenAI/Gemini/Grok 모델 선택을 settings.yaml에 저장."""
        try:
            data = load_yaml(SETTINGS_PATH)
            data.setdefault("api", {})["model"] = self.var_model.get()
            data.setdefault("openai", {})["model"] = self.var_openai_model.get()
            data.setdefault("gemini", {})["model"] = self.var_gemini_model.get()
            data.setdefault("grok", {})["model"] = self.var_grok_model.get()
            save_yaml(SETTINGS_PATH, data)
            messagebox.showinfo("모델 저장", "모델 설정이 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"모델 저장 실패: {e}")

    def _save_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            data["output"]["width"] = int(self.var_out_w.get())
            data["output"]["height"] = int(self.var_out_h.get())
            data["output"]["max_file_size_kb"] = int(self.var_max_kb.get())
            data["output"]["default_jpeg_quality"] = int(self.var_jpeg_q.get())
            data["api"]["model"] = self.var_model.get()

            # 프로바이더 설정 저장
            providers = data.setdefault("providers", {})
            providers["vision"] = self.var_vision_provider.get()
            providers["background_removal"] = self.var_bg_provider.get()
            providers["enhancement"] = self.var_enhance_provider.get()

            # OpenAI/Gemini/Grok 모델 설정 저장
            openai_config = data.setdefault("openai", {})
            openai_config["model"] = self.var_openai_model.get()
            gemini_config = data.setdefault("gemini", {})
            gemini_config["model"] = self.var_gemini_model.get()
            grok_config = data.setdefault("grok", {})
            grok_config["model"] = self.var_grok_model.get()

            save_yaml(SETTINGS_PATH, data)
            messagebox.showinfo("설정 저장", "설정이 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"설정 저장 실패: {e}")

    def _save_photoroom_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            pr_full = data.setdefault("photoroom", {}).setdefault("full", {})
            pr_full["shadow.mode"] = self.var_pr_shadow_mode.get()
            pr_full["shadow.opacity"] = float(self.var_pr_shadow_opacity.get())
            pr_full["padding"] = float(self.var_pr_padding.get())
            pr_full["outputSize"] = self.var_pr_output_size.get()

            # package에도 shadow 설정 동기화
            pr_pkg = data["photoroom"].setdefault("package", {})
            pr_pkg["shadow.mode"] = pr_full["shadow.mode"]
            pr_pkg["shadow.opacity"] = pr_full["shadow.opacity"]

            auto_opts = data.setdefault("auto_options", {})
            auto_opts["photoroom"] = self.var_photoroom_mode.get()

            save_yaml(SETTINGS_PATH, data)
            self.pr_status.config(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                foreground=SUCCESS)
        except Exception as e:
            self.pr_status.config(text=f"저장 실패: {e}", foreground=DANGER)

    def _save_claid_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            cl = data.setdefault("claid", {})
            for img_type in ["full", "detail", "worn", "package"]:
                type_data = cl.setdefault(img_type, {})
                type_data["hdr"] = int(self.claid_vars[(img_type, "hdr")].get())
                type_data["sharpness"] = int(self.claid_vars[(img_type, "sharpness")].get())
                # exposure/saturation/contrast: 0이 아닌 경우에만 저장
                for field in ["exposure", "saturation", "contrast"]:
                    val = int(self.claid_vars[(img_type, field)].get())
                    if val != 0:
                        type_data[field] = val
                    elif field in type_data:
                        del type_data[field]

            auto_opts = data.setdefault("auto_options", {})
            auto_opts["claid"] = self.var_claid_mode.get()

            save_yaml(SETTINGS_PATH, data)
            self.cl_status.config(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                foreground=SUCCESS)
        except Exception as e:
            self.cl_status.config(text=f"저장 실패: {e}", foreground=DANGER)

    def _save_api_key(self):
        key = self.var_api_key.get().strip()
        if not key:
            messagebox.showwarning("경고", "API 키를 입력하세요.")
            return
        try:
            if not ENV_PATH.exists():
                ENV_PATH.write_text("", encoding="utf-8")
            set_key(str(ENV_PATH), "ANTHROPIC_API_KEY", key)
            os.environ["ANTHROPIC_API_KEY"] = key
            messagebox.showinfo("저장 완료", "API 키가 .env 파일에 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"API 키 저장 실패: {e}")

    def _toggle_key_visibility(self):
        self.entry_api_key.config(show="" if self.var_show_key.get() else "*")

    def _save_photoroom_key(self):
        key = self.var_photoroom_key.get().strip()
        if not key:
            messagebox.showwarning("경고", "Photoroom API 키를 입력하세요.")
            return
        try:
            if not ENV_PATH.exists():
                ENV_PATH.write_text("", encoding="utf-8")
            set_key(str(ENV_PATH), "PHOTOROOM_API_KEY", key)
            os.environ["PHOTOROOM_API_KEY"] = key
            messagebox.showinfo("저장 완료", "Photoroom API 키가 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}")

    def _toggle_photoroom_key_visibility(self):
        self.entry_photoroom_key.config(show="" if self.var_show_photoroom_key.get() else "*")

    def _check_photoroom_credits(self):
        key = self.var_photoroom_key.get().strip() or os.environ.get("PHOTOROOM_API_KEY", "")
        if not key:
            messagebox.showwarning("경고", "Photoroom API 키를 먼저 입력하세요.")
            return
        self.lbl_photoroom_credits.config(text="확인 중...", foreground="#888")

        def _fetch():
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://image-api.photoroom.com/v1/account",
                    headers={"x-api-key": key},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    import json
                    data = json.loads(resp.read().decode())
                credits = data.get("credits", {})
                available = credits.get("available", "?")
                total = credits.get("subscription", "?")
                used = (total - available) if isinstance(total, int) and isinstance(available, int) else "?"
                text = f"남은 크레딧: {available:,} / {total:,}  (사용: {used:,})"
                color = "#16a34a" if isinstance(available, int) and available > 100 else "#dc2626"
                self.after(0, lambda: self.lbl_photoroom_credits.config(text=text, foreground=color))
            except Exception as e:
                self.after(0, lambda: self.lbl_photoroom_credits.config(
                    text=f"오류: {e}", foreground="#dc2626"))

        threading.Thread(target=_fetch, daemon=True).start()

    def _save_claid_key(self):
        key = self.var_claid_key.get().strip()
        if not key:
            messagebox.showwarning("경고", "Claid.ai API 키를 입력하세요.")
            return
        try:
            if not ENV_PATH.exists():
                ENV_PATH.write_text("", encoding="utf-8")
            set_key(str(ENV_PATH), "CLAID_API_KEY", key)
            os.environ["CLAID_API_KEY"] = key
            messagebox.showinfo("저장 완료", "Claid.ai API 키가 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}")

    def _toggle_claid_key_visibility(self):
        self.entry_claid_key.config(show="" if self.var_show_claid_key.get() else "*")

    def _save_removebg_key(self):
        key = self.var_removebg_key.get().strip()
        if not key:
            messagebox.showwarning("경고", "remove.bg API 키를 입력하세요.")
            return
        try:
            if not ENV_PATH.exists():
                ENV_PATH.write_text("", encoding="utf-8")
            set_key(str(ENV_PATH), "REMOVEBG_API_KEY", key)
            os.environ["REMOVEBG_API_KEY"] = key
            messagebox.showinfo("저장 완료", "remove.bg API 키가 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}")

    def _toggle_removebg_key_visibility(self):
        self.entry_removebg_key.config(show="" if self.var_show_removebg_key.get() else "*")

    def _save_openai_key(self):
        key = self.var_openai_key.get().strip()
        if not key:
            messagebox.showwarning("경고", "OpenAI API 키를 입력하세요.")
            return
        try:
            if not ENV_PATH.exists():
                ENV_PATH.write_text("", encoding="utf-8")
            set_key(str(ENV_PATH), "OPENAI_API_KEY", key)
            os.environ["OPENAI_API_KEY"] = key
            messagebox.showinfo("저장 완료", "OpenAI API 키가 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}")

    def _toggle_openai_key_visibility(self):
        self.entry_openai_key.config(show="" if self.var_show_openai_key.get() else "*")

    def _save_gemini_key(self):
        key = self.var_gemini_key.get().strip()
        if not key:
            messagebox.showwarning("경고", "Gemini API 키를 입력하세요.")
            return
        try:
            if not ENV_PATH.exists():
                ENV_PATH.write_text("", encoding="utf-8")
            set_key(str(ENV_PATH), "GEMINI_API_KEY", key)
            os.environ["GEMINI_API_KEY"] = key
            messagebox.showinfo("저장 완료", "Gemini API 키가 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}")

    def _toggle_gemini_key_visibility(self):
        self.entry_gemini_key.config(show="" if self.var_show_gemini_key.get() else "*")

    def _save_xai_key(self):
        key = self.var_xai_key.get().strip()
        if not key:
            messagebox.showwarning("경고", "xAI API 키를 입력하세요.")
            return
        try:
            if not ENV_PATH.exists():
                ENV_PATH.write_text("", encoding="utf-8")
            set_key(str(ENV_PATH), "XAI_API_KEY", key)
            os.environ["XAI_API_KEY"] = key
            messagebox.showinfo("저장 완료", "xAI API 키가 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}")

    def _toggle_xai_key_visibility(self):
        self.entry_xai_key.config(show="" if self.var_show_xai_key.get() else "*")

    # ── 폴더 ──
    def _register_drop(self, entry_widget, var, is_input=False):
        """Entry 위젯에 폴더/파일 드래그앤드롭 등록."""
        if not _DND_AVAILABLE:
            return
        def _on_drop(event):
            raw = event.data.strip()
            # tkinterdnd2 는 중괄호로 묶인 경로를 반환할 수 있음
            if raw.startswith("{") and raw.endswith("}"):
                raw = raw[1:-1]
            # 여러 항목이면 첫 번째만 사용
            path = raw.split("} {")[0].strip()
            p = Path(path)
            # 파일이 드롭되면 부모 폴더 사용
            folder = str(p.parent) if p.is_file() else str(p)
            var.set(folder)
            if is_input:
                out = Path(folder) / "OUTPUT"
                out.mkdir(parents=True, exist_ok=True)
                self.var_unified_output.set(str(out))
        entry_widget.drop_target_register(DND_FILES)
        entry_widget.dnd_bind("<<Drop>>", _on_drop)
        entry_widget.config(
            foreground="#374151" if not _DND_AVAILABLE else "#374151"
        )

    def _browse_unified_input(self):
        folder = filedialog.askdirectory(title="입력 이미지 폴더 선택", parent=self)
        if folder:
            self.var_unified_input.set(folder)
            out = Path(folder) / "OUTPUT"
            out.mkdir(parents=True, exist_ok=True)
            self.var_unified_output.set(str(out))

    def _open_unified_input_folder(self):
        path = self.var_unified_input.get().strip()
        if not path:
            messagebox.showwarning("알림", "입력 경로가 설정되지 않았습니다.")
            return
        p = Path(path)
        if p.is_file():
            os.startfile(str(p.parent))
        elif p.is_dir():
            os.startfile(path)
        else:
            messagebox.showwarning("알림", "입력 경로가 존재하지 않습니다.")

    def _browse_unified_output(self):
        folder = filedialog.askdirectory(title="출력 폴더 선택", parent=self)
        if folder:
            self.var_unified_output.set(folder)

    def _open_unified_output_folder(self):
        folder = self.var_unified_output.get().strip()
        if folder and Path(folder).is_dir():
            os.startfile(folder)
        else:
            messagebox.showwarning("알림", "출력 폴더가 존재하지 않습니다.")

    def _vf_make_log(self, fname, base_log=None):
        """stage 추적하는 로그 래퍼 생성"""
        _base = base_log or self._log

        def _wrapped(msg, level="info"):
            _base(msg, level)
            stage = self._vf_detect_stage(msg)
            if stage:
                done = (level == "success") or ("완료" in msg) or ("스킵" in msg) or ("생략" in msg)
                self._vf_update_file_stage(fname, stage, done=done)
                # 스킵 패턴 감지
                if "스킵" in msg or "생략" in msg:
                    self._vf_file_stages.get(fname, {}).get("stages", {})[stage] = "skip"
        return _wrapped

    def _vf_make_stage_cb(self, fname, output_dir):
        """단계별 이미지를 임시 폴더에 저장하는 콜백 생성"""
        stem = Path(fname).stem
        stage_dir = Path(output_dir) / "_temp_stages" / stem
        stage_dir.mkdir(parents=True, exist_ok=True)

        def _save_stage(stage_name, data):
            try:
                stage_path = stage_dir / f"{stage_name}.png"
                stage_path.write_bytes(data)
                # _vf_file_stages에 stage_images 기록
                if fname in self._vf_file_stages:
                    si = self._vf_file_stages[fname].setdefault("stage_images", {})
                    si[stage_name] = str(stage_path)
            except Exception:
                pass
        return _save_stage

    def _vf_register_file(self, file_path):
        """처리 시작 전에 파일을 뷰파인더에 등록"""
        fname = Path(file_path).name
        self._vf_file_stages[fname] = {"stages": {}, "status": "processing"}
        self._viewfinder_pairs.append({
            "input_path": str(file_path),
            "output_files": [],
            "success": False,
            "status": "processing",
        })
        return len(self._viewfinder_pairs) - 1  # index

    def _vf_complete_file(self, vf_idx, result):
        """처리 완료 후 뷰파인더 항목 업데이트"""
        if vf_idx < 0 or vf_idx >= len(self._viewfinder_pairs):
            return
        pair = self._viewfinder_pairs[vf_idx]
        out_files = result.get("files", [])
        pair["output_files"] = out_files
        pair["success"] = bool(out_files)
        pair["status"] = "done" if out_files else "fail"

        # 검증 결과 저장
        validation = result.get("validation")
        pair["validation"] = validation

        # 독립 평가 결과 저장
        independent_eval = result.get("independent_eval")
        if independent_eval:
            pair["independent_eval"] = independent_eval

        # Vision API 판단 정보 저장 (뷰파인더 표시용)
        inst = result.get("instruction")
        if inst:
            pair["vision_info"] = {
                "image_type": getattr(inst, "image_type", ""),
                "shooting_angle": getattr(inst, "shooting_angle", ""),
                "floor_visible": getattr(inst, "floor_visible", True),
                "needs_shadow": getattr(inst, "needs_shadow", True),
                "shadow_confidence": getattr(inst, "shadow_confidence", 0.5),
                "shadow_reason": getattr(inst, "_shadow_reason", ""),
                "is_full_body": getattr(inst, "is_full_body", None),
                "has_mannequin": getattr(inst, "has_mannequin", False),
                "has_human_hand": getattr(inst, "has_human_hand", False),
                "category": getattr(inst, "detected_category_display", "") or getattr(inst, "detected_category", ""),
                "confidence": getattr(inst, "confidence", 0),
            }

        fname = Path(pair["input_path"]).name
        if fname in self._vf_file_stages:
            fs = self._vf_file_stages[fname]
            fs["status"] = "done" if out_files else "fail"
            # 검증 단계 pip 업데이트
            if validation:
                overall = validation.get("overall", True)
                fs["stages"]["검증"] = "done" if overall else "fail"
                fs["validation"] = validation
            else:
                fs["stages"]["검증"] = "skip"

    _VF_STAGES = ["분석", "누끼", "보정", "그림자", "크롭", "저장", "검증"]
    _VF_STAGE_PATTERNS = {
        "분석": ["처리 시작", "분석"],
        "누끼": ["배경제거 중", "배경제거 완료", "배경제거 스킵", "배경제거 처리 생략"],
        "보정": ["이미지 보정 중", "보정 완료", "Claid.ai 완료", "OpenCV 보정 완료"],
        "그림자": ["그림자 추출", "그림자 생성", "그림자 합성", "shadow", "Shadow"],
        "크롭": ["크롭", "중앙 정렬", "센터링"],
        "저장": ["출력:", "처리 완료"],
        "검증": ["품질 검증 시작", "품질 검증 완료", "품질 검증 오류"],
    }

    def _vf_detect_stage(self, msg):
        """로그 메시지에서 현재 단계 감지"""
        for stage, patterns in self._VF_STAGE_PATTERNS.items():
            for pat in patterns:
                if pat in msg:
                    return stage
        return None

    def _vf_update_file_stage(self, fname, stage, done=False):
        """파일의 단계 업데이트 (thread-safe via after)"""
        key = fname
        if key not in self._vf_file_stages:
            self._vf_file_stages[key] = {"stages": {}, "status": "processing"}
        stages = self._vf_file_stages[key]["stages"]
        idx = self._VF_STAGES.index(stage) if stage in self._VF_STAGES else -1
        # 현재 단계 이전은 done으로
        for i, s in enumerate(self._VF_STAGES):
            if i < idx and s not in stages:
                stages[s] = "done"
        stages[stage] = "done" if done else "active"
        if done and stage == "저장":
            self._vf_file_stages[key]["status"] = "done"

    def _open_viewfinder(self):
        from PIL import Image, ImageTk

        # 이미 열려있으면 포커스
        if hasattr(self, '_vf_dlg') and self._vf_dlg and self._vf_dlg.winfo_exists():
            self._vf_dlg.lift()
            self._vf_dlg.focus_force()
            return

        # ── 컬러 팔레트 (다크 테마) ──
        VF_BG = "#1e1e2e"
        VF_SURFACE = "#2b2b3d"
        VF_CARD = "#313244"
        VF_BORDER = "#444"
        VF_TEXT = "#cdd6f4"
        VF_TEXT_DIM = "#888"
        VF_TEXT_FAINT = "#555"
        VF_ACCENT = "#89b4fa"
        VF_PURPLE = "#cba6f7"
        VF_GREEN = "#a6e3a1"
        VF_RED = "#f38ba8"
        VF_YELLOW = "#f9e2af"
        VF_PIP_BG = "#2a2a3a"
        VF_PIP_SKIP = "#45475a"
        VF_IMG_BG = "#ffffff"

        dlg = tk.Toplevel(self)
        self._vf_dlg = dlg
        dlg.title("뷰파인더 — 처리 결과 비교")
        # ★ 윈도우즈 작업 영역(work area) 기준으로 세로 100% 채우기
        try:
            import ctypes
            # SystemParametersInfoW(SPI_GETWORKAREA) → 작업표시줄 제외 영역
            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            rect = _RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0,
                                                       ctypes.byref(rect), 0)
            work_x, work_y = rect.left, rect.top
            work_w = rect.right - rect.left
            work_h = rect.bottom - rect.top
        except Exception:
            # ctypes 실패 시 (비윈도우 등) 폴백
            work_x, work_y = 0, 0
            work_w = dlg.winfo_screenwidth()
            work_h = dlg.winfo_screenheight() - 48
        dlg_h = work_h
        dlg_w = min(work_w, max(1500, int(dlg_h * 1.6)))
        dlg_x = work_x + max(0, (work_w - dlg_w) // 2)
        dlg_y = work_y
        dlg.geometry(f"{dlg_w}x{dlg_h}+{dlg_x}+{dlg_y}")
        dlg.minsize(1000, 650)
        dlg.configure(bg=VF_BG)

        current_idx = [0]
        out_idx = [0]
        photo_refs = []

        # ── 타이틀바 ──
        titlebar = tk.Frame(dlg, bg="#181825", height=32)
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)
        # 트래픽 라이트 도트
        dots_frame = tk.Frame(titlebar, bg="#181825")
        dots_frame.pack(side="left", padx=10)
        for c in [VF_RED, VF_YELLOW, VF_GREEN]:
            tk.Canvas(dots_frame, width=10, height=10, bg="#181825",
                      highlightthickness=0, bd=0).pack(side="left", padx=2)
            dot = dots_frame.winfo_children()[-1]
            dot.create_oval(1, 1, 9, 9, fill=c, outline="")
        tk.Label(titlebar, text="뷰파인더 — 처리 결과 비교",
                 bg="#181825", fg=VF_PURPLE, font=(FONT_FAMILY, 10, "bold")).pack(side="left", padx=8)
        tk.Label(titlebar, text="ESC로 닫기", bg="#181825", fg=VF_TEXT_FAINT,
                 font=(FONT_FAMILY, 9)).pack(side="right", padx=12)

        # ── 메인 컨텐츠 ──
        main = tk.Frame(dlg, bg=VF_BG)
        main.pack(fill="both", expand=True)

        # ── 좌측: 파일 리스트 ──
        left = tk.Frame(main, bg=VF_BG, width=280)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        # 구분선
        tk.Frame(main, bg=VF_BORDER, width=1).pack(side="left", fill="y")

        # 헤더
        header_frame = tk.Frame(left, bg=VF_BG)
        header_frame.pack(fill="x", padx=10, pady=(10, 6))
        lbl_header = tk.Label(header_frame, text="처리 현황",
                              bg=VF_BG, fg=VF_TEXT_DIM, font=(FONT_FAMILY, 10, "bold"),
                              anchor="w")
        lbl_header.pack(side="left")

        # 파일 리스트 영역
        list_frame = tk.Frame(left, bg=VF_BG)
        list_frame.pack(fill="both", expand=True, padx=4)
        list_canvas = tk.Canvas(list_frame, bg=VF_BG, highlightthickness=0, bd=0)
        list_sb = tk.Scrollbar(list_frame, orient="vertical", command=list_canvas.yview,
                               bg=VF_BG, troughcolor=VF_BG, activebackground=VF_CARD)
        list_canvas.configure(yscrollcommand=list_sb.set)
        list_canvas.pack(side="left", fill="both", expand=True)
        list_sb.pack(side="right", fill="y")
        inner_frame = tk.Frame(list_canvas, bg=VF_BG)
        _cw_id = list_canvas.create_window((0, 0), window=inner_frame, anchor="nw")
        # inner_frame이 캔버스 폭에 맞게 늘어나도록
        def _sync_inner_width(event):
            list_canvas.itemconfig(_cw_id, width=event.width)
        list_canvas.bind("<Configure>", _sync_inner_width)

        # 마우스 휠 스크롤
        def _on_mousewheel(event):
            list_canvas.yview_scroll(-1 * (event.delta // 120), "units")
        list_canvas.bind("<MouseWheel>", _on_mousewheel)

        file_rows = {}

        def _build_file_row(parent, idx, fname, pair):
            # 외곽 프레임 — 선택 시 좌측 보더 효과용
            row = tk.Frame(parent, bg=VF_BG, cursor="hand2", padx=0, pady=0)
            row.pack(fill="x", padx=4, pady=2)

            # 좌측 선택 표시 바
            sel_bar = tk.Frame(row, bg=VF_BG, width=3)
            sel_bar.pack(side="left", fill="y")

            # 컨텐츠 영역
            content = tk.Frame(row, bg=VF_BG)
            content.pack(side="left", fill="x", expand=True, padx=(4, 2), pady=3)

            # 상단: 아이콘 + 파일명
            top = tk.Frame(content, bg=VF_BG)
            top.pack(fill="x")

            status = pair.get("status", "pending")
            icon_map = {"done": "\u2705", "processing": "\u23f3", "fail": "\u274c"}
            icon = icon_map.get(status, "\u2b1c")
            lbl_icon = tk.Label(top, text=icon, bg=VF_BG, font=(FONT_FAMILY, 10))
            lbl_icon.pack(side="left", padx=(0, 6))

            lbl_name = tk.Label(top, text=fname, bg=VF_BG, fg=VF_TEXT,
                                font=(FONT_FAMILY, 9), anchor="w", cursor="hand2")
            lbl_name.pack(side="left", fill="x", expand=True)

            def _copy_fname(e, name=fname):
                dlg.clipboard_clear()
                dlg.clipboard_append(name)
                # 복사 피드백: 잠시 색상 변경
                e.widget.config(fg=VF_GREEN)
                dlg.after(500, lambda w=e.widget: w.config(fg=VF_TEXT))
            lbl_name.bind("<Button-3>", _copy_fname)
            lbl_name.bind("<Double-Button-1>", _copy_fname)

            # 스테이지 pip 바
            pip_frame = tk.Frame(content, bg=VF_BG)
            pip_frame.pack(fill="x", padx=(20, 2), pady=(3, 0))
            pips = []
            for s in self._VF_STAGES:
                pip = tk.Frame(pip_frame, height=4, bg=VF_PIP_BG, bd=0, highlightthickness=0)
                pip.pack(side="left", fill="x", expand=True, padx=1)
                pips.append(pip)

            # 상태/검증 행: 항상 고정 높이, 내용만 교체
            status_val_frame = tk.Frame(content, bg=VF_BG, height=16)
            status_val_frame.pack(fill="x", padx=(20, 2), pady=(1, 0))
            status_val_frame.pack_propagate(False)

            # 우측 성공/실패 텍스트
            lbl_result = tk.Label(status_val_frame, text="", bg=VF_BG,
                                  font=(FONT_FAMILY, 8, "bold"), anchor="e")
            lbl_result.pack(side="right", padx=(0, 4))

            # 진행 중 단계 텍스트 (좌측)
            lbl_stage_text = tk.Label(status_val_frame, text="", bg=VF_BG, fg=VF_TEXT_FAINT,
                                       font=(FONT_FAMILY, 8), anchor="w")
            lbl_stage_text.pack(side="left")

            # 검증 아이콘 (초기에는 숨김)
            val_icons = {}
            for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형")]:
                lbl = tk.Label(status_val_frame, text=f"  {label}", bg=VF_BG,
                               fg=VF_TEXT_FAINT, font=(FONT_FAMILY, 8))
                val_icons[key] = lbl

            file_rows[fname] = {
                "frame": row, "sel_bar": sel_bar, "content": content,
                "pips": pips, "lbl_icon": lbl_icon, "lbl_name": lbl_name,
                "lbl_stage_text": lbl_stage_text, "lbl_result": lbl_result,
                "val_icons": val_icons,
                "status_val_frame": status_val_frame, "idx": idx, "top": top,
            }

            # 클릭 바인딩
            all_widgets = [row, sel_bar, content, top, lbl_icon, lbl_name,
                          pip_frame, status_val_frame, lbl_stage_text, lbl_result] + pips
            for w in all_widgets:
                w.bind("<Button-1>", lambda e, i=idx: _show(i))
                w.bind("<MouseWheel>", _on_mousewheel)

            return row

        def _update_row_stages(fname):
            if fname not in file_rows:
                return
            row_info = file_rows[fname]
            stage_data = self._vf_file_stages.get(fname, {}).get("stages", {})
            status = self._vf_file_stages.get(fname, {}).get("status", "pending")

            active_stage_name = ""
            for i, s in enumerate(self._VF_STAGES):
                st = stage_data.get(s, "")
                if st == "done":
                    row_info["pips"][i].configure(bg=VF_GREEN)
                elif st == "fail":
                    row_info["pips"][i].configure(bg=VF_RED)
                elif st == "active":
                    row_info["pips"][i].configure(bg=VF_ACCENT)
                    active_stage_name = s
                elif st == "skip":
                    row_info["pips"][i].configure(bg=VF_PIP_SKIP)
                else:
                    row_info["pips"][i].configure(bg=VF_PIP_BG)

            # 상태 텍스트 + 검증 아이콘 업데이트
            validation = self._vf_file_stages.get(fname, {}).get("validation")
            val_icons = row_info.get("val_icons", {})

            lbl_result = row_info.get("lbl_result")
            _route_text  = {
                "full_shadow":    "전체컷",
                "detail_bg_only": "디테일(흰배경)",
                "claid_only":     "배경없는 디테일",
                "top_down_only":  "수직촬영",
                "label_skip":     "라벨/바코드",
            }
            _route_color = {
                "full_shadow":    "#3b82f6",
                "detail_bg_only": "#d97706",
                "claid_only":     "#16a34a",
                "top_down_only":  "#7c3aed",
                "label_skip":     "#6b7280",
            }

            def _route_label(ri):
                """라우트명 + 수행된 작업 배지 텍스트 반환."""
                if not ri:
                    return "완료", VF_GREEN
                route = ri.get("route", "")
                performed = ri.get("performed", [])
                ops = ("  " + "  ".join(f"[{op}]" for op in performed)) if performed else ""
                return _route_text.get(route, "완료") + ops, _route_color.get(route, VF_GREEN)

            if status == "processing":
                row_info["lbl_stage_text"].config(
                    text="처리 중..." if not active_stage_name else f"{active_stage_name} 중...",
                    fg=VF_ACCENT)
                row_info["lbl_stage_text"].pack(side="left")
                if lbl_result:
                    lbl_result.config(text="")
                for lbl in val_icons.values():
                    lbl.pack_forget()
            elif status == "done" and validation:
                # 완료 + 검증 결과: 라우팅 텍스트(좌) + 검증 아이콘
                ri = self._vf_file_stages.get(fname, {}).get("routing_info")
                txt, clr = _route_label(ri)
                row_info["lbl_stage_text"].config(text=txt, fg=clr)
                row_info["lbl_stage_text"].pack(side="left")
                for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형")]:
                    lbl = val_icons.get(key)
                    if not lbl:
                        continue
                    item = validation.get(key, {})
                    is_pass = item.get("pass", True)
                    mark = "\u2705" if is_pass else "\u274c"
                    color = VF_GREEN if is_pass else VF_RED
                    lbl.config(text=f"{mark}{label}", fg=color)
                    lbl.pack(side="left", padx=(0, 6))
                if lbl_result:
                    lbl_result.config(text="성공", fg=VF_GREEN)
            elif status == "done":
                ri = self._vf_file_stages.get(fname, {}).get("routing_info")
                txt, clr = _route_label(ri)
                row_info["lbl_stage_text"].config(text=txt, fg=clr)
                row_info["lbl_stage_text"].pack(side="left")
                if lbl_result:
                    lbl_result.config(text="성공", fg=VF_GREEN)
                for lbl in val_icons.values():
                    lbl.pack_forget()
            elif status == "fail":
                row_info["lbl_stage_text"].config(text="", fg=VF_TEXT_FAINT)
                row_info["lbl_stage_text"].pack(side="left")
                if lbl_result:
                    lbl_result.config(text="실패", fg=VF_RED)
                for lbl in val_icons.values():
                    lbl.pack_forget()
            else:
                row_info["lbl_stage_text"].config(text="")
                if lbl_result:
                    lbl_result.config(text="")
                for lbl in val_icons.values():
                    lbl.pack_forget()

            # 아이콘 업데이트
            validation = self._vf_file_stages.get(fname, {}).get("validation")
            if validation and not validation.get("overall", True):
                icon = "\u26a0\ufe0f"
            else:
                icon = {"done": "\u2705", "processing": "\u23f3", "fail": "\u274c"}.get(status, "\u2b1c")
            row_info["lbl_icon"].config(text=icon)

            # 대기 파일 투명도 효과
            opacity_fg = VF_TEXT if status != "pending" else VF_TEXT_FAINT
            row_info["lbl_name"].config(fg=opacity_fg)

        def _highlight_row(idx):
            for fname, info in file_rows.items():
                is_sel = (info["idx"] == idx)
                bg = VF_CARD if is_sel else VF_BG
                bar_bg = VF_ACCENT if is_sel else VF_BG
                info["sel_bar"].configure(bg=bar_bg)
                widgets = [info["frame"], info["content"], info["top"],
                           info["lbl_icon"], info["lbl_name"], info["lbl_stage_text"],
                           info.get("status_val_frame")]
                # 검증 아이콘 라벨들도 bg 업데이트
                for lbl in info.get("val_icons", {}).values():
                    widgets.append(lbl)
                for w in widgets:
                    if w is None:
                        continue
                    try:
                        w.configure(bg=bg)
                    except Exception:
                        pass
                # pip_frame bg
                for child in info["content"].winfo_children():
                    if isinstance(child, tk.Frame) and child != info["top"]:
                        try:
                            child.configure(bg=bg)
                        except Exception:
                            pass

        # 네비게이션
        nav = tk.Frame(left, bg=VF_BG)
        nav.pack(fill="x", padx=8, pady=(6, 8))
        tk.Frame(nav, bg=VF_BORDER, height=1).pack(fill="x", pady=(0, 6))

        btn_prev = tk.Button(nav, text="\u25c0 이전", bg=VF_CARD, fg=VF_TEXT,
                             font=(FONT_FAMILY, 9), bd=0, padx=10, pady=3,
                             activebackground=VF_ACCENT, activeforeground=VF_BG,
                             cursor="hand2", command=lambda: _go(-1))
        btn_prev.pack(side="left", padx=(0, 4))
        lbl_count = tk.Label(nav, text="0 / 0", bg=VF_BG, fg=VF_TEXT_DIM,
                             font=(FONT_FAMILY, 9))
        lbl_count.pack(side="left", padx=6)
        btn_next = tk.Button(nav, text="다음 \u25b6", bg=VF_CARD, fg=VF_TEXT,
                             font=(FONT_FAMILY, 9), bd=0, padx=10, pady=3,
                             activebackground=VF_ACCENT, activeforeground=VF_BG,
                             cursor="hand2", command=lambda: _go(1))
        btn_next.pack(side="left", padx=(4, 0))

        # ── 우측: 이미지 비교 영역 ──
        right = tk.Frame(main, bg=VF_BG)
        right.pack(side="left", fill="both", expand=True)

        # 라벨 행: 원본 / 처리 결과
        lbl_row = tk.Frame(right, bg=VF_BG)
        lbl_row.pack(fill="x", padx=12, pady=(8, 0))
        lbl_left_title = tk.Label(lbl_row, text="\U0001f4f7  원본", bg=VF_BG, fg="#bac2de",
                 font=(FONT_FAMILY, 11, "bold"))
        lbl_left_title.pack(side="left", expand=True)
        lbl_right_title = tk.Label(lbl_row, text="\u2728  처리 결과", bg=VF_BG, fg="#bac2de",
                 font=(FONT_FAMILY, 11, "bold"))
        lbl_right_title.pack(side="left", expand=True)

        # 단계별 보기 탭 바
        _STAGE_TABS = ["비교", "원본", "누끼", "보정", "그림자", "최종"]
        stage_tab_frame = tk.Frame(right, bg=VF_BG)
        stage_tab_frame.pack(fill="x", padx=12, pady=(4, 4))
        stage_mode = [None]  # None = 비교 모드
        stage_tab_btns = {}

        def _select_stage_tab(tab_name):
            stage_mode[0] = None if tab_name == "비교" else tab_name
            for name, btn in stage_tab_btns.items():
                if name == tab_name:
                    btn.configure(bg=VF_ACCENT, fg=VF_BG)
                else:
                    btn.configure(bg=VF_CARD, fg=VF_TEXT)
            _show(current_idx[0], out_idx[0])

        for tab in _STAGE_TABS:
            btn = tk.Button(stage_tab_frame, text=tab, bg=VF_CARD, fg=VF_TEXT,
                            font=(FONT_FAMILY, 9), bd=0, padx=8, pady=2,
                            activebackground=VF_ACCENT, activeforeground=VF_BG,
                            cursor="hand2",
                            command=lambda t=tab: _select_stage_tab(t))
            btn.pack(side="left", padx=2)
            stage_tab_btns[tab] = btn
        # 기본: 비교 탭 활성
        stage_tab_btns["비교"].configure(bg=VF_ACCENT, fg=VF_BG)

        # 캔버스 영역
        canvas_frame = tk.Frame(right, bg=VF_BG)
        canvas_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.columnconfigure(1, weight=0)
        canvas_frame.columnconfigure(2, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        cv_orig = tk.Canvas(canvas_frame, bg=VF_IMG_BG, highlightthickness=0, bd=0)
        cv_orig.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        # 보라색 중앙 구분선
        sep_canvas = tk.Canvas(canvas_frame, width=2, bg=VF_PURPLE, highlightthickness=0, bd=0)
        sep_canvas.grid(row=0, column=1, sticky="ns")
        cv_proc = tk.Canvas(canvas_frame, bg=VF_IMG_BG, highlightthickness=0, bd=0)
        cv_proc.grid(row=0, column=2, sticky="nsew", padx=(1, 0))

        # 정보 행
        info_row = tk.Frame(right, bg=VF_BG)
        info_row.pack(fill="x", padx=12, pady=(4, 0))
        lbl_orig_info = tk.Label(info_row, text="", bg=VF_BG, fg=VF_TEXT_DIM,
                                 font=(FONT_FAMILY, 9))
        lbl_orig_info.pack(side="left", expand=True)
        lbl_out_sel = tk.Label(info_row, text="", bg=VF_BG, fg=VF_PURPLE,
                               font=(FONT_FAMILY, 9))
        lbl_out_sel.pack(side="left")
        lbl_proc_info = tk.Label(info_row, text="", bg=VF_BG, fg=VF_TEXT_DIM,
                                 font=(FONT_FAMILY, 9))
        lbl_proc_info.pack(side="left", expand=True)

        # 검증 결과 행
        val_row = tk.Frame(right, bg=VF_BG)
        val_row.pack(fill="x", padx=12, pady=(4, 0))
        lbl_val = tk.Label(val_row, text="", bg=VF_BG, font=(FONT_FAMILY, 9))
        lbl_val.pack(side="left", expand=True)

        def _update_validation_display(pair):
            validation = pair.get("validation")
            if not validation or validation.get("overall") is None:
                lbl_val.config(text="", fg=VF_TEXT_DIM)
                return
            parts = []
            for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형")]:
                item = validation.get(key, {})
                is_pass = item.get("pass", True)
                mark = "\u2705" if is_pass else "\u274c"
                parts.append(f"{mark}{label}")
            overall = validation.get("overall", True)
            color = VF_GREEN if overall else VF_RED
            text = "  ".join(parts)
            fails = []
            for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형")]:
                item = validation.get(key, {})
                if not item.get("pass", True):
                    detail = item.get("detail", "")
                    if detail:
                        fails.append(f"{label}: {detail}")
            if fails:
                text += "  |  " + " / ".join(fails)
            lbl_val.config(text=text, fg=color)

        # Vision API 판단 정보 행
        vision_row = tk.Frame(right, bg=VF_BG)
        vision_row.pack(fill="x", padx=12, pady=(2, 0))
        lbl_vision = tk.Label(vision_row, text="", bg=VF_BG, fg=VF_TEXT_DIM,
                              font=(FONT_FAMILY, 9), anchor="w", justify="left")
        lbl_vision.pack(side="left", expand=True, fill="x")

        # 라우팅 배지 행 (임시옵션 탭 전용)
        routing_row = tk.Frame(right, bg=VF_BG)
        routing_row.pack(fill="x", padx=12, pady=(2, 0))
        lbl_routing = tk.Label(routing_row, text="", bg=VF_BG,
                               font=(FONT_FAMILY, 9, "bold"), anchor="w")
        lbl_routing.pack(side="left")

        _ROUTE_STYLES = {
            "full_shadow":    ("\U0001f535 전체컷  →  누끼 + 그림자 + 보정",              "#3b82f6"),
            "detail_bg_only": ("\U0001f7e1 디테일컷 (흰배경)  →  누끼 + 보정",           "#d97706"),
            "claid_only":     ("\U0001f7e2 배경없는 디테일컷  →  보정만",                "#16a34a"),
            "top_down_only":  ("\U0001f7e3 수직촬영(탑다운)  →  보정만  (누끼·그림자 제외)", "#7c3aed"),
            "label_skip":     ("\u26aa 라벨/바코드컷  →  처리 없음  (원본 그대로)",        "#6b7280"),
        }

        def _update_routing_display(pair):
            ri = pair.get("routing_info")
            if not ri:
                lbl_routing.config(text="")
                routing_row.pack_forget()
                return
            route = ri.get("route", "")
            text, color = _ROUTE_STYLES.get(route, (f"? {route}", VF_TEXT_DIM))
            bg_val = ri.get("background", "")
            img_t = ri.get("image_type", "")
            detail = f"  ({img_t} / bg={bg_val})" if img_t else ""
            performed = ri.get("performed", [])
            ops_text = ("  ▶ " + " · ".join(performed)) if performed else ""
            lbl_routing.config(text=text + detail + ops_text, fg=color)
            routing_row.pack(fill="x", padx=12, pady=(2, 0))

        def _update_vision_display(pair):
            vi = pair.get("vision_info")
            if not vi:
                lbl_vision.config(text="", fg=VF_TEXT_DIM)
                return
            angle = vi.get("shooting_angle", "?")
            floor = "\u2705" if vi.get("floor_visible") else "\u274c"
            shadow = "\u2705" if vi.get("needs_shadow") else "\u274c"
            conf = vi.get("shadow_confidence", 0)
            reason = vi.get("shadow_reason", "")
            cat = vi.get("category", "")
            hand = "\u270b" if vi.get("has_human_hand") else ""
            mannequin = "\U0001f9cd" if vi.get("has_mannequin") else ""
            angle_kr = {"front": "\uc815\uba74", "top_down": "\ud0d1\ub2e4\uc6b4",
                        "side": "\uce21\uba74", "detail": "\ub514\ud14c\uc77c",
                        "held": "\uc190\uc7a1\uc774", "worn": "\ucc29\uc6a9"}.get(angle, angle)
            full_body = vi.get("is_full_body")
            full_tag = ""
            if angle == "worn" and full_body is not None:
                full_tag = "\U0001f455\ud480\uc0f7" if full_body else "\U0001f455\ubc18\uc2e0"
            parts = [
                f"\U0001f3af {cat}" if cat else "",
                f"\U0001f4d0 {angle_kr}",
                full_tag,
                f"\U0001f6b6 \ubc14\ub2e5{floor}",
                f"\U0001f4a1 \uadf8\ub9bc\uc790{shadow}({conf:.0%})",
                hand, mannequin,
                f"\u2192 {reason}" if reason else "",
            ]
            text = "  ".join(p for p in parts if p)
            shadow_on = vi.get("needs_shadow", False)
            lbl_vision.config(text=text, fg=VF_ACCENT if shadow_on else VF_TEXT_DIM)

        # ── 독립 평가 + 자동수정 패널 ──
        eval_panel = tk.Frame(right, bg=VF_BG)
        eval_panel.pack(fill="x", padx=12, pady=(4, 0))

        tk.Frame(eval_panel, bg=VF_BORDER, height=1).pack(fill="x", pady=(0, 6))

        eval_score_row = tk.Frame(eval_panel, bg=VF_BG)
        eval_score_row.pack(fill="x")

        lbl_eval_title = tk.Label(eval_score_row, text="", bg=VF_BG, fg=VF_PURPLE,
                                   font=(FONT_FAMILY, 9, "bold"), anchor="w")
        lbl_eval_title.pack(side="left")

        eval_score_labels = {}
        for cat_key, label in [("shadow_natural", "\uadf8\ub9bc\uc790"), ("background_clean", "\ubc30\uacbd"),
                                ("edge_quality", "\uacbd\uacc4\uc120"), ("product_integrity", "\ubcf4\uc874"),
                                ("commercial_quality", "\uc0c1\uc5c5\uc131")]:
            lbl = tk.Label(eval_score_row, text="", bg=VF_BG, fg=VF_TEXT_DIM,
                           font=(FONT_FAMILY, 8))
            lbl.pack(side="left", padx=(6, 0))
            eval_score_labels[cat_key] = lbl

        lbl_eval_issues = tk.Label(eval_panel, text="", bg=VF_BG, fg=VF_YELLOW,
                                    font=(FONT_FAMILY, 8), anchor="w", wraplength=600,
                                    justify="left")
        lbl_eval_issues.pack(fill="x", pady=(2, 0))

        feedback_row = tk.Frame(eval_panel, bg=VF_BG)
        feedback_row.pack(fill="x", pady=(4, 0))

        tk.Label(feedback_row, text="\uc758\uacac:", bg=VF_BG, fg=VF_TEXT_DIM,
                 font=(FONT_FAMILY, 9)).pack(side="left")

        eval_feedback_entry = tk.Entry(feedback_row, bg=VF_CARD, fg=VF_TEXT,
                                        font=(FONT_FAMILY, 9), insertbackground=VF_TEXT,
                                        relief="flat", bd=0)
        eval_feedback_entry.pack(side="left", fill="x", expand=True, padx=(4, 4), ipady=3)
        eval_feedback_entry.insert(0, "")

        def _entry_focus_in(e):
            eval_feedback_entry._has_focus = True

        def _entry_focus_out(e):
            eval_feedback_entry._has_focus = False

        eval_feedback_entry._has_focus = False
        eval_feedback_entry.bind("<FocusIn>", _entry_focus_in)
        eval_feedback_entry.bind("<FocusOut>", _entry_focus_out)
        eval_feedback_entry.bind("<Escape>", lambda e: dlg.focus_set())

        btn_row = tk.Frame(eval_panel, bg=VF_BG)
        btn_row.pack(fill="x", pady=(4, 4))

        lbl_autofix_status = tk.Label(btn_row, text="", bg=VF_BG, fg=VF_TEXT_DIM,
                                       font=(FONT_FAMILY, 8), anchor="w")
        lbl_autofix_status.pack(side="left", padx=(0, 8))

        btn_autofix = tk.Button(btn_row, text="\U0001f504 \uc790\ub3d9\uc218\uc815 (\ud504\ub86c\ud504\ud2b8)",
                                bg="#45475a", fg=VF_TEXT, font=(FONT_FAMILY, 9),
                                bd=0, padx=10, pady=3, cursor="hand2",
                                activebackground=VF_ACCENT, activeforeground=VF_BG,
                                state="disabled")
        btn_autofix.pack(side="right", padx=(4, 0))

        btn_val_feedback = tk.Button(btn_row, text="\U0001f4dd \uac80\uc99d\uc218\uc815",
                                bg="#45475a", fg=VF_TEXT, font=(FONT_FAMILY, 9),
                                bd=0, padx=10, pady=3, cursor="hand2",
                                activebackground="#d97706", activeforeground=VF_BG,
                                state="disabled")
        btn_val_feedback.pack(side="right", padx=(4, 0))

        btn_claude = tk.Button(btn_row, text="\U0001f4cb \ud074\ub85c\ub4dc \ubcf5\uc0ac",
                               bg="#45475a", fg=VF_TEXT, font=(FONT_FAMILY, 9),
                               bd=0, padx=10, pady=3, cursor="hand2",
                               activebackground=VF_PURPLE, activeforeground=VF_BG,
                               state="disabled")
        btn_claude.pack(side="right", padx=(4, 0))

        # ── 수동 재처리 패널 ──────────────────────────────────────────────────
        rp_panel = tk.Frame(right, bg=VF_BG)
        rp_panel.pack(fill="x", padx=12, pady=(6, 0))

        tk.Frame(rp_panel, bg=VF_BORDER, height=1).pack(fill="x", pady=(0, 6))

        tk.Label(rp_panel, text="\u270f\ufe0f  \uc218\ub3d9 \uc7ac\uc791\uc5c5",
                 bg=VF_BG, fg="#bac2de", font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")

        # 누끼 방식 선택
        nukki_row = tk.Frame(rp_panel, bg=VF_BG)
        nukki_row.pack(fill="x", pady=(4, 0))
        tk.Label(nukki_row, text="\ub204\ub07c:", bg=VF_BG, fg=VF_TEXT_DIM,
                 font=(FONT_FAMILY, 9), width=5, anchor="w").pack(side="left")
        rp_nukki_var = tk.StringVar(value="\uc5c6\uc74c")
        for label in ["\uc5c6\uc74c", "Photoroom", "RemoveBG"]:
            tk.Radiobutton(nukki_row, text=label, variable=rp_nukki_var, value=label,
                           bg=VF_BG, fg=VF_TEXT, selectcolor=VF_CARD,
                           activebackground=VF_BG, font=(FONT_FAMILY, 9),
                           cursor="hand2").pack(side="left", padx=(0, 8))

        # 보정 선택
        enhance_row = tk.Frame(rp_panel, bg=VF_BG)
        enhance_row.pack(fill="x", pady=(2, 0))
        tk.Label(enhance_row, text="\ubcf4\uc815:", bg=VF_BG, fg=VF_TEXT_DIM,
                 font=(FONT_FAMILY, 9), width=5, anchor="w").pack(side="left")
        rp_enhance_var = tk.BooleanVar(value=True)
        tk.Checkbutton(enhance_row, text="Claid \ubcf4\uc815", variable=rp_enhance_var,
                       bg=VF_BG, fg=VF_TEXT, selectcolor=VF_CARD,
                       activebackground=VF_BG, font=(FONT_FAMILY, 9),
                       cursor="hand2").pack(side="left")

        # 버튼 행
        rp_btn_row = tk.Frame(rp_panel, bg=VF_BG)
        rp_btn_row.pack(fill="x", pady=(6, 4))

        lbl_rp_status = tk.Label(rp_btn_row, text="", bg=VF_BG, fg=VF_TEXT_DIM,
                                  font=(FONT_FAMILY, 8), anchor="w")
        lbl_rp_status.pack(side="left", fill="x", expand=True)

        btn_rp_confirm = tk.Button(rp_btn_row,
                                    text="\u2713 \uc218\uc815\uc644\ub8cc (\ud30c\uc77c \uad50\uccb4)",
                                    bg="#166534", fg="white", font=(FONT_FAMILY, 9),
                                    bd=0, padx=10, pady=3, cursor="hand2",
                                    state="disabled")
        btn_rp_confirm.pack(side="right", padx=(4, 0))

        btn_rp_run = tk.Button(rp_btn_row, text="\u25b6 \uc7ac\uc791\uc5c5 \uc2e4\ud589",
                                bg="#2563eb", fg="white", font=(FONT_FAMILY, 9),
                                bd=0, padx=10, pady=3, cursor="hand2")
        btn_rp_run.pack(side="right", padx=(4, 0))

        rp_result_bytes = [None]  # 재처리 결과 (수정완료 전까지 임시 보관)

        def _on_rp_run():
            pairs = self._viewfinder_pairs
            if not pairs or current_idx[0] >= len(pairs):
                return
            pair = pairs[current_idx[0]]
            input_path = pair.get("input_path", "")
            if not input_path or not Path(input_path).exists():
                lbl_rp_status.config(text="\uc6d0\ubcf8 \ud30c\uc77c \uc5c6\uc74c", fg=VF_RED)
                return

            nukki_mode = rp_nukki_var.get()
            use_enhance = rp_enhance_var.get()

            btn_rp_run.config(state="disabled", text="\u23f3 \ucc98\ub9ac \uc911...")
            btn_rp_confirm.config(state="disabled")
            lbl_rp_status.config(text="\ucc98\ub9ac \uc900\ube44 \uc911...", fg=VF_ACCENT)
            rp_result_bytes[0] = None

            def _run():
                try:
                    from src.pipeline import ImageEditPipeline
                    from src.photoroom.client import PhotoroomClient
                    from src.removebg.client import RemoveBgClient
                    from src.claid.client import ClaidClient
                    import tempfile

                    image_bytes = Path(input_path).read_bytes()
                    current = image_bytes
                    steps_done = []

                    # 누끼
                    if nukki_mode == "Photoroom":
                        dlg.after(0, lambda: lbl_rp_status.config(
                            text="Photoroom \ub204\ub07c \uc791\uc5c5 \uc911...", fg=VF_ACCENT))
                        pr = PhotoroomClient()
                        pr_config = {
                            "background.color": "FFFFFF",
                            "export.format": "jpg",
                            "outputSize": "1000x1000",
                            "padding": "0.1",
                            "scaling": "fit",
                        }
                        res = pr.process(current, "full", "clean",
                                         output_size="1000x1000", config=pr_config)
                        if res:
                            current = res
                            steps_done.append("누끼(Photoroom)")
                    elif nukki_mode == "RemoveBG":
                        dlg.after(0, lambda: lbl_rp_status.config(
                            text="RemoveBG \ub204\ub07c \uc791\uc5c5 \uc911...", fg=VF_ACCENT))
                        rb = RemoveBgClient()
                        res = rb.process(current)
                        if res:
                            current = res
                            steps_done.append("누끼(RemoveBG)")

                    # 보정
                    if use_enhance:
                        dlg.after(0, lambda: lbl_rp_status.config(
                            text="Claid \ubcf4\uc815 \uc911...", fg=VF_ACCENT))
                        pl = ImageEditPipeline(config_dir=str(CONFIG_DIR))
                        claid_settings = pl._settings.get("claid", {})
                        claid_config = dict(claid_settings.get("full", {}))
                        cl = ClaidClient()
                        res = cl.process(current, "full", config=claid_config)
                        if res:
                            current = res
                            steps_done.append("보정(Claid)")

                    rp_result_bytes[0] = current
                    size_kb = len(current) // 1024

                    # 임시 파일에 저장 (뷰파인더 표시용)
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    tmp.write(current)
                    tmp.close()
                    pair["_rp_temp_path"] = tmp.name

                    steps_text = " + ".join(steps_done) if steps_done else "\ubcc0\ud658 \uc5c6\uc74c"

                    def _done():
                        lbl_rp_status.config(
                            text=f"\uc644\ub8cc: {steps_text}  ({size_kb}KB)", fg=VF_GREEN)
                        btn_rp_run.config(state="normal", text="\u25b6 \uc7ac\uc791\uc5c5 \uc2e4\ud589")
                        btn_rp_confirm.config(state="normal")
                        # 뷰파인더 우측 이미지 갱신
                        try:
                            from PIL import Image as _PILImage
                            img = _PILImage.open(tmp.name)
                            _fit_image(cv_proc, img)
                            lbl_right_title.config(text="\u270f\ufe0f  \uc7ac\ucc98\ub9ac \uacb0\uacfc (\ubbf8\ud655\uc815)")
                            lbl_proc_info.config(text=f"\uc7ac\ucc98\ub9ac  \u00b7  {size_kb}KB")
                        except Exception:
                            pass
                    dlg.after(0, _done)

                except Exception as e:
                    import traceback as _tb
                    err_msg = str(e)
                    tb_str = _tb.format_exc()

                    def _err():
                        lbl_rp_status.config(text=f"\uc624\ub958: {err_msg[:50]}", fg=VF_RED)
                        btn_rp_run.config(state="normal", text="\u25b6 \uc7ac\uc791\uc5c5 \uc2e4\ud589")
                        self._log_unified(tb_str, "error")
                    dlg.after(0, _err)

            threading.Thread(target=_run, daemon=True).start()

        def _on_rp_confirm():
            if rp_result_bytes[0] is None:
                return
            pairs = self._viewfinder_pairs
            if not pairs or current_idx[0] >= len(pairs):
                return
            pair = pairs[current_idx[0]]
            out_files = pair.get("output_files", [])
            if not out_files:
                lbl_rp_status.config(text="\ucd9c\ub825 \ud30c\uc77c \uc815\ubcf4 \uc5c6\uc74c", fg=VF_RED)
                return
            out_path = out_files[0]["path"]
            try:
                Path(out_path).write_bytes(rp_result_bytes[0])
                lbl_rp_status.config(
                    text=f"\u2713 \uc800\uc7a5 \uc644\ub8cc: {Path(out_path).name}", fg=VF_GREEN)
                btn_rp_confirm.config(state="disabled")
                rp_result_bytes[0] = None
                lbl_right_title.config(text="\u2728  \ucc98\ub9ac \uacb0\uacfc")
                _show(current_idx[0], out_idx[0])
            except Exception as e:
                lbl_rp_status.config(text=f"\uc800\uc7a5 \uc2e4\ud328: {e}", fg=VF_RED)

        btn_rp_run.config(command=_on_rp_run)
        btn_rp_confirm.config(command=_on_rp_confirm)
        # ─────────────────────────────────────────────────────────────────────

        def _update_eval_panel(pair):
            ind_eval = pair.get("independent_eval")
            validation = pair.get("validation")
            # 검증수정 버튼: 독립평가 또는 검증 결과가 있으면 활성화
            has_val_fail = (validation and not validation.get("overall", True))
            has_eval = bool(ind_eval and ind_eval.get("overall_score"))
            btn_val_feedback.config(state="normal" if (has_val_fail or has_eval) else "disabled")
            if not ind_eval or not ind_eval.get("overall_score"):
                lbl_eval_title.config(text="")
                for lbl in eval_score_labels.values():
                    lbl.config(text="")
                lbl_eval_issues.config(text="")
                btn_autofix.config(state="disabled")
                btn_claude.config(state="disabled")
                lbl_autofix_status.config(text="")
                return

            overall = ind_eval.get("overall_score", 0)
            if overall >= 8:
                score_color = VF_GREEN
            elif overall >= 5:
                score_color = VF_YELLOW
            else:
                score_color = VF_RED
            lbl_eval_title.config(text=f"\ub3c5\ub9bd\ud3c9\uac00 {overall}/10", fg=score_color)

            label_map = {
                "shadow_natural": "\uadf8\ub9bc\uc790",
                "background_clean": "\ubc30\uacbd",
                "edge_quality": "\uacbd\uacc4\uc120",
                "product_integrity": "\ubcf4\uc874",
                "commercial_quality": "\uc0c1\uc5c5\uc131",
            }
            for cat_key, lbl in eval_score_labels.items():
                item = ind_eval.get(cat_key, {})
                score = item.get("score", 0)
                label_text = label_map.get(cat_key, cat_key)
                if score >= 8:
                    color = VF_GREEN
                elif score >= 7:
                    color = VF_TEXT_DIM
                elif score >= 5:
                    color = VF_YELLOW
                else:
                    color = VF_RED
                lbl.config(text=f"{label_text}{score}", fg=color)

            critical = ind_eval.get("critical_issues", [])
            rec = ind_eval.get("recommendation", "")
            issue_parts = []
            if critical:
                issue_parts.extend(critical)
            if rec:
                bulb = "\U0001f4a1"
                issue_parts.append(f"{bulb} {rec}")
            lbl_eval_issues.config(text=" | ".join(issue_parts) if issue_parts else "")

            btn_autofix.config(state="normal")
            btn_claude.config(state="normal")

        def _on_autofix():
            pairs = self._viewfinder_pairs
            if not pairs or current_idx[0] >= len(pairs):
                return
            pair = pairs[current_idx[0]]
            ind_eval = pair.get("independent_eval")
            if not ind_eval:
                return

            user_fb = eval_feedback_entry.get().strip()
            btn_autofix.config(state="disabled", text="\u23f3 AI \uc9c8\ubb38 \uc911...")
            lbl_autofix_status.config(text="AI\uc5d0\uac8c \ud504\ub86c\ud504\ud2b8 \ucd94\ucc9c \uc694\uccad \uc911...", fg=VF_ACCENT)
            dlg.update()

            vi = pair.get("vision_info", {})
            input_path = pair.get("input_path", "")
            fname = Path(input_path).name
            stage_data = self._vf_file_stages.get(fname, {}).get("stage_images", {})

            enhance_path = stage_data.get("\ubcf4\uc815")
            nukki_path = stage_data.get("\ub204\ub07c")

            if not enhance_path or not Path(enhance_path).exists():
                lbl_autofix_status.config(text="\ubcf4\uc815 \ub2e8\uacc4 \uc774\ubbf8\uc9c0 \uc5c6\uc74c", fg=VF_RED)
                btn_autofix.config(state="normal", text="\U0001f504 \uc790\ub3d9\uc218\uc815 (\ud504\ub86c\ud504\ud2b8)")
                return

            def _step1_ask_ai():
                """1단계: AI에게 프롬프트 추천 요청 (백그라운드)"""
                try:
                    from src.pipeline import ImageEditPipeline
                    pipe = ImageEditPipeline(config_dir=str(CONFIG_DIR))

                    def _log_to_status(msg, tag="info"):
                        clean_msg = msg.strip()
                        if len(clean_msg) > 60:
                            clean_msg = clean_msg[:57] + "..."
                        color_map = {"success": VF_GREEN, "warn": VF_YELLOW, "error": VF_RED}
                        color = color_map.get(tag, VF_TEXT_DIM)
                        dlg.after(0, lambda m=clean_msg, c=color:
                                  lbl_autofix_status.config(text=m, fg=c))

                    preview = pipe.preview_prompt_fix(
                        evaluation=ind_eval,
                        user_feedback=user_fb,
                        image_type=vi.get("image_type", "full"),
                        category=vi.get("category", ""),
                        shooting_angle=vi.get("shooting_angle", "front"),
                        on_log=_log_to_status,
                    )

                    # UI 스레드에서 미리보기 다이얼로그 표시
                    dlg.after(0, lambda: _step2_show_preview(preview, pipe))

                except Exception as e:
                    err_msg = str(e)[:50]
                    dlg.after(0, lambda m=err_msg: lbl_autofix_status.config(
                        text=f"\uc624\ub958: {m}", fg=VF_RED))
                    dlg.after(0, lambda: btn_autofix.config(
                        state="normal", text="\U0001f504 \uc790\ub3d9\uc218\uc815 (\ud504\ub86c\ud504\ud2b8)"))

            def _step2_show_preview(preview, pipe):
                """2단계: 미리보기 다이얼로그 표시 (UI 스레드)"""
                suggested = preview.get("suggested_hint", "")
                if not suggested:
                    lbl_autofix_status.config(
                        text="AI \ucd94\ucc9c \ud504\ub86c\ud504\ud2b8 \uc5c6\uc74c", fg=VF_YELLOW)
                    btn_autofix.config(state="normal",
                                       text="\U0001f504 \uc790\ub3d9\uc218\uc815 (\ud504\ub86c\ud504\ud2b8)")
                    return

                # ── 미리보기 팝업 ──
                pop = tk.Toplevel(dlg)
                pop.title("\ud504\ub86c\ud504\ud2b8 \ubcc0\uacbd \ubbf8\ub9ac\ubcf4\uae30")
                pop.geometry("700x620")
                pop.transient(dlg)
                pop.grab_set()
                pop.configure(bg=VF_BG)

                prov_name = preview.get("provider_name", "")
                hint_key = preview.get("hint_key", "")
                current = preview.get("current_hint", "")

                # 헤더
                tk.Label(pop, text=f"{prov_name} AI \ucd94\ucc9c \ud504\ub86c\ud504\ud2b8",
                         bg=VF_BG, fg=VF_ACCENT,
                         font=(FONT_FAMILY, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
                tk.Label(pop, text=f"\uc800\uc7a5 \ud0a4: {hint_key}",
                         bg=VF_BG, fg=VF_TEXT_DIM,
                         font=(FONT_FAMILY, 9)).pack(anchor="w", padx=16, pady=(0, 8))

                # 현재 프롬프트
                tk.Label(pop, text="\u25b6 \ud604\uc7ac \ud504\ub86c\ud504\ud2b8:",
                         bg=VF_BG, fg=VF_TEXT_DIM,
                         font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=16, pady=(4, 2))
                cur_text = scrolledtext.ScrolledText(pop, height=6, font=(FONT_FAMILY, 9),
                    bg="#2a2a3a", fg="#a0a0b0", wrap="word", relief="flat", borderwidth=1)
                cur_text.pack(fill="x", padx=16, pady=(0, 8))
                cur_text.insert("1.0", current or "(\uc5c6\uc74c)")
                cur_text.config(state="disabled")

                # 변경 프롬프트 (편집 가능)
                tk.Label(pop, text=f"\u25b6 {prov_name} \ucd94\ucc9c \ud504\ub86c\ud504\ud2b8 (\ud3b8\uc9d1 \uac00\ub2a5):",
                         bg=VF_BG, fg=VF_GREEN,
                         font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=16, pady=(4, 2))
                new_text = scrolledtext.ScrolledText(pop, height=10, font=(FONT_FAMILY, 10),
                    bg="#1a2a1a", fg="#c0e0c0", wrap="word", relief="flat", borderwidth=1,
                    insertbackground="#c0e0c0")
                new_text.pack(fill="x", padx=16, pady=(0, 8))
                new_text.insert("1.0", suggested)

                # 문제 설명 (접기)
                prob_frame = tk.LabelFrame(pop, text=" \ubb38\uc81c \uc124\uba85 (AI\uc5d0\uac8c \uc804\ub2ec\ub41c \ub0b4\uc6a9) ",
                    bg=VF_CARD, fg=VF_TEXT_DIM, font=(FONT_FAMILY, 9))
                prob_frame.pack(fill="x", padx=16, pady=(0, 8))
                prob_lbl = tk.Label(prob_frame, text=preview.get("problem_description", ""),
                    bg=VF_CARD, fg=VF_TEXT_FAINT, font=(FONT_FAMILY, 8),
                    wraplength=650, justify="left")
                prob_lbl.pack(anchor="w", padx=8, pady=4)

                # 미리보기 이미지 영역
                preview_frame = tk.Frame(pop, bg=VF_BG)
                preview_frame.pack(fill="x", padx=16, pady=(0, 8))
                lbl_preview_img = tk.Label(preview_frame, bg=VF_BG)
                lbl_preview_status = tk.Label(preview_frame, text="",
                    bg=VF_BG, fg=VF_TEXT_DIM, font=(FONT_FAMILY, 9))

                # 버튼
                btn_f = tk.Frame(pop, bg=VF_BG)
                btn_f.pack(fill="x", padx=16, pady=(0, 12))

                _preview_result = {"bytes": None}  # 미리보기 결과 저장

                def _on_preview():
                    """프롬프트를 저장하지 않고 결과만 미리보기"""
                    final_hint = new_text.get("1.0", "end-1c").strip()
                    if not final_hint:
                        lbl_preview_status.config(text="프롬프트를 입력하세요", fg=VF_YELLOW)
                        lbl_preview_status.pack(anchor="w")
                        return

                    btn_preview.config(state="disabled", text="⏳ 생성 중...")
                    btn_apply.config(state="disabled")
                    lbl_preview_status.config(text="그림자 생성 중... (프롬프트 미저장)", fg=VF_ACCENT)
                    lbl_preview_status.pack(anchor="w")
                    pop.update()

                    def _run_preview():
                        try:
                            with open(enhance_path, "rb") as f:
                                pre_shadow_bytes = f.read()
                            with open(input_path, "rb") as f:
                                original_bytes = f.read()
                            nukki_bytes = None
                            if nukki_path and Path(nukki_path).exists():
                                with open(nukki_path, "rb") as f:
                                    nukki_bytes = f.read()

                            def _log_preview(msg, tag="info"):
                                clean = msg.strip()
                                if len(clean) > 55:
                                    clean = clean[:52] + "..."
                                color_map = {"success": VF_GREEN, "warn": VF_YELLOW, "error": VF_RED}
                                c = color_map.get(tag, VF_TEXT_DIM)
                                pop.after(0, lambda m=clean, cl=c:
                                          lbl_preview_status.config(text=m, fg=cl))

                            result_bytes = pipe.preview_shadow_only(
                                pre_shadow_bytes=pre_shadow_bytes,
                                original_bytes=original_bytes,
                                nukki_png_bytes=nukki_bytes,
                                temp_hint=final_hint,
                                image_type=vi.get("image_type", "full"),
                                category=vi.get("category", ""),
                                shooting_angle=vi.get("shooting_angle", "front"),
                                has_mannequin=vi.get("has_mannequin", False),
                                on_log=_log_preview,
                            )

                            def _show_preview_result():
                                if result_bytes:
                                    _preview_result["bytes"] = result_bytes
                                    from PIL import Image as _PILImage, ImageTk as _PILImageTk
                                    import io as _io
                                    _img = _PILImage.open(_io.BytesIO(result_bytes))
                                    # 미리보기 크기 조정
                                    disp_w = 660
                                    ratio = disp_w / _img.width
                                    disp_h = int(_img.height * ratio)
                                    if disp_h > 350:
                                        disp_h = 350
                                        ratio = disp_h / _img.height
                                        disp_w = int(_img.width * ratio)
                                    _img_resized = _img.resize((disp_w, disp_h), _PILImage.LANCZOS)
                                    _tk_img = _PILImageTk.PhotoImage(_img_resized)
                                    lbl_preview_img.configure(image=_tk_img)
                                    lbl_preview_img._photo = _tk_img  # 참조 유지
                                    lbl_preview_img.pack(anchor="w", pady=(4, 4))
                                    lbl_preview_status.config(
                                        text="✅ 미리보기 생성 완료 — 만족하면 '적용' 클릭",
                                        fg=VF_GREEN)
                                    btn_apply.config(state="normal")
                                    # 팝업 크기 조정
                                    cur_h = pop.winfo_height()
                                    pop.geometry(f"750x{cur_h + disp_h + 30}")
                                else:
                                    lbl_preview_status.config(
                                        text="그림자 생성 실패", fg=VF_RED)
                                btn_preview.config(state="normal", text="👁 결과 미리보기")

                            pop.after(0, _show_preview_result)

                        except Exception as e:
                            err = str(e)[:50]
                            pop.after(0, lambda m=err: lbl_preview_status.config(
                                text=f"오류: {m}", fg=VF_RED))
                            pop.after(0, lambda: btn_preview.config(
                                state="normal", text="👁 결과 미리보기"))

                    import threading
                    threading.Thread(target=_run_preview, daemon=True).start()

                def _on_apply():
                    """미리보기 확인 후 → 프롬프트 저장 + 결과 적용"""
                    final_hint = new_text.get("1.0", "end-1c").strip()
                    if _preview_result["bytes"]:
                        # 미리보기 결과가 있으면 → 프롬프트 저장 + 결과 바로 적용 (재생성 안 함)
                        pop.destroy()
                        _apply_preview_result(pipe, final_hint, hint_key,
                                              _preview_result["bytes"])
                    else:
                        # 미리보기 없이 적용 → 기존 플로우 (재생성)
                        pop.destroy()
                        _step3_regenerate(pipe, final_hint, hint_key)

                def _on_cancel():
                    pop.destroy()
                    lbl_autofix_status.config(text="사용자 취소", fg=VF_TEXT_DIM)
                    btn_autofix.config(state="normal",
                                       text="🔄 자동수정 (프롬프트)")

                btn_preview = tk.Button(btn_f, text="👁 결과 미리보기",
                          bg="#2563eb", fg="white", font=(FONT_FAMILY, 11, "bold"),
                          activebackground="#1d4ed8", activeforeground="white",
                          relief="flat", cursor="hand2",
                          command=_on_preview)
                btn_preview.pack(side="left", padx=(0, 8), ipady=4)

                btn_apply = tk.Button(btn_f, text="  ✅ 적용 (프롬프트 저장)  ",
                          bg="#16a34a", fg="white", font=(FONT_FAMILY, 10, "bold"),
                          activebackground="#15803d", activeforeground="white",
                          relief="flat", cursor="hand2", state="disabled",
                          command=_on_apply)
                btn_apply.pack(side="left", padx=(0, 8), ipady=4)

                tk.Button(btn_f, text="  취소  ",
                          bg=VF_CARD, fg=VF_TEXT, font=(FONT_FAMILY, 10),
                          activebackground=VF_BORDER, relief="flat", cursor="hand2",
                          command=_on_cancel).pack(side="left", ipady=4)

            def _apply_preview_result(pipe, final_hint, hint_key, result_bytes):
                """미리보기 결과를 확정: 프롬프트 저장 + 이미지 적용 (재생성 안 함)"""
                btn_autofix.config(state="disabled", text="⏳ 적용 중...")
                lbl_autofix_status.config(text="프롬프트 저장 + 결과 적용 중...", fg=VF_ACCENT)
                _regen_fname = Path(input_path).name

                def _run_apply():
                    try:
                        # 프롬프트 저장
                        pipe._save_shadow_hint(hint_key, final_hint)

                        def _finish():
                            # 이미지 저장
                            out_files = pair.get("output_files", [])
                            if out_files:
                                out_path = out_files[0]["path"]
                                from PIL import Image as _PILImage
                                import io as _io
                                _img = _PILImage.open(_io.BytesIO(result_bytes))
                                _img.save(out_path, format="JPEG", quality=95)
                                fsize = Path(out_path).stat().st_size
                                pair["output_files"][0]["size"] = fsize

                            lbl_autofix_status.config(
                                text="✅ 프롬프트 저장 + 결과 적용 완료", fg=VF_GREEN)

                            # 왼쪽 파일 목록 업데이트
                            shadow_idx = self._VF_STAGES.index("그림자") if "그림자" in self._VF_STAGES else -1
                            if _regen_fname in self._vf_file_stages:
                                stages = self._vf_file_stages[_regen_fname].get("stages", {})
                                stages["그림자"] = "done"
                                self._vf_file_stages[_regen_fname]["status"] = "done"
                            if _regen_fname in file_rows:
                                _ri = file_rows[_regen_fname]
                                if shadow_idx >= 0:
                                    _ri["pips"][shadow_idx].configure(bg=VF_GREEN)
                                _ri["lbl_stage_text"].config(
                                    text="🔄적용 완료", fg=VF_GREEN)
                                _ri["lbl_stage_text"].pack(side="left")
                                for lbl in _ri.get("val_icons", {}).values():
                                    lbl.pack_forget()

                            btn_autofix.config(state="normal",
                                               text="🔄 자동수정 (프롬프트)")
                            _show(current_idx[0], out_idx[0])
                            _update_eval_panel(pair)

                        dlg.after(0, _finish)

                    except Exception as e:
                        err_msg = str(e)[:50]
                        dlg.after(0, lambda m=err_msg: lbl_autofix_status.config(
                            text=f"오류: {m}", fg=VF_RED))
                        dlg.after(0, lambda: btn_autofix.config(
                            state="normal", text="🔄 자동수정 (프롬프트)"))

                import threading
                threading.Thread(target=_run_apply, daemon=True).start()

            def _step3_regenerate(pipe, final_hint, hint_key):
                """3단계: 확정 프롬프트로 그림자만 재생성 (백그라운드)"""
                btn_autofix.config(state="disabled", text="\u23f3 \uadf8\ub9bc\uc790 \uc7ac\uc0dd\uc131 \uc911...")
                lbl_autofix_status.config(text="\ubcc0\uacbd\ub41c \ud504\ub86c\ud504\ud2b8\ub85c \uadf8\ub9bc\uc790 \uc7ac\uc0dd\uc131 \uc911...", fg=VF_ACCENT)

                # ── 왼쪽 파일 목록에 "그림자 재생성 중..." 표시 ──
                _regen_fname = Path(input_path).name
                if _regen_fname in self._vf_file_stages:
                    self._vf_file_stages[_regen_fname]["status"] = "processing"
                    stages = self._vf_file_stages[_regen_fname].get("stages", {})
                    # 그림자 단계만 active로, 나머지는 유지
                    for s in self._VF_STAGES:
                        if s == "그림자":
                            stages[s] = "active"
                        elif stages.get(s) == "done":
                            pass  # 이미 완료된 단계는 유지
                    self._vf_file_stages[_regen_fname]["stages"] = stages
                if _regen_fname in file_rows:
                    row_info = file_rows[_regen_fname]
                    row_info["lbl_stage_text"].config(
                        text="\uadf8\ub9bc\uc790 \uc7ac\uc0dd\uc131 \uc911...", fg=VF_ACCENT)
                    row_info["lbl_stage_text"].pack(side="left")
                    for lbl in row_info.get("val_icons", {}).values():
                        lbl.pack_forget()
                    # 그림자 pip을 active 색상으로
                    shadow_idx = self._VF_STAGES.index("그림자") if "그림자" in self._VF_STAGES else -1
                    if shadow_idx >= 0:
                        row_info["pips"][shadow_idx].configure(bg=VF_ACCENT)
                dlg.update()

                def _run_regen():
                    try:
                        with open(enhance_path, "rb") as f:
                            pre_shadow_bytes = f.read()
                        with open(input_path, "rb") as f:
                            original_bytes = f.read()
                        nukki_bytes = None
                        if nukki_path and Path(nukki_path).exists():
                            with open(nukki_path, "rb") as f:
                                nukki_bytes = f.read()

                        def _log_to_status(msg, tag="info"):
                            clean_msg = msg.strip()
                            if len(clean_msg) > 60:
                                clean_msg = clean_msg[:57] + "..."
                            color_map = {"success": VF_GREEN, "warn": VF_YELLOW, "error": VF_RED}
                            color = color_map.get(tag, VF_TEXT_DIM)
                            dlg.after(0, lambda m=clean_msg, c=color:
                                      lbl_autofix_status.config(text=m, fg=c))

                        result = pipe.apply_prompt_and_regenerate(
                            pre_shadow_bytes=pre_shadow_bytes,
                            original_bytes=original_bytes,
                            nukki_png_bytes=nukki_bytes,
                            suggested_hint=final_hint,
                            hint_key=hint_key,
                            evaluation=ind_eval,
                            image_type=vi.get("image_type", "full"),
                            category=vi.get("category", ""),
                            shooting_angle=vi.get("shooting_angle", "front"),
                            has_mannequin=vi.get("has_mannequin", False),
                            needs_shadow=vi.get("needs_shadow", True),
                            on_log=_log_to_status,
                        )

                        def _apply_regen_result():
                            if result.get("success") and result.get("result_bytes"):
                                out_files = pair.get("output_files", [])
                                if out_files:
                                    out_path = out_files[0]["path"]
                                    from PIL import Image as _PILImage
                                    import io as _io
                                    _img = _PILImage.open(_io.BytesIO(result["result_bytes"]))
                                    _img.save(out_path, format="JPEG", quality=95)
                                    fsize = Path(out_path).stat().st_size
                                    pair["output_files"][0]["size"] = fsize

                                new_eval = result.get("new_eval", {})
                                pair["independent_eval"] = new_eval

                                score_before = ind_eval.get("overall_score", 0)
                                score_after = new_eval.get("overall_score", 0)
                                status_msg = f"\u2705 \uadf8\ub9bc\uc790 \uc7ac\uc0dd\uc131 {score_before:.0f}\u2192{score_after:.0f}/10"
                                lbl_autofix_status.config(text=status_msg, fg=VF_GREEN)

                                # ── 왼쪽 파일 목록: 재생성 완료 표시 ──
                                if _regen_fname in self._vf_file_stages:
                                    stages = self._vf_file_stages[_regen_fname].get("stages", {})
                                    stages["그림자"] = "done"
                                    self._vf_file_stages[_regen_fname]["status"] = "done"
                                if _regen_fname in file_rows:
                                    _ri = file_rows[_regen_fname]
                                    if shadow_idx >= 0:
                                        _ri["pips"][shadow_idx].configure(bg=VF_GREEN)
                                    # "재생성 완료" + 검증 아이콘 대신 재생성 결과 표시
                                    _ri["lbl_stage_text"].config(
                                        text=f"\U0001f504\uc7ac\uc0dd\uc131 {score_after:.0f}/10",
                                        fg=VF_GREEN)
                                    _ri["lbl_stage_text"].pack(side="left")
                                    for lbl in _ri.get("val_icons", {}).values():
                                        lbl.pack_forget()
                            else:
                                lbl_autofix_status.config(
                                    text="\uadf8\ub9bc\uc790 \uc7ac\uc0dd\uc131 \uc2e4\ud328", fg=VF_RED)
                                # ── 왼쪽 파일 목록: 재생성 실패 표시 ──
                                if _regen_fname in self._vf_file_stages:
                                    stages = self._vf_file_stages[_regen_fname].get("stages", {})
                                    stages["그림자"] = "fail"
                                    self._vf_file_stages[_regen_fname]["status"] = "done"
                                if _regen_fname in file_rows:
                                    _ri = file_rows[_regen_fname]
                                    if shadow_idx >= 0:
                                        _ri["pips"][shadow_idx].configure(bg=VF_RED)
                                    _ri["lbl_stage_text"].config(
                                        text="\U0001f504\uc7ac\uc0dd\uc131 \uc2e4\ud328", fg=VF_RED)
                                    _ri["lbl_stage_text"].pack(side="left")

                            btn_autofix.config(state="normal",
                                               text="\U0001f504 \uc790\ub3d9\uc218\uc815 (\ud504\ub86c\ud504\ud2b8)")
                            _show(current_idx[0], out_idx[0])
                            _update_eval_panel(pair)

                        dlg.after(0, _apply_regen_result)

                    except Exception as e:
                        err_msg = str(e)[:50]
                        dlg.after(0, lambda m=err_msg: lbl_autofix_status.config(
                            text=f"\uc624\ub958: {m}", fg=VF_RED))
                        dlg.after(0, lambda: btn_autofix.config(
                            state="normal", text="\U0001f504 \uc790\ub3d9\uc218\uc815 (\ud504\ub86c\ud504\ud2b8)"))
                        # 왼쪽 파일 목록: 오류 표시
                        def _show_error_in_row():
                            if _regen_fname in file_rows:
                                _ri = file_rows[_regen_fname]
                                _ri["lbl_stage_text"].config(
                                    text="\U0001f504\uc7ac\uc0dd\uc131 \uc624\ub958", fg=VF_RED)
                                _ri["lbl_stage_text"].pack(side="left")
                        dlg.after(0, _show_error_in_row)

                import threading
                threading.Thread(target=_run_regen, daemon=True).start()

            # 1단계 백그라운드 시작
            import threading
            threading.Thread(target=_step1_ask_ai, daemon=True).start()

        def _on_claude_copy():
            pairs = self._viewfinder_pairs
            if not pairs or current_idx[0] >= len(pairs):
                return
            pair = pairs[current_idx[0]]
            ind_eval = pair.get("independent_eval", {})
            validation = pair.get("validation", {})

            input_path = pair.get("input_path", "")
            out_files = pair.get("output_files", [])
            output_path = out_files[0]["path"] if out_files else ""

            user_fb = eval_feedback_entry.get().strip()

            log_text = ""
            try:
                log_widget = self.log_text
                log_text = log_widget.get("1.0", "end-1c")
                log_lines = log_text.strip().split("\n")
                if len(log_lines) > 100:
                    log_text = "\n".join(log_lines[-100:])
            except Exception:
                pass

            settings_snap = {}
            try:
                _s = load_yaml(SETTINGS_PATH)
                settings_snap = {
                    "shadow_provider": _s.get("providers", {}).get("shadow", ""),
                    "shadow_composite_method": _s.get("shadow_composite_method", ""),
                    "gemini_shadow.model": _s.get("gemini_shadow", {}).get("model", ""),
                    "gemini_shadow.main_prompt": _s.get("gemini_shadow", {}).get("main_prompt", "")[:300],
                }
            except Exception:
                pass

            autofix_result = {"attempts": pair.get("autofix_attempts", [])}

            from src.pipeline import ImageEditPipeline
            report = ImageEditPipeline._build_claude_report(
                input_path=input_path,
                output_path=output_path,
                evaluation=ind_eval,
                validation=validation,
                auto_fix_result=autofix_result,
                user_feedback=user_fb,
                log_text=log_text,
                settings_snapshot=settings_snap,
            )

            dlg.clipboard_clear()
            dlg.clipboard_append(report)

            btn_claude.config(text="\u2705 \ubcf5\uc0ac\ub428!", fg=VF_GREEN)
            dlg.after(2000, lambda: btn_claude.config(
                text="\U0001f4cb \ud074\ub85c\ub4dc \ubcf5\uc0ac", fg=VF_TEXT))

        def _on_val_feedback():
            """검증 결과에 이의 → 수정 대상 선택 후 프롬프트 수정"""
            pairs = self._viewfinder_pairs
            if not pairs or current_idx[0] >= len(pairs):
                return
            pair = pairs[current_idx[0]]
            validation = pair.get("validation", {})
            ind_eval = pair.get("independent_eval", {})

            if not validation and not ind_eval:
                return

            user_fb = eval_feedback_entry.get().strip()
            if not user_fb:
                lbl_autofix_status.config(
                    text="의견을 입력해주세요 (예: 원본에 있는 자국인데 감점됨)", fg=VF_YELLOW)
                return

            # 수정 대상 선택 팝업
            has_val_fail = (validation and not validation.get("overall", True))
            has_eval = bool(ind_eval and ind_eval.get("overall_score"))

            # 둘 다 있으면 선택, 하나만 있으면 바로 진행
            if has_val_fail and has_eval:
                _show_target_selector(pair, user_fb, has_val_fail, has_eval)
            elif has_eval:
                _run_feedback_fix(pair, user_fb, target="independent")
            elif has_val_fail:
                _run_feedback_fix(pair, user_fb, target="validation")

        def _show_target_selector(pair, user_fb, has_val_fail, has_eval):
            """수정 대상 선택 팝업"""
            sel_pop = tk.Toplevel(dlg)
            sel_pop.title("수정 대상 선택")
            sel_pop.geometry("380x200")
            sel_pop.transient(dlg)
            sel_pop.grab_set()
            sel_pop.configure(bg=VF_BG)

            tk.Label(sel_pop, text="어떤 프롬프트를 수정할까요?",
                     bg=VF_BG, fg=VF_TEXT,
                     font=(FONT_FAMILY, 12, "bold")).pack(pady=(20, 16))

            btn_frame = tk.Frame(sel_pop, bg=VF_BG)
            btn_frame.pack(fill="x", padx=24)

            def _select(t):
                sel_pop.destroy()
                _run_feedback_fix(pair, user_fb, target=t)

            if has_eval:
                tk.Button(btn_frame, text="  독립평가 프롬프트 수정  ",
                          bg="#7c3aed", fg="white", font=(FONT_FAMILY, 11, "bold"),
                          activebackground="#6d28d9", activeforeground="white",
                          relief="flat", cursor="hand2",
                          command=lambda: _select("independent")
                          ).pack(fill="x", pady=(0, 8), ipady=6)

            if has_val_fail:
                tk.Button(btn_frame, text="  개별 검증 프롬프트 수정  ",
                          bg="#2563eb", fg="white", font=(FONT_FAMILY, 11, "bold"),
                          activebackground="#1d4ed8", activeforeground="white",
                          relief="flat", cursor="hand2",
                          command=lambda: _select("validation")
                          ).pack(fill="x", pady=(0, 8), ipady=6)

            tk.Button(btn_frame, text="  취소  ",
                      bg=VF_CARD, fg=VF_TEXT, font=(FONT_FAMILY, 10),
                      activebackground=VF_BORDER, relief="flat", cursor="hand2",
                      command=sel_pop.destroy).pack(fill="x", ipady=4)

        def _run_feedback_fix(pair, user_fb, target="validation"):
            """사용자 의견 기반 프롬프트 수정 실행"""
            btn_val_feedback.config(state="disabled", text="⏳ AI 분석 중...")
            target_name = "독립평가" if target == "independent" else "개별검증"
            lbl_autofix_status.config(text=f"{target_name} 프롬프트 개선안 생성 중...", fg=VF_ACCENT)
            dlg.update()

            def _run_fix_thread():
                try:
                    import numpy as np
                    from src.pipeline import ImageEditPipeline
                    pipe = ImageEditPipeline(config_dir=str(CONFIG_DIR))
                    import yaml as _yaml

                    prompts_path = CONFIG_DIR / "prompts.yaml"
                    with open(prompts_path, "r", encoding="utf-8") as f:
                        all_prompts = _yaml.safe_load(f)

                    vision_client = pipe._get_vision_client()

                    # 이미지 로드 (원본 + 결과)
                    out_files = pair.get("output_files", [])
                    result_path = out_files[0]["path"] if out_files else ""
                    input_path_val = pair.get("input_path", "")

                    import cv2
                    images_for_ai = []
                    if input_path_val and Path(input_path_val).exists():
                        orig_arr = np.frombuffer(Path(input_path_val).read_bytes(), dtype=np.uint8)
                        orig_img = cv2.imdecode(orig_arr, cv2.IMREAD_COLOR)
                        if orig_img is not None:
                            images_for_ai.append(orig_img)
                    if result_path and Path(result_path).exists():
                        res_arr = np.frombuffer(Path(result_path).read_bytes(), dtype=np.uint8)
                        res_img = cv2.imdecode(res_arr, cv2.IMREAD_COLOR)
                        if res_img is not None:
                            images_for_ai.append(res_img)

                    if target == "independent":
                        suggestion = _fix_independent_prompt(
                            pair, user_fb, all_prompts, vision_client, images_for_ai)
                        dlg.after(0, lambda: _show_independent_preview(
                            suggestion, all_prompts, prompts_path, pair))
                    else:
                        suggestion = _fix_validation_prompt(
                            pair, user_fb, all_prompts, vision_client, images_for_ai)
                        val_section = all_prompts.get("validation", {})
                        dlg.after(0, lambda: _show_val_preview(
                            suggestion, val_section, prompts_path, all_prompts, pair))

                except Exception as e:
                    err_msg = str(e)[:60]
                    dlg.after(0, lambda m=err_msg: lbl_autofix_status.config(
                        text=f"오류: {m}", fg=VF_RED))
                    dlg.after(0, lambda: btn_val_feedback.config(
                        state="normal", text="\U0001f4dd 검증수정"))

            import threading
            threading.Thread(target=_run_fix_thread, daemon=True).start()

        def _fix_independent_prompt(pair, user_fb, all_prompts, vision_client, images):
            """독립평가 프롬프트 수정안 생성"""
            eval_section = all_prompts.get("independent_evaluation", {})
            current_system = eval_section.get("system", "")
            current_prompt = eval_section.get("prompt", "")
            ind_eval = pair.get("independent_eval", {})

            # 현재 평가 결과 요약
            eval_summary_parts = []
            for key in ["shadow_natural", "background_clean", "edge_quality",
                         "product_integrity", "commercial_quality"]:
                item = ind_eval.get(key, {})
                score = item.get("score", "?")
                issues = item.get("issues", [])
                issues_str = ", ".join(issues) if issues else "없음"
                label_map = {
                    "shadow_natural": "그림자", "background_clean": "배경",
                    "edge_quality": "경계선", "product_integrity": "원형보존",
                    "commercial_quality": "상업성"
                }
                eval_summary_parts.append(
                    f"- {label_map.get(key, key)}: {score}/10 (문제: {issues_str})")
            eval_summary = "\n".join(eval_summary_parts)

            overall = ind_eval.get("overall_score", "?")
            critical = ind_eval.get("critical_issues", [])
            critical_str = ", ".join(critical) if critical else "없음"
            recommendation = ind_eval.get("recommendation", "")

            ai_system = (
                "당신은 상품 이미지 품질 평가 프롬프트를 개선하는 전문가입니다.\n"
                "사용자가 독립평가 결과에 이의를 제기했습니다.\n"
                "현재 평가 프롬프트의 기준을 분석하고, 사용자 의견을 반영하여\n"
                "개선된 프롬프트를 제안하세요.\n"
                "원본 이미지를 확인하여 사용자의 의견이 합리적인지 직접 판단하세요.\n"
                "반드시 JSON만 출력하세요."
            )

            ai_prompt = (
                f"첫 번째 이미지는 원본, 두 번째 이미지는 처리 결과입니다.\n\n"
                f"[현재 독립평가 결과]\n"
                f"종합점수: {overall}/10\n"
                f"{eval_summary}\n"
                f"핵심 문제: {critical_str}\n"
                f"권장사항: {recommendation}\n\n"
                f"[사용자 의견]\n{user_fb}\n\n"
                f"[현재 독립평가 시스템 프롬프트]\n{current_system}\n\n"
                f"[현재 독립평가 사용자 프롬프트]\n{current_prompt}\n\n"
                f"이미지를 직접 확인하고, 사용자의 의견이 합리적인지 판단하세요.\n"
                f"합리적이라면 현재 프롬프트에 예외 조건이나 수정을 추가하여\n"
                f"이런 유형의 평가가 다음에는 올바르게 수행될 수 있도록 하세요.\n\n"
                f"응답 형식 (JSON만):\n"
                f'{{"agree": true/false, "reason": "판단 근거", '
                f'"updated_system": "수정된 system 프롬프트 전문 (변경이 필요한 경우만, 불필요하면 빈 문자열)", '
                f'"updated_prompt": "수정된 prompt 전문 (변경이 필요한 경우만, 불필요하면 빈 문자열)"}}'
            )

            import json as _json
            response_text = vision_client.analyze_images(
                images if images else [],
                ai_system, ai_prompt,
                max_tokens=8192, temperature=0.1,
            )

            text = (response_text or "").strip()
            if "```" in text:
                import re
                m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
                if m:
                    text = m.group(1).strip()
            return _json.loads(text)

        def _fix_validation_prompt(pair, user_fb, all_prompts, vision_client, images):
            """개별 검증 프롬프트 수정안 생성 (기존 로직)"""
            val_section = all_prompts.get("validation", {})
            validation = pair.get("validation", {})

            fail_items = []
            label_map = {"background": "배경", "shadow": "그림자", "integrity": "원형보존"}
            for key in ["background", "shadow", "integrity"]:
                item = validation.get(key, {})
                if not item.get("pass", True):
                    fail_items.append({
                        "key": key,
                        "label": label_map.get(key, key),
                        "detail": item.get("detail", ""),
                    })

            fail_summary = "\n".join(
                f"- {fi['label']}: FAIL ({fi['detail']})" for fi in fail_items)

            current_shadow_prompt = val_section.get("shadow_needed", "")

            ai_system = (
                "당신은 상품 이미지 품질 검증 프롬프트를 개선하는 전문가입니다.\n"
                "사용자가 검증 결과에 이의를 제기했습니다.\n"
                "현재 프롬프트의 판정 기준을 분석하고, 사용자 의견을 반영하여\n"
                "개선된 프롬프트를 제안하세요.\n"
                "반드시 JSON만 출력하세요."
            )

            ai_prompt = (
                f"첫 번째 이미지는 원본, 두 번째 이미지는 처리 결과입니다.\n\n"
                f"현재 검증에서 불합격된 항목:\n{fail_summary}\n\n"
                f"사용자 의견: {user_fb}\n\n"
                f"현재 그림자 판정 프롬프트:\n{current_shadow_prompt}\n\n"
                f"이미지를 직접 확인하고, 사용자의 의견이 합리적인지 판단하세요.\n"
                f"합리적이라면 현재 프롬프트에 예외 조건이나 수정을 추가하여\n"
                f"이런 유형의 이미지가 다음에는 올바르게 판정될 수 있도록 하세요.\n\n"
                f"응답 형식 (JSON만):\n"
                f'{{"agree": true/false, "reason": "판단 근거", '
                f'"updated_shadow_needed": "수정된 shadow_needed 프롬프트 전문 (변경이 필요한 경우만)", '
                f'"updated_user_template": "수정된 user_template 프롬프트 전문 (변경이 필요한 경우만)"}}'
            )

            import json as _json
            response_text = vision_client.analyze_images(
                images if images else [],
                ai_system, ai_prompt,
                max_tokens=4096, temperature=0.1,
            )

            text = (response_text or "").strip()
            if "```" in text:
                import re
                m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
                if m:
                    text = m.group(1).strip()
            return _json.loads(text)

        def _show_independent_preview(suggestion, all_prompts, prompts_path, pair):
            """독립평가 프롬프트 수정 미리보기"""
            agree = suggestion.get("agree", False)
            reason = suggestion.get("reason", "")
            new_system = suggestion.get("updated_system", "")
            new_prompt = suggestion.get("updated_prompt", "")

            pop = tk.Toplevel(dlg)
            pop.title("독립평가 프롬프트 수정 미리보기")
            pop.geometry("800x700")
            pop.transient(dlg)
            pop.grab_set()
            pop.configure(bg=VF_BG)

            # 헤더
            if agree:
                tk.Label(pop, text="✅ AI가 사용자 의견에 동의합니다",
                         bg=VF_BG, fg=VF_GREEN,
                         font=(FONT_FAMILY, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
            else:
                tk.Label(pop, text="⚠️ AI가 사용자 의견에 동의하지 않습니다",
                         bg=VF_BG, fg=VF_YELLOW,
                         font=(FONT_FAMILY, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 4))

            tk.Label(pop, text=f"판단 근거: {reason}",
                     bg=VF_BG, fg=VF_TEXT_DIM, wraplength=750, justify="left",
                     font=(FONT_FAMILY, 9)).pack(anchor="w", padx=16, pady=(0, 8))

            has_changes = bool(new_system or new_prompt)

            system_text_w = None
            prompt_text_w = None

            if has_changes and new_system:
                tk.Label(pop, text="▶ 수정된 독립평가 시스템 프롬프트 (편집 가능):",
                         bg=VF_BG, fg="#a78bfa",
                         font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=16, pady=(4, 2))
                system_text_w = scrolledtext.ScrolledText(pop, height=7, font=(FONT_FAMILY, 9),
                    bg="#1a1028", fg="#d4b8ff", wrap="word", relief="flat", borderwidth=1,
                    insertbackground="#d4b8ff")
                system_text_w.pack(fill="x", padx=16, pady=(0, 8))
                system_text_w.insert("1.0", new_system)

            if has_changes and new_prompt:
                tk.Label(pop, text="▶ 수정된 독립평가 사용자 프롬프트 (편집 가능):",
                         bg=VF_BG, fg="#a78bfa",
                         font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=16, pady=(4, 2))
                prompt_text_w = scrolledtext.ScrolledText(pop, height=10, font=(FONT_FAMILY, 9),
                    bg="#1a1028", fg="#d4b8ff", wrap="word", relief="flat", borderwidth=1,
                    insertbackground="#d4b8ff")
                prompt_text_w.pack(fill="x", padx=16, pady=(0, 8))
                prompt_text_w.insert("1.0", new_prompt)

            if not has_changes:
                tk.Label(pop, text="프롬프트 변경 불필요 (AI 판단)",
                         bg=VF_BG, fg=VF_TEXT_DIM,
                         font=(FONT_FAMILY, 10)).pack(anchor="w", padx=16, pady=(8, 4))

            # 버튼
            btn_f = tk.Frame(pop, bg=VF_BG)
            btn_f.pack(fill="x", padx=16, pady=(8, 12))

            def _on_apply_indep():
                import yaml as _yaml
                changed = False
                eval_section = all_prompts.setdefault("independent_evaluation", {})
                if system_text_w:
                    final_sys = system_text_w.get("1.0", "end-1c").strip()
                    if final_sys:
                        eval_section["system"] = final_sys
                        changed = True
                if prompt_text_w:
                    final_prompt = prompt_text_w.get("1.0", "end-1c").strip()
                    if final_prompt:
                        eval_section["prompt"] = final_prompt
                        changed = True

                if changed:
                    with open(prompts_path, "w", encoding="utf-8") as f:
                        _yaml.dump(all_prompts, f, allow_unicode=True,
                                   default_flow_style=False, sort_keys=False)
                    lbl_autofix_status.config(
                        text="✅ 독립평가 프롬프트 저장 완료 (다음 처리부터 적용)",
                        fg=VF_GREEN)
                else:
                    lbl_autofix_status.config(text="변경 없음", fg=VF_TEXT_DIM)

                pop.destroy()
                btn_val_feedback.config(state="normal", text="\U0001f4dd 검증수정")

            def _on_cancel_indep():
                pop.destroy()
                lbl_autofix_status.config(text="취소", fg=VF_TEXT_DIM)
                btn_val_feedback.config(state="normal", text="\U0001f4dd 검증수정")

            if has_changes:
                tk.Button(btn_f, text="  프롬프트 저장  ",
                          bg="#7c3aed", fg="white", font=(FONT_FAMILY, 11, "bold"),
                          activebackground="#6d28d9", activeforeground="white",
                          relief="flat", cursor="hand2",
                          command=_on_apply_indep).pack(side="left", padx=(0, 8), ipady=4)

            tk.Button(btn_f, text="  취소  ",
                      bg=VF_CARD, fg=VF_TEXT, font=(FONT_FAMILY, 10),
                      activebackground=VF_BORDER, relief="flat", cursor="hand2",
                      command=_on_cancel_indep).pack(side="left", ipady=4)

            btn_val_feedback.config(state="normal", text="\U0001f4dd 검증수정")

            def _show_val_preview(suggestion, val_section, prompts_path, all_prompts, pair):
                """검증 프롬프트 수정 미리보기"""
                agree = suggestion.get("agree", False)
                reason = suggestion.get("reason", "")
                new_shadow = suggestion.get("updated_shadow_needed", "")
                new_template = suggestion.get("updated_user_template", "")

                pop = tk.Toplevel(dlg)
                pop.title("검증 프롬프트 수정 미리보기")
                pop.geometry("750x650")
                pop.transient(dlg)
                pop.grab_set()
                pop.configure(bg=VF_BG)

                # 헤더
                if agree:
                    tk.Label(pop, text="✅ AI가 사용자 의견에 동의합니다",
                             bg=VF_BG, fg=VF_GREEN,
                             font=(FONT_FAMILY, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
                else:
                    tk.Label(pop, text="⚠️ AI가 사용자 의견에 동의하지 않습니다",
                             bg=VF_BG, fg=VF_YELLOW,
                             font=(FONT_FAMILY, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 4))

                tk.Label(pop, text=f"판단 근거: {reason}",
                         bg=VF_BG, fg=VF_TEXT_DIM, wraplength=700, justify="left",
                         font=(FONT_FAMILY, 9)).pack(anchor="w", padx=16, pady=(0, 8))

                has_changes = bool(new_shadow or new_template)

                if has_changes and new_shadow:
                    tk.Label(pop, text="▶ 수정된 그림자 판정 기준 (편집 가능):",
                             bg=VF_BG, fg=VF_GREEN,
                             font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=16, pady=(4, 2))
                    shadow_text = scrolledtext.ScrolledText(pop, height=8, font=(FONT_FAMILY, 9),
                        bg="#1a2a1a", fg="#c0e0c0", wrap="word", relief="flat", borderwidth=1,
                        insertbackground="#c0e0c0")
                    shadow_text.pack(fill="x", padx=16, pady=(0, 8))
                    shadow_text.insert("1.0", new_shadow)
                else:
                    shadow_text = None
                    if not has_changes:
                        tk.Label(pop, text="프롬프트 변경 불필요 (AI 판단)",
                                 bg=VF_BG, fg=VF_TEXT_DIM,
                                 font=(FONT_FAMILY, 10)).pack(anchor="w", padx=16, pady=(8, 4))

                if has_changes and new_template:
                    tk.Label(pop, text="▶ 수정된 검증 템플릿 (편집 가능):",
                             bg=VF_BG, fg=VF_GREEN,
                             font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=16, pady=(4, 2))
                    template_text = scrolledtext.ScrolledText(pop, height=8, font=(FONT_FAMILY, 9),
                        bg="#1a2a1a", fg="#c0e0c0", wrap="word", relief="flat", borderwidth=1,
                        insertbackground="#c0e0c0")
                    template_text.pack(fill="x", padx=16, pady=(0, 8))
                    template_text.insert("1.0", new_template)
                else:
                    template_text = None

                # 버튼
                btn_f = tk.Frame(pop, bg=VF_BG)
                btn_f.pack(fill="x", padx=16, pady=(8, 12))

                def _on_apply_val():
                    import yaml as _yaml
                    changed = False
                    if shadow_text:
                        final_shadow = shadow_text.get("1.0", "end-1c").strip()
                        if final_shadow:
                            all_prompts["validation"]["shadow_needed"] = final_shadow
                            changed = True
                    if template_text:
                        final_template = template_text.get("1.0", "end-1c").strip()
                        if final_template:
                            all_prompts["validation"]["user_template"] = final_template
                            changed = True

                    if changed:
                        with open(prompts_path, "w", encoding="utf-8") as f:
                            _yaml.dump(all_prompts, f, allow_unicode=True,
                                       default_flow_style=False, sort_keys=False)
                        lbl_autofix_status.config(
                            text="✅ 검증 프롬프트 저장 완료 (다음 처리부터 적용)",
                            fg=VF_GREEN)
                    else:
                        lbl_autofix_status.config(
                            text="변경 없음", fg=VF_TEXT_DIM)

                    pop.destroy()
                    btn_val_feedback.config(state="normal", text="\U0001f4dd 검증수정")

                def _on_force_pass():
                    """강제 합격 처리 + 프롬프트 저장"""
                    import yaml as _yaml
                    # 프롬프트 변경사항 저장
                    changed = False
                    if shadow_text:
                        final_shadow = shadow_text.get("1.0", "end-1c").strip()
                        if final_shadow:
                            all_prompts["validation"]["shadow_needed"] = final_shadow
                            changed = True
                    if template_text:
                        final_template = template_text.get("1.0", "end-1c").strip()
                        if final_template:
                            all_prompts["validation"]["user_template"] = final_template
                            changed = True
                    if changed:
                        with open(prompts_path, "w", encoding="utf-8") as f:
                            _yaml.dump(all_prompts, f, allow_unicode=True,
                                       default_flow_style=False, sort_keys=False)

                    # 현재 이미지 검증 결과 강제 합격으로 변경
                    for key in ["background", "shadow", "integrity"]:
                        if key in pair.get("validation", {}):
                            pair["validation"][key]["pass"] = True
                    pair["validation"]["overall"] = True

                    # 파일 목록 갱신
                    _regen_fname = Path(pair.get("input_path", "")).name
                    if _regen_fname in self._vf_file_stages:
                        self._vf_file_stages[_regen_fname]["validation"] = pair["validation"]
                    if _regen_fname in file_rows:
                        _update_row_stages(_regen_fname)

                    lbl_autofix_status.config(
                        text="✅ 강제 합격 + 프롬프트 저장 완료",
                        fg=VF_GREEN)
                    pop.destroy()
                    btn_val_feedback.config(state="normal", text="\U0001f4dd 검증수정")
                    _update_eval_panel(pair)
                    _show(current_idx[0], out_idx[0])

                def _on_cancel_val():
                    pop.destroy()
                    lbl_autofix_status.config(text="취소", fg=VF_TEXT_DIM)
                    btn_val_feedback.config(state="normal", text="\U0001f4dd 검증수정")

                if has_changes:
                    tk.Button(btn_f, text="  프롬프트 저장 + 강제 합격  ",
                              bg="#16a34a", fg="white", font=(FONT_FAMILY, 11, "bold"),
                              activebackground="#15803d", activeforeground="white",
                              relief="flat", cursor="hand2",
                              command=_on_force_pass).pack(side="left", padx=(0, 8), ipady=4)
                    tk.Button(btn_f, text="  프롬프트만 저장  ",
                              bg="#2563eb", fg="white", font=(FONT_FAMILY, 10),
                              activebackground="#1d4ed8", activeforeground="white",
                              relief="flat", cursor="hand2",
                              command=_on_apply_val).pack(side="left", padx=(0, 8), ipady=4)
                else:
                    tk.Button(btn_f, text="  강제 합격 처리  ",
                              bg="#d97706", fg="white", font=(FONT_FAMILY, 11, "bold"),
                              activebackground="#b45309", activeforeground="white",
                              relief="flat", cursor="hand2",
                              command=_on_force_pass).pack(side="left", padx=(0, 8), ipady=4)

                tk.Button(btn_f, text="  취소  ",
                          bg=VF_CARD, fg=VF_TEXT, font=(FONT_FAMILY, 10),
                          activebackground=VF_BORDER, relief="flat", cursor="hand2",
                          command=_on_cancel_val).pack(side="left", ipady=4)

        btn_autofix.config(command=_on_autofix)
        btn_claude.config(command=_on_claude_copy)
        btn_val_feedback.config(command=_on_val_feedback)

        # 키보드 힌트
        hint_frame = tk.Frame(right, bg=VF_BG)
        hint_frame.pack(fill="x", padx=12, pady=(4, 8))
        tk.Frame(hint_frame, bg=VF_BORDER, height=1).pack(fill="x", pady=(0, 6))
        hint_text = tk.Label(hint_frame, bg=VF_BG, fg=VF_TEXT_FAINT,
                             font=(FONT_FAMILY, 9),
                             text="\u2191\u2193 파일이동  \u2190\u2192 출력전환  1~6 단계보기  ESC 닫기")
        hint_text.pack()

        def _fit_image(canvas, img):
            canvas.update_idletasks()
            cw = max(canvas.winfo_width(), 100)
            ch = max(canvas.winfo_height(), 100)
            iw, ih = img.size
            if iw == 0 or ih == 0:
                return
            # height 기준으로 최대한 크게 표시, 가로 초과 시에만 가로 기준으로 축소
            ratio_h = (ch - 10) / ih
            ratio_w = (cw - 10) / iw
            ratio = min(ratio_h, ratio_w)
            # height 우선: 가로 여유가 있으면 height에 맞춤
            if ratio_h <= ratio_w:
                ratio = ratio_h
            new_w = max(1, int(iw * ratio))
            new_h = max(1, int(ih * ratio))
            img_copy = img.resize((new_w, new_h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img_copy)
            photo_refs.append(photo)
            if len(photo_refs) > 40:
                del photo_refs[:20]
            canvas.delete("all")
            canvas.create_image(cw // 2, ch // 2, anchor="center", image=photo)

        def _show_placeholder(canvas, text, icon_text=""):
            canvas.delete("all")
            canvas.update_idletasks()
            cw = max(canvas.winfo_width(), 100)
            ch = max(canvas.winfo_height(), 100)
            cx, cy = cw // 2, ch // 2
            if icon_text:
                canvas.create_text(cx, cy - 16, text=icon_text, fill="#ccc",
                                   font=(FONT_FAMILY, 28))
                canvas.create_text(cx, cy + 20, text=text, fill="#999",
                                   font=(FONT_FAMILY, 11))
            else:
                canvas.create_text(cx, cy, text=text, fill="#999",
                                   font=(FONT_FAMILY, 12))

        def _load_stage_image(fname, stage_name):
            """단계별 저장 이미지를 로드해 반환 (PIL Image 또는 None)"""
            si = self._vf_file_stages.get(fname, {}).get("stage_images", {})
            path = si.get(stage_name)
            if path and Path(path).exists():
                try:
                    return Image.open(path)
                except Exception:
                    pass
            return None

        def _show(idx, out_sub=0):
            pairs = self._viewfinder_pairs
            if not pairs or idx < 0 or idx >= len(pairs):
                return
            current_idx[0] = idx
            out_idx[0] = out_sub
            pair = pairs[idx]
            _highlight_row(idx)
            # 재처리 패널 초기화 (다른 이미지로 전환 시)
            try:
                rp_result_bytes[0] = None
                btn_rp_confirm.config(state="disabled")
                lbl_rp_status.config(text="")
                lbl_right_title.config(text="\u2728  \ucc98\ub9ac \uacb0\uacfc")
            except Exception:
                pass

            total = len(pairs)
            done_count = sum(1 for p in pairs if p.get("success"))
            lbl_count.config(text=f"{idx + 1} / {total}")
            lbl_header.config(text=f"처리 현황 ({done_count}/{total} 완료)")

            inp = pair["input_path"]
            fname = Path(inp).name
            sm = stage_mode[0]  # None=비교, or stage name

            if sm is not None:
                # ── 단계별 보기 모드 ──
                stage_order = ["원본", "누끼", "보정", "그림자", "최종"]
                si_idx = stage_order.index(sm) if sm in stage_order else 0
                # 왼쪽: 이전 단계 (없으면 원본)
                prev_stage = stage_order[si_idx - 1] if si_idx > 0 else None
                lbl_left_title.config(text=f"\U0001f4f7  {prev_stage or '원본'}")
                lbl_right_title.config(text=f"\u2728  {sm}")

                if prev_stage:
                    prev_img = _load_stage_image(fname, prev_stage)
                else:
                    prev_img = None
                if prev_img:
                    _fit_image(cv_orig, prev_img)
                    w, h = prev_img.size
                    lbl_orig_info.config(text=f"{prev_stage}  ·  {w}×{h}")
                else:
                    try:
                        img_orig = Image.open(inp)
                        _fit_image(cv_orig, img_orig)
                        w, h = img_orig.size
                        lbl_orig_info.config(text=f"원본  ·  {w}×{h}")
                    except Exception:
                        _show_placeholder(cv_orig, "로드 실패", "\U0001f5bc\ufe0f")
                        lbl_orig_info.config(text="")

                cur_img = _load_stage_image(fname, sm)
                if cur_img:
                    _fit_image(cv_proc, cur_img)
                    pw, ph = cur_img.size
                    lbl_proc_info.config(text=f"{sm}  ·  {pw}×{ph}")
                else:
                    _show_placeholder(cv_proc, f"{sm} 이미지 없음", "\U0001f4ad")
                    lbl_proc_info.config(text="")
                lbl_out_sel.config(text="")
            else:
                # ── 비교 모드 (기존) ──
                lbl_left_title.config(text="\U0001f4f7  원본")
                lbl_right_title.config(text="\u2728  처리 결과")

                try:
                    img_orig = Image.open(inp)
                    w, h = img_orig.size
                    sz = Path(inp).stat().st_size // 1024
                    lbl_orig_info.config(
                        text=f"{Path(inp).name}  \u00b7  {w}\u00d7{h}  \u00b7  {sz}KB")
                    _fit_image(cv_orig, img_orig)
                except Exception:
                    _show_placeholder(cv_orig, "로드 실패", "\U0001f5bc\ufe0f")
                    lbl_orig_info.config(text=Path(inp).name)

                out_files = pair.get("output_files", [])
                if out_files and out_sub < len(out_files):
                    out_path = out_files[out_sub]["path"]
                    try:
                        img_proc = Image.open(out_path)
                        pw, ph = img_proc.size
                        pkb = out_files[out_sub].get("size_kb",
                                  Path(out_path).stat().st_size // 1024)
                        lbl_proc_info.config(
                            text=f"{Path(out_path).name}  \u00b7  {pw}\u00d7{ph}  \u00b7  {pkb}KB")
                        _fit_image(cv_proc, img_proc)
                    except Exception:
                        _show_placeholder(cv_proc, "로드 실패", "\U0001f5bc\ufe0f")
                        lbl_proc_info.config(text="")
                    if len(out_files) > 1:
                        lbl_out_sel.config(
                            text=f"  출력 {out_sub + 1}/{len(out_files)} (\u2190 \u2192 전환)  ")
                    else:
                        lbl_out_sel.config(text="")
                elif pair.get("status") == "processing":
                    _show_placeholder(cv_proc, "처리 중...", "\u23f3")
                    lbl_proc_info.config(text="")
                    lbl_out_sel.config(text="")
                else:
                    _show_placeholder(cv_proc, "출력 없음", "\u2716")
                    lbl_proc_info.config(
                        text="처리 실패" if not pair.get("success") else "",
                        fg=VF_RED if not pair.get("success") else VF_TEXT_DIM)
                    lbl_out_sel.config(text="")

            _update_validation_display(pair)
            _update_vision_display(pair)
            _update_routing_display(pair)
            _update_eval_panel(pair)

        def _go(delta):
            _show(current_idx[0] + delta, 0)

        def _on_key(event):
            if getattr(eval_feedback_entry, "_has_focus", False):
                return
            if event.keysym == "Up":
                _go(-1)
            elif event.keysym == "Down":
                _go(1)
            elif event.keysym == "Left":
                if out_idx[0] > 0:
                    _show(current_idx[0], out_idx[0] - 1)
            elif event.keysym == "Right":
                pairs = self._viewfinder_pairs
                if pairs and current_idx[0] < len(pairs):
                    out_files = pairs[current_idx[0]].get("output_files", [])
                    if out_idx[0] < len(out_files) - 1:
                        _show(current_idx[0], out_idx[0] + 1)
            elif event.keysym == "Escape":
                dlg.destroy()
            elif event.char in ("1", "2", "3", "4", "5", "6"):
                tab_idx = int(event.char) - 1
                if tab_idx < len(_STAGE_TABS):
                    _select_stage_tab(_STAGE_TABS[tab_idx])

        dlg.bind("<Key>", _on_key)

        # 리사이즈 디바운스
        _resize_timer = [None]
        def _on_resize(event):
            if _resize_timer[0]:
                dlg.after_cancel(_resize_timer[0])
            _resize_timer[0] = dlg.after(150, lambda: _show(current_idx[0], out_idx[0]))
        cv_orig.bind("<Configure>", _on_resize)
        cv_proc.bind("<Configure>", _on_resize)

        # ── 실시간 업데이트 ──
        _prev_count = [0]

        _refresh_id = [None]  # after() ID for cancellation

        def _refresh():
            if not dlg.winfo_exists():
                return
            try:
                pairs = self._viewfinder_pairs

                if len(pairs) > _prev_count[0]:
                    for i in range(_prev_count[0], len(pairs)):
                        p = pairs[i]
                        fname = Path(p["input_path"]).name
                        _build_file_row(inner_frame, i, fname, p)
                        _update_row_stages(fname)
                    _prev_count[0] = len(pairs)
                    inner_frame.update_idletasks()
                    list_canvas.configure(scrollregion=list_canvas.bbox("all"))

                for fname in list(self._vf_file_stages.keys()):
                    _update_row_stages(fname)
            except (RuntimeError, TclError, AttributeError, KeyError):
                # 앱 종료 중 위젯/데이터 접근 오류 — 타이머 중단
                return

            _refresh_id[0] = dlg.after(500, _refresh)

        # 초기 빌드
        for i, p in enumerate(self._viewfinder_pairs):
            fname = Path(p["input_path"]).name
            _build_file_row(inner_frame, i, fname, p)
            if p.get("success"):
                if fname not in self._vf_file_stages:
                    self._vf_file_stages[fname] = {"stages": {}, "status": "done"}
                for s in self._VF_STAGES:
                    self._vf_file_stages[fname]["stages"][s] = "done"
            _update_row_stages(fname)
        _prev_count[0] = len(self._viewfinder_pairs)
        inner_frame.update_idletasks()
        list_canvas.configure(scrollregion=list_canvas.bbox("all"))

        if self._viewfinder_pairs:
            dlg.after(100, lambda: _show(0))
        _refresh_id[0] = dlg.after(500, _refresh)

        def _on_dlg_close():
            # 타이머 취소 후 파괴 — 종료 후 콜백 방지
            if _refresh_id[0] is not None:
                try:
                    dlg.after_cancel(_refresh_id[0])
                except (TclError, ValueError):
                    pass
            self._vf_dlg = None
            dlg.destroy()
        dlg.protocol("WM_DELETE_WINDOW", _on_dlg_close)




if __name__ == "__main__":
    import traceback as _tb
    _crash_log = APP_DIR / "crash.log"

    def _global_exception_handler(exc_type, exc_value, exc_tb):
        msg = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_crash_log, "a", encoding="utf-8") as f:
            f.write("\n" + "="*60 + "\n[" + timestamp + "] Unhandled Exception\n" + msg + "\n")
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _global_exception_handler

    def _thread_exception_handler(args):
        msg = "".join(_tb.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_crash_log, "a", encoding="utf-8") as f:
            f.write("\n" + "="*60 + "\n[" + timestamp + "] Thread Exception (" + str(args.thread) + ")\n" + msg + "\n")

    threading.excepthook = _thread_exception_handler

    app = App()
    app.mainloop()
