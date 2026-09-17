"""OpenAI gpt-image-2.5 사후 보정 + gpt-4o-mini 변형 검증 클라이언트.

2026-09-16 gpt-image-2.5 전환. 2.5는 두 가지로 나온다.
  - gpt-image-2.5-flare   : 빠른 쪽 (2.0 대비 지연 약 50%↓, 품질은 2.0 이상)
  - gpt-image-2.5-sunburst: 품질 우선 (세밀한 편집/피사체 보존이 더 정확)
품질 단계는 low/medium/high 에 **xhigh, max** 가 더해졌고(2.5 전용),
출력 크기는 고정 3종이 아니라 16의 배수 임의 크기를 쓸 수 있다.
"""
from __future__ import annotations

import io
import os
import json
import base64
import time
from dataclasses import dataclass, field

from loguru import logger
from openai import OpenAI, APIStatusError

from ..utils.model_registry import LATEST, is_reasoning_openai, resolve


@dataclass
class GPTImage2Result:
    enhanced_bytes: bytes
    quality: str
    prompt_used: str
    cost_estimate_usd: float = 0.0
    elapsed_sec: float = 0.0
    model: str = ""
    size: str = ""
    output_tokens: int = 0


@dataclass
class VerificationResult:
    safe: bool
    issues: list[str] = field(default_factory=list)
    raw_response: str = ""
    elapsed_sec: float = 0.0


class GPTImage2NoCreditError(RuntimeError):
    """OpenAI 크레딧 부족 (HTTP 402)."""


class GPTImage2OrgVerificationError(RuntimeError):
    """OpenAI 조직 검증 필요 (HTTP 403).

    gpt-image 계열은 조직 검증이 완료된 OpenAI 계정만 사용 가능.
    https://platform.openai.com/settings/organization/general 에서
    'Verify Organization' 클릭 후 최대 15분 대기.
    """


# 모델 ──────────────────────────────────────────────────────────────
DEFAULT_MODEL = "gpt-image-2.5-flare"
MODELS = ("gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2")
LEGACY_MODELS = ("gpt-image-2",)          # xhigh/max 를 못 쓰는 구버전

# 품질 단계 — xhigh/max 는 2.5 전용
QUALITY_TIERS = ("low", "medium", "high", "xhigh", "max", "auto")
LEGACY_QUALITY_TIERS = ("low", "medium", "high", "auto")

# 출력 크기 제약 (2.5 / 2.0 공통, 2026-09 기준 실측)
#   - 가로·세로 모두 16의 배수
#   - 비율 1:3 ~ 3:1, 한 변 3840px 이하
#   - 총 픽셀 655,360 ~ 8,294,400 (2560x1440 초과는 실험적)
SIZE_MULTIPLE = 16
SIZE_MAX_EDGE = 3840
SIZE_MIN_PIXELS = 655_360
SIZE_MAX_PIXELS = 8_294_400

# 이미지 출력 토큰 요금 ($30 / 1M tokens)
_USD_PER_OUTPUT_TOKEN = 30.0 / 1_000_000

# 1024x1024 기준 실측 출력 토큰 (2026-09-16, gpt-image-2.5-flare)
_OUTPUT_TOKENS_1K = {
    "low": 196,
    "medium": 439,
    "high": 1756,
    "xhigh": 3122,
    "max": 7024,
    "hd": 1756,     # 구 명칭 alias
    "auto": 439,
}
# 참고용 1024x1024 1장 비용 — 실제 비용은 응답의 usage 로 계산한다
_COST_PER_IMAGE = {
    k: round(v * _USD_PER_OUTPUT_TOKEN, 4)
    for k, v in _OUTPUT_TOKENS_1K.items()
}


def snap_size(width: int, height: int | None = None) -> str:
    """원본 크기를 API가 받는 크기 문자열로 맞춘다(16의 배수 + 한계 clamp)."""
    height = int(height or width)
    width = int(width)
    ratio = width / height

    def _snap(v: int) -> int:
        v = min(int(v), SIZE_MAX_EDGE)
        return max(SIZE_MULTIPLE, int(round(v / SIZE_MULTIPLE)) * SIZE_MULTIPLE)

    w, h = _snap(width), _snap(height)
    # 총 픽셀 상·하한 보정 (비율은 유지)
    for _ in range(8):
        px = w * h
        if px > SIZE_MAX_PIXELS:
            k = (SIZE_MAX_PIXELS / px) ** 0.5
        elif px < SIZE_MIN_PIXELS:
            k = (SIZE_MIN_PIXELS / px) ** 0.5 * 1.01
        else:
            break
        w, h = _snap(w * k), _snap(h * k)
    # 비율 1:3 ~ 3:1
    if not (1 / 3) <= ratio <= 3:
        side = _snap((w * h) ** 0.5)
        w = h = side
    return f"{w}x{h}"


class GPTImage2Client:
    """gpt-image-2.5 보정 + gpt-5.4-mini 검증 통합 클라이언트.

    검증 모델은 2026-09-17 gpt-4o-mini → gpt-5.4-mini 로 올렸다(실측: JSON 응답
    정상, reasoning_effort=low 로 52 토큰). gpt-4o-mini 도 그대로 고를 수 있다.
    """

    def __init__(
        self,
        api_key: str | None = None,
        verification_model: str = LATEST["openai_mini"],
        timeout: int = 300,
        model: str = DEFAULT_MODEL,
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
        self.verification_model = resolve(verification_model, "openai_mini", logger.warning)
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self._client = OpenAI(api_key=self._api_key, timeout=timeout)

    def _quality_for(self, model: str, quality: str) -> str:
        """구버전(2.0)에 2.5 전용 단계가 오면 high 로 내려준다."""
        if model in LEGACY_MODELS and quality in ("xhigh", "max"):
            logger.warning(
                f"[GPTImage] {model}는 quality={quality}를 지원하지 않습니다 → high")
            return "high"
        return quality

    def enhance(
        self,
        image_bytes: bytes,
        prompt: str,
        quality: str = "medium",
        size: str = "match",
        model: str | None = None,
        input_fidelity: str | None = None,
    ) -> GPTImage2Result:
        """이미지 1장 보정.

        size: "match"(원본 크기에 맞춤) | "1024x1024" 등 임의 16배수 크기 | "auto"
        input_fidelity: gpt-image-2 / 2.5 계열은 **지원하지 않는다**(2026-09-16
            실측: invalid_input_fidelity_model). 나중에 지원하는 모델이 나오면
            "high"를 넘기면 되고, 거부되면 자동으로 빼고 1회 재시도한다.
        """
        img_file = io.BytesIO(image_bytes)
        img_file.name = "input.png"

        model = model or self.model
        quality = self._quality_for(model, quality)
        if str(size).lower() in ("match", "원본", "source", ""):
            try:
                from PIL import Image as _PILImage
                with _PILImage.open(io.BytesIO(image_bytes)) as im:
                    size = snap_size(*im.size)
            except Exception as e:
                logger.warning(f"[GPTImage] 원본 크기 확인 실패 → 1024x1024 ({e})")
                size = "1024x1024"

        kwargs = dict(
            model=model,
            image=img_file,
            prompt=prompt,
            size=size,
            quality=quality,
        )
        if input_fidelity:
            kwargs["input_fidelity"] = input_fidelity

        t0 = time.time()
        try:
            resp = self._client.images.edit(**kwargs)
        except APIStatusError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            msg = str(e)
            if status == 402:
                logger.error("[GPTImage2] 크레딧 부족 (402)")
                raise GPTImage2NoCreditError(
                    "OpenAI 크레딧이 부족합니다. "
                    "https://platform.openai.com/account/billing/overview")
            if status == 400 and "input_fidelity" in msg.lower():
                # 구버전 모델/SDK 가 input_fidelity 를 모르면 빼고 1회 재시도
                logger.warning("[GPTImage] input_fidelity 미지원 → 제외하고 재시도")
                kwargs.pop("input_fidelity", None)
                img_file.seek(0)
                resp = self._client.images.edit(**kwargs)
                return self._result(resp, model, quality, size, prompt,
                                    time.time() - t0)
            if status == 403 and "must be verified" in msg.lower():
                logger.error("[GPTImage2] 조직 검증 필요 (403)")
                raise GPTImage2OrgVerificationError(
                    "OpenAI 조직 검증이 필요합니다.\n"
                    "https://platform.openai.com/settings/organization/general "
                    "에서 'Verify Organization' 클릭 후 최대 15분 대기.")
            raise
        return self._result(resp, model, quality, size, prompt,
                            time.time() - t0)

    def _result(self, resp, model, quality, size, prompt, elapsed):
        """API 응답 → GPTImage2Result. 비용은 응답의 usage 로 실측한다."""
        enhanced = base64.b64decode(resp.data[0].b64_json)
        out_tok = 0
        try:
            out_tok = int(resp.usage.output_tokens or 0)
        except Exception:
            pass
        cost = (out_tok * _USD_PER_OUTPUT_TOKEN if out_tok
                else _COST_PER_IMAGE.get(quality, 0.0132))
        logger.info(
            f"[GPTImage] 보정 완료 — {model} {size} quality={quality}, "
            f"{len(enhanced)//1024}KB, {elapsed:.1f}s, ${cost:.4f}")

        return GPTImage2Result(
            enhanced_bytes=enhanced,
            quality=quality,
            prompt_used=prompt,
            cost_estimate_usd=round(cost, 4),
            elapsed_sec=elapsed,
            model=model,
            size=size,
            output_tokens=out_tok,
        )

    def verify(
        self,
        original_bytes: bytes,
        enhanced_bytes: bytes,
        prompt: str,
    ) -> VerificationResult:
        """검증 모델(기본 gpt-5.4-mini)로 원본 vs 보정 이미지 변형 여부 검증."""
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
                         "image_url": {"url": f"data:image/png;base64,{o_b64}"}},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{e_b64}"}},
                    ],
                }],
                response_format={"type": "json_object"},
                timeout=self.timeout,
                # gpt-5 계열은 temperature 를 못 바꾸는 대신 추론 깊이를 정한다
                **({"reasoning_effort": "low"}
                   if is_reasoning_openai(self.verification_model) else {}),
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

    def enhance_and_verify(
        self,
        image_bytes: bytes,
        enhance_prompt: str,
        verify_prompt: str,
        quality: str = "medium",
        size: str = "match",
        run_verification: bool = True,
        model: str | None = None,
        input_fidelity: str | None = None,
    ) -> tuple:
        """편의 메서드: 보정 후 즉시 검증."""
        result = self.enhance(image_bytes, enhance_prompt, quality, size,
                              model=model, input_fidelity=input_fidelity)
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
