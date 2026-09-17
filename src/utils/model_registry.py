"""AI 모델 ID 를 한 곳에서 관리한다 — 최신 기본값 + 퇴역 ID 자동 치환.

2026-09-17 전면 갱신. 각 공급자의 모델 목록 API 를 실제로 조회해 정했다.

왜 이 파일이 필요한가
  모델 ID 가 코드 곳곳(클라이언트 기본 인자, pipeline 의 .get(..., "기본값"),
  GUI 콤보박스, settings.yaml)에 흩어져 있어 하나가 퇴역하면 어디선가 404 가
  났다. 실제로 `claude-sonnet-4-20250514` 가 코드 기본값으로 남아 있었는데
  이미 404(퇴역)였다. 사용자 PC 의 settings.yaml 에 옛 ID 가 저장돼 있어도
  깨지지 않도록, 클라이언트가 만들어질 때 `resolve()` 로 한 번 걸러 준다.

값을 바꿀 때
  1) 공급자 모델 목록을 실제로 조회해 존재를 확인한다.
  2) 이미지 1장으로 실호출해 응답을 본다(파라미터 거부 여부 포함).
  3) history.md 에 실측 결과를 남긴다.
"""
from __future__ import annotations

import re

# ── 최신 기본값 ─────────────────────────────────────────────────────────────
LATEST = {
    # 비전(분류/판정) — 텍스트+이미지 입력
    "claude":        "claude-sonnet-5",          # sonnet-4-20250514 는 404(퇴역)
    "claude_cheap":  "claude-haiku-4-5-20251001", # 여전히 최신 Haiku
    "openai":        "gpt-5.5",                  # gpt-4o 후속. 추론 모델(아래 참고)
    "openai_mini":   "gpt-5.4-mini",             # gpt-4o-mini 후속(검증용)
    "gemini":        "gemini-3.8-flash",         # gemini-2.5-flash 후속
    "grok":          "grok-4.6",                 # grok-4-fast-non-reasoning 후속
    # 이미지 편집(그림자 등)
    "gemini_image":          "gemini-3-pro-image",       # preview → GA
    "gemini_image_fallback": "gemini-3.1-flash-image",   # preview → GA
    "grok_image":            "grok-imagine-image-2.0",
    # 그 외
    "web_search":    "gpt-5.5",                  # Responses API + web_search
    "tts":           "gpt-4o-mini-tts",          # tts-1-hd 후속
}

# ── 퇴역/구버전 ID → 대체 ID ─────────────────────────────────────────────────
# 사용자 settings.yaml 이나 개인 설정에 남아 있어도 조용히 최신으로 넘긴다.
RETIRED = {
    # Anthropic — 4.0 세대는 모델 목록에서 사라졌다(실측 404)
    "claude-sonnet-4-20250514":  "claude-sonnet-5",
    "claude-opus-4-20250514":    "claude-opus-5",
    "claude-opus-4-1-20250805":  "claude-opus-5",
    "claude-3-7-sonnet-20250219": "claude-sonnet-5",
    "claude-3-5-sonnet-20241022": "claude-sonnet-5",
    "claude-3-5-haiku-20241022": "claude-haiku-4-5-20251001",
    # OpenAI
    "gpt-4-turbo":          "gpt-5.5",
    "gpt-4-vision-preview": "gpt-5.5",
    # Google — preview 는 GA 로
    "gemini-2.0-flash":              "gemini-3.8-flash",
    "gemini-3-pro-image-preview":    "gemini-3-pro-image",
    "gemini-3.1-flash-image-preview": "gemini-3.1-flash-image",
    "gemini-2.5-flash-image-preview": "gemini-3.1-flash-image",
    # xAI
    "grok-3":              "grok-4.6",
    "grok-4-0709":         "grok-4.6",
    "grok-imagine-image":  "grok-imagine-image-2.0",
}

# GUI 콤보박스용 선택지 (첫 항목이 기본값)
CHOICES = {
    "claude": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001",
               "claude-fable-5-1"],
    "openai": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.1", "gpt-4o", "gpt-4o-mini"],
    "openai_verify": ["gpt-5.4-mini", "gpt-5.5", "gpt-4o-mini", "gpt-4o"],
    "gemini": ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-pro-preview",
               "gemini-2.5-flash", "gemini-2.5-pro"],
    "grok":   ["grok-4.6", "grok-4.5", "grok-4.3", "grok-4.20-0309-non-reasoning",
               "grok-4-fast-non-reasoning"],
    "gemini_image": ["gemini-3-pro-image", "gemini-3.1-flash-image",
                     "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image"],
    "grok_image": ["grok-imagine-image-2.0", "grok-imagine-image-quality",
                   "grok-imagine-image"],
    "tts": ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"],
}

_REASONING_OPENAI = re.compile(r"^(gpt-5|o[1-9]|gpt-4\.5)")


def resolve(model: str | None, kind: str | None = None, log=None) -> str:
    """설정에 적힌 모델 ID 를 실제로 쓸 ID 로 바꾼다.

    - 비어 있으면 kind 의 최신 기본값.
    - 퇴역 ID 면 대체 ID (log 가 있으면 한 줄 알린다).
    - 그 외는 그대로.
    """
    if not model:
        return LATEST[kind] if kind else ""
    new = RETIRED.get(model)
    if new and new != model:
        if log:
            try:
                log(f"모델 {model} 은 퇴역/구버전이라 {new} 로 대체합니다")
            except Exception:                        # noqa: BLE001 — 로그 실패는 무시
                pass
        return new
    return model


def is_reasoning_openai(model: str) -> bool:
    """gpt-5 계열·o 계열 추론 모델인가.

    이 모델들은 chat.completions 에서 `max_tokens` 를 거부하고
    (`max_completion_tokens` 를 써야 함) `temperature` 는 기본값 1 만 받는다
    (2026-09-17 실측: 'Unsupported value: temperature does not support 0.1').
    """
    return bool(_REASONING_OPENAI.match(model or ""))


def is_claude_5_plus(model: str) -> bool:
    """Claude 4.6 이후 — `temperature` 를 보내면 400 (실측: '`temperature` is
    deprecated for this model')."""
    m = re.match(r"^claude-(fable|mythos|opus|sonnet|haiku)-(\d+)(?:-(\d+))?", model or "")
    if not m:
        return False
    major = int(m.group(2))
    minor = int(m.group(3) or 0)
    return major >= 5 or (major == 4 and minor >= 6)
