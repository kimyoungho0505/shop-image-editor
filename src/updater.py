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

    notes = data.get("body", "")[:3000]   # 릴리즈 노트 (변경사항 + 설치 방법)
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

def _compute_new_exe_path(current_exe: str, new_version: str) -> str:
    """현재 EXE 경로 + 새 버전으로 새 파일명 계산.

    - 'LUXBOY_ShopEditor_v1.0.6.exe' + '1.0.12' → 'LUXBOY_ShopEditor_v1.0.12.exe'
    - 'LUXBOY_ShopEditor.exe' (버전 없음) + '1.0.12' → 그대로 유지
    - '내가지은이름.exe' (사용자 변경) + '1.0.12' → 그대로 유지 (안전)
    """
    import re
    if not new_version:
        return current_exe
    ver = new_version.lstrip("v")
    cur_path = Path(current_exe)
    cur_name = cur_path.name
    # 버전 패턴이 들어간 표준 파일명만 변경 (그 외는 그대로)
    m = re.match(r"^(LUXBOY_ShopEditor)_v[\d.]+\.exe$", cur_name, re.IGNORECASE)
    if not m:
        return current_exe
    new_name = f"{m.group(1)}_v{ver}.exe"
    return str(cur_path.parent / new_name)


def apply_update(new_exe_path: str, new_version: str = "") -> None:
    """
    현재 실행 중인 EXE를 새 EXE로 교체하고 재시작.

    Windows에서 실행 중인 EXE는 직접 교체 불가 → 배치스크립트가 대신 교체.

    Args:
        new_exe_path: 다운로드된 새 EXE 파일 경로
        new_version: 새 버전 번호 (예: '1.0.12') — 표준 파일명일 경우 자동 갱신
    """
    if not getattr(sys, "frozen", False):
        # 개발 모드 (python gui3.py) → 그냥 안내만
        logger.info("[Updater] 개발 모드: 실제 EXE 교체는 건너뜁니다.")
        return

    current_exe = sys.executable
    target_exe = _compute_new_exe_path(current_exe, new_version)
    rename_needed = (target_exe != current_exe)
    bat_path = os.path.join(tempfile.gettempdir(), "luxboy_update_apply.bat")

    # 배치: EXE 종료 대기 → 새 EXE로 교체 → 재시작
    # ⚠️ 주의: _MEI 임시 폴더 자동 정리 코드는 절대 추가하지 말 것!
    # 새 EXE가 막 만들기 시작한 _MEI<NNN> 폴더와 충돌해 python312.dll 로드 실패
    # ("Failed to load Python DLL") 발생. 오래된 _MEI 폴더는 Windows가 자체적으로
    # 정리하거나 사용자가 수동 청소.
    delete_old_block = ""
    if rename_needed:
        delete_old_block = f'''
:: 파일명 변경됨 — 기존 EXE 삭제
del /q "{current_exe}" 2>nul'''

    bat = f"""@echo off
chcp 65001 > nul
timeout /t 3 /nobreak > nul
echo 업데이트 적용 중...
copy /y "{new_exe_path}" "{target_exe}"
if errorlevel 1 (
    echo 업데이트 실패 — 수동으로 교체하세요.
    pause
    goto :eof
){delete_old_block}
del "{new_exe_path}" 2>nul
echo 업데이트 완료. 재시작합니다.
start "" "{target_exe}"
del "%~f0" 2>nul
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat)

    if rename_needed:
        logger.info(
            f"[Updater] 파일명 변경: {Path(current_exe).name} "
            f"→ {Path(target_exe).name}")
    logger.info(f"[Updater] 업데이트 배치 실행: {bat_path}")
    subprocess.Popen(["cmd", "/c", bat_path], creationflags=subprocess.CREATE_NO_WINDOW)
    # sys.exit 대신 os._exit로 더 깔끔히 종료 (PyInstaller 정리 단계 스킵 → 경고 회피)
    os._exit(0)


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
