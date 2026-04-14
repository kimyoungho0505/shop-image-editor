"""Grok (xAI) Vision API 클라이언트."""
import os

import cv2
import numpy as np
from loguru import logger

from ..utils.image_io import to_base64


class GrokVisionClient:
    """xAI Grok Vision API를 사용하여 이미지를 분석한다.

    OpenAI 호환 API 형식을 사용하며, base_url만 xAI 엔드포인트로 변경.
    """

    def __init__(self, api_key: str = None, model: str = "grok-4-fast-non-reasoning"):
        """
        Args:
            api_key: xAI API 키. None이면 환경변수에서 로드.
            model: 사용할 모델명 (grok-4-fast-non-reasoning, grok-3 등)
        """
        self._api_key = api_key or os.getenv("XAI_API_KEY")
        if not self._api_key:
            raise ValueError(
                "XAI_API_KEY가 설정되지 않았습니다. "
                ".env 파일 또는 환경변수를 확인하세요."
            )
        self._model = model

        import openai
        self._client = openai.OpenAI(
            api_key=self._api_key,
            base_url="https://api.x.ai/v1",
        )
        self._openai = openai
        logger.info(f"Grok Vision 클라이언트 초기화 (model={model})")

    def analyze_image(
        self,
        img: np.ndarray,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        """이미지를 Grok Vision API로 분석한다."""
        return self.analyze_images(
            [img], system_prompt, user_prompt, max_tokens, temperature
        )

    def analyze_images(
        self,
        images: list,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        """여러 이미지를 동시에 Grok Vision API로 분석한다.

        Args:
            images: BGR numpy 이미지 리스트
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            max_tokens: 최대 토큰 수
            temperature: 온도

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

        logger.info(f"Grok Vision API 호출 중... ({len(images)}장 이미지)")

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
            )

            response_text = response.choices[0].message.content
            logger.info(
                f"Grok API 응답 수신 (tokens: input={response.usage.prompt_tokens}, "
                f"output={response.usage.completion_tokens})"
            )
            logger.debug(f"응답 내용: {response_text[:200]}...")
            return response_text

        except self._openai.APIError as e:
            logger.error(f"Grok API 오류: {e}")
            raise
        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}")
            raise
