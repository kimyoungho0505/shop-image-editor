"""쇼핑몰 이미지 자동 편집 도구 - Windows GUI."""
import os
import sys
import json
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import customtkinter as ctk
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
    audio_packages = {
        "pygame": ("pygame", "오디오 재생 엔진 (OpenAI TTS 재생용)"),
    }

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
        print("[의존성 검사] 모든 패키지 설치 확인 완료 ✓")
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
            cb.configure(state="disabled")
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
            _tk.Label(f, text=f"  ✓ {info['label']}", font=("맑은 고딕", 9),
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
                print("[완료] 필수 패키지 설치 완료 ✓")
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
            print("[완료] API 패키지 설치 완료 ✓")
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
            print("[완료] 오디오 패키지 설치 완료 ✓")
        except subprocess.CalledProcessError as e:
            print(f"[오류] 오디오 패키지 설치 실패: {e}")

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
            print("[완료] PyTorch 설치 완료 ✓")
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
            print("[완료] SAM 패키지 설치 완료 ✓")
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
            print("[완료] MobileSAM 설치 완료 ✓")
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
ENV_PATH = APP_DIR / ".env"
GUI_STATE_PATH = APP_DIR / "gui_state.json"

WINDOW_TITLE = "LUXBOY 이미지 자동 편집 도구"
WINDOW_SIZE = "1100x850"
BG_COLOR = "#1a1d2e"
ACCENT = "#6366f1"
ACCENT_HOVER = "#4f46e5"
DANGER = "#ef4444"
SUCCESS = "#22c55e"
CARD_BG = "#13151f"
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
        label = tk.Label(self.tip, text=self.text, background="#1a1d2e",
                         foreground="#c4c9e2", relief="solid", borderwidth=1,
                         font=(FONT_FAMILY, 8), wraplength=350,
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


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.configure(fg_color=BG_COLOR)
        self.minsize(900, 700)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

        self._processing = False
        self._load_state()
        self._build_ui()
        self._load_configs()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 상태 저장/복원 ──
    def _load_state(self):
        self._state = {}
        if GUI_STATE_PATH.exists():
            try:
                with open(str(GUI_STATE_PATH), "r", encoding="utf-8") as f:
                    self._state = json.load(f)
            except Exception:
                pass

    def _save_state(self):
        self._state["input_folder"] = self.var_input.get()
        self._state["output_folder"] = self.var_output.get()
        self._state["skip_bg"] = self.var_skip_bg.get()
        try:
            with open(str(GUI_STATE_PATH), "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self._save_state()
        self.destroy()

    # ── UI 빌드 ──
    def _build_ui(self):
        self.notebook = ctk.CTkTabview(self, corner_radius=8)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        # 프로바이더 변수 (메인탭 + 설정탭에서 공유)
        self.var_vision_provider = tk.StringVar(value="claude")
        self.var_bg_provider = tk.StringVar(value="photoroom")
        self.var_enhance_provider = tk.StringVar(value="claid")
        self.var_shadow_provider = tk.StringVar(value="opencv_extract")

        self.notebook.add("  실행  ")
        self.notebook.add("  프롬프트 편집  ")
        self.notebook.add("  설정  ")
        self.tab_main = self.notebook.tab("  실행  ")
        self.tab_prompt = self.notebook.tab("  프롬프트 편집  ")
        self.tab_settings = self.notebook.tab("  설정  ")

        self._build_main_tab()
        self._build_prompt_tab()
        self._build_settings_tab()

        self.status_bar = ctk.CTkLabel(self, text="준비 완료", anchor="w",
                                       font=ctk.CTkFont(size=9),
                                       fg_color="#13151f", text_color="#6b7299",
                                       corner_radius=0)
        self.status_bar.pack(fill="x", padx=10, pady=(5, 10))

    # ── 탭 1: 실행 ──
    def _build_main_tab(self):
        parent = self.tab_main

        # ━━━ 상단 영역: 폴더 + 프로바이더 + 옵션 + 버튼 ━━━
        top_area = ctk.CTkFrame(parent, fg_color="transparent")
        top_area.pack(fill="x", padx=12, pady=(8, 0))

        # ── 1. 폴더 섹션 (좌측 라벨 + 우측 입력) ──
        folder_card = ctk.CTkFrame(top_area, fg_color=CARD_BG, corner_radius=10)
        folder_card.pack(fill="x", pady=(0, 6))
        folder_card.columnconfigure(1, weight=1)

        self.var_input = tk.StringVar(value=self._state.get("input_folder", ""))
        self.var_output = tk.StringVar(
            value=self._state.get("output_folder", str(APP_DIR / "output")))

        for r, (lbl, var, browse_cmd, open_cmd) in enumerate([
            ("입력", self.var_input, self._browse_input, self._open_input_folder),
            ("출력", self.var_output, self._browse_output, self._open_output_folder),
        ]):
            ctk.CTkLabel(folder_card, text=lbl,
                         font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"), width=40).grid(
                row=r, column=0, sticky="w", padx=(12, 4), pady=6)
            e = ctk.CTkEntry(folder_card, textvariable=var, corner_radius=6)
            e.grid(row=r, column=1, sticky="ew", padx=0, pady=6)
            bf = ctk.CTkFrame(folder_card, fg_color="transparent")
            bf.grid(row=r, column=2, padx=(4, 8), pady=6)
            ctk.CTkButton(bf, text="...", width=30, command=browse_cmd, corner_radius=8).pack(side="left", padx=(0, 2))
            ctk.CTkButton(bf, text="열기", width=50, command=open_cmd, corner_radius=8).pack(side="left")

        # ── 2. 프로바이더 + 옵션 (좌우 분할) ──
        mid_row = ctk.CTkFrame(top_area, fg_color="transparent")
        mid_row.pack(fill="x", pady=(0, 6))
        mid_row.columnconfigure(0, weight=3)
        mid_row.columnconfigure(1, weight=1)

        # 프로바이더 카드 (좌측, 넓게)
        prov_card = ctk.CTkFrame(mid_row, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        prov_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        ctk.CTkLabel(prov_card, text=" 프로바이더 ", font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        prov_grid = ctk.CTkFrame(prov_card, fg_color="transparent")
        prov_grid.pack(fill="x")

        # 분석 / 배경 / 보정 (1행)
        c = 0
        ctk.CTkLabel(prov_grid, text="분석",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold")).grid(row=0, column=c, sticky="w", padx=(8, 4))
        c += 1
        for txt, val in [("Claude", "claude"), ("ChatGPT", "chatgpt"), ("Gemini", "gemini")]:
            ctk.CTkRadioButton(prov_grid, text=txt, variable=self.var_vision_provider,
                               value=val).grid(row=0, column=c, padx=2)
            c += 1

        c += 1  # skip separator column

        ctk.CTkLabel(prov_grid, text="배경",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold")).grid(row=0, column=c, sticky="w", padx=(8, 4))
        c += 1
        for txt, val in [("Photoroom", "photoroom"), ("remove.bg", "removebg")]:
            ctk.CTkRadioButton(prov_grid, text=txt, variable=self.var_bg_provider,
                               value=val).grid(row=0, column=c, padx=2)
            c += 1

        c += 1  # skip separator column

        ctk.CTkLabel(prov_grid, text="보정",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold")).grid(row=0, column=c, sticky="w", padx=(8, 4))
        c += 1
        for txt, val in [("Claid.ai", "claid"), ("OpenCV", "opencv")]:
            ctk.CTkRadioButton(prov_grid, text=txt, variable=self.var_enhance_provider,
                               value=val).grid(row=0, column=c, padx=2)
            c += 1

        # 그림자 (2행)
        shadow_f = ctk.CTkFrame(prov_card, fg_color="transparent")
        shadow_f.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(shadow_f, text="그림자",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold")).pack(side="left", padx=(8, 6))
        for txt, val in [("API", "api_shadow"), ("Gemini", "gemini_shadow"),
                         ("누끼합성", "opencv_extract"), ("SAM-M", "sam_mobile"),
                         ("SAM-CPU", "sam_cpu")]:
            ctk.CTkRadioButton(shadow_f, text=txt, variable=self.var_shadow_provider,
                               value=val).pack(side="left", padx=2)
        self.rb_sam_gpu_b_main = ctk.CTkRadioButton(shadow_f, text="GPU-B",
                        variable=self.var_shadow_provider, value="sam_gpu_b")
        self.rb_sam_gpu_b_main.pack(side="left", padx=2)
        self.rb_sam_gpu_l_main = ctk.CTkRadioButton(shadow_f, text="GPU-L",
                        variable=self.var_shadow_provider, value="sam_gpu_l")
        self.rb_sam_gpu_l_main.pack(side="left", padx=2)
        self.rb_sam_gpu_h_main = ctk.CTkRadioButton(shadow_f, text="GPU-H",
                        variable=self.var_shadow_provider, value="sam_gpu_h")
        self.rb_sam_gpu_h_main.pack(side="left", padx=2)
        ctk.CTkRadioButton(shadow_f, text="없음", variable=self.var_shadow_provider,
                           value="none").pack(side="left", padx=2)

        # 옵션 카드 (우측, 좁게)
        opt_card = ctk.CTkFrame(mid_row, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        opt_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ctk.CTkLabel(opt_card, text=" 옵션 ", font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        self.var_skip_bg = tk.BooleanVar(value=self._state.get("skip_bg", False))
        self.var_skip_analysis = tk.BooleanVar(value=False)
        self.var_auto_refine = tk.BooleanVar(value=False)
        self.var_max_iterations = tk.IntVar(value=3)

        ctk.CTkCheckBox(opt_card, text="배경 제거 생략",
                        variable=self.var_skip_bg, checkbox_width=18, checkbox_height=18, corner_radius=4).pack(anchor="w", padx=8, pady=1)
        ctk.CTkCheckBox(opt_card, text="AI 분석 생략",
                        variable=self.var_skip_analysis, checkbox_width=18, checkbox_height=18, corner_radius=4).pack(anchor="w", padx=8, pady=1)

        refine_f = ctk.CTkFrame(opt_card, fg_color="transparent")
        refine_f.pack(anchor="w", pady=1)
        ctk.CTkCheckBox(refine_f, text="자동 수정",
                        variable=self.var_auto_refine, checkbox_width=18, checkbox_height=18, corner_radius=4).pack(side="left", padx=(8, 0))
        tk.Spinbox(refine_f, from_=1, to=10, textvariable=self.var_max_iterations,
                   width=3, font=(FONT_FAMILY, 9), bg="#2d3148", fg="#cdd6f4",
                   insertbackground="white", relief="flat").pack(side="left", padx=(4, 0))
        ctk.CTkLabel(refine_f, text="회",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=9)).pack(side="left", padx=(2, 0))

        # ── 3. 실행 버튼 + 프로그레스 (한 줄) ──
        action_bar = ctk.CTkFrame(top_area, fg_color="transparent")
        action_bar.pack(fill="x", pady=(0, 6))

        self.btn_run_single = ctk.CTkButton(action_bar, text="  단일 처리  ",
            command=lambda: self._run("single"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"))
        self.btn_run_single.pack(side="left", padx=(0, 6))
        self.btn_run_batch = ctk.CTkButton(action_bar, text="  배치 처리  ",
            command=lambda: self._run("batch"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"))
        self.btn_run_batch.pack(side="left", padx=(0, 6))
        self.btn_analyze = ctk.CTkButton(action_bar, text="분석만",
            command=lambda: self._run("analyze"), corner_radius=8)
        self.btn_analyze.pack(side="left", padx=(0, 6))
        self.btn_stop = ctk.CTkButton(action_bar, text="중지", command=self._stop, state="disabled",
            fg_color=DANGER, hover_color="#dc2626", corner_radius=8)
        self.btn_stop.pack(side="left", padx=(0, 10))

        # 프로그레스 (버튼 우측에 배치)
        self.progress = ctk.CTkProgressBar(action_bar, corner_radius=6, height=12)
        self.progress.set(0)
        self.progress.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.lbl_progress = ctk.CTkLabel(action_bar, text="0%", width=40, anchor="e",
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=9))
        self.lbl_progress.pack(side="left", padx=(4, 0))

        # ━━━ 하단 영역: 로그 (최대 확장) ━━━
        log_frame = ctk.CTkFrame(parent, fg_color="#0f1117", corner_radius=8)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.log_text = tk.Text(log_frame, height=14, font=("Consolas", 9),
            bg="#0f1117", fg="#cdd6f4", insertbackground="white",
            wrap="word", state="disabled", relief="flat", borderwidth=0)
        log_scrollbar = ctk.CTkScrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_text.tag_config("info", foreground="#89b4fa")
        self.log_text.tag_config("success", foreground="#a6e3a1")
        self.log_text.tag_config("error", foreground="#f38ba8")
        self.log_text.tag_config("warn", foreground="#fab387")

    # ── 탭 2: 프롬프트 편집 ──
    def _build_prompt_tab(self):
        parent = self.tab_prompt

        # 상단 안내
        info_f = ctk.CTkFrame(parent, fg_color="transparent")
        info_f.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(info_f, text="AI 비전 분석 프롬프트",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold")).pack(side="left")
        hint = ctk.CTkLabel(info_f, text="한글/영어 모두 사용 가능  |  수정 후 [저장] 클릭",
                            font=ctk.CTkFont(family=FONT_FAMILY, size=9), text_color="#6b7299")
        hint.pack(side="left", padx=(12, 0))

        # 버튼 바 (상단 배치)
        bf = ctk.CTkFrame(parent, fg_color="transparent")
        bf.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkButton(bf, text="  저장  ", command=self._save_prompts,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bf, text="한글 기본값 복원", command=self._reset_prompts, corner_radius=8).pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(bf, text="파일에서 다시 불러오기", command=self._load_prompts, corner_radius=8).pack(
            side="left")
        self.prompt_status = ctk.CTkLabel(bf, text="")
        self.prompt_status.pack(side="left", padx=15)

        # ── 시스템 프롬프트 ──
        sys_lf = ctk.CTkFrame(parent, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        sys_lf.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(sys_lf, text=" 시스템 프롬프트 (AI 역할 정의) ",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        # 툴팁 아이콘 + 설명
        sys_info = ctk.CTkLabel(sys_lf, text="(?) 이 프롬프트의 역할",
                                font=ctk.CTkFont(family=FONT_FAMILY, size=9), text_color=ACCENT, cursor="hand2")
        sys_info.pack(anchor="w", padx=12, pady=(0, 2))
        ToolTip(sys_info,
                "시스템 프롬프트는 AI의 '역할'을 정의합니다.\n\n"
                "여기서 AI에게 '당신은 럭셔리 이커머스 상품 이미지 분류 전문가입니다' 같은\n"
                "역할을 부여합니다. AI가 응답할 때 이 역할에 맞춰 답변합니다.\n\n"
                "이 프롬프트는 모든 이미지 분석 요청에 공통으로 적용됩니다.\n"
                "JSON만 반환하라는 지시도 여기에 포함하세요.")

        self.txt_system = ctk.CTkTextbox(sys_lf, height=140,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color="#1a1d2e", text_color="#cdd6f4", wrap="word", corner_radius=8)
        self.txt_system.pack(fill="x", padx=8, pady=(0, 8))

        # ── 유저 프롬프트 ──
        usr_lf = ctk.CTkFrame(parent, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        usr_lf.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        ctk.CTkLabel(usr_lf, text=" 분석 요청 프롬프트 (이미지별 전송) ",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        usr_info = ctk.CTkLabel(usr_lf, text="(?) 이 프롬프트의 역할",
                                font=ctk.CTkFont(family=FONT_FAMILY, size=9), text_color=ACCENT, cursor="hand2")
        usr_info.pack(anchor="w", padx=12, pady=(0, 2))
        ToolTip(usr_info,
                "분석 요청 프롬프트는 각 이미지를 분석할 때 전송되는 지시문입니다.\n\n"
                "이미지와 함께 이 프롬프트가 AI에게 전달되며,\n"
                "AI는 이 지시에 따라 이미지 유형(full/detail/worn/package),\n"
                "카테고리(bag/shoes/clothing 등), 배경 상태, 그림자 정보 등을\n"
                "JSON 형식으로 분류하여 반환합니다.\n\n"
                "반환 JSON 구조(필드명)를 변경하면 프로그램이 정상 동작하지\n"
                "않을 수 있습니다. 필드명은 유지하고 설명만 수정하세요.\n\n"
                "{{중괄호 2개}}는 변수 치환 방지용입니다. 실제 JSON 예시에 사용하세요.")

        self.txt_user = ctk.CTkTextbox(usr_lf, height=280,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color="#1a1d2e", text_color="#cdd6f4", wrap="word", corner_radius=8)
        self.txt_user.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ── 탭 3: 설정 ──
    def _build_settings_tab(self):
        parent = self.tab_settings
        canvas = tk.Canvas(parent, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ctk.CTkScrollbar(parent, orientation="vertical", command=canvas.yview)
        scroll_frame = ctk.CTkFrame(canvas, fg_color="transparent")
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
        api_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        api_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(api_lf, text=" API 키 및 모델 ", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

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
        ]

        api_grid = ctk.CTkFrame(api_lf, fg_color="transparent")
        api_grid.pack(fill="x", padx=8)
        for r, (label, env_key, var_name, entry_name, show_var_name, toggle_cmd, save_cmd) in enumerate(api_keys):
            ctk.CTkLabel(api_grid, text=f"{label}:",
                         font=ctk.CTkFont(family=FONT_FAMILY, size=9)).grid(row=r, column=0, sticky="w", padx=(2, 8), pady=3)
            var = tk.StringVar(value=os.environ.get(env_key, ""))
            setattr(self, var_name, var)
            entry = ctk.CTkEntry(api_grid, textvariable=var, show="*", width=400, corner_radius=6)
            entry.grid(row=r, column=1, padx=0, pady=3, sticky="ew")
            setattr(self, entry_name, entry)
            show_var = tk.BooleanVar(value=False)
            setattr(self, show_var_name, show_var)
            ctk.CTkCheckBox(api_grid, text="표시", variable=show_var,
                            command=getattr(self, toggle_cmd),
                            checkbox_width=18, checkbox_height=18, corner_radius=4).grid(row=r, column=2, padx=4)
            ctk.CTkButton(api_grid, text="저장", width=50,
                          command=getattr(self, save_cmd), corner_radius=8).grid(row=r, column=3, padx=(2, 0), pady=3)

        api_grid.columnconfigure(1, weight=1)

        # 모델 선택 행
        model_f = ctk.CTkFrame(api_lf, fg_color="transparent")
        model_f.pack(fill="x", padx=8, pady=(6, 8))

        ctk.CTkLabel(model_f, text="Claude:",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=9)).pack(side="left", padx=(2, 4))
        self.var_model = tk.StringVar(value="claude-sonnet-4-20250514")
        ctk.CTkComboBox(model_f, variable=self.var_model, width=220,
            values=["claude-opus-4-20250514", "claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
            corner_radius=6).pack(side="left", padx=(0, 12))

        ctk.CTkLabel(model_f, text="OpenAI:",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=9)).pack(side="left", padx=(0, 4))
        self.var_openai_model = tk.StringVar(value="gpt-4o")
        ctk.CTkComboBox(model_f, variable=self.var_openai_model, width=130,
            values=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            corner_radius=6).pack(side="left", padx=(0, 12))

        ctk.CTkLabel(model_f, text="Gemini:",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=9)).pack(side="left", padx=(0, 4))
        self.var_gemini_model = tk.StringVar(value="gemini-2.5-flash")
        ctk.CTkComboBox(model_f, variable=self.var_gemini_model, width=160,
            values=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
            corner_radius=6).pack(side="left")

        # ══════════════════════════════════════
        #  2. 처리 프로바이더 선택
        # ══════════════════════════════════════
        prov_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        prov_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(prov_lf, text=" 처리 프로바이더 ", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        prov_f = ctk.CTkFrame(prov_lf, fg_color="transparent")
        prov_f.pack(fill="x", padx=8)

        # 분석
        lbl = ctk.CTkLabel(prov_f, text="이미지 분석:")
        lbl.grid(row=0, column=0, sticky="w", padx=(2, 8), pady=4)
        ToolTip(lbl, "이미지 분석 Vision API 선택.\nClaude: 정밀 분석 (비용 높음)\nChatGPT: GPT-4o Vision\nGemini: 저비용, 빠름")
        for c, (txt, val) in enumerate([("Claude", "claude"), ("ChatGPT", "chatgpt"), ("Gemini", "gemini")]):
            ctk.CTkRadioButton(prov_f, text=txt, variable=self.var_vision_provider,
                               value=val).grid(row=0, column=c+1, padx=4, pady=4)

        # 배경 제거
        lbl = ctk.CTkLabel(prov_f, text="배경 제거:")
        lbl.grid(row=1, column=0, sticky="w", padx=(2, 8), pady=4)
        ToolTip(lbl, "누끼(배경 제거) API 선택.\nPhotoroom: 고품질+그림자 옵션\nremove.bg: 빠름, 무료 티어")
        for c, (txt, val) in enumerate([("Photoroom", "photoroom"), ("remove.bg", "removebg")]):
            ctk.CTkRadioButton(prov_f, text=txt, variable=self.var_bg_provider,
                               value=val).grid(row=1, column=c+1, padx=4, pady=4)

        # 보정
        lbl = ctk.CTkLabel(prov_f, text="이미지 보정:")
        lbl.grid(row=2, column=0, sticky="w", padx=(2, 8), pady=4)
        ToolTip(lbl, "Claid.ai: AI 기반 고품질 (API 비용)\nOpenCV: 로컬 무료 처리")
        for c, (txt, val) in enumerate([("Claid.ai", "claid"), ("OpenCV", "opencv")]):
            ctk.CTkRadioButton(prov_f, text=txt, variable=self.var_enhance_provider,
                               value=val).grid(row=2, column=c+1, padx=4, pady=4)

        # 그림자
        lbl = ctk.CTkLabel(prov_f, text="그림자:")
        lbl.grid(row=3, column=0, sticky="w", padx=(2, 8), pady=4)
        ToolTip(lbl, "API 그림자: 배경제거 API 옵션\nGemini AI: Gemini로 그림자 생성\n"
                "누끼 합성: 원본에서 추출\nSAM: Segment Anything 기반 추출\n없음: 그림자 없이")
        shadow_opts = [("API", "api_shadow"), ("Gemini", "gemini_shadow"),
                       ("누끼합성", "opencv_extract"), ("SAM-M", "sam_mobile"),
                       ("SAM-CPU", "sam_cpu")]
        for c, (txt, val) in enumerate(shadow_opts):
            ctk.CTkRadioButton(prov_f, text=txt, variable=self.var_shadow_provider,
                               value=val).grid(row=3, column=c+1, padx=4, pady=4)
        # GPU options
        gpu_col = len(shadow_opts) + 1
        self.rb_sam_gpu_b_settings = ctk.CTkRadioButton(prov_f, text="GPU-B",
                        variable=self.var_shadow_provider, value="sam_gpu_b")
        self.rb_sam_gpu_b_settings.grid(row=3, column=gpu_col, padx=4, pady=4)
        self.rb_sam_gpu_l_settings = ctk.CTkRadioButton(prov_f, text="GPU-L",
                        variable=self.var_shadow_provider, value="sam_gpu_l")
        self.rb_sam_gpu_l_settings.grid(row=3, column=gpu_col+1, padx=4, pady=4)
        self.rb_sam_gpu_h_settings = ctk.CTkRadioButton(prov_f, text="GPU-H",
                        variable=self.var_shadow_provider, value="sam_gpu_h")
        self.rb_sam_gpu_h_settings.grid(row=3, column=gpu_col+2, padx=4, pady=4)
        ctk.CTkRadioButton(prov_f, text="없음", variable=self.var_shadow_provider,
                           value="none").grid(row=3, column=gpu_col+3, padx=4, pady=4)

        # GPU 상태 + 경고 + 저장
        info_row = ctk.CTkFrame(prov_lf, fg_color="transparent")
        info_row.pack(fill="x", padx=8, pady=(4, 0))
        self.sam_gpu_label = ctk.CTkLabel(info_row, text="",
                                          font=ctk.CTkFont(family=FONT_FAMILY, size=9))
        self.sam_gpu_label.pack(side="left", padx=2)
        self._detect_sam_gpu()
        self.prov_warning = ctk.CTkLabel(info_row, text="", text_color=DANGER,
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=9))
        self.prov_warning.pack(side="left", padx=10)

        btn_row = ctk.CTkFrame(prov_lf, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(4, 8))
        ctk.CTkButton(btn_row, text="설정 저장", command=self._save_provider_settings,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(2, 10))
        self.prov_status = ctk.CTkLabel(btn_row, text="")
        self.prov_status.pack(side="left")

        # 프로바이더 변경 감지
        self.var_bg_provider.trace_add("write", self._update_provider_warning)
        self.var_shadow_provider.trace_add("write", self._update_provider_warning)

        # ══════════════════════════════════════
        #  3. 출력 이미지 설정
        # ══════════════════════════════════════
        out_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        out_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(out_lf, text=" 출력 이미지 ", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        out_grid = ctk.CTkFrame(out_lf, fg_color="transparent")
        out_grid.pack(fill="x", padx=8)
        labels = [
            ("가로 (px):", "var_out_w", "860"),
            ("세로 (px):", "var_out_h", "860"),
            ("최대 용량 (KB):", "var_max_kb", "2024"),
            ("JPEG 품질:", "var_jpeg_q", "95"),
        ]
        for i, (label, var_name, default) in enumerate(labels):
            ctk.CTkLabel(out_grid, text=label).grid(
                row=0, column=i*2, sticky="w", padx=(2 if i==0 else 12, 4), pady=4)
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            ctk.CTkEntry(out_grid, textvariable=var, width=70, corner_radius=6).grid(
                row=0, column=i*2+1, sticky="w", padx=0, pady=4)

        ctk.CTkButton(out_lf, text="설정 저장", command=self._save_settings,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(anchor="w", padx=10, pady=(6, 8))

        # ══════════════════════════════════════
        #  4. Photoroom API 옵션
        # ══════════════════════════════════════
        pr_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        pr_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(pr_lf, text=" Photoroom API 옵션 ", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        self.var_photoroom_mode = tk.StringVar(value="manual")
        pr_mode_f = ctk.CTkFrame(pr_lf, fg_color="transparent")
        pr_mode_f.pack(fill="x", padx=8, pady=(0, 4))
        rb1 = ctk.CTkRadioButton(pr_mode_f, text="수동 설정", variable=self.var_photoroom_mode, value="manual")
        rb1.pack(side="left", padx=(2, 8))
        ToolTip(rb1, "아래 입력값을 그대로 사용합니다")
        rb2 = ctk.CTkRadioButton(pr_mode_f, text="AI 자동", variable=self.var_photoroom_mode, value="ai_auto")
        rb2.pack(side="left")
        ToolTip(rb2, "Vision API가 최적 값을 자동 설정. 아래 값은 AI 실패 시 기본값")

        pr_f = ctk.CTkFrame(pr_lf, fg_color="transparent")
        pr_f.pack(fill="x", padx=8)

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
            lbl = ctk.CTkLabel(pr_f, text=label)
            lbl.grid(row=i, column=0, sticky="w", padx=(2, 8), pady=3)
            ToolTip(lbl, tooltip)
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            if wtype == "combobox":
                w = ctk.CTkComboBox(pr_f, variable=var, values=values,
                                    width=150, corner_radius=6)
            else:
                w = ctk.CTkEntry(pr_f, textvariable=var, width=100, corner_radius=6)
            w.grid(row=i, column=1, sticky="w", padx=0, pady=3)
            ToolTip(w, tooltip)

        pr_btn_f = ctk.CTkFrame(pr_lf, fg_color="transparent")
        pr_btn_f.pack(fill="x", padx=8, pady=(4, 8))
        ctk.CTkButton(pr_btn_f, text="설정 저장", command=self._save_photoroom_settings,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(2, 10))
        self.pr_status = ctk.CTkLabel(pr_btn_f, text="")
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
            mode_f = ctk.CTkFrame(parent_lf, fg_color="transparent")
            mode_f.pack(fill="x", padx=8, pady=(0, 4))
            rb1 = ctk.CTkRadioButton(mode_f, text="수동 설정", variable=mode_var, value="manual")
            rb1.pack(side="left", padx=(2, 8))
            ToolTip(rb1, "아래 입력값을 그대로 사용")
            rb2 = ctk.CTkRadioButton(mode_f, text="AI 자동", variable=mode_var, value="ai_auto")
            rb2.pack(side="left")
            ToolTip(rb2, "Vision API가 최적 값 자동 설정. 아래 값은 기본값")

            grid = ctk.CTkFrame(parent_lf, fg_color="transparent")
            grid.pack(fill="x", padx=8)

            # 헤더 행
            ctk.CTkLabel(grid, text="").grid(row=0, column=0)
            for ci, t in enumerate(enhance_types):
                lbl = ctk.CTkLabel(grid, text=t, font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"))
                lbl.grid(row=0, column=ci*2+1, columnspan=2, padx=6, pady=(0, 2))
                ToolTip(lbl, type_tooltips[t])

            for ri, field in enumerate(enhance_fields):
                lbl = ctk.CTkLabel(grid, text=field, font=ctk.CTkFont(family=FONT_FAMILY, size=9))
                lbl.grid(row=ri+1, column=0, sticky="w", padx=(2, 6), pady=2)
                ToolTip(lbl, field_tooltips[field])
                for ci, t in enumerate(enhance_types):
                    var = tk.StringVar(value=enhance_defaults[t][field])
                    vars_dict[(t, field)] = var
                    ctk.CTkEntry(grid, textvariable=var, width=50, corner_radius=6).grid(
                        row=ri+1, column=ci*2+1, columnspan=2, padx=6, pady=2)

            btn_f = ctk.CTkFrame(parent_lf, fg_color="transparent")
            btn_f.pack(fill="x", padx=8, pady=(4, 8))
            ctk.CTkButton(btn_f, text="설정 저장", command=save_cmd,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                          font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(2, 10))
            status = ctk.CTkLabel(btn_f, text="")
            status.pack(side="left")
            setattr(self, status_attr, status)

        # Claid.ai
        cl_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        cl_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(cl_lf, text=" Claid.ai 보정 옵션 ", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))
        self.var_claid_mode = tk.StringVar(value="manual")
        self.claid_vars = {}
        _build_enhance_grid(cl_lf, self.var_claid_mode, self.claid_vars,
                            "manual", self._save_claid_settings, "cl_status")

        # OpenCV
        cv_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        cv_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(cv_lf, text=" OpenCV 보정 옵션 ", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))
        self.var_opencv_mode = tk.StringVar(value="manual")
        self.opencv_vars = {}
        _build_enhance_grid(cv_lf, self.var_opencv_mode, self.opencv_vars,
                            "manual", self._save_opencv_settings, "cv_status")

        # ══════════════════════════════════════
        #  6. remove.bg 옵션
        # ══════════════════════════════════════
        rb_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        rb_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(rb_lf, text=" remove.bg 옵션 ", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        rb_f = ctk.CTkFrame(rb_lf, fg_color="transparent")
        rb_f.pack(fill="x", padx=8)

        lbl = ctk.CTkLabel(rb_f, text="size:")
        lbl.grid(row=0, column=0, sticky="w", padx=(2, 8), pady=3)
        ToolTip(lbl, "auto: 자동 / full: 원본 크기 (유료) / preview: 저해상도")
        self.var_rb_size = tk.StringVar(value="auto")
        ctk.CTkComboBox(rb_f, variable=self.var_rb_size,
                        values=["auto", "preview", "full"], width=120,
                        corner_radius=6).grid(row=0, column=1, sticky="w", padx=0, pady=3)

        lbl = ctk.CTkLabel(rb_f, text="type:")
        lbl.grid(row=0, column=2, sticky="w", padx=(16, 8), pady=3)
        ToolTip(lbl, "product: 상품 (권장) / person: 사람 / car: 자동차")
        self.var_rb_type = tk.StringVar(value="product")
        ctk.CTkComboBox(rb_f, variable=self.var_rb_type,
                        values=["product", "person", "car"], width=120,
                        corner_radius=6).grid(row=0, column=3, sticky="w", padx=0, pady=3)

        rb_btn_f = ctk.CTkFrame(rb_lf, fg_color="transparent")
        rb_btn_f.pack(fill="x", padx=8, pady=(4, 8))
        ctk.CTkButton(rb_btn_f, text="설정 저장", command=self._save_removebg_settings,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(2, 10))
        self.rb_status = ctk.CTkLabel(rb_btn_f, text="")
        self.rb_status.pack(side="left")

        # ══════════════════════════════════════
        #  7. 누끼 합성 그림자 옵션
        # ══════════════════════════════════════
        se_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        se_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(se_lf, text=" 누끼 합성 그림자 (원본 그림자 추출) ",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        # 추출 방식
        se_top = ctk.CTkFrame(se_lf, fg_color="transparent")
        se_top.pack(fill="x", padx=8, pady=(0, 4))

        self.var_shadow_method = tk.StringVar(value="level_correction")
        ctk.CTkLabel(se_top, text="추출 방식:").pack(side="left", padx=(2, 6))
        rb_lv = ctk.CTkRadioButton(se_top, text="레벨보정", variable=self.var_shadow_method,
                                   value="level_correction")
        rb_lv.pack(side="left", padx=4)
        ToolTip(rb_lv, "pixel/bg*255 비율 정규화.\n배경→흰색, 그림자→비례 보존")
        rb_tp = ctk.CTkRadioButton(se_top, text="원본이식", variable=self.var_shadow_method,
                                   value="transplant")
        rb_tp.pack(side="left", padx=4)
        ToolTip(rb_tp, "255-(bg-pixel) 절대 명암차 보존.\n원본 그림자 색감/질감 유지")

        self.var_shadow_mode = tk.StringVar(value="ai_auto")
        ctk.CTkLabel(se_top, text="파라미터:").pack(side="left", padx=(16, 6))
        rb1 = ctk.CTkRadioButton(se_top, text="수동", variable=self.var_shadow_mode, value="manual")
        rb1.pack(side="left", padx=4)
        ToolTip(rb1, "아래 입력값을 그대로 사용")
        rb2 = ctk.CTkRadioButton(se_top, text="AI 자동", variable=self.var_shadow_mode, value="ai_auto")
        rb2.pack(side="left", padx=4)
        ToolTip(rb2, "Vision API가 최적 값을 자동 설정")

        se_f = ctk.CTkFrame(se_lf, fg_color="transparent")
        se_f.pack(fill="x", padx=8)

        se_opts = [
            ("opacity:", "var_se_opacity", "70", "그림자 진하기 (0~100%). 65~75 자연스러움"),
            ("threshold:", "var_se_threshold", "8", "감지 임계값. 6~12 권장"),
            ("blur:", "var_se_blur", "3", "블러 정도 (0~10). 3~5 자연스러움"),
            ("search_top:", "var_se_search_top", "5", "상단 탐색 (%). 5~8 권장"),
            ("search_bottom:", "var_se_search_bottom", "60", "하단 탐색 (%). 50~70 권장"),
            ("search_sides:", "var_se_search_sides", "30", "좌우 탐색 (%). 25~35 권장"),
            ("mask_expand:", "var_se_mask_expand", "2.5", "마스크 확장 (%). 2~3 권장"),
            ("distance_falloff:", "var_se_distance_falloff", "60", "그라데이션 범위 (%). 30=짧음, 60=보통, 100=넓음"),
        ]
        # 2열 레이아웃
        half = len(se_opts) // 2
        for i, (label, var_name, default, tooltip) in enumerate(se_opts):
            col = 0 if i < half else 2
            row = i if i < half else i - half
            lbl = ctk.CTkLabel(se_f, text=label, font=ctk.CTkFont(family=FONT_FAMILY, size=9))
            lbl.grid(row=row, column=col, sticky="w", padx=(2 if col==0 else 20, 6), pady=3)
            ToolTip(lbl, tooltip)
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            w = ctk.CTkEntry(se_f, textvariable=var, width=70, corner_radius=6)
            w.grid(row=row, column=col+1, sticky="w", padx=0, pady=3)
            ToolTip(w, tooltip)

        se_btn_f = ctk.CTkFrame(se_lf, fg_color="transparent")
        se_btn_f.pack(fill="x", padx=8, pady=(4, 8))
        ctk.CTkButton(se_btn_f, text="설정 저장", command=self._save_shadow_extract_settings,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(2, 10))
        self.se_status = ctk.CTkLabel(se_btn_f, text="")
        self.se_status.pack(side="left")

        # ══════════════════════════════════════
        #  8. Gemini AI 그림자 프롬프트
        # ══════════════════════════════════════
        gs_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        gs_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(gs_lf, text=" Gemini AI 그림자 프롬프트 ",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        # 순서 옵션
        gs_top = ctk.CTkFrame(gs_lf, fg_color="transparent")
        gs_top.pack(fill="x", padx=8, pady=(0, 4))
        self.var_gemini_shadow_order = tk.StringVar(value="after_enhance")
        ctk.CTkLabel(gs_top, text="생성 순서:").pack(side="left", padx=(2, 6))
        rb_after = ctk.CTkRadioButton(gs_top, text="보정 후 (권장)",
                                      variable=self.var_gemini_shadow_order, value="after_enhance")
        rb_after.pack(side="left", padx=4)
        ToolTip(rb_after, "누끼 → 색보정 → Gemini 그림자\n최종 톤에 맞는 그림자 생성")
        rb_before = ctk.CTkRadioButton(gs_top, text="보정 전",
                                       variable=self.var_gemini_shadow_order, value="before_enhance")
        rb_before.pack(side="left", padx=4)
        ToolTip(rb_before, "누끼 → Gemini 그림자 → 색보정\n그림자에도 보정이 적용됨")

        gs_f = ctk.CTkFrame(gs_lf, fg_color="transparent")
        gs_f.pack(fill="x", padx=8)
        gs_f.columnconfigure(1, weight=1)

        prompt_items = [
            ("원본 참고:", "_gemini_ref_prompt", 2,
             "원본 이미지를 함께 전송할 때 사용. 원본 그림자 방향/농도 참고 지시",
             "위 이미지는 원본 제품 사진입니다. 원본에 있는 자연스러운 그림자의 방향, 농도, 부드러움을 참고하세요."),
            ("그림자 생성:", "_gemini_main_prompt", 4,
             "누끼 이미지에 그림자 추가 메인 프롬프트.\n{has_original}은 원본이 있을 때 자동 삽입됨",
             "위 이미지는 배경이 제거된 누끼 이미지입니다. "
             "이 누끼 이미지의 바닥에 자연스러운 접지 그림자(ground shadow)를 추가해주세요. "
             "{has_original}"
             "제품 자체는 절대 변경하지 마세요. 배경은 깨끗한 흰색을 유지하세요. "
             "그림자는 제품 바로 아래에 부드럽게 퍼지는 형태로, "
             "럭셔리 이커머스 제품 사진처럼 고급스럽게 만들어주세요. "
             "누끼 이미지를 기반으로 결과를 출력하세요."),
            ("원본 삽입문:", "_gemini_orig_insert", 2,
             "원본이 있을 때 {has_original} 위치에 삽입되는 문구",
             "원본 사진의 그림자를 최대한 동일하게 재현해주세요. "),
        ]
        for r, (label, attr, height, tooltip, default) in enumerate(prompt_items):
            lbl = ctk.CTkLabel(gs_f, text=label)
            lbl.grid(row=r, column=0, sticky="nw", padx=(2, 8), pady=(4, 2))
            ToolTip(lbl, tooltip)
            txt = tk.Text(gs_f, width=60, height=height,
                          font=(FONT_FAMILY, 10), wrap="word",
                          bg="#1a1d2e", fg="#cdd6f4", insertbackground="white",
                          relief="flat", borderwidth=1)
            txt.grid(row=r, column=1, sticky="ew", padx=0, pady=(4, 2))
            txt.insert("1.0", default)
            setattr(self, attr, txt)

        gs_btn_f = ctk.CTkFrame(gs_lf, fg_color="transparent")
        gs_btn_f.pack(fill="x", padx=8, pady=(4, 8))
        ctk.CTkButton(gs_btn_f, text="설정 저장", command=self._save_gemini_shadow_settings,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(2, 10))
        ctk.CTkButton(gs_btn_f, text="기본값 복원", command=self._reset_gemini_shadow_prompts,
                      corner_radius=8).pack(side="left", padx=(0, 10))
        self.gs_status = ctk.CTkLabel(gs_btn_f, text="")
        self.gs_status.pack(side="left")

        # ══════════════════════════════════════
        #  9. 음성 합성 (TTS)
        # ══════════════════════════════════════
        tts_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        tts_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(tts_lf, text=" 음성 합성 (TTS) ",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        tts_f = ctk.CTkFrame(tts_lf, fg_color="transparent")
        tts_f.pack(fill="x", padx=8)

        # TTS 모드
        r = 0
        lbl = ctk.CTkLabel(tts_f, text="TTS 모드:")
        lbl.grid(row=r, column=0, sticky="w", padx=(2, 8), pady=4)
        ToolTip(lbl, "회의 시 AI 발언을 음성으로 출력")
        self.var_tts_provider = tk.StringVar(value="off")
        tts_mode_f = ctk.CTkFrame(tts_f, fg_color="transparent")
        tts_mode_f.grid(row=r, column=1, sticky="w", pady=4)
        rb_off = ctk.CTkRadioButton(tts_mode_f, text="끄기", variable=self.var_tts_provider, value="off")
        rb_off.pack(side="left", padx=4)
        rb_win = ctk.CTkRadioButton(tts_mode_f, text="Windows TTS (무료)",
                                    variable=self.var_tts_provider, value="windows")
        rb_win.pack(side="left", padx=4)
        ToolTip(rb_win, "Windows 내장 음성 (pyttsx3). 무료, 한국어 1~2개")
        rb_oai = ctk.CTkRadioButton(tts_mode_f, text="OpenAI TTS (유료)",
                                    variable=self.var_tts_provider, value="openai")
        rb_oai.pack(side="left", padx=4)
        ToolTip(rb_oai, "OpenAI TTS API. 자연스러운 음성, 회의 1회당 ~$0.15")

        # OpenAI 모델 + 속도
        r += 1
        ctk.CTkLabel(tts_f, text="OpenAI 모델:").grid(
            row=r, column=0, sticky="w", padx=(2, 8), pady=3)
        self.var_tts_openai_model = tk.StringVar(value="tts-1")
        model_speed_f = ctk.CTkFrame(tts_f, fg_color="transparent")
        model_speed_f.grid(row=r, column=1, sticky="w", pady=3)
        ctk.CTkComboBox(model_speed_f, variable=self.var_tts_openai_model,
                        values=["tts-1", "tts-1-hd", "gpt-4o-mini-tts"],
                        width=150, corner_radius=6).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(model_speed_f, text="속도:").pack(side="left", padx=(0, 4))
        self.var_tts_speed = tk.StringVar(value="1.0")
        ctk.CTkEntry(model_speed_f, textvariable=self.var_tts_speed,
                     width=50, corner_radius=6).pack(side="left")

        # 발언자별 음성
        r += 1
        ctk.CTkLabel(tts_f, text="발언자 음성:").grid(
            row=r, column=0, sticky="nw", padx=(2, 8), pady=3)
        voice_f = ctk.CTkFrame(tts_f, fg_color="transparent")
        voice_f.grid(row=r, column=1, sticky="w", pady=3)

        oai_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        self.var_tts_voice_claude = tk.StringVar(value="alloy")
        self.var_tts_voice_chatgpt = tk.StringVar(value="nova")
        self.var_tts_voice_gemini = tk.StringVar(value="echo")
        self.var_tts_voice_mc = tk.StringVar(value="shimmer")

        for lbl_txt, var in [("Claude:", self.var_tts_voice_claude),
                              ("ChatGPT:", self.var_tts_voice_chatgpt),
                              ("Gemini:", self.var_tts_voice_gemini),
                              ("사회자:", self.var_tts_voice_mc)]:
            vf = ctk.CTkFrame(voice_f, fg_color="transparent")
            vf.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(vf, text=lbl_txt, font=ctk.CTkFont(family=FONT_FAMILY, size=9)).pack(side="left")
            ctk.CTkComboBox(vf, variable=var, values=oai_voices,
                            width=90, corner_radius=6).pack(side="left", padx=2)

        tts_btn_f = ctk.CTkFrame(tts_lf, fg_color="transparent")
        tts_btn_f.pack(fill="x", padx=8, pady=(4, 8))
        ctk.CTkButton(tts_btn_f, text="설정 저장", command=self._save_tts_settings,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(2, 10))
        ctk.CTkButton(tts_btn_f, text="음성 테스트",
                      command=self._test_tts, corner_radius=8).pack(side="left", padx=(0, 10))
        self.tts_status = ctk.CTkLabel(tts_btn_f, text="")
        self.tts_status.pack(side="left")

        # ══════════════════════════════════════
        #  11. 카테고리별 여백
        # ══════════════════════════════════════
        cat_lf = ctk.CTkFrame(sf, corner_radius=10, fg_color=CARD_BG, border_width=1, border_color="#2d3148")
        cat_lf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(cat_lf, text=" 카테고리별 여백 규칙 (더블클릭으로 편집) ",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color="#a5b4fc").pack(anchor="w", padx=12, pady=(8, 2))

        tree_frame = ctk.CTkFrame(cat_lf, fg_color="transparent")
        tree_frame.pack(fill="x", padx=8)

        cols = ("display", "top", "bottom", "left", "right")
        self.cat_tree = ttk.Treeview(tree_frame, columns=cols, height=10)
        self.cat_tree.heading("#0", text="ID")
        self.cat_tree.heading("display", text="이름")
        self.cat_tree.heading("top", text="상")
        self.cat_tree.heading("bottom", text="하")
        self.cat_tree.heading("left", text="좌")
        self.cat_tree.heading("right", text="우")
        self.cat_tree.column("#0", width=160)
        self.cat_tree.column("display", width=120)
        self.cat_tree.column("top", width=60)
        self.cat_tree.column("bottom", width=60)
        self.cat_tree.column("left", width=60)
        self.cat_tree.column("right", width=60)
        self.cat_tree.pack(fill="x")
        self.cat_tree.bind("<Double-1>", self._on_cat_double_click)

        cat_btn = ctk.CTkFrame(cat_lf, fg_color="transparent")
        cat_btn.pack(fill="x", padx=8, pady=(6, 8))
        ctk.CTkButton(cat_btn, text="저장", command=self._save_categories,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left", padx=(2, 8))
        ctk.CTkButton(cat_btn, text="카테고리 추가",
                      command=self._add_category, corner_radius=8).pack(side="left", padx=(0, 8))
        ctk.CTkButton(cat_btn, text="선택 삭제",
                      command=self._delete_category, corner_radius=8).pack(side="left", padx=(0, 8))
        ctk.CTkButton(cat_btn, text="다시 불러오기",
                      command=self._load_categories, corner_radius=8).pack(side="left")
        self.cat_status = ctk.CTkLabel(cat_btn, text="")
        self.cat_status.pack(side="left", padx=15)

    # ── 카테고리 더블클릭 편집 ──
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
            self.cat_status.configure(text="수정됨 (저장 필요)", text_color="#ca8a04")

        entry.bind("<Return>", _save_edit)
        entry.bind("<FocusOut>", _save_edit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    # ── 카테고리 추가 ──
    def _add_category(self):
        self.cat_tree.insert("", "end", text="new_category", values=(
            "새 카테고리", 64, 64, 64, 64))
        self.cat_status.configure(text="추가됨 (저장 필요)", text_color="#ca8a04")

    # ── 카테고리 삭제 ──
    def _delete_category(self):
        selected = self.cat_tree.selection()
        if not selected:
            messagebox.showwarning("선택 필요", "삭제할 카테고리를 선택하세요.")
            return
        for item in selected:
            cat_id = self.cat_tree.item(item, "text")
            self.cat_tree.delete(item)
        self.cat_status.configure(text="삭제됨 (저장 필요)", text_color="#ca8a04")

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
                base["padding_860"] = {
                    "top": int(vals[1]),
                    "bottom": int(vals[2]),
                    "left": int(vals[3]),
                    "right": int(vals[4]),
                }
                if "thumbnail_padding" not in base:
                    base["thumbnail_padding"] = {
                        "top": 359, "bottom": 359, "left": 148, "right": 148
                    }
                new_cats[cat_id] = base

            data["categories"] = new_cats
            save_yaml(CATEGORIES_PATH, data)

            self.cat_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.cat_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

    # ── 설정 로드 ──
    def _load_configs(self):
        self._load_prompts()
        self._load_settings()
        self._load_categories()

    def _load_prompts(self):
        try:
            data = load_yaml(PROMPTS_PATH)
            analysis = data.get("analysis", {})
            self.txt_system.delete("1.0", "end")
            self.txt_system.insert("1.0", analysis.get("system", "").strip())
            self.txt_user.delete("1.0", "end")
            self.txt_user.insert("1.0", analysis.get("user_template", "").strip())
            self.prompt_status.configure(text="프롬프트 로드 완료", text_color=SUCCESS)
        except Exception as e:
            self.prompt_status.configure(text=f"로드 실패: {e}", text_color=DANGER)

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
            self.var_shadow_provider.set(providers.get("shadow", "opencv_extract"))

            # OpenAI/Gemini 설정 로드
            openai_config = data.get("openai", {})
            self.var_openai_model.set(openai_config.get("model", "gpt-4o"))
            gemini_config = data.get("gemini", {})
            self.var_gemini_model.set(gemini_config.get("model", "gemini-2.5-flash"))

            # OpenCV 보정 설정 로드
            cv = data.get("opencv_enhance", {})
            for img_type in ["full", "detail", "worn", "package"]:
                type_data = cv.get(img_type, {})
                for field in ["hdr", "sharpness", "exposure", "saturation", "contrast"]:
                    key = (img_type, field)
                    if key in self.opencv_vars:
                        val = type_data.get(field, 0)
                        self.opencv_vars[key].set(str(val))

            # 누끼 합성 그림자 설정 로드
            se = data.get("shadow_extract", {})
            self.var_shadow_method.set(se.get("method", "level_correction"))
            self.var_se_opacity.set(str(se.get("opacity", 80)))
            self.var_se_threshold.set(str(se.get("threshold", 5)))
            self.var_se_blur.set(str(se.get("blur", 1)))
            self.var_se_search_top.set(str(se.get("search_top", 10)))
            self.var_se_search_bottom.set(str(se.get("search_bottom", 50)))
            self.var_se_search_sides.set(str(se.get("search_sides", 40)))
            self.var_se_mask_expand.set(str(se.get("mask_expand", 1.5)))
            self.var_se_distance_falloff.set(str(se.get("distance_falloff", 60)))

            # Gemini 그림자 설정 로드
            gs = data.get("gemini_shadow", {})
            self.var_gemini_shadow_order.set(gs.get("order", "after_enhance"))
            if gs.get("ref_prompt"):
                self._gemini_ref_prompt.delete("1.0", "end")
                self._gemini_ref_prompt.insert("1.0", gs["ref_prompt"])
            if gs.get("main_prompt"):
                self._gemini_main_prompt.delete("1.0", "end")
                self._gemini_main_prompt.insert("1.0", gs["main_prompt"])
            if gs.get("orig_insert"):
                self._gemini_orig_insert.delete("1.0", "end")
                self._gemini_orig_insert.insert("1.0", gs["orig_insert"])

            # remove.bg 설정 로드
            rb = data.get("removebg", {})
            self.var_rb_size.set(rb.get("size", "auto"))
            self.var_rb_type.set(rb.get("type", "product"))

            # TTS 설정 로드
            tts = data.get("tts", {})
            self.var_tts_provider.set(tts.get("provider", "off"))
            self.var_tts_openai_model.set(tts.get("openai_model", "tts-1"))
            self.var_tts_speed.set(str(tts.get("speed", 1.0)))
            voices = tts.get("voices", {})
            self.var_tts_voice_claude.set(voices.get("claude", "alloy"))
            self.var_tts_voice_chatgpt.set(voices.get("chatgpt", "nova"))
            self.var_tts_voice_gemini.set(voices.get("gemini", "echo"))
            self.var_tts_voice_mc.set(voices.get("mc", "shimmer"))

            # AI 자동/수동 모드 설정 로드
            auto_opts = data.get("auto_options", {})
            self.var_claid_mode.set(auto_opts.get("claid", "manual"))
            self.var_opencv_mode.set(auto_opts.get("opencv", "manual"))
            self.var_photoroom_mode.set(auto_opts.get("photoroom", "manual"))
            self.var_shadow_mode.set(auto_opts.get("shadow", "ai_auto"))
        except Exception:
            pass

    def _load_categories(self):
        try:
            data = load_yaml(CATEGORIES_PATH)
            cats = data.get("categories", {})

            for item in self.cat_tree.get_children():
                self.cat_tree.delete(item)

            for cat_id, cat_data in cats.items():
                p = cat_data.get("padding_860", {})
                self.cat_tree.insert("", "end", text=cat_id, values=(
                    cat_data.get("display_name", ""),
                    p.get("top", 0), p.get("bottom", 0),
                    p.get("left", 0), p.get("right", 0),
                ))
            self.cat_status.configure(text="", text_color=SUCCESS)
        except Exception:
            pass

    # ── 프롬프트 저장 ──
    def _save_prompts(self):
        try:
            data = load_yaml(PROMPTS_PATH)
            data["analysis"]["system"] = self.txt_system.get("1.0", "end").strip() + "\n"
            data["analysis"]["user_template"] = self.txt_user.get("1.0", "end").strip() + "\n"
            save_yaml(PROMPTS_PATH, data)
            self.prompt_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.prompt_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

    def _reset_prompts(self):
        self.txt_system.delete("1.0", "end")
        self.txt_system.insert("1.0",
            "당신은 LUXBOY 럭셔리 이커머스 플랫폼의 전문 상품 이미지 분류기입니다.\n"
            "제공된 상품 이미지를 분석하고 JSON 객체만 반환하세요.\n"
            "JSON 외의 텍스트는 포함하지 마세요.")
        self.txt_user.delete("1.0", "end")
        self.txt_user.insert("1.0",
            "이 상품 이미지를 이커머스 처리용으로 분석하세요.\n"
            "여러 이미지가 제공되면 동일 상품의 다른 각도입니다. 첫 번째 이미지가 분류 대상입니다.\n\n"
            "분류 기준:\n"
            "- image_type:\n"
            '  - "full": 상품 전체가 보이는 사진 (가방 전체, 신발 전체 등)\n'
            '  - "detail": 상품 일부분 클로즈업 (로고, 버클, 질감, 내부, 솔, 스티칭 등)\n'
            '  - "worn": 모델 착용 또는 마네킹 착용 사진\n'
            '  - "package": 패키징 요소 (박스, 더스트백, 보증서, 태그 등)\n\n'
            "- background:\n"
            '  - "clean": 단색/무지 배경 (흰색, 회색, 스튜디오 배경)\n'
            '  - "complex": 매장, 야외, 소품이 보이는 배경\n'
            '  - "none": 극단적 클로즈업으로 배경이 거의 없음\n\n'
            "다음 JSON 구조로 반환하세요:\n"
            "{{\n"
            '  "image_type": "<full | detail | worn | package>",\n'
            '  "category": "<bag | shoes | clothing | accessory | watch | jewelry | wallet | belt | scarf | hat | sunglasses | other>",\n'
            '  "category_display": "<카테고리 한글 표시명>",\n'
            '  "background": "<clean | complex | none>",\n'
            '  "subject_position": "<center | left | right | top | bottom>",\n'
            '  "is_detail_cut": <boolean, image_type이 "detail"이면 true>,\n'
            '  "detail_focus_area": <객체 또는 null. is_detail_cut이 true일 때만 강조 영역 제공. 정규화 좌표(0.0~1.0). 예: {{"x": 0.15, "y": 0.20, "width": 0.65, "height": 0.65}}>,\n'
            '  "needs_shadow": <boolean. 이커머스 표시용 바닥 그림자가 필요한지. 주의: 탑다운(위에서 내려다본) 촬영이면 반드시 false. 플랫레이, 디테일컷, 착용샷도 false. 정면/측면 촬영으로 바닥에 놓인 상품만 true>,\n'
            '  "shadow_direction": <문자열 또는 null. needs_shadow가 true이고 원본에 그림자가 보일 때 방향. "bottom", "bottom-left", "bottom-right", "left", "right" 중 선택>,\n'
            '  "shadow_params": <객체 또는 null. needs_shadow가 true일 때 최적 그림자 추출 파라미터. 원본 그림자를 최대한 재현하는 것이 목표.\n'
            '    예: {{"search_bottom": 120, "search_top": 5, "search_sides": 50, "blur": 8.0, "opacity": 80, "threshold": 10, "mask_expand": 2.0, "distance_falloff": 60}}>,\n'
            '  "has_human_hand": <boolean. 사람의 손이나 손가락이 보이면 true>,\n'
            '  "hand_region": <객체 또는 null. has_human_hand가 true일 때 손 영역 바운딩 박스. 정규화 좌표>,\n'
            '  "product_only_region": <객체 또는 null. has_human_hand가 true일 때 손을 제외한 상품만의 바운딩 박스. 상품이 최대한 크게 나오도록>,\n'
            '  "enhance_params": {{\n'
            '    "hdr": <정수 0-50. HDR/로컬 대비 강도>,\n'
            '    "sharpness": <정수 0-30. 선명도>,\n'
            '    "exposure": <정수 -30~30. 노출 보정>,\n'
            '    "saturation": <정수 -20~20. 채도 조정>,\n'
            '    "contrast": <정수 -20~20. 대비 조정>\n'
            "  }},\n"
            '  "photoroom_params": <객체 또는 null. image_type이 "full" 또는 "package"이고 needs_shadow가 true일 때만.\n'
            '    예: {{"shadow.opacity": 0.5, "padding": 0.05}}>,\n'
            '  "confidence": <0~1 실수>,\n'
            '  "notes": "<이미지에 대한 간단한 설명>"\n'
            "}}\n\n"
            "정확하게 분류하세요. image_type과 background 판정이 처리 파이프라인을 결정합니다.")
        self.prompt_status.configure(text="한글 기본값 복원됨 (저장 필요)", text_color="#ca8a04")

    # ── 설정 저장 ──
    def _save_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            data["output"]["width"] = int(self.var_out_w.get())
            data["output"]["height"] = int(self.var_out_h.get())
            data["output"]["max_file_size_kb"] = int(self.var_max_kb.get())
            data["output"]["default_jpeg_quality"] = int(self.var_jpeg_q.get())
            data["api"]["model"] = self.var_model.get()
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
            self.pr_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.pr_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

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
            self.cl_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.cl_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

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
        self.entry_api_key.configure(show="" if self.var_show_key.get() else "*")

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
        self.entry_photoroom_key.configure(show="" if self.var_show_photoroom_key.get() else "*")

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
        self.entry_claid_key.configure(show="" if self.var_show_claid_key.get() else "*")

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
        self.entry_removebg_key.configure(show="" if self.var_show_removebg_key.get() else "*")

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
        self.entry_openai_key.configure(show="" if self.var_show_openai_key.get() else "*")

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
        self.entry_gemini_key.configure(show="" if self.var_show_gemini_key.get() else "*")

    def _save_provider_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            providers = data.setdefault("providers", {})
            providers["vision"] = self.var_vision_provider.get()
            providers["background_removal"] = self.var_bg_provider.get()
            providers["enhancement"] = self.var_enhance_provider.get()
            providers["shadow"] = self.var_shadow_provider.get()
            # SAM 모델 설정 저장
            save_yaml(SETTINGS_PATH, data)
            self.prov_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.prov_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

    def _detect_sam_gpu(self):
        """GPU 감지 → VRAM별 SAM GPU-B/L/H 버튼 활성화/비활성화."""
        has_gpu = False
        vram_gb = 0
        try:
            from src.sam.client import SamShadowClient
            info = SamShadowClient.detect_gpu_capability()
            has_gpu = info.get("has_gpu", False)
            vram_gb = info.get("vram_gb", 0)
            if has_gpu:
                gpu_text = f"GPU: {info['gpu_name']} ({vram_gb}GB VRAM)"
                # VRAM별 사용 가능 모델 표시
                avail = []
                if vram_gb >= 2:
                    avail.append("VIT-B")
                if vram_gb >= 4:
                    avail.append("VIT-L")
                if vram_gb >= 6:
                    avail.append("VIT-H")
                gpu_text += f" — 사용 가능: {', '.join(avail)}"
                self.sam_gpu_label.configure(text=gpu_text, text_color=SUCCESS)
            else:
                self.sam_gpu_label.configure(text="GPU 없음 — SAM GPU 비활성",
                                           text_color="#ca8a04")
        except Exception:
            self.sam_gpu_label.configure(text="torch 미설치 — SAM 사용 불가",
                                       text_color=DANGER)

        # VRAM별 GPU 버튼 활성화/비활성화
        gpu_buttons = {
            "b": {"min_vram": 2, "main": "rb_sam_gpu_b_main", "settings": "rb_sam_gpu_b_settings"},
            "l": {"min_vram": 4, "main": "rb_sam_gpu_l_main", "settings": "rb_sam_gpu_l_settings"},
            "h": {"min_vram": 6, "main": "rb_sam_gpu_h_main", "settings": "rb_sam_gpu_h_settings"},
        }
        for suffix, cfg in gpu_buttons.items():
            enabled = has_gpu and vram_gb >= cfg["min_vram"]
            state = "normal" if enabled else "disabled"
            for attr in (cfg["main"], cfg["settings"]):
                if hasattr(self, attr):
                    getattr(self, attr).configure(state=state)

        # GPU 부족한 모델 선택되어 있으면 가능한 최상위로 변경
        current = self.var_shadow_provider.get()
        if current.startswith("sam_gpu_"):
            suffix = current.split("_")[-1]  # b, l, h
            min_vram = {"b": 2, "l": 4, "h": 6}.get(suffix, 0)
            if not has_gpu or vram_gb < min_vram:
                # VRAM에 맞는 최상위 GPU 모델로 폴백
                if has_gpu and vram_gb >= 4:
                    self.var_shadow_provider.set("sam_gpu_l")
                elif has_gpu and vram_gb >= 2:
                    self.var_shadow_provider.set("sam_gpu_b")
                else:
                    self.var_shadow_provider.set("sam_mobile")

    def _update_provider_warning(self, *args):
        bg = self.var_bg_provider.get()
        shadow = self.var_shadow_provider.get()
        if shadow == "api_shadow" and bg == "removebg":
            self.prov_warning.configure(
                text="* remove.bg는 그림자 API 옵션을 지원하지 않습니다. Photoroom 선택 시 사용 가능")
        elif shadow == "sam_mobile":
            self.prov_warning.configure(
                text="* SAM Mobile: MobileSAM 경량 (models/mobile_sam.pt 40.7MB, CPU 3~5초)")
        elif shadow == "sam_cpu":
            self.prov_warning.configure(
                text="* SAM CPU: VIT-B CPU (models/sam_vit_b_01ec64.pth 375MB, 10~30초)")
        elif shadow == "sam_gpu_b":
            self.prov_warning.configure(
                text="* GPU-B: VIT-B GPU (375MB, VRAM 2GB+, 2~5초)")
        elif shadow == "sam_gpu_l":
            self.prov_warning.configure(
                text="* GPU-L: VIT-L GPU (models/sam_vit_l_0b3195.pth 1.2GB, VRAM 4GB+, 3~8초)")
        elif shadow == "sam_gpu_h":
            self.prov_warning.configure(
                text="* GPU-H: VIT-H GPU (models/sam_vit_h_4b8939.pth 2.5GB, VRAM 6GB+, 5~10초)")
        else:
            self.prov_warning.configure(text="")

    def _save_opencv_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            cv = data.setdefault("opencv_enhance", {})
            for img_type in ["full", "detail", "worn", "package"]:
                type_data = cv.setdefault(img_type, {})
                for field in ["hdr", "sharpness", "exposure", "saturation", "contrast"]:
                    key = (img_type, field)
                    if key in self.opencv_vars:
                        type_data[field] = int(self.opencv_vars[key].get())

            auto_opts = data.setdefault("auto_options", {})
            auto_opts["opencv"] = self.var_opencv_mode.get()

            save_yaml(SETTINGS_PATH, data)
            self.cv_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.cv_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

    def _save_shadow_extract_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            se = data.setdefault("shadow_extract", {})
            se["method"] = self.var_shadow_method.get()
            se["opacity"] = int(float(self.var_se_opacity.get()))
            se["threshold"] = int(float(self.var_se_threshold.get()))
            se["blur"] = float(self.var_se_blur.get())
            se["search_top"] = int(float(self.var_se_search_top.get()))
            se["search_bottom"] = int(float(self.var_se_search_bottom.get()))
            se["search_sides"] = int(float(self.var_se_search_sides.get()))
            se["mask_expand"] = float(self.var_se_mask_expand.get())
            se["distance_falloff"] = int(float(self.var_se_distance_falloff.get()))

            auto_opts = data.setdefault("auto_options", {})
            auto_opts["shadow"] = self.var_shadow_mode.get()

            save_yaml(SETTINGS_PATH, data)
            self.se_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.se_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

    def _save_tts_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            tts = data.setdefault("tts", {})
            tts["provider"] = self.var_tts_provider.get()
            tts["openai_model"] = self.var_tts_openai_model.get()
            tts["speed"] = float(self.var_tts_speed.get())
            tts["voices"] = {
                "claude": self.var_tts_voice_claude.get(),
                "chatgpt": self.var_tts_voice_chatgpt.get(),
                "gemini": self.var_tts_voice_gemini.get(),
                "mc": self.var_tts_voice_mc.get(),
            }
            save_yaml(SETTINGS_PATH, data)
            # TTS 엔진 업데이트
            if hasattr(self, '_tts_engine'):
                self._tts_engine.update_config(
                    provider=tts["provider"],
                    openai_model=tts["openai_model"],
                    speed=tts["speed"],
                    voice_map=tts["voices"],
                    openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                )
            self.tts_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.tts_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

    def _test_tts(self):
        """TTS 음성 테스트."""
        provider = self.var_tts_provider.get()
        if provider == "off":
            self.tts_status.configure(text="TTS가 꺼져 있습니다.", text_color=DANGER)
            return
        self._ensure_tts_engine()
        self.tts_status.configure(text="음성 테스트 중...", text_color="#89b4fa")

        def _do_test():
            try:
                self._tts_engine.speak_sync(
                    "안녕하세요. 음성 테스트입니다.", "claude")
                self.after(0, lambda: self.tts_status.configure(
                    text="테스트 완료!", text_color=SUCCESS))
            except Exception as e:
                self.after(0, lambda: self.tts_status.configure(
                    text=f"테스트 실패: {e}", text_color=DANGER))

        threading.Thread(target=_do_test, daemon=True).start()

    def _ensure_tts_engine(self):
        """TTS 엔진 초기화 (없으면 생성). GUI 값을 항상 우선 사용."""
        # GUI 현재 값 읽기 (사용자가 변경했을 수 있음)
        gui_provider = self.var_tts_provider.get()
        gui_model = self.var_tts_openai_model.get()
        gui_speed = float(self.var_tts_speed.get())
        gui_voices = {
            "claude": self.var_tts_voice_claude.get(),
            "chatgpt": self.var_tts_voice_chatgpt.get(),
            "gemini": self.var_tts_voice_gemini.get(),
            "mc": self.var_tts_voice_mc.get(),
        }

        if not hasattr(self, '_tts_engine') or self._tts_engine is None:
            from src.tts.engine import TTSEngine
            self._tts_engine = TTSEngine(
                provider=gui_provider,
                openai_model=gui_model,
                openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                voice_map=gui_voices,
                speed=gui_speed,
            )
        else:
            # 현재 GUI 설정으로 업데이트
            self._tts_engine.update_config(
                provider=gui_provider,
                openai_model=gui_model,
                openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                speed=gui_speed,
                voice_map=gui_voices,
            )
        return self._tts_engine

    def _save_gemini_shadow_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            gs = data.setdefault("gemini_shadow", {})
            gs["order"] = self.var_gemini_shadow_order.get()
            gs["ref_prompt"] = self._gemini_ref_prompt.get("1.0", "end-1c").strip()
            gs["main_prompt"] = self._gemini_main_prompt.get("1.0", "end-1c").strip()
            gs["orig_insert"] = self._gemini_orig_insert.get("1.0", "end-1c").strip()
            save_yaml(SETTINGS_PATH, data)
            self.gs_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.gs_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

    def _reset_gemini_shadow_prompts(self):
        self._gemini_ref_prompt.delete("1.0", "end")
        self._gemini_ref_prompt.insert("1.0",
            "위 이미지는 원본 제품 사진입니다. 원본에 있는 자연스러운 그림자의 "
            "방향, 농도, 부드러움을 참고하세요.")
        self._gemini_main_prompt.delete("1.0", "end")
        self._gemini_main_prompt.insert("1.0",
            "위 이미지는 배경이 제거된 누끼 이미지입니다. "
            "이 누끼 이미지의 바닥에 자연스러운 접지 그림자(ground shadow)를 추가해주세요. "
            "{has_original}"
            "제품 자체는 절대 변경하지 마세요. 배경은 깨끗한 흰색을 유지하세요. "
            "그림자는 제품 바로 아래에 부드럽게 퍼지는 형태로, "
            "럭셔리 이커머스 제품 사진처럼 고급스럽게 만들어주세요. "
            "누끼 이미지를 기반으로 결과를 출력하세요.")
        self._gemini_orig_insert.delete("1.0", "end")
        self._gemini_orig_insert.insert("1.0",
            "원본 사진의 그림자를 최대한 동일하게 재현해주세요. ")
        self.gs_status.configure(text="기본값 복원됨", text_color=SUCCESS)

    def _save_removebg_settings(self):
        try:
            data = load_yaml(SETTINGS_PATH)
            rb = data.setdefault("removebg", {})
            rb["size"] = self.var_rb_size.get()
            rb["type"] = self.var_rb_type.get()
            save_yaml(SETTINGS_PATH, data)
            self.rb_status.configure(
                text=f"저장 완료 ({datetime.now().strftime('%H:%M:%S')})",
                text_color=SUCCESS)
        except Exception as e:
            self.rb_status.configure(text=f"저장 실패: {e}", text_color=DANGER)

    # ── 폴더 ──
    def _browse_input(self):
        folder = filedialog.askdirectory(title="입력 이미지 폴더 선택")
        if folder:
            self.var_input.set(folder)

    def _open_input_folder(self):
        path = self.var_input.get().strip()
        if not path:
            messagebox.showwarning("알림", "입력 경로가 설정되지 않았습니다.")
            return
        p = Path(path)
        # 단일 파일이면 해당 파일의 부모 폴더를 열기
        if p.is_file():
            os.startfile(str(p.parent))
        elif p.is_dir():
            os.startfile(path)
        else:
            messagebox.showwarning("알림", "입력 경로가 존재하지 않습니다.")

    def _browse_output(self):
        folder = filedialog.askdirectory(title="출력 폴더 선택")
        if folder:
            self.var_output.set(folder)

    def _open_output_folder(self):
        folder = self.var_output.get().strip()
        if folder and Path(folder).is_dir():
            os.startfile(folder)
        else:
            messagebox.showwarning("알림", "출력 폴더가 존재하지 않습니다.")

    # ── 로그 ──
    def _log(self, msg, tag="info"):
        def _do():
            self.log_text.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{ts}] {msg}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_progress(self, current, total):
        if total <= 0:
            return
        pct = (current / total) * 100
        def _do():
            self.progress.set(current / total if total > 0 else 0)
            self.lbl_progress.configure(text=f"{pct:.0f}%")
            self.status_bar.configure(text=f"처리 중... {current}/{total}")
        self.after(0, _do)

    # ── 실행 ──
    def _set_running(self, running):
        self._processing = running
        state = "disabled" if running else "normal"
        self.btn_run_single.configure(state=state)
        self.btn_run_batch.configure(state=state)
        self.btn_analyze.configure(state=state)
        self.btn_stop.configure(state="normal" if running else "disabled")
        if not running:
            self.progress.set(0)
            self.lbl_progress.configure(text="0%")

    def _stop(self):
        self._processing = False
        self._log("사용자에 의해 중지 요청됨", "warn")

    def _browse_single_file(self):
        """단일 이미지 파일 선택 대화상자. 기존 입력 경로를 초기 디렉토리로 사용."""
        filetypes = [
            ("이미지 파일", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp"),
            ("모든 파일", "*.*"),
        ]
        # 기존 입력 경로에서 초기 디렉토리 결정
        current = self.var_input.get().strip()
        initial_dir = ""
        if current:
            p = Path(current)
            if p.is_file():
                initial_dir = str(p.parent)
            elif p.is_dir():
                initial_dir = str(p)

        filepath = filedialog.askopenfilename(
            title="처리할 이미지 파일 선택",
            filetypes=filetypes,
            initialdir=initial_dir or None)
        if filepath:
            self.var_input.set(filepath)
        return filepath

    def _run(self, mode):
        if mode == "single":
            # 항상 파일 선택 대화상자 표시
            input_path = self._browse_single_file()
            if not input_path:
                return
            if not Path(input_path).is_file():
                messagebox.showerror("오류", f"이미지 파일이 존재하지 않습니다:\n{input_path}")
                return
        else:
            input_path = self.var_input.get().strip()
            if not input_path:
                messagebox.showwarning("경고", "입력 폴더를 선택하세요.")
                return
            if not Path(input_path).exists():
                messagebox.showerror("오류", f"입력 경로가 존재하지 않습니다:\n{input_path}")
                return

        if not self.var_skip_analysis.get():
            vision_prov = self.var_vision_provider.get()
            if vision_prov == "chatgpt":
                openai_key = self.var_openai_key.get().strip() or os.environ.get("OPENAI_API_KEY", "")
                if not openai_key:
                    messagebox.showwarning("API 키 필요",
                        "ChatGPT Vision 분석을 위해 OpenAI API 키가 필요합니다.\n"
                        "[설정] 탭에서 OPENAI_API_KEY를 입력하거나,\n"
                        "[AI분석 생략] 옵션을 체크하세요.")
                    return
                os.environ["OPENAI_API_KEY"] = openai_key
            elif vision_prov == "gemini":
                gemini_key = self.var_gemini_key.get().strip() or os.environ.get("GEMINI_API_KEY", "")
                if not gemini_key:
                    messagebox.showwarning("API 키 필요",
                        "Gemini Vision 분석을 위해 Gemini API 키가 필요합니다.\n"
                        "[설정] 탭에서 GEMINI_API_KEY를 입력하거나,\n"
                        "[AI분석 생략] 옵션을 체크하세요.")
                    return
                os.environ["GEMINI_API_KEY"] = gemini_key
            else:
                api_key = self.var_api_key.get().strip() or os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    messagebox.showwarning("API 키 필요",
                        "Claude Vision API 분석을 위해 API 키가 필요합니다.\n"
                        "[설정] 탭에서 API 키를 입력하거나,\n"
                        "[AI분석 생략] 옵션을 체크하세요.")
                    return

        # 프로바이더별 API 키 검증
        bg_prov = self.var_bg_provider.get()
        enhance_prov = self.var_enhance_provider.get()

        if not self.var_skip_bg.get():
            if bg_prov == "photoroom":
                photoroom_key = self.var_photoroom_key.get().strip() or os.environ.get("PHOTOROOM_API_KEY", "")
                if not photoroom_key:
                    messagebox.showwarning("API 키 필요",
                        "Photoroom API 키가 필요합니다.\n"
                        "[설정] 탭에서 PHOTOROOM_API_KEY를 입력하세요.")
                    return
                os.environ["PHOTOROOM_API_KEY"] = photoroom_key
            elif bg_prov == "removebg":
                removebg_key = self.var_removebg_key.get().strip() or os.environ.get("REMOVEBG_API_KEY", "")
                if not removebg_key:
                    messagebox.showwarning("API 키 필요",
                        "remove.bg API 키가 필요합니다.\n"
                        "[설정] 탭에서 REMOVEBG_API_KEY를 입력하세요.")
                    return
                os.environ["REMOVEBG_API_KEY"] = removebg_key

        if enhance_prov == "claid":
            claid_key = self.var_claid_key.get().strip() or os.environ.get("CLAID_API_KEY", "")
            if not claid_key:
                messagebox.showwarning("API 키 필요",
                    "Claid.ai API 키가 필요합니다.\n"
                    "[설정] 탭에서 CLAID_API_KEY를 입력하세요.")
                return
            os.environ["CLAID_API_KEY"] = claid_key

        # 실행 전 프로바이더 설정을 settings.yaml에 저장
        try:
            data = load_yaml(SETTINGS_PATH)
            providers = data.setdefault("providers", {})
            providers["vision"] = self.var_vision_provider.get()
            providers["background_removal"] = self.var_bg_provider.get()
            providers["enhancement"] = self.var_enhance_provider.get()
            providers["shadow"] = self.var_shadow_provider.get()
            # OpenAI/Gemini 모델 설정 저장
            openai_config = data.setdefault("openai", {})
            openai_config["model"] = self.var_openai_model.get()
            gemini_config = data.setdefault("gemini", {})
            gemini_config["model"] = self.var_gemini_model.get()
            save_yaml(SETTINGS_PATH, data)
        except Exception:
            pass

        self._clear_log()
        self._set_running(True)
        self._log(f"작업 모드: {mode}")
        self._log(f"입력: {input_path}")
        self._log(f"카테고리: 자동 감지")
        out_w = self.var_out_w.get()
        out_h = self.var_out_h.get()
        self._log(f"출력 사이즈: {out_w}x{out_h} px")

        thread = threading.Thread(target=self._run_worker, args=(mode,), daemon=True)
        thread.start()

    def _run_worker(self, mode):
        try:
            self._log("파이프라인 초기화 중...")
            from src.pipeline import ImageEditPipeline

            pipeline = ImageEditPipeline(config_dir=str(CONFIG_DIR))

            input_path = self.var_input.get().strip()
            output_dir = self.var_output.get().strip()
            category = ""  # 항상 자동 감지
            skip_analysis = self.var_skip_analysis.get()
            skip_bg = self.var_skip_bg.get()

            def _resolve_target(p_str):
                p = Path(p_str)
                if p.is_dir():
                    from src.utils.image_io import get_image_files
                    files = get_image_files(str(p))
                    if not files:
                        self._log("이미지를 찾을 수 없습니다.", "error")
                        return None
                    return files[0]
                return str(p)

            if mode == "analyze":
                target = _resolve_target(input_path)
                if not target:
                    return
                self._set_progress(0, 1)
                instruction = pipeline.analyze_only(
                    target, category, on_log=self._log)
                self._set_progress(1, 1)

                from src.photoroom.client import PhotoroomClient

                self._log("━━━ 분류 결과 ━━━", "success")
                if instruction.detected_category:
                    self._log(f"  감지 카테고리: {instruction.detected_category} "
                              f"({instruction.detected_category_display})", "success")
                self._log(f"  이미지 유형: {instruction.image_type}", "success")
                self._log(f"  배경 상태:   {instruction.background}", "success")
                self._log(f"  피사체 위치: {instruction.subject_position}", "success")
                self._log(f"  확신도:      {instruction.confidence:.2f}", "success")
                detail_info = '아니오'
                if instruction.is_detail_cut:
                    fa = instruction.detail_focus_area
                    if fa:
                        detail_info = f"예 (focus: x={fa['x']:.2f} y={fa['y']:.2f} {fa['width']:.2f}x{fa['height']:.2f})"
                    else:
                        detail_info = '예 (중앙 크롭)'
                self._log(f"  디테일 컷:   {detail_info}", "success")
                self._log(f"  비고:        {instruction.notes}", "success")

                will_photoroom = not self.var_skip_bg.get() and PhotoroomClient.should_process(
                    instruction.image_type, instruction.background)
                self._log(f"  Photoroom:   {'처리' if will_photoroom else '스킵'}", "success")
                self._log(f"  그림자:      {'필요' if instruction.needs_shadow else '불필요'}", "success")
                self._log(f"  사람 손:     {'감지' if instruction.has_human_hand else '없음'}", "success")
                self._log(f"  Claid.ai:    처리 ({instruction.image_type} 프리셋)", "success")
                self._log("━━━━━━━━━━━━━━━━━", "success")

            elif mode == "single":
                target = input_path
                if not Path(target).is_file():
                    self._log("이미지 파일을 찾을 수 없습니다.", "error")
                    return
                self._set_progress(0, 1)

                if self.var_auto_refine.get():
                    max_iter = self.var_max_iterations.get()
                    # 토론 채팅 윈도우 열기
                    self.after(0, self._open_deliberation_window)
                    result = pipeline.process_with_refinement(
                        image_path=target, category=category,
                        output_dir=output_dir, max_iterations=max_iter,
                        skip_analysis=skip_analysis, skip_photoroom=skip_bg,
                        on_log=self._log,
                        on_iteration=lambda i, t: self._set_progress(i, t),
                        on_deliberation=self._on_deliberation,
                        is_cancelled=lambda: not self._processing,
                        get_user_input=self._get_user_messages,
                    )
                    self._log_refinement_result(result)
                else:
                    result = pipeline.process_single(
                        image_path=target, category=category, output_dir=output_dir,
                        skip_analysis=skip_analysis, skip_photoroom=skip_bg,
                        on_log=self._log)
                    self._log_result(result)

                self._set_progress(1, 1)

            elif mode == "batch":
                from src.utils.image_io import get_image_files
                files = get_image_files(input_path)
                total = len(files)
                if total == 0:
                    self._log("이미지를 찾을 수 없습니다.", "error")
                    return

                results = pipeline.process_batch(
                    input_dir=input_path, category=category, output_dir=output_dir,
                    skip_analysis=skip_analysis, skip_photoroom=skip_bg,
                    on_log=self._log,
                    on_progress=self._set_progress,
                    is_cancelled=lambda: not self._processing,
                )

                success = sum(1 for r in results if r.get("success"))
                total_files = sum(
                    len(r.get("files", [])) for r in results if r.get("success"))
                self._log(
                    f"━━━ 배치 완료: 성공 {success}/{len(results)}, "
                    f"총 {total_files}개 파일 생성 ━━━", "success")

        except Exception as e:
            self._log(f"오류 발생: {e}", "error")
            import traceback
            self._log(traceback.format_exc(), "error")
        finally:
            self.after(0, lambda: self._set_running(False))
            self.after(0, lambda: self.status_bar.configure(text="완료"))

    def _log_result(self, result):
        actions = result.get("edit_actions", [])
        if actions:
            self._log("━━━ 편집 적용 요약 ━━━", "success")
            for a in actions:
                self._log(f"  {a}", "success")

        files = result.get("files", [])
        self._log(f"━━━ 처리 완료: {len(files)}개 파일 생성 ━━━", "success")
        for f in files:
            self._log(f"  {f['path']} ({f['size_kb']}KB, Q={f['quality']})", "success")

    # ── AI 토론 채팅 윈도우 ──

    def _open_deliberation_window(self):
        """AI 토론 과정을 실시간으로 보여주는 채팅 스타일 윈도우."""
        if hasattr(self, '_delib_win') and self._delib_win and self._delib_win.winfo_exists():
            self._delib_win.lift()
            # 기존 내용 초기화
            self._delib_chat.delete("1.0", "end")
            return

        win = ctk.CTkToplevel(self)
        win.title("AI 회의실 (Claude / ChatGPT / Gemini)")
        win.geometry("800x700")
        win.configure(fg_color="#11111b")
        self._delib_win = win
        self._delib_current_phase = 0
        self._user_messages = []  # 사용자 입력 메시지 큐

        # ── 상단 헤더 ──
        hdr = tk.Frame(win, bg="#1e1e2e", height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="AI 패널 회의",
                 font=(FONT_FAMILY, 13, "bold"),
                 bg="#1e1e2e", fg="#cdd6f4").pack(side="left", padx=15, pady=10)
        self._delib_phase_label = tk.Label(
            hdr, text="대기 중...",
            font=(FONT_FAMILY, 10), bg="#1e1e2e", fg="#a6adc8")
        self._delib_phase_label.pack(side="right", padx=15)

        # ── 단계 진행 바 ──
        phase_bar = tk.Frame(win, bg="#181825", height=32)
        phase_bar.pack(fill="x")
        phase_bar.pack_propagate(False)
        self._phase_labels = {}
        phase_names = {
            1: "1.발의", 2: "2.검토", 3: "3.문제인식",
            4: "4.해결제시", 5: "5.토론", 6: "6.결정"
        }
        for i, name in phase_names.items():
            lbl = tk.Label(phase_bar, text=name, font=(FONT_FAMILY, 9),
                           bg="#181825", fg="#585b70", padx=8, pady=4)
            lbl.pack(side="left", padx=2, pady=2)
            self._phase_labels[i] = lbl

        # ── 채팅 영역 ──
        chat_frame = tk.Frame(win, bg="#11111b")
        chat_frame.pack(fill="both", expand=True, padx=0, pady=0)

        self._delib_chat = scrolledtext.ScrolledText(
            chat_frame, font=(FONT_FAMILY, 10), bg="#11111b", fg="#cdd6f4",
            insertbackground="#11111b", wrap="word",
            relief="flat", borderwidth=0, padx=12, pady=8,
            takefocus=False, cursor="arrow")
        self._delib_chat.pack(fill="both", expand=True)
        # ★ state 토글 대신: 항상 normal 상태 유지 + 키 입력만 차단
        #   → Windows IME(한글 조합) 깨짐 완전 방지
        self._delib_chat.bind("<Key>", lambda e: "break")

        # 태그 설정 — 프로바이더별 색상 + 배경 구분
        c = self._delib_chat
        c.tag_config("claude_name", foreground="#a6e3a1", font=(FONT_FAMILY, 10, "bold"))
        c.tag_config("chatgpt_name", foreground="#89b4fa", font=(FONT_FAMILY, 10, "bold"))
        c.tag_config("gemini_name", foreground="#fab387", font=(FONT_FAMILY, 10, "bold"))
        c.tag_config("claude_text", foreground="#a6e3a1", lmargin1=20, lmargin2=20)
        c.tag_config("chatgpt_text", foreground="#89b4fa", lmargin1=20, lmargin2=20)
        c.tag_config("gemini_text", foreground="#fab387", lmargin1=20, lmargin2=20)
        # 프로바이더별 배경 강조 (미묘한 차이)
        c.tag_config("claude_bg", background="#1a2e1a")
        c.tag_config("chatgpt_bg", background="#1a1a2e")
        c.tag_config("gemini_bg", background="#2e1a0a")
        # 단계 구분
        c.tag_config("phase_header", foreground="#f5c2e7",
                     font=(FONT_FAMILY, 12, "bold"), justify="center")
        c.tag_config("phase_line", foreground="#45475a")
        # 내용별 색상
        c.tag_config("score_tag", foreground="#f9e2af")
        c.tag_config("problem_tag", foreground="#f38ba8")
        c.tag_config("agree_tag", foreground="#a6e3a1")
        c.tag_config("rebut_tag", foreground="#fab387")
        c.tag_config("code_tag", foreground="#cba6f7")
        c.tag_config("fix_tag", foreground="#94e2d5")
        c.tag_config("consensus_tag", foreground="#f5c2e7",
                     font=(FONT_FAMILY, 10, "bold"))
        c.tag_config("system_tag", foreground="#585b70")
        c.tag_config("deep_tag", foreground="#f38ba8",
                     font=(FONT_FAMILY, 10, "bold"))
        c.tag_config("novel_tag", foreground="#89dceb")
        # 사회자 전용 스타일
        c.tag_config("mc_name", foreground="#f5e0dc",
                     font=(FONT_FAMILY, 10, "bold"))
        c.tag_config("mc_text", foreground="#f5e0dc", lmargin1=20, lmargin2=20)
        c.tag_config("mc_bg", background="#2e2620")
        # 사용자(나) 전용 스타일
        c.tag_config("user_name", foreground="#74c7ec",
                     font=(FONT_FAMILY, 10, "bold"))
        c.tag_config("user_text", foreground="#74c7ec", lmargin1=20, lmargin2=20)
        c.tag_config("user_bg", background="#0a2030")
        # 발언자 구분선
        c.tag_config("speaker_sep", foreground="#313244")

        # 아바타 이미지 표시용 (image는 tag에서 직접 지원하지 않으므로 window로 삽입)

        # ── 하단 입력 영역 ──
        input_frame = tk.Frame(win, bg="#1e1e2e")
        input_frame.pack(fill="x", side="bottom")

        input_bar = tk.Frame(input_frame, bg="#1e1e2e")
        input_bar.pack(fill="x", padx=10, pady=8)

        tk.Label(input_bar, text="나:", font=(FONT_FAMILY, 10, "bold"),
                 bg="#1e1e2e", fg="#74c7ec").pack(side="left", padx=(0, 6))

        self._delib_input = tk.Entry(
            input_bar, font=(FONT_FAMILY, 10), bg="#313244", fg="#cdd6f4",
            insertbackground="#cdd6f4", relief="flat", borderwidth=0)
        self._delib_input.pack(side="left", fill="x", expand=True, ipady=6)
        self._delib_input.bind("<Return>", self._on_delib_user_send)

        self._delib_send_btn = tk.Button(
            input_bar, text="전송", font=(FONT_FAMILY, 9, "bold"),
            bg="#74c7ec", fg="#1e1e2e", relief="flat", padx=12, pady=4,
            command=self._on_delib_user_send)
        self._delib_send_btn.pack(side="left", padx=(6, 0))

        win.protocol("WM_DELETE_WINDOW", lambda: win.withdraw())

    def _on_delib_user_send(self, event=None):
        """사용자가 입력한 메시지를 채팅에 표시하고 큐에 추가."""
        if not hasattr(self, '_delib_input'):
            return "break"
        msg = self._delib_input.get().strip()
        if not msg:
            return "break"
        self._delib_input.delete(0, "end")

        # 채팅 윈도우에 표시
        chat = self._delib_chat
        ts = datetime.now().strftime("%H:%M:%S")
        chat.insert("end", "\n  ─────────────────────\n", "speaker_sep")
        chat.insert("end", "  💬 ", "user_name")
        chat.insert("end", "나", "user_name")
        chat.insert("end", f"  ({ts})\n", "system_tag")
        chat.insert("end", f"  \"{msg}\"\n", ("user_text", "user_bg"))
        self._delib_auto_scroll()

        # 메시지 큐에 추가 — 다음 API 호출 시 반영됨
        self._user_messages.append(msg)
        return "break"

    def _get_user_messages(self):
        """큐에 쌓인 사용자 메시지를 가져오고 비운다."""
        if not hasattr(self, '_user_messages'):
            return []
        msgs = list(self._user_messages)
        self._user_messages.clear()
        return msgs

    def _delib_auto_scroll(self):
        """스크롤이 하단 근처일 때만 자동 스크롤."""
        chat = self._delib_chat
        # yview 반환값: (top_fraction, bottom_fraction)
        # bottom이 0.95 이상이면 사용자가 맨 아래 근처에 있는 것
        try:
            _, bottom = chat.yview()
            if bottom >= 0.95:
                chat.see("end")
        except Exception:
            chat.see("end")

    def _on_deliberation(self, phase, provider, data):
        """6단계 회의 콜백 — 사회자 + AI 패널 대화체로 표시."""
        def _do():
            if not hasattr(self, '_delib_win') or not self._delib_win:
                return
            if not self._delib_win.winfo_exists():
                return
            try:
                self._delib_win.deiconify()
            except Exception:
                pass

            chat = self._delib_chat
            self._on_deliberation_inner(chat, phase, provider, data)

        self.after(0, _do)

    def _on_deliberation_inner(self, chat, phase, provider, data):
        """_on_deliberation 실제 표시 로직."""
        names = {"claude": "Claude", "chatgpt": "ChatGPT",
                 "gemini": "Gemini", "mc": "사회자"}
        ts = datetime.now().strftime("%H:%M:%S")

        # ── 사회자 발언 ──
        if phase == "mc":
            speech = data.get("speech", "") if isinstance(data, dict) else str(data)
            chat.insert("end", "\n  ─────────────────────\n", "speaker_sep")
            chat.insert("end", "  🎙 ", "mc_name")
            chat.insert("end", " 사회자", "mc_name")
            chat.insert("end", f"  ({ts})\n", "system_tag")
            chat.insert("end", f"  {speech}\n", ("mc_text", "mc_bg"))
            # TTS 음성 출력 (사회자)
            self._tts_speak(speech, "mc")
            self._delib_auto_scroll()
            return

        # ── 단계 헤더 표시 ──
        if phase == "phase" and isinstance(data, dict):
            p = data.get("phase", 0)
            title = data.get("title", "")
            self._delib_current_phase = p
            for i, lbl in self._phase_labels.items():
                if i < p:
                    lbl.configure(fg="#a6e3a1", bg="#181825")
                elif i == p:
                    lbl.configure(fg="#11111b", bg="#f5c2e7")
                else:
                    lbl.configure(fg="#585b70", bg="#181825")
            self._delib_phase_label.configure(text=f"{p}단계: {title}")
            chat.insert("end", f"\n{'═' * 55}\n", "phase_line")
            chat.insert("end", f"  {p}단계: {title}\n", "phase_header")
            chat.insert("end", f"{'═' * 55}\n", "phase_line")
            if data.get("deep_explore"):
                chat.insert("end",
                            "\n  ** 심화 탐색 모드 — 새로운 접근법 필요 **\n",
                            "deep_tag")
            self._delib_auto_scroll()
            return

        # ── 에러 처리 ──
        if isinstance(data, dict) and data.get("error"):
            name = names.get(provider, provider)
            name_tag = f"{provider}_name" if provider in names else "system_tag"
            err_dots = {"claude": "🟢", "chatgpt": "🔵", "gemini": "🟠"}
            chat.insert("end", "\n  ─────────────────────\n", "speaker_sep")
            chat.insert("end", f"  {err_dots.get(provider, '⚪')} ", name_tag)
            chat.insert("end", f" {name}", name_tag)
            chat.insert("end", f"  ({ts})\n", "system_tag")
            chat.insert("end", f"  (응답 실패: {data['error']})\n", "problem_tag")
            self._delib_auto_scroll()
            return

        if not isinstance(data, dict):
            self._delib_auto_scroll()
            return

        # ── AI 패널원 발언 ──
        name = names.get(provider, provider)
        name_tag = f"{provider}_name" if provider in names else "system_tag"
        text_tag = f"{provider}_text" if provider in names else "system_tag"
        bg_tag = f"{provider}_bg" if provider in names else None
        dots = {"claude": "🟢", "chatgpt": "🔵", "gemini": "🟠"}
        dot = dots.get(provider, "⚪")

        chat.insert("end", "\n  ─────────────────────\n", "speaker_sep")
        chat.insert("end", f"  {dot} ", name_tag)
        chat.insert("end", f" {name}", name_tag)
        chat.insert("end", f"  ({ts})\n", "system_tag")

        # speech — 대화체 발언 (말풍선 스타일)
        speech = data.get("speech", "")
        speech_tags = (text_tag, bg_tag) if bg_tag else text_tag
        if speech:
            # 말풍선 테두리
            chat.insert("end", "  ╭─\n", "speaker_sep")
            chat.insert("end", f"  │ {speech}\n", speech_tags)
            chat.insert("end", "  ╰─\n", "speaker_sep")
            # TTS 음성 출력
            self._tts_speak(speech, provider)

        # reasoning — speech가 없을 때 대체
        if not speech:
            reasoning = data.get("reasoning", "")
            if reasoning:
                chat.insert("end", f"  {reasoning}\n", speech_tags)

        # 점수
        scores = data.get("scores") or data.get("updated_scores") or \
                 data.get("consolidated_scores")
        if scores:
            parts = [f"{k}:{v}" for k, v in scores.items()]
            avg = data.get("average_score", "")
            avg_str = f" (평균 {avg})" if avg else ""
            chat.insert("end", f"  [{', '.join(parts)}]{avg_str}\n",
                        "score_tag")

        # verdict
        verdict = data.get("verdict")
        if verdict:
            chat.insert("end", f"  판정: {verdict}\n", "consensus_tag")

        # 동의
        agrees = data.get("agreements") or data.get("fix_agreements") or []
        for a in agrees:
            chat.insert("end", f"  + {a}\n", "agree_tag")

        # 반박
        rebuts = data.get("rebuttals") or data.get("fix_rebuttals") or []
        for rb in rebuts:
            chat.insert("end", f"  - {rb}\n", "rebut_tag")

        # 문제점
        for prob in data.get("problems", []):
            chat.insert("end", f"  ! {prob}\n", "problem_tag")

        # 공통 인식 문제 (3단계)
        for ap in data.get("agreed_problems", []):
            sev = ap.get("severity", "?")
            desc = ap.get("description", "")
            who = ", ".join(ap.get("agreed_by", []))
            chat.insert("end", f"  [{sev}] {desc}", "problem_tag")
            chat.insert("end", f" ({who})\n", "system_tag")

        # 쟁점 (3단계)
        for dp in data.get("disputed_points", []):
            topic = dp.get("topic", "")
            chat.insert("end", f"  ? 쟁점: {topic}\n", "rebut_tag")
            for who, pos in dp.get("positions", {}).items():
                w = names.get(who, who)
                wtag = f"{who}_text" if who in names else "system_tag"
                chat.insert("end", f"      {w}: ", wtag)
                chat.insert("end", f"{pos}\n", "system_tag")

        # 파라미터 수정 제안 (4,5단계)
        for pf in data.get("param_fixes", []):
            prob = pf.get("problem", "")
            fix = pf.get("fix", "")
            chat.insert("end", f"  [옵션] ", "fix_tag")
            if prob:
                chat.insert("end", f"{prob} → ", "system_tag")
            chat.insert("end", f"{fix}\n", "fix_tag")

        # 코드 수정 제안
        code_fixes = data.get("code_fixes") or \
                     data.get("recommended_code_fixes") or \
                     data.get("code_issues") or []
        for cf in code_fixes:
            sev = cf.get("severity", "?")
            desc = cf.get("description", "")
            fix = cf.get("suggested_fix", "")
            chat.insert("end", f"  [코드/{sev}] {desc}\n", "code_tag")
            if fix:
                chat.insert("end", f"      → {fix}\n", "fix_tag")

        # 창의적 접근 (4단계 심화)
        for na in data.get("novel_approaches", []):
            chat.insert("end", f"  * {na}\n", "novel_tag")

        # 추천 파라미터
        rec = data.get("recommended_params") or data.get("adjusted_params")
        if rec and isinstance(rec, dict):
            sc = rec.get("shadow_config")
            ec = rec.get("enhance_config")
            if sc and isinstance(sc, dict):
                s = ", ".join(f"{k}={v}" for k, v in sc.items())
                chat.insert("end", f"  shadow → {s}\n", "system_tag")
            if ec and isinstance(ec, dict):
                s = ", ".join(f"{k}={v}" for k, v in ec.items())
                chat.insert("end", f"  enhance → {s}\n", "system_tag")

        # 합의 여부
        if data.get("consensus_reached"):
            chat.insert("end", f"  >> 합의 도달 <<\n", "consensus_tag")
        if data.get("consensus_on_scores"):
            chat.insert("end", f"  >> 점수 합의 <<\n", "consensus_tag")

        self._delib_auto_scroll()

        # 6단계 완료 시 영상 자동 저장
        if self._delib_current_phase >= 6 and data.get("verdict"):
            self._export_delib_video()

    def _export_delib_video(self):
        """회의 종료 후 영상 자동 저장."""
        if not hasattr(self, 'var_video_export') or not self.var_video_export.get():
            return
        if not hasattr(self, '_delib_recording') or not self._delib_recording:
            return

        def _do_export():
            try:
                from src.video.exporter import export_deliberation_video
                output_dir = self.var_output.get() or str(APP_DIR / "output")
                os.makedirs(output_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = os.path.join(output_dir, f"deliberation_{ts}.mp4")

                res = self.var_video_res.get().split("x")
                w, h = int(res[0]), int(res[1])
                fps = int(self.var_video_fps.get())

                result = export_deliberation_video(
                    frames=self._delib_recording,
                    output_path=output_path,
                    width=w, height=h, fps=fps,
                )
                if result:
                    self.after(0, lambda: self._log(
                        f"[영상] 회의 영상 저장 완료: {result}", "success"))
                else:
                    self.after(0, lambda: self._log(
                        "[영상] 영상 저장 실패 — moviepy 또는 ffmpeg 필요", "warn"))
            except Exception as e:
                self.after(0, lambda: self._log(
                    f"[영상] 영상 저장 오류: {e}", "error"))

        threading.Thread(target=_do_export, daemon=True).start()

    def _tts_speak(self, text: str, evaluator: str):
        """TTS 엔진으로 발언 음성 출력 (비동기)."""
        try:
            self._ensure_tts_engine()
            if self._tts_engine.is_enabled:
                self._tts_engine.speak(text, evaluator)
        except Exception as e:
            logger.debug(f"TTS 발언 실패: {e}")

    def _log_refinement_result(self, result):
        """자동 수정 루프 결과를 GUI 로그에 표시."""
        iterations = result.get("iterations", [])
        best = result.get("best_iteration", 1)
        best_score = result.get("best_score", 0)

        self._log(f"━━━ 자동 수정 결과: {len(iterations)}회 반복 ━━━", "success")
        for it in iterations:
            scores = it.get("scores", {})
            avg = it.get("average_score", 0)
            verdict = it.get("verdict", "?")
            fname = Path(it.get("output_file", "")).name
            self._log(f"  {it['iteration']}회차: {verdict} "
                      f"(평균 {avg:.1f}/10) → {fname}", "success")
            if it.get("problems"):
                for p in it["problems"]:
                    self._log(f"    - {p}")

        self._log(f"  최적 결과: {best}회차 (평균 {best_score:.1f}/10)", "success")
        self._log(f"  파라미터 로그: *_refinement_log.json 참조", "success")

        # 롤백 스냅샷 경로 저장
        snapshot = result.get("rollback_snapshot")
        if snapshot:
            self._last_rollback_snapshot = snapshot
            self._log(f"  롤백 스냅샷: {snapshot}", "info")
            self._log(f"  문제가 있으면 [롤백] 버튼으로 자동수정 이전 상태로 복원 가능", "warn")
            # 롤백 버튼 활성화
            self.after(0, lambda: self._show_rollback_button(snapshot))

    def _show_rollback_button(self, snapshot_dir):
        """롤백 버튼을 로그 영역 아래에 표시."""
        if hasattr(self, '_rollback_frame') and self._rollback_frame:
            self._rollback_frame.destroy()

        self._rollback_frame = tk.Frame(self.log_text.master, bg="#1e1e2e")
        self._rollback_frame.pack(fill="x", padx=10, pady=(0, 5))

        tk.Label(self._rollback_frame, text="자동수정 이전 상태로 되돌리기:",
                 bg="#1e1e2e", fg="#fab387", font=(FONT_FAMILY, 9)).pack(side="left")

        btn = tk.Button(
            self._rollback_frame, text="롤백 (코드 복원)",
            bg="#f38ba8", fg="white", font=(FONT_FAMILY, 10, "bold"),
            relief="flat", padx=12, pady=4,
            command=lambda: self._do_rollback(snapshot_dir),
        )
        btn.pack(side="left", padx=(8, 0))

        # 스냅샷 폴더 열기 버튼
        btn2 = tk.Button(
            self._rollback_frame, text="스냅샷 폴더",
            bg="#313244", fg="#cdd6f4", font=(FONT_FAMILY, 9),
            relief="flat", padx=8, pady=4,
            command=lambda: os.startfile(snapshot_dir) if os.path.exists(snapshot_dir) else None,
        )
        btn2.pack(side="left", padx=(5, 0))

    def _do_rollback(self, snapshot_dir):
        """롤백 실행."""
        if not messagebox.askyesno(
            "롤백 확인",
            f"자동수정 이전 상태로 소스 코드를 복원합니다.\n\n"
            f"스냅샷: {snapshot_dir}\n\n"
            f"현재 src/ 와 config/ 가 덮어씌워집니다.\n계속하시겠습니까?"
        ):
            return

        try:
            from src.pipeline import ImageEditPipeline
            success = ImageEditPipeline.rollback_from_snapshot(snapshot_dir)
            if success:
                self._log("━━━ 롤백 완료! 프로그램을 재시작해주세요. ━━━", "success")
                messagebox.showinfo("롤백 완료",
                                    "소스 코드가 복원되었습니다.\n프로그램을 재시작해주세요.")
            else:
                self._log("롤백 실패!", "error")
                messagebox.showerror("롤백 실패", "스냅샷 복원에 실패했습니다.")
        except Exception as e:
            self._log(f"롤백 오류: {e}", "error")
            messagebox.showerror("롤백 오류", str(e))

        # 롤백 버튼 제거
        if hasattr(self, '_rollback_frame') and self._rollback_frame:
            self._rollback_frame.destroy()
            self._rollback_frame = None


if __name__ == "__main__":
    app = App()
    app.mainloop()
