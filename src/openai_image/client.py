"""OpenAI gpt-image-2 사후 보정 + gpt-4o-mini 변형 검증 클라이언트."""
from __future__ import annotations

import io
import os
import json
import base64
import time
from dataclasses import dataclass, field

from loguru import logger
from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError


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


class GPTImage2NoCreditError(RuntimeError):
    """OpenAI 크레딧 부족 (HTTP 402)."""


_COST_PER_IMAGE = {
    "low": 0.006,
    "medium": 0.053,
    "hd": 0.211,
    "high": 0.211,
}


class GPTImage2Client:
    """gpt-image-2 보정 + gpt-4o-mini 검증 통합 클라이언트."""

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

    def enhance(
        self,
        image_bytes: bytes,
        prompt: str,
        quality: str = "medium",
        size: str = "1024x1024",
    ) -> GPTImage2Result:
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

    def verify(
        self,
        original_bytes: bytes,
        enhanced_bytes: bytes,
        prompt: str,
    ) -> VerificationResult:
        """gpt-4o-mini로 원본 vs 보정 이미지 변형 여부 검증."""
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
