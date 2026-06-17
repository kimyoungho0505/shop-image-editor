"""Photoroom 크레딧 사용량 추적 (추정 기반).

각 Photoroom API 호출이 어떤 엔드포인트를 썼는지 보고 크레딧을 자동 집계한다.
  · v1/segment (배경제거만)  → 0.2 크레딧
  · v2/edit   (그림자/크롭)  → 1.0 크레딧

3단계 누적:
  · 이미지 단위:  thread-local (워커 스레드별, ThreadPoolExecutor 안전)
  · 세션 단위:    이번 실행/배치 합계 (메모리)
  · 누적 단위:    config/credit_usage.json 영구 저장 (전체 기간)
"""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

# 엔드포인트별 추정 크레딧 단가
COST = {"segment": 0.2, "edit": 1.0}
KIND_LABEL = {"segment": "배경제거(v1)", "edit": "편집/그림자/크롭(v2)"}

_lock = threading.Lock()
_local = threading.local()

_path: "Path | None" = None
_session = {"total": 0.0, "segment": 0.0, "edit": 0.0, "calls": 0}


def configure(config_dir) -> None:
    """누적 저장 파일 경로 설정 (config/credit_usage.json)."""
    global _path
    _path = Path(config_dir) / "credit_usage.json"


def reset_session() -> None:
    """세션(이번 배치) 카운터 초기화."""
    with _lock:
        _session.update({"total": 0.0, "segment": 0.0, "edit": 0.0, "calls": 0})


def start_image() -> None:
    """현재 워커 스레드의 이미지 단위 카운터 초기화."""
    _local.credits = 0.0
    _local.segment = 0
    _local.edit = 0


def image_credits() -> float:
    """현재 워커 스레드에서 이번 이미지에 사용한 추정 크레딧."""
    return getattr(_local, "credits", 0.0)


def record(kind: str) -> float:
    """API 호출 1건 기록. kind: 'segment' | 'edit'. 사용 크레딧 반환."""
    credits = COST.get(kind, 1.0)
    # 이미지(thread-local)
    _local.credits = getattr(_local, "credits", 0.0) + credits
    setattr(_local, kind, getattr(_local, kind, 0) + 1)
    # 세션 + 누적
    with _lock:
        _session["total"] = round(_session["total"] + credits, 3)
        _session[kind] = round(_session.get(kind, 0.0) + credits, 3)
        _session["calls"] += 1
        _persist_locked(kind, credits)
    return credits


def record_url(url: str, segment_url: str, edit_url: str) -> float:
    """엔드포인트 URL로 kind를 판정해 기록."""
    kind = "segment" if url == segment_url else "edit"
    return record(kind)


def session_summary() -> dict:
    """세션 누계 스냅샷."""
    with _lock:
        return dict(_session)


def cumulative() -> dict:
    """누적(영구) 사용량 조회."""
    if not _path or not _path.exists():
        return {"total_credits": 0.0, "by_type": {}, "daily": {}}
    try:
        return json.loads(_path.read_text(encoding="utf-8"))
    except Exception:
        return {"total_credits": 0.0, "by_type": {}, "daily": {}}


def _persist_locked(kind: str, credits: float) -> None:
    """_lock 보유 상태에서 누적 JSON 갱신 (호출자가 lock 보유)."""
    if not _path:
        return
    try:
        data = {}
        if _path.exists():
            data = json.loads(_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data["total_credits"] = round(data.get("total_credits", 0.0) + credits, 3)
    bt = data.setdefault("by_type", {})
    bt[kind] = round(bt.get(kind, 0.0) + credits, 3)
    # 일자별 누적 (최근 추세 확인용)
    today = date.today().isoformat()
    daily = data.setdefault("daily", {})
    daily[today] = round(daily.get(today, 0.0) + credits, 3)
    try:
        _path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception:
        pass
