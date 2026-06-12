"""image-2.0 프롬프트 GitHub 공유 동기화.

3명 내외의 조율된 팀용 — 한 명이 조건 탭에서 프롬프트를 저장하면
GitHub 저장소의 공유 파일에 푸시되고, 다른 사용자는 프로그램 시작 시
자동으로 받아 적용한다 (last-writer-wins).

설정 (.env):
    SHARED_PROMPTS_REPO=owner/repo        # 예: kimyoungho0505/shop-editor-shared
    SHARED_PROMPTS_TOKEN=github_pat_...   # 해당 repo Contents R/W 권한 fine-grained PAT
    SHARED_PROMPTS_BRANCH=main            # 생략 가능 (기본 main)

REPO 또는 TOKEN이 없으면 기능 전체가 조용히 비활성화된다.
"""
from __future__ import annotations

import base64
import os

import requests
from loguru import logger

SHARED_FILE_PATH = "shared/image2_prompts.yaml"
API_BASE = "https://api.github.com"
TIMEOUT = 15


def get_config() -> dict | None:
    """환경변수에서 공유 설정을 읽는다. 미설정 시 None (기능 OFF)."""
    repo = (os.getenv("SHARED_PROMPTS_REPO") or "").strip()
    token = (os.getenv("SHARED_PROMPTS_TOKEN") or "").strip()
    if not repo or "/" not in repo or not token:
        return None
    return {
        "repo": repo,
        "token": token,
        "branch": (os.getenv("SHARED_PROMPTS_BRANCH") or "main").strip(),
    }


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_shared(cfg: dict) -> tuple[str, str] | None:
    """공유 파일을 가져온다.

    Returns:
        (yaml_text, sha) — 파일이 아직 없으면 ("", ""), 오류 시 None
    """
    url = (f"{API_BASE}/repos/{cfg['repo']}/contents/{SHARED_FILE_PATH}"
           f"?ref={cfg['branch']}")
    try:
        r = requests.get(url, headers=_headers(cfg["token"]), timeout=TIMEOUT)
    except Exception as e:
        logger.warning(f"공유 프롬프트 가져오기 실패 (네트워크): {e}")
        return None
    if r.status_code == 404:
        return ("", "")  # 아직 공유 파일 없음 — 첫 푸시 대기 상태
    if r.status_code != 200:
        logger.warning(f"공유 프롬프트 가져오기 실패: {r.status_code} {r.text[:120]}")
        return None
    data = r.json()
    try:
        text = base64.b64decode(data.get("content", "")).decode("utf-8")
    except Exception as e:
        logger.warning(f"공유 프롬프트 디코드 실패: {e}")
        return None
    return (text, data.get("sha", ""))


def push_shared(cfg: dict, yaml_text: str, author: str = "") -> bool:
    """로컬 프롬프트를 공유 파일로 푸시한다 (last-writer-wins).

    매 푸시 전에 최신 sha를 받아 충돌 없이 덮어쓴다.
    """
    fetched = fetch_shared(cfg)
    if fetched is None:
        return False
    _, sha = fetched

    who = author or os.getenv("USERNAME") or os.getenv("USER") or "user"
    body = {
        "message": f"image2 프롬프트 공유 업데이트 ({who})",
        "content": base64.b64encode(yaml_text.encode("utf-8")).decode("ascii"),
        "branch": cfg["branch"],
    }
    if sha:
        body["sha"] = sha

    url = f"{API_BASE}/repos/{cfg['repo']}/contents/{SHARED_FILE_PATH}"
    try:
        r = requests.put(url, headers=_headers(cfg["token"]), json=body,
                         timeout=TIMEOUT)
    except Exception as e:
        logger.warning(f"공유 프롬프트 푸시 실패 (네트워크): {e}")
        return False
    if r.status_code in (200, 201):
        logger.info("공유 프롬프트 푸시 완료")
        return True
    if r.status_code == 409:
        # sha 경합 — 그 사이 다른 사용자가 푸시함. 한 번만 재시도.
        logger.warning("공유 프롬프트 푸시 경합 — 재시도")
        fetched = fetch_shared(cfg)
        if fetched is None:
            return False
        _, sha2 = fetched
        if sha2:
            body["sha"] = sha2
        try:
            r2 = requests.put(url, headers=_headers(cfg["token"]), json=body,
                              timeout=TIMEOUT)
            return r2.status_code in (200, 201)
        except Exception:
            return False
    logger.warning(f"공유 프롬프트 푸시 실패: {r.status_code} {r.text[:120]}")
    return False
