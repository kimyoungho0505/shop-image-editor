# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — LUXBOY Shop Image Editor (gui3.py)
# 빌드: pyinstaller gui3.spec --clean
#
# 의존성 제외 목록:
#   PySide6  → gui3.py는 tkinter 사용
#   torch / segment_anything / mobile_sam → 선택적 SAM 기능 (설치 시 자동 포함)

import sys
from pathlib import Path

ROOT = Path(SPECPATH)   # noqa: F821  (PyInstaller 내장 변수)

# ── 포함할 데이터 파일 ──────────────────────────────────────────
datas = [
    # config YAML 파일들 (런타임에 읽음)
    (str(ROOT / "config"), "config"),
    # version.py (업데이터가 읽음)
    (str(ROOT / "version.py"), "."),
]

# models 폴더가 있으면 포함
if (ROOT / "models").exists():
    datas.append((str(ROOT / "models"), "models"))

# ── 숨겨진 임포트 (PyInstaller 자동탐지 불가능한 것들) ───────────
hidden_imports = [
    # 표준
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "tkinter.simpledialog",
    "tkinter.colorchooser",
    # 이미지
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageFilter",
    # 과학/수치
    "numpy",
    "cv2",
    # API 클라이언트
    "anthropic",
    "openai",
    "google.genai",
    "requests",
    # 유틸
    "loguru",
    "yaml",
    "dotenv",
    "pyttsx3",
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    # 앱 내부
    "src.pipeline",
    "src.updater",
    "src.analyzer.vision_client",
    "src.analyzer.openai_vision_client",
    "src.analyzer.gemini_vision_client",
    "src.analyzer.grok_vision_client",
    "src.analyzer.prompt_builder",
    "src.analyzer.result_parser",
    "src.photoroom.client",
    "src.removebg.client",
    "src.claid.client",
    "src.opencv_enhance.enhancer",
    "src.exporter.namer",
    "src.exporter.optimizer",
    "src.sam.client",
    "src.utils.image_io",
    "src.utils.category",
    "src.utils.logger",
]

# DnD (tkinterdnd2) — 설치돼 있으면 포함
try:
    import tkinterdnd2 as _dnd
    hidden_imports.append("tkinterdnd2")
    import os as _os
    _dnd_dir = _os.path.dirname(_dnd.__file__)
    datas.append((_dnd_dir, "tkinterdnd2"))
except ImportError:
    pass

# ── 제외할 모듈 (크기 절약) ──────────────────────────────────────
excludes = [
    "PySide6",
    "PyQt5",
    "PyQt6",
    "wx",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "sphinx",
    "setuptools",
    "pip",
]

# ── 분석 ────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "gui3.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)   # noqa: F821

# ── 단일 EXE (onefile) ──────────────────────────────────────────
exe = EXE(   # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LUXBOY_ShopEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,          # UPX 압축 (설치 시 크기 30~40% 감소)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,     # 콘솔 창 없이 GUI만
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # 아이콘 파일이 있으면 주석 해제
)
