# gpt-image-2 사후 보정 + 검증 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 뷰파인더에서 카드별로 OpenAI gpt-image-2 사후 보정 + gpt-4o-mini 자동 변형 검증을 수행하고, 사용자가 결과 토글에서 선택해 최종 저장 시 OUTPUT/original을 덮어쓰고 멀티사이즈를 자동 재생성한다.

**Architecture:** `src/openai_image/client.py`에 `GPTImage2Client` 신설(보정 + 검증). 조건 탭에 카테고리별 enhance/verify 프롬프트 설정. 뷰파인더 카드에 라디오 토글 영역 + 보정/저장 버튼 추가. 최종 저장 시 기존 `MultiSizeResizer`를 재사용하여 1500/860/crop을 갱신.

**Tech Stack:** Python 3.12, openai SDK (이미 설치됨), tkinter, PyYAML, pytest, base64, threading

**Spec:** `docs/superpowers/specs/2026-05-06-gpt-image-2-post-enhance-design.md`

---

## File Structure

**Create:**
- `src/openai_image/__init__.py` — 빈 패키지 초기화
- `src/openai_image/client.py` — `GPTImage2Client`, `GPTImage2Result`, `VerificationResult`, `GPTImage2NoCreditError`
- `config/image2_prompts.yaml` — 카테고리별 enhance/verify 프롬프트 + 검증 모델 설정
- `tests/test_openai_image.py` — 단위 테스트 (mock 기반)

**Modify:**
- `gui3.py`:
  - 조건 탭(`_build_conditions_tab`)에 image-2.0 프롬프트 섹션 추가
  - 뷰파인더 카드(`_build_file_row`)에 image-2.0 보정/최종 저장 버튼 + 라디오 토글 영역
  - 보정 다이얼로그 (`_vf_open_image2_dialog`) 신규 메서드
  - 백그라운드 워커 + 스테이지 동적 추가 메서드
  - 최종 저장 워크플로우 (`_vf_apply_image2_final`)

---

## Task 1: GPTImage2Client 골격 + enhance() (TDD)

**Files:**
- Create: `src/openai_image/__init__.py`
- Create: `src/openai_image/client.py`
- Create: `tests/test_openai_image.py`

- [ ] **Step 1: 패키지 디렉토리 생성**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && mkdir -p src/openai_image
```

- [ ] **Step 2: 빈 `__init__.py` 생성**

`src/openai_image/__init__.py`:

```python
"""OpenAI gpt-image-2 사후 보정 + gpt-4o-mini 검증."""
from .client import (
    GPTImage2Client,
    GPTImage2Result,
    VerificationResult,
    GPTImage2NoCreditError,
)

__all__ = [
    "GPTImage2Client",
    "GPTImage2Result",
    "VerificationResult",
    "GPTImage2NoCreditError",
]
```

- [ ] **Step 3: 실패 테스트 작성**

`tests/test_openai_image.py`:

```python
"""GPTImage2Client 단위 테스트 (openai SDK mock)."""
import sys
import io
import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.openai_image.client import (
    GPTImage2Client,
    GPTImage2Result,
    VerificationResult,
    GPTImage2NoCreditError,
)


def _fake_b64_image(size: int = 64) -> str:
    """테스트용 작은 PNG의 base64."""
    from PIL import Image
    img = Image.new("RGB", (size, size), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class TestEnhance:
    def test_enhance_returns_result_with_bytes(self):
        c = GPTImage2Client(api_key="sk-test")
        b64 = _fake_b64_image()
        fake_resp = MagicMock()
        fake_resp.data = [MagicMock(b64_json=b64)]

        with patch.object(c._client.images, "edit", return_value=fake_resp) as m:
            r = c.enhance(
                image_bytes=b"\x89PNG\r\n\x1a\nfake",
                prompt="enhance please",
                quality="medium",
                size="1024x1024",
            )

        assert isinstance(r, GPTImage2Result)
        assert r.enhanced_bytes == base64.b64decode(b64)
        assert r.quality == "medium"
        assert r.prompt_used == "enhance please"
        # API 호출 인자 검증
        args, kwargs = m.call_args
        assert kwargs["model"] == "gpt-image-2"
        assert kwargs["prompt"] == "enhance please"
        assert kwargs["quality"] == "medium"
        assert kwargs["size"] == "1024x1024"

    def test_enhance_passes_quality_high(self):
        c = GPTImage2Client(api_key="sk-test")
        b64 = _fake_b64_image()
        fake_resp = MagicMock()
        fake_resp.data = [MagicMock(b64_json=b64)]
        with patch.object(c._client.images, "edit", return_value=fake_resp) as m:
            c.enhance(b"\x89PNG", prompt="x", quality="hd")
        assert m.call_args.kwargs["quality"] == "hd"

    def test_enhance_402_raises_no_credit_error(self):
        from openai import APIStatusError
        c = GPTImage2Client(api_key="sk-test")
        # openai SDK는 status_code 속성을 가진 예외를 던짐
        err = APIStatusError(
            message="credit balance too low",
            response=MagicMock(status_code=402),
            body={"error": {"code": "insufficient_quota"}},
        )
        with patch.object(c._client.images, "edit", side_effect=err):
            with pytest.raises(GPTImage2NoCreditError):
                c.enhance(b"\x89PNG", prompt="x")
```

- [ ] **Step 4: 테스트 실행 → 실패 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_openai_image.py -v
```
Expected: `ImportError: cannot import name 'GPTImage2Client'`

- [ ] **Step 5: 클라이언트 구현**

`src/openai_image/client.py`:

```python
"""OpenAI gpt-image-2 사후 보정 + gpt-4o-mini 변형 검증 클라이언트."""
from __future__ import annotations

import io
import os
import json
import base64
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

# openai SDK는 프로젝트에 이미 설치됨 (pip list openai)
from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError


# ─────────────────────────────────────────────
# 데이터 클래스
# ─────────────────────────────────────────────

@dataclass
class GPTImage2Result:
    enhanced_bytes: bytes
    quality: str
    prompt_used: str
    cost_estimate_usd: float = 0.0
    elapsed_sec: float = 0.0


@dataclass
class VerificationResult:
    safe: bool
    issues: list = field(default_factory=list)
    raw_response: str = ""
    elapsed_sec: float = 0.0


# ─────────────────────────────────────────────
# 에러
# ─────────────────────────────────────────────

class GPTImage2NoCreditError(RuntimeError):
    """OpenAI 크레딧 부족 (HTTP 402)."""


# 가격 추정 (1024×1024 기준, OpenAI 공시값)
_COST_PER_IMAGE = {
    "low": 0.006,
    "medium": 0.053,
    "hd": 0.211,
    "high": 0.211,
}


# ─────────────────────────────────────────────
# 메인 클라이언트
# ─────────────────────────────────────────────

class GPTImage2Client:
    """gpt-image-2 보정 + gpt-4o-mini 검증 통합 클라이언트.

    환경변수 OPENAI_API_KEY를 자동 사용. 명시 인자가 우선.
    """

    def __init__(
        self,
        api_key: str = None,
        verification_model: str = "gpt-4o-mini",
        timeout: int = 120,
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
        self.verification_model = verification_model
        self.timeout = timeout
        self._client = OpenAI(api_key=self._api_key, timeout=timeout)

    # ────────── 보정 ──────────
    def enhance(
        self,
        image_bytes: bytes,
        prompt: str,
        quality: str = "medium",
        size: str = "1024x1024",
    ) -> GPTImage2Result:
        """gpt-image-2로 이미지 보정.

        Returns: GPTImage2Result(enhanced_bytes, quality, prompt_used, ...)
        Raises:  GPTImage2NoCreditError on 402.
        """
        img_file = io.BytesIO(image_bytes)
        img_file.name = "input.png"

        t0 = time.time()
        try:
            resp = self._client.images.edit(
                model="gpt-image-2",
                image=img_file,
                prompt=prompt,
                size=size,
                quality=quality,
            )
        except APIStatusError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 402:
                logger.error("[GPTImage2] 크레딧 부족 (402)")
                raise GPTImage2NoCreditError(
                    "OpenAI 크레딧이 부족합니다. "
                    "https://platform.openai.com/account/billing/overview")
            raise
        elapsed = time.time() - t0

        b64 = resp.data[0].b64_json
        enhanced = base64.b64decode(b64)
        logger.info(
            f"[GPTImage2] 보정 완료 — quality={quality}, "
            f"{len(enhanced)//1024}KB, {elapsed:.1f}s")

        return GPTImage2Result(
            enhanced_bytes=enhanced,
            quality=quality,
            prompt_used=prompt,
            cost_estimate_usd=_COST_PER_IMAGE.get(quality, 0.053),
            elapsed_sec=elapsed,
        )
```

- [ ] **Step 6: 테스트 실행 → 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_openai_image.py -v
```
Expected: 3 passed

- [ ] **Step 7: 커밋**

```bash
git add src/openai_image/ tests/test_openai_image.py
git commit -m "feat(openai_image): GPTImage2Client.enhance — gpt-image-2 보정"
```

---

## Task 2: verify() — 변형 검증 (TDD)

**Files:**
- Modify: `src/openai_image/client.py`
- Modify: `tests/test_openai_image.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_openai_image.py` 끝에 추가:

```python
class TestVerify:
    def _make_resp(self, content: str):
        msg = MagicMock(content=content)
        choice = MagicMock(message=msg)
        return MagicMock(choices=[choice])

    def test_verify_parses_safe_json(self):
        c = GPTImage2Client(api_key="sk-test")
        resp = self._make_resp('{"safe": true, "issues": []}')
        with patch.object(c._client.chat.completions, "create", return_value=resp):
            r = c.verify(b"orig", b"enh", prompt="check")
        assert r.safe is True
        assert r.issues == []

    def test_verify_parses_unsafe_with_issues(self):
        c = GPTImage2Client(api_key="sk-test")
        resp = self._make_resp(
            '{"safe": false, "issues": ["로고 흐려짐", "패턴 단순화"]}')
        with patch.object(c._client.chat.completions, "create", return_value=resp):
            r = c.verify(b"orig", b"enh", prompt="check")
        assert r.safe is False
        assert "로고 흐려짐" in r.issues
        assert "패턴 단순화" in r.issues

    def test_verify_invalid_json_falls_back_to_unsafe(self):
        c = GPTImage2Client(api_key="sk-test")
        resp = self._make_resp("this is not JSON")
        with patch.object(c._client.chat.completions, "create", return_value=resp):
            r = c.verify(b"orig", b"enh", prompt="check")
        assert r.safe is False
        assert any("파싱" in s for s in r.issues)

    def test_verify_passes_two_images_in_request(self):
        c = GPTImage2Client(api_key="sk-test")
        resp = self._make_resp('{"safe": true, "issues": []}')
        with patch.object(c._client.chat.completions, "create", return_value=resp) as m:
            c.verify(b"AAA", b"BBB", prompt="compare")
        kwargs = m.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        msgs = kwargs["messages"]
        # 첫 번째 사용자 메시지에 텍스트 + 이미지 2개
        content = msgs[0]["content"]
        types = [c["type"] for c in content]
        assert types == ["text", "image_url", "image_url"]
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_openai_image.py::TestVerify -v
```
Expected: `AttributeError: 'GPTImage2Client' object has no attribute 'verify'`

- [ ] **Step 3: verify 메서드 구현**

`src/openai_image/client.py`의 `GPTImage2Client` 클래스에 추가:

```python
    # ────────── 검증 ──────────
    def verify(
        self,
        original_bytes: bytes,
        enhanced_bytes: bytes,
        prompt: str,
    ) -> VerificationResult:
        """gpt-4o-mini로 원본 vs 보정 이미지 변형 여부 검증.

        모델은 JSON 응답 강제: {"safe": bool, "issues": ["..."]}.
        파싱 실패 시 safe=False로 폴백.
        """
        o_b64 = base64.b64encode(original_bytes).decode()
        e_b64 = base64.b64encode(enhanced_bytes).decode()

        t0 = time.time()
        try:
            resp = self._client.chat.completions.create(
                model=self.verification_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{o_b64}"}},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{e_b64}"}},
                    ],
                }],
                response_format={"type": "json_object"},
                timeout=self.timeout,
            )
        except APIStatusError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 402:
                raise GPTImage2NoCreditError(
                    "OpenAI 크레딧이 부족합니다 (검증 단계).")
            raise
        elapsed = time.time() - t0

        text = resp.choices[0].message.content or ""
        try:
            parsed = json.loads(text)
            safe = bool(parsed.get("safe", False))
            issues = list(parsed.get("issues", []))
        except (json.JSONDecodeError, AttributeError, TypeError):
            safe = False
            issues = ["검증 응답 파싱 실패 (수동 확인 필요)"]
            logger.warning(f"[GPTImage2] 검증 JSON 파싱 실패: {text[:100]}")

        logger.info(
            f"[GPTImage2] 검증 완료 — safe={safe}, "
            f"issues={len(issues)}, {elapsed:.1f}s")
        return VerificationResult(
            safe=safe, issues=issues, raw_response=text, elapsed_sec=elapsed,
        )
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_openai_image.py -v
```
Expected: 7 passed (3 + 4)

- [ ] **Step 5: 커밋**

```bash
git add src/openai_image/client.py tests/test_openai_image.py
git commit -m "feat(openai_image): verify — gpt-4o-mini 변형 검증 + JSON 파싱"
```

---

## Task 3: enhance_and_verify 통합 메서드 (TDD)

**Files:**
- Modify: `src/openai_image/client.py`
- Modify: `tests/test_openai_image.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
class TestEnhanceAndVerify:
    def test_runs_both_in_order(self):
        c = GPTImage2Client(api_key="sk-test")
        b64 = _fake_b64_image()

        edit_resp = MagicMock()
        edit_resp.data = [MagicMock(b64_json=b64)]

        verify_msg = MagicMock(content='{"safe": true, "issues": []}')
        verify_resp = MagicMock(choices=[MagicMock(message=verify_msg)])

        with patch.object(c._client.images, "edit", return_value=edit_resp), \
             patch.object(c._client.chat.completions, "create",
                          return_value=verify_resp):
            enh, ver = c.enhance_and_verify(
                image_bytes=b"orig",
                enhance_prompt="boost",
                verify_prompt="compare",
                quality="medium",
            )
        assert isinstance(enh, GPTImage2Result)
        assert isinstance(ver, VerificationResult)
        assert ver.safe is True

    def test_returns_none_verification_when_disabled(self):
        c = GPTImage2Client(api_key="sk-test")
        b64 = _fake_b64_image()
        edit_resp = MagicMock()
        edit_resp.data = [MagicMock(b64_json=b64)]
        with patch.object(c._client.images, "edit", return_value=edit_resp):
            enh, ver = c.enhance_and_verify(
                image_bytes=b"orig",
                enhance_prompt="boost",
                verify_prompt="compare",
                quality="medium",
                run_verification=False,
            )
        assert ver is None
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_openai_image.py::TestEnhanceAndVerify -v
```
Expected: `AttributeError: ... no attribute 'enhance_and_verify'`

- [ ] **Step 3: enhance_and_verify 구현**

`GPTImage2Client`에 추가:

```python
    # ────────── 통합 ──────────
    def enhance_and_verify(
        self,
        image_bytes: bytes,
        enhance_prompt: str,
        verify_prompt: str,
        quality: str = "medium",
        size: str = "1024x1024",
        run_verification: bool = True,
    ) -> tuple:
        """편의 메서드: 보정 후 즉시 검증.

        Returns: (GPTImage2Result, VerificationResult | None)
        """
        result = self.enhance(image_bytes, enhance_prompt, quality, size)
        verification = None
        if run_verification:
            try:
                verification = self.verify(
                    image_bytes, result.enhanced_bytes, verify_prompt)
            except GPTImage2NoCreditError:
                raise
            except Exception as e:
                logger.warning(f"[GPTImage2] 검증 실패 (보정 결과는 보존): {e}")
                verification = VerificationResult(
                    safe=False,
                    issues=[f"검증 실행 실패: {e}"],
                    raw_response="",
                    elapsed_sec=0.0,
                )
        return result, verification
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_openai_image.py -v
```
Expected: 9 passed

- [ ] **Step 5: 커밋**

```bash
git add src/openai_image/client.py tests/test_openai_image.py
git commit -m "feat(openai_image): enhance_and_verify — 보정+검증 통합"
```

---

## Task 4: image2_prompts.yaml 설정 파일 작성

**Files:**
- Create: `config/image2_prompts.yaml`

- [ ] **Step 1: 파일 생성**

`config/image2_prompts.yaml`:

```yaml
# ─────────────────────────────────────────────────────────
# gpt-image-2 사후 보정 + 검증 프롬프트 설정
# 카테고리는 Vision 분석 결과(detected_category, image_type, has_mannequin)로 자동 매핑
# ─────────────────────────────────────────────────────────
image2:
  default_quality: medium        # low | medium | hd
  default_size: "1024x1024"

  verification:
    model: "gpt-4o-mini"
    block_on_unsafe: false       # true면 변형 감지 결과는 토글 비활성화

  prompts:
    default:
      enhance: |
        Enhance this product photo for an e-commerce listing.
        Improve sharpness, color accuracy, and lighting.
        Keep the product, pose, and composition exactly the same.
        Pure white background. No text, no watermarks.
      verify: |
        Compare the original (first image) and enhanced (second image).
        Check if logos, text, brand marks, or distinctive product features
        have been altered, distorted, or blurred.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["short Korean strings"]}.

    jewelry:
      enhance: |
        Enhance details and reflective highlights on this jewelry product photo.
        Keep engravings, gemstones, metal texture, and brand marks sharp and accurate.
        Do not alter shape, color, or proportions of stones and metalwork.
        Pure white background.
      verify: |
        Compare the original and enhanced jewelry images.
        Check for changes in engravings, gemstones, settings, or brand marks.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["short Korean strings"]}.

    mannequin:
      enhance: |
        Enhance fabric texture, folds, and color accuracy of this clothing on mannequin.
        Smooth mannequin contours but keep clothing exactly as is.
        Do not change garment shape or print details.
      verify: |
        Compare original and enhanced mannequin clothing photos.
        Check if logos, prints, embroidery, buttons, or seams were altered.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["short Korean strings"]}.

    model:
      enhance: |
        Enhance natural skin tones and clothing details on this fashion model photo.
        Keep the model's pose, face, body shape exactly as is.
      verify: |
        Compare original and enhanced fashion photos.
        Check if face, body, garment logos, or prints were altered.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["short Korean strings"]}.

    full:
      enhance: |
        Enhance overall product photo for clarity and color accuracy.
      verify: |
        Compare original and enhanced full-shot images. Check for any visible alteration.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["short Korean strings"]}.

    detail:
      enhance: |
        Enhance fine detail, texture, and color of this close-up product shot.
        Keep all features intact.
      verify: |
        Compare original and enhanced detail shots.
        Check if textures, materials, or stitching were altered.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["short Korean strings"]}.

    package:
      enhance: |
        Enhance package photo for clarity. Keep all printed text and logos sharp and unchanged.
      verify: |
        Compare original and enhanced package images.
        Check carefully if any printed text, barcode, or logo was altered. Even minor blur counts.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["short Korean strings"]}.
```

- [ ] **Step 2: YAML 파싱 검증**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import yaml; d = yaml.safe_load(open('config/image2_prompts.yaml', encoding='utf-8')); assert d['image2']['default_quality'] == 'medium'; assert 'jewelry' in d['image2']['prompts']; assert 'enhance' in d['image2']['prompts']['jewelry']; assert 'verify' in d['image2']['prompts']['jewelry']; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git add config/image2_prompts.yaml
git commit -m "feat(config): image2_prompts.yaml — 카테고리별 보정+검증 프롬프트"
```

---

## Task 5: 조건 탭에 image-2.0 프롬프트 섹션 추가

**Files:**
- Modify: `gui3.py` (`_build_conditions_tab` 메서드 끝부분)

- [ ] **Step 1: 현재 _build_conditions_tab 메서드 위치 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import re; t=open('gui3.py',encoding='utf-8').read(); m=re.search(r'def _build_conditions_tab', t); print('line', t[:m.start()].count(chr(10))+1 if m else 'NOT FOUND')"
```

- [ ] **Step 2: SETTINGS_PATH 옆에 IMAGE2_PROMPTS_PATH 상수 추가**

`gui3.py` 상단의 상수 정의 영역에서 `SETTINGS_PATH = ...` 라인을 Read한 뒤 그 직후에 추가:

```python
IMAGE2_PROMPTS_PATH = CONFIG_DIR / "image2_prompts.yaml"
```

(`CONFIG_DIR`은 이미 정의되어 있음 — Read로 확인.)

- [ ] **Step 3: image-2.0 섹션 빌더 메서드 추가**

`_build_conditions_tab` 메서드 정의 끝 직전에 다음 메서드 호출을 추가하고, 별도 빌더 메서드를 작성한다.

먼저 `_build_conditions_tab`의 마지막 줄에 `self._build_image2_section(self.tab_conditions)` 추가.

그 다음 `_build_conditions_tab` 메서드 직후에 다음 메서드를 추가:

```python
    def _build_image2_section(self, parent):
        """조건 탭 하단 image-2.0 카테고리별 프롬프트 섹션."""
        import tkinter as tk
        from tkinter import ttk, messagebox

        # 구분선
        ttk.Separator(parent, orient="horizontal").pack(
            fill="x", padx=12, pady=(20, 8))

        # 헤더
        hdr = tk.Label(
            parent, text="✨ image-2.0 카테고리별 프롬프트",
            font=("맑은 고딕", 11, "bold"))
        hdr.pack(anchor="w", padx=12, pady=(0, 6))

        # 글로벌 옵션
        glob = tk.Frame(parent); glob.pack(fill="x", padx=12, pady=4)
        tk.Label(glob, text="기본 품질:").pack(side="left")
        self.var_image2_default_quality = tk.StringVar(value="medium")
        ttk.Combobox(
            glob, textvariable=self.var_image2_default_quality,
            values=["low", "medium", "hd"], state="readonly", width=10,
        ).pack(side="left", padx=(4, 16))

        tk.Label(glob, text="검증 모델:").pack(side="left")
        self.var_image2_verify_model = tk.StringVar(value="gpt-4o-mini")
        ttk.Combobox(
            glob, textvariable=self.var_image2_verify_model,
            values=["gpt-4o-mini", "gpt-4o"], state="readonly", width=14,
        ).pack(side="left", padx=4)

        self.var_image2_block_unsafe = tk.BooleanVar(value=False)
        tk.Checkbutton(
            glob, text="변형 감지 시 저장 차단",
            variable=self.var_image2_block_unsafe,
        ).pack(side="left", padx=(16, 0))

        # 카테고리 선택
        cat_row = tk.Frame(parent); cat_row.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(cat_row, text="카테고리:").pack(side="left")
        self.var_image2_category = tk.StringVar(value="default")
        cat_combo = ttk.Combobox(
            cat_row, textvariable=self.var_image2_category,
            values=["default", "jewelry", "mannequin", "model",
                    "full", "detail", "package"],
            state="readonly", width=14,
        )
        cat_combo.pack(side="left", padx=4)
        cat_combo.bind("<<ComboboxSelected>>",
                       lambda _e: self._image2_load_category())

        # 보정 프롬프트
        tk.Label(parent, text="보정 프롬프트:",
                 font=("맑은 고딕", 9)).pack(anchor="w", padx=12, pady=(8, 2))
        self.txt_image2_enhance = tk.Text(parent, height=5,
                                          font=("Consolas", 9), wrap="word")
        self.txt_image2_enhance.pack(fill="x", padx=12)

        # 검증 프롬프트
        tk.Label(parent, text="검증 프롬프트:",
                 font=("맑은 고딕", 9)).pack(anchor="w", padx=12, pady=(8, 2))
        self.txt_image2_verify = tk.Text(parent, height=5,
                                         font=("Consolas", 9), wrap="word")
        self.txt_image2_verify.pack(fill="x", padx=12)

        # 버튼
        btn = tk.Frame(parent); btn.pack(fill="x", padx=12, pady=10)
        tk.Button(btn, text="기본값으로 복원",
                  command=self._image2_reset_category).pack(side="left")
        tk.Button(btn, text="저장",
                  command=self._image2_save,
                  bg="#3498db", fg="white", padx=14
                  ).pack(side="right")

        # 초기 로드
        self._image2_load_category()

    def _image2_load_category(self):
        """선택된 카테고리의 enhance/verify 프롬프트를 텍스트박스에 로드."""
        try:
            data = load_yaml(IMAGE2_PROMPTS_PATH)
        except Exception:
            data = {}
        cfg = data.get("image2", {})
        if hasattr(self, "var_image2_default_quality"):
            self.var_image2_default_quality.set(
                cfg.get("default_quality", "medium"))
            self.var_image2_verify_model.set(
                cfg.get("verification", {}).get("model", "gpt-4o-mini"))
            self.var_image2_block_unsafe.set(
                bool(cfg.get("verification", {}).get("block_on_unsafe", False)))

        cat = self.var_image2_category.get()
        prompts = cfg.get("prompts", {}).get(cat, {})
        self.txt_image2_enhance.delete("1.0", "end")
        self.txt_image2_enhance.insert("1.0", prompts.get("enhance", ""))
        self.txt_image2_verify.delete("1.0", "end")
        self.txt_image2_verify.insert("1.0", prompts.get("verify", ""))

    def _image2_reset_category(self):
        from tkinter import messagebox
        if not messagebox.askyesno("확인",
                                   "현재 카테고리의 프롬프트를 기본값으로 되돌립니다."):
            return
        # 기본값 = 코드에 하드코딩된 default 카테고리 프롬프트
        defaults = {
            "default": {
                "enhance": "Enhance this product photo for an e-commerce listing.\n"
                           "Improve sharpness, color accuracy, and lighting.\n"
                           "Keep the product, pose, and composition exactly the same.\n"
                           "Pure white background. No text, no watermarks.",
                "verify": "Compare the original (first image) and enhanced (second image).\n"
                          "Check if logos, text, brand marks, or distinctive product features\n"
                          "have been altered, distorted, or blurred.\n"
                          "Respond ONLY in JSON: {\"safe\": true|false, \"issues\": [\"...\"]}.",
            },
        }
        cat = self.var_image2_category.get()
        d = defaults.get(cat, defaults["default"])
        self.txt_image2_enhance.delete("1.0", "end")
        self.txt_image2_enhance.insert("1.0", d["enhance"])
        self.txt_image2_verify.delete("1.0", "end")
        self.txt_image2_verify.insert("1.0", d["verify"])

    def _image2_save(self):
        """현재 카테고리 프롬프트 + 글로벌 옵션을 image2_prompts.yaml에 저장."""
        from tkinter import messagebox
        try:
            data = load_yaml(IMAGE2_PROMPTS_PATH)
        except Exception:
            data = {"image2": {}}

        cfg = data.setdefault("image2", {})
        cfg["default_quality"] = self.var_image2_default_quality.get()
        cfg.setdefault("verification", {})["model"] = self.var_image2_verify_model.get()
        cfg["verification"]["block_on_unsafe"] = bool(self.var_image2_block_unsafe.get())
        prompts = cfg.setdefault("prompts", {})
        cat = self.var_image2_category.get()
        prompts.setdefault(cat, {})["enhance"] = \
            self.txt_image2_enhance.get("1.0", "end").strip()
        prompts[cat]["verify"] = \
            self.txt_image2_verify.get("1.0", "end").strip()

        save_yaml(IMAGE2_PROMPTS_PATH, data)
        messagebox.showinfo("저장 완료",
                            f"image-2.0 프롬프트 ({cat})가 저장되었습니다.")
```

`load_yaml`, `save_yaml`은 gui3.py에 이미 import되어 있음(Task 8에서 확인).

- [ ] **Step 4: 문법 검증 + 스모크 임포트**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('SYNTAX OK')"
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import gui3; print('IMPORT OK')"
```

- [ ] **Step 5: 커밋**

```bash
git add gui3.py
git commit -m "feat(gui): 조건 탭에 image-2.0 카테고리별 프롬프트 섹션 추가"
```

---

## Task 6: 카드 데이터 구조 + 라디오 토글 UI

**Files:**
- Modify: `gui3.py` (뷰파인더 카드 렌더링 함수 `_build_file_row`)

- [ ] **Step 1: _build_file_row 위치 확인 + 현재 구조 파악**

`gui3.py:2750-2830` 부근의 `_build_file_row` 메서드를 Read하여 카드의 컨테이너 구조 파악. 기존 "리사이즈" 버튼 위치 확인.

- [ ] **Step 2: 카드 데이터 초기화 — `_vf_register_file`에 image2 필드 추가**

`_vf_register_file` 메서드(line ~2320)를 Read하여 `self._viewfinder_pairs.append({...})` 부분에 image2 필드 추가:

```python
        self._viewfinder_pairs.append({
            "input_path": file_path,
            "output_files": [],
            "success": False,
            "status": "processing",
            # ── 신규: image-2.0 결과 ──
            "image2_results": [],          # list of dict
            "image2_selected_idx": -1,     # -1=편집본, 0+=image2_results 인덱스
            "final_saved": False,
        })
```

(기존 dict의 정확한 키 이름은 코드 확인 후 매칭 — Read 필수)

- [ ] **Step 3: _build_file_row 끝부분에 라디오 토글 영역 추가**

`_build_file_row` 메서드의 카드 컨텐츠 영역 끝(보통 버튼 행 직전)에 다음 코드 추가:

```python
        # ── image-2.0 결과 라디오 영역 ──
        self._vf_image2_rows = getattr(self, "_vf_image2_rows", {})
        i2_frame = tk.Frame(content)
        i2_frame.pack(fill="x", pady=(4, 0))
        self._vf_image2_rows[idx] = {
            "frame": i2_frame,
            "selection": tk.IntVar(value=-1),  # -1=편집본
            "rows": [],
        }
        self._vf_render_image2_options(idx)
```

그리고 별도 메서드 `_vf_render_image2_options`를 카드 생성 메서드 근처에 추가:

```python
    def _vf_render_image2_options(self, vf_idx: int):
        """카드의 image-2.0 결과 토글 영역을 다시 그린다."""
        if vf_idx not in self._vf_image2_rows:
            return
        slot = self._vf_image2_rows[vf_idx]
        frm = slot["frame"]
        for w in frm.winfo_children():
            w.destroy()
        slot["rows"] = []

        item = self._viewfinder_pairs[vf_idx]
        sel_var = slot["selection"]
        sel_var.set(item.get("image2_selected_idx", -1))

        # 편집본
        tk.Radiobutton(
            frm, text="◉ 편집본 (기본)",
            variable=sel_var, value=-1,
            command=lambda: self._vf_image2_select(vf_idx, -1),
            font=("맑은 고딕", 9),
        ).pack(anchor="w")

        # image-2.0 결과들
        for i, r in enumerate(item.get("image2_results", [])):
            v = r.get("verification", {}) or {}
            badge = "✅ 검증 통과" if v.get("safe") else (
                "⚠️ 변형 감지" if v else "ℹ️ 검증 없음")
            label = (f"image-2.0 {r.get('quality','?')} ({i+1}차) "
                     f"{badge}")
            tk.Radiobutton(
                frm, text=label,
                variable=sel_var, value=i,
                command=lambda x=i: self._vf_image2_select(vf_idx, x),
                font=("맑은 고딕", 9),
            ).pack(anchor="w")
            if v and not v.get("safe"):
                # 상세 보기
                issues = "; ".join(v.get("issues", []))[:80]
                tk.Label(frm, text=f"   → {issues}",
                         font=("맑은 고딕", 8), fg="#c0392b"
                         ).pack(anchor="w")

    def _vf_image2_select(self, vf_idx: int, choice_idx: int):
        """라디오 변경 처리 — 메모리에만 반영. 최종 저장은 별도 버튼."""
        if 0 <= vf_idx < len(self._viewfinder_pairs):
            self._viewfinder_pairs[vf_idx]["image2_selected_idx"] = choice_idx
```

- [ ] **Step 4: 카드 버튼 행에 "image-2.0 보정" + "최종 저장" 버튼 추가**

기존 "리사이즈" 버튼 옆에 추가 (Task 13에서 만든 `card_btn_row` 구조 재사용):

```python
                tk.Button(
                    btn_row, text="✨ image-2.0",
                    command=lambda i=idx: self._vf_open_image2_dialog(i),
                    font=("맑은 고딕", 8),
                    bg="#9b59b6", fg="white", padx=6,
                ).pack(side="left", padx=2)
                tk.Button(
                    btn_row, text="💾 최종 저장",
                    command=lambda i=idx: self._vf_apply_image2_final(i),
                    font=("맑은 고딕", 8),
                    bg="#27ae60", fg="white", padx=6,
                ).pack(side="left", padx=2)
```

이 두 메서드는 다음 태스크에서 구현. 지금은 빈 placeholder로 추가:

```python
    def _vf_open_image2_dialog(self, vf_idx: int):
        """Task 7에서 구현"""
        from tkinter import messagebox
        messagebox.showinfo("준비 중", "Task 7에서 구현됩니다.")

    def _vf_apply_image2_final(self, vf_idx: int):
        """Task 9에서 구현"""
        from tkinter import messagebox
        messagebox.showinfo("준비 중", "Task 9에서 구현됩니다.")
```

- [ ] **Step 5: 문법 검증 + 스모크 임포트**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('SYNTAX OK')"
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import gui3; print('IMPORT OK')"
```

- [ ] **Step 6: 커밋**

```bash
git add gui3.py
git commit -m "feat(viewfinder): image-2.0 결과 토글 영역 + 보정/저장 버튼 (placeholder)"
```

---

## Task 7: 보정 다이얼로그 (`_vf_open_image2_dialog`) 구현

**Files:**
- Modify: `gui3.py` (Task 6의 placeholder 교체)

- [ ] **Step 1: 카테고리 자동 감지 헬퍼 추가**

`_vf_open_image2_dialog` 정의 직전에:

```python
    def _vf_image2_detect_category(self, vf_idx: int) -> str:
        """Vision 분석 결과에서 image-2.0 프롬프트 카테고리 매핑."""
        item = self._viewfinder_pairs[vf_idx]
        category = (item.get("detected_category") or "").lower()
        image_type = (item.get("image_type") or "").lower()
        has_mannequin = bool(item.get("has_mannequin", False))

        if category == "jewelry":
            return "jewelry"
        if image_type == "worn":
            return "mannequin" if has_mannequin else "model"
        if image_type in ("full", "detail", "package"):
            return image_type
        return "default"
```

- [ ] **Step 2: placeholder 교체 — 다이얼로그 본체**

Task 6에서 만든 `_vf_open_image2_dialog` placeholder를 다음으로 교체:

```python
    def _vf_open_image2_dialog(self, vf_idx: int):
        """image-2.0 보정 다이얼로그 — 프롬프트/품질 입력."""
        import tkinter as tk
        from tkinter import ttk, messagebox

        if vf_idx >= len(self._viewfinder_pairs):
            return
        item = self._viewfinder_pairs[vf_idx]

        # 원본(편집본 또는 이전 보정 결과) 경로 확보
        orig_path = self._vf_image2_get_source(vf_idx)
        if not orig_path or not orig_path.exists():
            messagebox.showerror(
                "오류",
                "보정할 원본 이미지를 찾을 수 없습니다.\n"
                "먼저 메인 처리를 완료해 주세요.",
                parent=self._vf_dlg)
            return

        # 카테고리 자동 감지 + 프롬프트 prefill
        try:
            cfg = load_yaml(IMAGE2_PROMPTS_PATH).get("image2", {})
        except Exception:
            cfg = {}
        prompts = cfg.get("prompts", {})
        cat_default = self._vf_image2_detect_category(vf_idx)
        default_quality = cfg.get("default_quality", "medium")

        dlg = tk.Toplevel(self._vf_dlg)
        dlg.title(f"✨ image-2.0 보정 — {orig_path.name}")
        dlg.resizable(False, False)
        dlg.grab_set()

        f = tk.Frame(dlg, padx=18, pady=14); f.pack(fill="both", expand=True)

        # 카테고리
        row = tk.Frame(f); row.pack(fill="x", pady=4)
        tk.Label(row, text="카테고리:", width=10, anchor="w").pack(side="left")
        var_cat = tk.StringVar(value=cat_default)
        cat_combo = ttk.Combobox(
            row, textvariable=var_cat,
            values=list(prompts.keys()) or ["default"],
            state="readonly", width=18,
        )
        cat_combo.pack(side="left")
        tk.Label(row, text=f"(자동 감지: {cat_default})",
                 fg="#888", font=("맑은 고딕", 8)).pack(side="left", padx=8)

        # 보정 프롬프트
        tk.Label(f, text="보정 프롬프트 (이번 1회만 수정 가능):",
                 anchor="w").pack(fill="x", pady=(10, 2))
        txt_prompt = tk.Text(f, height=6, width=70,
                             font=("Consolas", 9), wrap="word")
        txt_prompt.pack(fill="x")

        def _load_prompt():
            cat = var_cat.get()
            txt_prompt.delete("1.0", "end")
            txt_prompt.insert("1.0",
                              prompts.get(cat, {}).get("enhance", ""))
        cat_combo.bind("<<ComboboxSelected>>", lambda _e: _load_prompt())
        _load_prompt()

        # 품질
        row = tk.Frame(f); row.pack(fill="x", pady=10)
        tk.Label(row, text="품질:").pack(side="left")
        var_quality = tk.StringVar(value=default_quality)
        for q, label in [("low", "low (~$0.006)"),
                         ("medium", "medium (~$0.05)"),
                         ("hd", "hd (~$0.21)")]:
            tk.Radiobutton(row, text=label, value=q,
                           variable=var_quality).pack(side="left", padx=4)

        # 검증 토글
        var_verify = tk.BooleanVar(value=True)
        tk.Checkbutton(
            f, text="자동 검증 (gpt-4o-mini, ~$0.001)",
            variable=var_verify,
        ).pack(anchor="w", pady=(4, 8))

        # 버튼
        btn_row = tk.Frame(f); btn_row.pack(fill="x", pady=(10, 0))
        tk.Button(btn_row, text="취소", command=dlg.destroy,
                  padx=14, pady=4).pack(side="right", padx=4)

        def _start():
            prompt = txt_prompt.get("1.0", "end").strip()
            if not prompt:
                messagebox.showwarning("경고", "프롬프트가 비어있습니다.",
                                       parent=dlg)
                return
            cat = var_cat.get()
            verify_prompt = prompts.get(cat, {}).get("verify", "")
            quality = var_quality.get()
            run_verify = var_verify.get()
            dlg.destroy()
            self._vf_image2_run(
                vf_idx, orig_path, prompt, verify_prompt,
                quality, run_verify, cat,
            )

        tk.Button(btn_row, text="✨ 보정 시작", command=_start,
                  bg="#9b59b6", fg="white", padx=14, pady=4
                  ).pack(side="right", padx=4)

    def _vf_image2_get_source(self, vf_idx: int) -> "Path | None":
        """image-2.0 보정 원본 경로 — 항상 OUTPUT/original/{stem}_1.jpg에서 로드.

        설계서 6.2: '단순화 옵션 — 항상 OUTPUT/original 사용'.
        """
        item = self._viewfinder_pairs[vf_idx]
        in_path = Path(item.get("input_path", ""))
        stem = in_path.stem
        # output_files에서 OUTPUT 디렉토리 추정
        for of in item.get("output_files", []):
            p = Path(of.get("path", ""))
            if p.parent.exists():
                cand = p.parent.parent / "original" / f"{stem}_1.jpg"
                if cand.exists():
                    return cand
        return None
```

- [ ] **Step 3: _vf_image2_run 메서드 추가 (워커 스레드 트리거)**

다음 메서드도 같이 추가 (Task 8에서 구체 구현 예정이지만 placeholder로 시작):

```python
    def _vf_image2_run(self, vf_idx, src_path, enhance_prompt,
                       verify_prompt, quality, run_verify, category):
        """Task 8에서 구현 — 백그라운드 워커 + 결과 누적."""
        from tkinter import messagebox
        messagebox.showinfo("준비 중", "Task 8에서 구현됩니다.")
```

- [ ] **Step 4: 문법 검증 + 스모크 임포트**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('SYNTAX OK')"
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import gui3; print('IMPORT OK')"
```

- [ ] **Step 5: 커밋**

```bash
git add gui3.py
git commit -m "feat(viewfinder): image-2.0 보정 다이얼로그 + 카테고리 자동 감지"
```

---

## Task 8: 백그라운드 워커 + 동적 스테이지 추가

**Files:**
- Modify: `gui3.py`

- [ ] **Step 1: 동적 스테이지 추가 헬퍼**

기존 `_vf_update_file_stage` 메서드 근처에 다음 메서드 추가:

```python
    def _vf_image2_add_stage(self, vf_idx: int, label: str, state: str = "active"):
        """image-2.0 동적 스테이지 추가/갱신.

        state: "active" | "done" | "warning" | "error"
        """
        if vf_idx >= len(self._viewfinder_pairs):
            return
        item = self._viewfinder_pairs[vf_idx]
        stages_dyn = item.setdefault("image2_stages", [])
        # 기존 라벨이 있으면 갱신, 없으면 추가
        for s in stages_dyn:
            if s["label"] == label:
                s["state"] = state
                break
        else:
            stages_dyn.append({"label": label, "state": state})
        # UI 다시 렌더 (카드 단계 표시 영역 재구성)
        self._vf_redraw_stages(vf_idx)

    def _vf_redraw_stages(self, vf_idx: int):
        """카드의 단계 표시줄을 다시 렌더한다.

        기존 7단계 + image-2.0 동적 스테이지를 표시.
        """
        # 카드별 stage row를 self._vf_stage_rows에 저장해 두었다고 가정.
        if not hasattr(self, "_vf_stage_rows"):
            return
        slot = self._vf_stage_rows.get(vf_idx)
        if not slot:
            return
        # 기존 동적 스테이지 위젯 제거
        for w in slot.get("dynamic_widgets", []):
            try:
                w.destroy()
            except Exception:
                pass
        slot["dynamic_widgets"] = []

        item = self._viewfinder_pairs[vf_idx]
        for s in item.get("image2_stages", []):
            color = {"active": "#f1c40f", "done": "#27ae60",
                     "warning": "#e67e22", "error": "#c0392b"
                     }.get(s["state"], "#7f8c8d")
            lbl = tk.Label(
                slot["frame"],
                text=f"→ {s['label']}",
                font=("맑은 고딕", 8),
                fg=color,
            )
            lbl.pack(side="left", padx=2)
            slot["dynamic_widgets"].append(lbl)
```

**중요:** `_build_file_row`에서 단계 표시 행을 만드는 부분을 찾아 다음과 같이 frame 참조를 저장하도록 수정:

```python
        # 단계 표시 행 (기존 코드)
        stage_row = tk.Frame(content)
        stage_row.pack(fill="x")
        # 신규: 참조 저장
        self._vf_stage_rows = getattr(self, "_vf_stage_rows", {})
        self._vf_stage_rows[idx] = {
            "frame": stage_row,
            "dynamic_widgets": [],
        }
        # ... 기존 7개 스테이지 위젯 생성 코드 ...
```

(정확한 위치는 Read로 확인. 기존에 stage 패턴이 어떻게 그려지는지 추적)

- [ ] **Step 2: _vf_image2_run placeholder 교체**

Task 7의 placeholder를 다음으로 교체:

```python
    def _vf_image2_run(self, vf_idx, src_path, enhance_prompt,
                       verify_prompt, quality, run_verify, category):
        """백그라운드 스레드에서 image-2.0 보정+검증 실행."""
        import threading
        from tkinter import messagebox

        # 스테이지 표시 시작
        stage_label = f"image-2.0 ({quality})"
        self.after(0, lambda: self._vf_image2_add_stage(
            vf_idx, stage_label, "active"))
        self._log_unified(
            f"  ✨ image-2.0 보정 시작 — {src_path.name} ({quality})")

        def _worker():
            from src.openai_image import (
                GPTImage2Client, GPTImage2NoCreditError)
            try:
                with open(src_path, "rb") as f:
                    img_bytes = f.read()

                # 검증 모델은 설정에서 로드
                try:
                    cfg = load_yaml(IMAGE2_PROMPTS_PATH).get("image2", {})
                except Exception:
                    cfg = {}
                verify_model = cfg.get("verification", {}).get(
                    "model", "gpt-4o-mini")

                client = GPTImage2Client(
                    verification_model=verify_model)

                enh, ver = client.enhance_and_verify(
                    image_bytes=img_bytes,
                    enhance_prompt=enhance_prompt,
                    verify_prompt=verify_prompt,
                    quality=quality,
                    run_verification=run_verify,
                )

                # 메인 스레드에서 결과 반영
                def _on_done():
                    item = self._viewfinder_pairs[vf_idx]
                    item.setdefault("image2_results", []).append({
                        "bytes": enh.enhanced_bytes,
                        "quality": enh.quality,
                        "prompt": enh.prompt_used,
                        "category": category,
                        "verification": (
                            {"safe": ver.safe,
                             "issues": ver.issues,
                             "elapsed_sec": ver.elapsed_sec}
                            if ver else None),
                        "elapsed_sec": enh.elapsed_sec,
                        "cost_estimate": enh.cost_estimate_usd,
                    })
                    state = "done"
                    if ver and not ver.safe:
                        state = "warning"
                    self._vf_image2_add_stage(vf_idx, stage_label, state)
                    self._vf_render_image2_options(vf_idx)
                    issues_msg = ""
                    if ver and not ver.safe and ver.issues:
                        issues_msg = f" ⚠️ {ver.issues[0]}"
                    self._log_unified(
                        f"  ✅ image-2.0 보정 완료 — {src_path.name} "
                        f"({quality}, {enh.elapsed_sec:.1f}s){issues_msg}",
                        "success")
                self.after(0, _on_done)

            except GPTImage2NoCreditError as e:
                self.after(0, lambda: self._vf_image2_add_stage(
                    vf_idx, stage_label, "error"))
                self.after(0, lambda: messagebox.showerror(
                    "OpenAI 크레딧 부족",
                    f"{e}\n\n충전 후 다시 시도해 주세요.",
                    parent=self._vf_dlg))
                self._log_unified(
                    f"  ❌ image-2.0 — 크레딧 부족", "error")
            except Exception as e:
                self.after(0, lambda: self._vf_image2_add_stage(
                    vf_idx, stage_label, "error"))
                self.after(0, lambda err=str(e): messagebox.showerror(
                    "image-2.0 실패", f"보정 실패:\n{err}",
                    parent=self._vf_dlg))
                self._log_unified(
                    f"  ❌ image-2.0 실패 — {e}", "error")

        threading.Thread(target=_worker, daemon=True,
                         name="image2-worker").start()
```

- [ ] **Step 3: 문법 검증 + 스모크 임포트**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('SYNTAX OK')"
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import gui3; print('IMPORT OK')"
```

- [ ] **Step 4: 커밋**

```bash
git add gui3.py
git commit -m "feat(viewfinder): image-2.0 백그라운드 워커 + 동적 스테이지"
```

---

## Task 9: 최종 저장 워크플로우 (`_vf_apply_image2_final`)

**Files:**
- Modify: `gui3.py` (Task 6의 placeholder 교체)

- [ ] **Step 1: placeholder를 실제 구현으로 교체**

```python
    def _vf_apply_image2_final(self, vf_idx: int):
        """선택된 image-2.0 결과를 최종 저장 — OUTPUT/original 덮어쓰기 +
        멀티사이즈 자동 재생성."""
        from tkinter import messagebox
        from PIL import Image
        import io

        if vf_idx >= len(self._viewfinder_pairs):
            return
        item = self._viewfinder_pairs[vf_idx]
        sel = item.get("image2_selected_idx", -1)
        if sel < 0:
            messagebox.showinfo(
                "안내",
                "선택된 image-2.0 결과가 없습니다.\n"
                "라디오에서 적용할 결과를 먼저 선택하세요.",
                parent=self._vf_dlg)
            return
        if sel >= len(item.get("image2_results", [])):
            messagebox.showerror("오류", "잘못된 선택 인덱스입니다.",
                                 parent=self._vf_dlg)
            return

        result = item["image2_results"][sel]
        ver = result.get("verification") or {}
        # 변형 감지 시 한 번 더 확인
        if ver and not ver.get("safe"):
            issues = "\n  - ".join(ver.get("issues", []))
            if not messagebox.askyesno(
                "변형 감지 결과 저장 확인",
                f"이 결과는 변형이 감지되었습니다:\n\n  - {issues}\n\n"
                f"정말 최종 저장하시겠습니까?",
                parent=self._vf_dlg,
                icon="warning"):
                return

        # OUTPUT/original 경로 확보
        orig_path = self._vf_image2_get_source(vf_idx)
        if not orig_path:
            messagebox.showerror(
                "오류", "원본 보존 파일을 찾을 수 없습니다.",
                parent=self._vf_dlg)
            return

        # 백업: {stem}_1.jpg → {stem}_1_v0.jpg (이미 있으면 _v0_1, _v0_2 ...)
        stem = orig_path.stem  # "상품명_1"
        backup = orig_path.with_name(f"{stem}_v0.jpg")
        suffix = 1
        while backup.exists():
            backup = orig_path.with_name(f"{stem}_v0_{suffix}.jpg")
            suffix += 1
        try:
            orig_path.rename(backup)
        except Exception as e:
            messagebox.showerror(
                "백업 실패",
                f"기존 원본 백업에 실패했습니다:\n{e}",
                parent=self._vf_dlg)
            return

        # image-2.0 결과를 1024 → 2250로 업스케일하여 저장
        try:
            i2_img = Image.open(io.BytesIO(result["bytes"]))
            if i2_img.mode != "RGB":
                if i2_img.mode == "RGBA":
                    bg = Image.new("RGB", i2_img.size, (255, 255, 255))
                    bg.paste(i2_img, mask=i2_img.split()[3])
                    i2_img = bg
                else:
                    i2_img = i2_img.convert("RGB")
            # base_size로 업스케일 (설계서 6.3)
            from src.exporter.resizer import MultiSizeResizer
            from src.utils.config_loader import load_yaml as _ly
            try:
                rcfg = _ly(SETTINGS_PATH).get("resize", {})
            except Exception:
                rcfg = {}
            base = int(rcfg.get("base_size", 2250))
            if i2_img.size != (base, base):
                i2_img = i2_img.resize((base, base), Image.LANCZOS)
            # JPEG로 저장
            i2_img.save(orig_path, format="JPEG", quality=95, optimize=True)
        except Exception as e:
            # 백업 복구
            try:
                backup.rename(orig_path)
            except Exception:
                pass
            messagebox.showerror(
                "저장 실패",
                f"image-2.0 결과를 저장하는 중 오류:\n{e}",
                parent=self._vf_dlg)
            return

        # 멀티사이즈 재생성 (기존 MultiSizeResizer 재사용)
        try:
            output_root = orig_path.parent.parent  # OUTPUT
            try:
                full_settings = _ly(SETTINGS_PATH)
            except Exception:
                full_settings = {}
            resizer = MultiSizeResizer(output_root, full_settings)
            seq_n = item.get("seq_n", vf_idx + 1)
            is_first = (vf_idx == 0)
            resizer.resize_from_file(
                orig_path,
                seq_n=seq_n,
                variants={"size_1500": True, "size_860": True,
                          "crop": is_first},
                overwrite=True,
            )
        except Exception as e:
            messagebox.showwarning(
                "멀티사이즈 재생성 경고",
                f"OUTPUT/original은 갱신되었지만 멀티사이즈 재생성 중 오류:\n{e}\n"
                f"리사이징 탭에서 수동 재실행이 가능합니다.",
                parent=self._vf_dlg)

        # 카드 상태 업데이트
        item["final_saved"] = True
        self._vf_render_image2_options(vf_idx)  # 재렌더
        self._log_unified(
            f"  💾 image-2.0 최종 저장 완료 — {orig_path.name} "
            f"(백업: {backup.name})",
            "success")
        messagebox.showinfo(
            "최종 저장 완료",
            f"image-2.0 결과가 최종 저장되었습니다.\n\n"
            f"  • 원본 → {backup.name}로 백업\n"
            f"  • 새 원본: {orig_path.name}\n"
            f"  • 1500/860/crop 자동 재생성 완료",
            parent=self._vf_dlg)
```

- [ ] **Step 2: 문법 검증 + 스모크 임포트**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('SYNTAX OK')"
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import gui3; print('IMPORT OK')"
```

- [ ] **Step 3: 커밋**

```bash
git add gui3.py
git commit -m "feat(viewfinder): image-2.0 최종 저장 — 백업 + 덮어쓰기 + 멀티사이즈 재생성"
```

---

## Task 10: 통합 구동 테스트 + 음성 알림 + history.md + 푸시

**Files:**
- Modify: `history.md`
- Use: 실 이미지 1장

- [ ] **Step 1: 단위 테스트 전체 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/ -v
```
Expected: resizer 14 + openai_image 9 = 23 passed

- [ ] **Step 2: 실 구동 시나리오**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python gui3.py
```

체크리스트:
- [ ] 메인 탭에서 이미지 1장 처리 → OUTPUT/original/{stem}_1.jpg 생성 확인
- [ ] 뷰파인더에서 해당 카드 → "✨ image-2.0" 버튼 클릭
- [ ] 다이얼로그 확인: 카테고리 자동 감지 + 프롬프트 prefill + 품질 medium 기본
- [ ] [✨ 보정 시작] → 단계에 "image-2.0 (medium)" 추가됨
- [ ] 약 10~30초 후 보정 완료 → 카드 라디오에 새 항목 + 검증 배지 표시
- [ ] 같은 카드에서 한 번 더 high 품질로 시도 → 라디오 2개
- [ ] 라디오로 high 선택 → [💾 최종 저장]
- [ ] 변형 감지 시 확인 다이얼로그 (있으면)
- [ ] OUTPUT/original/{stem}_1.jpg 변경 + {stem}_1_v0.jpg 백업 확인
- [ ] OUTPUT/1500/{n}.jpg, OUTPUT/860/100_{n}.jpg 갱신 확인

- [ ] **Step 3: history.md 업데이트**

`history.md` 헤더 부근에 신규 섹션 추가:

```markdown
## 2026-05-06 (9차) — gpt-image-2 사후 보정 + 검증

### 추가된 기능
- **뷰파인더에서 카드별 image-2.0 보정**: 메인 처리 결과를 보고 선택적으로 OpenAI gpt-image-2로 사후 보정
- **카테고리별 보정/검증 프롬프트** (조건 탭): default/jewelry/mannequin/model/full/detail/package
- **자동 변형 검증** (gpt-4o-mini): 원본 + 보정본을 함께 보내 로고/문자/디테일 왜곡 감지
- **결과 토글 누적**: 한 카드에서 여러 번 시도(품질/프롬프트 조합) → 라디오로 비교 후 선택
- **최종 저장**: 선택 결과로 OUTPUT/original 덮어쓰기 → 1500/860/crop 자동 재생성, 기존 원본은 _v0.jpg로 백업
- **뷰파인더 단계 표시** 동적 추가: image-2.0 (medium/high) 단계가 시도마다 추가됨

### 기술
- 신규 모듈: src/openai_image/client.py — GPTImage2Client (보정+검증 통합)
- 신규 설정: config/image2_prompts.yaml
- 9개 단위 테스트 (tests/test_openai_image.py)
- 가격: medium ~$0.05, hd ~$0.21 per 1024×1024 + 검증 ~$0.001
```

- [ ] **Step 4: 음성 알림**

PowerShell:
```powershell
Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('image-2.0 사후 보정 기능 완료되었습니다')
```

- [ ] **Step 5: 최종 커밋 + 푸시**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && git add history.md && \
git commit -m "docs: history.md — 9차 gpt-image-2 사후 보정 추가" && \
git push origin main
```

---

## 자체 검토 결과

### ✅ Spec 커버리지

| 사양 요구 | 구현 태스크 |
|---------|----------|
| GPTImage2Client.enhance() | Task 1 |
| GPTImage2Client.verify() | Task 2 |
| enhance_and_verify() 통합 | Task 3 |
| 카테고리별 프롬프트 YAML | Task 4 |
| 조건 탭 UI 확장 | Task 5 |
| 카드 라디오 토글 + 보정/저장 버튼 | Task 6 |
| 보정 다이얼로그 + 카테고리 자동 감지 | Task 7 |
| 백그라운드 워커 + 동적 스테이지 | Task 8 |
| 최종 저장 (백업+덮어쓰기+멀티사이즈 재생성) | Task 9 |
| 통합 구동 테스트 + 음성 + history.md | Task 10 |
| 변형 감지 시 확인 다이얼로그 | Task 9 |
| 402 크레딧 부족 → 한글 팝업 | Task 1 + Task 8 |
| _v0.jpg 백업 (이미 있으면 증분) | Task 9 |

### ✅ 타입 일관성

- `GPTImage2Result.enhanced_bytes: bytes` — Task 1, 8, 9 일관
- `VerificationResult.safe: bool, issues: list[str]` — Task 2, 8, 9 일관
- `enhance_and_verify(...)→ tuple[GPTImage2Result, VerificationResult|None]` — Task 3, 8 일관
- `MultiSizeResizer.resize_from_file(...)` — Task 9에서 기존 시그니처 그대로 사용
- 카드 데이터 `image2_results`, `image2_selected_idx`, `final_saved` — Task 6, 7, 8, 9 일관

### ✅ Placeholder 스캔

모든 코드 블록은 완전 구현. Task 6, 7의 일시적 placeholder는 Task 8, 9에서 명시적으로 교체됨 (각 Task에 명시).

### ✅ Frequent commits

10개 태스크 = 10개 이상 커밋. TDD 사이클은 단위로 잘게 쪼개져 있음.

---

**Plan 완료 — `docs/superpowers/plans/2026-05-06-gpt-image-2-post-enhance-plan.md`에 저장됨.**
