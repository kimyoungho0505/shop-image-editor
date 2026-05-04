"""자동 업데이터 — GitHub Releases API로 버전 체크 후 EXE 교체."""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
from typing import Callable, Optional

import requests
from loguru import logger

# version.py 로드 (EXE 실행 시에도 동작하도록 경로 처리)
try:
    # 일반 실행 (python gui3.py)
    from version import __version__, APP_NAME, GITHUB_REPO, EXE_NAME
except ImportError:
    # PyInstaller EXE 실행: sys._MEIPASS 기준
    import importlib.util, pathlib
    _base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent.parent))
    _spec = importlib.util.spec_from_file_location("version", _base / "version.py")
    _mod  = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    __version__ = _mod.__version__
    APP_NAME    = _mod.APP_NAME
    GITHUB_REPO = _mod.GITHUB_REPO
    EXE_NAME    = _mod.EXE_NAME

RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
TIMEOUT      = 10   # 초


# ──────────────────────────────────────────────
# 버전 비교 (SemVer: "1.2.3")
# ──────────────────────────────────────────────

def _parse(v: str) -> tuple[int, ...]:
    """'v1.2.3' 또는 '1.2.3' → (1, 2, 3)"""
    return tuple(int(x) for x in v.lstrip("v").split(".")[:3])


def is_newer(remote: str, local: str) -> bool:
    try:
        return _parse(remote) > _parse(local)
    except Exception:
        return False


# ──────────────────────────────────────────────
# GitHub Releases 체크
# ──────────────────────────────────────────────

class UpdateInfo:
    def __init__(self, version: str, download_url: str, release_notes: str):
        self.version       = version
        self.download_url  = download_url
        self.release_notes = release_notes


def check_for_update(github_token: str = "") -> Optional[UpdateInfo]:
    """
    GitHub 최신 릴리즈 확인. 현재보다 새 버전이면 UpdateInfo 반환, 없으면 None.

    Args:
        github_token: private repo의 경우 Personal Access Token (선택)
    """
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    try:
        resp = requests.get(RELEASES_API, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        logger.debug(f"[Updater] 버전 확인 실패: {e}")
        return None

    data = resp.json()
    tag  = data.get("tag_name", "")
    if not tag or not is_newer(tag, __version__):
        logger.debug(f"[Updater] 최신 버전 사용 중 ({__version__})")
        return None

    # 릴리즈 에셋 중 EXE 파일 URL 탐색
    download_url = ""
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            download_url = asset.get("browser_download_url", "")
            break

    if not download_url:
        logger.debug("[Updater] EXE 에셋 없음")
        return None

    notes = data.get("body", "")[:400]   # 릴리즈 노트 앞부분만
    logger.info(f"[Updater] 새 버전 발견: {tag}")
    return UpdateInfo(version=tag, download_url=download_url, release_notes=notes)


# ──────────────────────────────────────────────
# 다운로드
# ──────────────────────────────────────────────

def download_update(
    url: str,
    on_progress: Callable[[int, int], None] = None,
    github_token: str = "",
) -> str:
    """
    새 EXE를 임시 폴더에 다운로드.
    Returns: 다운로드된 파일 경로
    """
    headers = {}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    dest = os.path.join(tempfile.gettempdir(), f"luxboy_update_{EXE_NAME}")
    logger.info(f"[Updater] 다운로드 시작: {url} → {dest}")

    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total:
                        on_progress(downloaded, total)

    logger.info(f"[Updater] 다운로드 완료: {dest} ({downloaded // 1024}KB)")
    return dest


# ──────────────────────────────────────────────
# 업데이트 적용 (Windows: batch 교체 방식)
# ──────────────────────────────────────────────

def apply_update(new_exe_path: str) -> None:
    """
    현재 실행 중인 EXE를 새 EXE로 교체하고 재시작.

    Windows에서 실행 중인 EXE는 직접 교체 불가 → 배치스크립트가 대신 교체.
    """
    if not getattr(sys, "frozen", False):
        # 개발 모드 (python gui3.py) → 그냥 안내만
        logger.info("[Updater] 개발 모드: 실제 EXE 교체는 건너뜁니다.")
        return

    current_exe = sys.executable
    bat_path = os.path.join(tempfile.gettempdir(), "luxboy_update_apply.bat")

    bat = f"""@echo off
chcp 65001 > nul
timeout /t 2 /nobreak > nul
echo 업데이트 적용 중...
copy /y "{new_exe_path}" "{current_exe}"
if errorlevel 1 (
    echo 업데이트 실패 — 수동으로 교체하세요.
    pause
    goto :eof
)
del "{new_exe_path}"
echo 업데이트 완료. 재시작합니다.
start "" "{current_exe}"
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat)

    logger.info(f"[Updater] 업데이트 배치 실행: {bat_path}")
    subprocess.Popen(["cmd", "/c", bat_path], creationflags=subprocess.CREATE_NO_WINDOW)
    sys.exit(0)


# ──────────────────────────────────────────────
# 백그라운드 체크 (GUI에서 호출)
# ──────────────────────────────────────────────

def check_update_in_background(
    on_update_found: Callable[[UpdateInfo], None],
    github_token: str = "",
) -> None:
    """
    별도 스레드에서 업데이트를 조용히 체크.
    새 버전이 있으면 on_update_found(info) 콜백 호출 (메인 스레드에서 UI 표시).
    """
    def _run():
        try:
            info = check_for_update(github_token=github_token)
            if info:
                on_update_found(info)
        except Exception as e:
            logger.debug(f"[Updater] 백그라운드 체크 오류: {e}")

    t = threading.Thread(target=_run, daemon=True, name="update-checker")
    t.start()
