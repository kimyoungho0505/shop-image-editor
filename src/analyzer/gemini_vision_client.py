"""Google Gemini Vision API 클라이언트."""
import os
import time

import cv2
import numpy as np
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class GeminiVisionClient:
    """Google Gemini Vision API를 사용하여 이미지를 분석한다."""

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        """
        Args:
            api_key: Gemini API 키. None이면 환경변수에서 로드.
            model: 사용할 모델명
        """
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self._api_key:
            raise ValueError(
                "GEMINI_API_KEY가 설정되지 않았습니다. "
                ".env 파일 또는 환경변수를 확인하세요."
            )
        self._model = model

        from google import genai
        self._genai = genai
        self._client = genai.Client(api_key=self._api_key)
        logger.info(f"Gemini Vision 클라이언트 초기화 (model={model})")

    def _encode_image_bytes(self, img: np.ndarray, max_size: int = 1568) -> bytes:
        """BGR numpy 이미지를 JPEG bytes로 변환한다."""
        h, w = img.shape[:2]
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            logger.debug(f"API 전송용 리사이즈: {w}x{h} -> {new_w}x{new_h}")

        success, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not success:
            raise ValueError("이미지 JPEG 인코딩 실패")
        return buffer.tobytes()

    def analyze_image(
        self,
        img: np.ndarray,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        """이미지를 Gemini Vision API로 분석한다."""
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
        """여러 이미지를 동시에 Gemini Vision API로 분석한다.

        Args:
            images: BGR numpy 이미지 리스트
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            max_tokens: 최대 토큰 수
            temperature: 온도

        Returns:
            API 응답 텍스트
        """
        from google.genai import types

        contents = []
        for i, img in enumerate(images):
            img_bytes = self._encode_image_bytes(img)
            logger.debug(f"이미지 {i+1}/{len(images)} 크기: {img.shape}, bytes 길이: {len(img_bytes)}")
            contents.append(
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
            )

        contents.append(user_prompt)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

        logger.info(f"Gemini Vision API 호출 중... ({len(images)}장 이미지)")

        response = self._call_api_with_retry(contents, config)

        response_text = response.text

        # MAX_TOKENS로 잘린 경우: 부분 텍스트라도 추출 시도
        finish_reason_val = None
        if response.candidates and response.candidates[0].finish_reason:
            finish_reason_val = response.candidates[0].finish_reason

        if response_text is None:
            # 부분 응답 추출 시도
            partial_text = None
            if response.candidates and response.candidates[0].content:
                parts = response.candidates[0].content.parts
                if parts:
                    partial_text = "".join(
                        p.text for p in parts if hasattr(p, "text") and p.text)
            if partial_text:
                logger.warning(
                    f"Gemini 응답이 잘림 (reason: {finish_reason_val}), "
                    f"부분 응답 {len(partial_text)}자 사용")
                response_text = partial_text
            else:
                block_reason = ""
                if finish_reason_val:
                    block_reason = f" (reason: {finish_reason_val})"
                logger.error(f"Gemini 응답이 비어있음{block_reason}")
                raise ValueError(f"Gemini API가 빈 응답을 반환했습니다{block_reason}")

        usage = response.usage_metadata
        finish_reason = ""
        if response.candidates and response.candidates[0].finish_reason:
            finish_reason = f", finish={response.candidates[0].finish_reason.name}"
        logger.info(
            f"API 응답 수신 (tokens: input={usage.prompt_token_count}, "
            f"output={usage.candidates_token_count}{finish_reason})"
        )
        logger.debug(f"응답 내용: {response_text[:200]}...")
        return response_text

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type(Exception),
        before_sleep=lambda retry_state: logger.warning(
            f"Gemini API 재시도 {retry_state.attempt_number}/5 "
            f"({retry_state.outcome.exception().__class__.__name__}), "
            f"대기 후 재시도..."
        ),
        reraise=True,
    )
    def _call_api_with_retry(self, contents, config):
        """503 등 서버 에러 시 자동 재시도."""
        return self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )
