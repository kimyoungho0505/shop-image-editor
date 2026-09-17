"""OpenAI (ChatGPT) Vision API 클라이언트.

2026-09-17 갱신 — gpt-4o → gpt-5.5
  gpt-5 계열은 chat.completions 규칙이 다르다(실측):
    · `max_tokens` 거부 → `max_completion_tokens`
    · `temperature` 는 기본값(1)만 허용 → 보내지 않는다
    · `reasoning_effort` 로 생각 깊이를 정한다. 분류/판정에는 "low" 가
      속도·비용 면에서 맞다(기본). settings.yaml 의 openai.reasoning_effort 로 바꾼다.
  gpt-4o 계열을 고르면 예전 방식(temperature 전송)으로 그대로 동작한다.
"""
import os

import cv2  # noqa: F401
import numpy as np
import openai
from loguru import logger

from ..utils.image_io import to_base64
from ..utils.model_registry import LATEST, is_reasoning_openai, resolve


class OpenAIVisionClient:
    """OpenAI GPT Vision API를 사용하여 이미지를 분석한다."""

    def __init__(self, api_key: str = None, model: str = LATEST["openai"],
                 reasoning_effort: str | None = "low"):
        """
        Args:
            api_key: OpenAI API 키. None이면 환경변수에서 로드.
            model: 사용할 모델명 (gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-4o …)
            reasoning_effort: gpt-5 계열 전용. "none" | "low" | "medium" | "high".
                None 이면 보내지 않는다(서버 기본값).
        """
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError(
                "OPENAI_API_KEY가 설정되지 않았습니다. "
                ".env 파일 또는 환경변수를 확인하세요."
            )
        self._model = resolve(model, "openai", logger.warning)
        self._reasoning_effort = reasoning_effort

        self._client = openai.OpenAI(api_key=self._api_key)
        logger.info(f"OpenAI Vision 클라이언트 초기화 (model={self._model})")

    @property
    def model(self) -> str:
        return self._model

    def analyze_image(
        self,
        img: np.ndarray,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        """이미지를 OpenAI Vision API로 분석한다."""
        return self.analyze_images(
            [img], system_prompt, user_prompt, max_tokens, temperature
        )

    def _request_kwargs(self, max_tokens: int, temperature: float) -> dict:
        """모델 세대에 맞는 요청 인자를 만든다."""
        kw = {"max_completion_tokens": max_tokens}
        if is_reasoning_openai(self._model):
            if self._reasoning_effort:
                kw["reasoning_effort"] = self._reasoning_effort
        else:
            kw["temperature"] = temperature
        return kw

    def analyze_images(
        self,
        images: list,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        """여러 이미지를 동시에 OpenAI Vision API로 분석한다.

        Args:
            images: BGR numpy 이미지 리스트
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            max_tokens: 최대 토큰 수 (gpt-5 계열은 추론 토큰을 포함한다)
            temperature: 온도 — gpt-4o 계열에만 전송

        Returns:
            API 응답 텍스트
        """
        content = []
        for i, img in enumerate(images):
            b64_image = to_base64(img, fmt=".jpg")
            logger.debug(f"이미지 {i+1}/{len(images)} 크기: {img.shape}, base64 길이: {len(b64_image)}")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64_image}",
                    "detail": "high",
                },
            })

        content.append({
            "type": "text",
            "text": user_prompt,
        })

        logger.info(f"OpenAI Vision API 호출 중... ({len(images)}장 이미지)")

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                **self._request_kwargs(max_tokens, temperature),
            )

            response_text = response.choices[0].message.content or ""
            logger.info(
                f"API 응답 수신 (tokens: input={response.usage.prompt_tokens}, "
                f"output={response.usage.completion_tokens})"
            )
            logger.debug(f"응답 내용: {response_text[:200]}...")
            return response_text

        except openai.APIError as e:
            logger.error(f"OpenAI API 오류: {e}")
            raise
        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}")
            raise
