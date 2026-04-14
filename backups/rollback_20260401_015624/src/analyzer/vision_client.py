"""Claude Vision API 클라이언트."""
import os

import anthropic
import cv2
import numpy as np
from loguru import logger

from ..utils.image_io import to_base64


class VisionClient:
    """Claude Vision API를 사용하여 이미지를 분석한다."""

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        """
        Args:
            api_key: Anthropic API 키. None이면 환경변수에서 로드.
            model: 사용할 모델명
        """
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
                ".env 파일 또는 환경변수를 확인하세요."
            )
        self._model = model
        self._client = anthropic.Anthropic(api_key=self._api_key)
        logger.info(f"Vision 클라이언트 초기화 (model={model})")

    def analyze_image(
        self,
        img: np.ndarray,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        """이미지를 Claude Vision API로 분석한다."""
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
        """여러 이미지를 동시에 Claude Vision API로 분석한다.

        Args:
            images: BGR numpy 이미지 리스트
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            max_tokens: 최대 토큰 수
            temperature: 온도

        Returns:
            API 응답 텍스트
        """
        media_type = "image/jpeg"

        content = []
        for i, img in enumerate(images):
            b64_image = to_base64(img, fmt=".jpg")
            logger.debug(f"이미지 {i+1}/{len(images)} 크기: {img.shape}, base64 길이: {len(b64_image)}")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64_image,
                },
            })

        content.append({
            "type": "text",
            "text": user_prompt,
        })

        logger.info(f"Claude Vision API 호출 중... ({len(images)}장 이미지)")

        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": content}],
            )

            response_text = message.content[0].text
            logger.info(
                f"API 응답 수신 (tokens: input={message.usage.input_tokens}, "
                f"output={message.usage.output_tokens})"
            )
            logger.debug(f"응답 내용: {response_text[:200]}...")
            return response_text

        except anthropic.APIError as e:
            logger.error(f"Claude API 오류: {e}")
            raise
        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}")
            raise
