"""Photoroom API 클라이언트."""
import os
import random
import time

import requests
from loguru import logger
from typing import Optional


class PhotoroomClient:
    """Photoroom API를 통한 배경 제거, 센터링, 그림자 생성."""

    API_URL = "https://image-api.photoroom.com/v2/edit"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("PHOTOROOM_API_KEY", "")
        if not self.api_key:
            logger.warning("PHOTOROOM_API_KEY가 설정되지 않았습니다")

    def _call_api(self, image_bytes: bytes, params: dict) -> bytes:
        """Photoroom API 호출하여 처리된 이미지 바이트를 반환."""
        headers = {"x-api-key": self.api_key}

        logger.info(f"Photoroom API 호출 중... (파라미터: {params})")

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            files = {"imageFile": ("image.jpg", image_bytes, "image/jpeg")}

            response = requests.post(
                self.API_URL,
                headers=headers,
                files=files,
                data=params,
                timeout=60,
            )

            if response.status_code == 200:
                break

            if response.status_code in (429, 500, 502, 503) and attempt < max_retries:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Photoroom API {response.status_code} 오류, {wait:.1f}초 후 재시도 ({attempt}/{max_retries})")
                time.sleep(wait)
                continue

            error_msg = f"Photoroom API 오류: {response.status_code} - {response.text[:200]}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        logger.info(f"Photoroom API 완료 ({len(response.content)} bytes)")
        return response.content

    def _build_params(self, config: dict, output_size: str) -> dict:
        """settings.yaml의 config를 Photoroom API 파라미터로 변환.

        센터링/패딩은 후처리에서 담당하므로 Photoroom에는 전달하지 않는다.
        배경색도 후처리에서 흰 캔버스로 합성하므로 투명 PNG로 받는다.
        """
        # outputSize: settings.yaml 값 우선, 없으면 인자값
        cfg_output_size = config.get("outputSize", output_size)

        params = {
            "removeBackground": "true",
            "outputSize": str(cfg_output_size),
            "padding": "0",
            "scaling": "fit",
            "referenceBox": "originalImage",
            "export.format": config.get("export.format", "png"),
        }

        # 배경색 (config에 있으면 적용)
        bg_color = config.get("background.color")

        # 그림자 모드 (설정에 있으면 적용)
        shadow_mode = config.get("shadow.mode")
        if shadow_mode:
            params["shadow.mode"] = str(shadow_mode)
            params["background.color"] = bg_color or "FFFFFF"
            shadow_opacity = config.get("shadow.opacity")
            if shadow_opacity is not None:
                params["shadow.opacity"] = str(shadow_opacity)
        elif bg_color:
            # 그림자 없이 배경색 지정 (jpg 포맷일 때 transparent 충돌 방지)
            params["background.color"] = bg_color

        return params

    @staticmethod
    def should_process(image_type: str, background: str) -> bool:
        """Photoroom 처리 여부를 판단한다."""
        if image_type == "full":
            return True
        if image_type == "package":
            return True
        if image_type == "detail":
            return True
        # 착용샷(worn): 배경이 완전한 흰색이 아닐 수 있으므로 누끼 처리
        if image_type == "worn":
            return True
        return False

    def crop_to_aspect(
        self,
        image_bytes: bytes,
        output_size: str = "1500x2250",
        padding: float = 0.05,
        keep_background: bool = True,
        background_color: str = "FFFFFF",
    ) -> bytes:
        """Photoroom v2/edit으로 정확한 비율 크롭/리사이즈.

        제품을 자동 감지해 outputSize 비율 안에 fit하며 padding만큼 여유를 둠.
        scaling=fit이라 콘텐츠 잘림 없음. 배경은 keep_background 옵션 따라 처리.

        Args:
            image_bytes: 입력 이미지 (이미 누끼 처리된 흰배경 제품이 권장)
            output_size: 출력 사이즈 (예: "1500x2250")
            padding: 제품 주변 여유 비율 (0~1, 기본 0.05 = 5%)
            keep_background: True면 흰배경 유지, False면 누끼만 추출
            background_color: 흰배경 색 (HEX, 기본 FFFFFF)

        Returns:
            처리된 이미지 bytes (JPEG)

        Raises:
            RuntimeError: API 오류 (402 포함)
        """
        params = {
            "outputSize": str(output_size),
            "padding": str(max(0.0, min(1.0, float(padding)))),
            "scaling": "fit",
            "referenceBox": "subjectBox",
            "removeBackground": "false" if keep_background else "true",
            "background.color": background_color,
            "export.format": "jpg",
        }
        logger.info(
            f"Photoroom crop_to_aspect: outputSize={output_size}, "
            f"padding={padding}, scaling=fit")
        return self._call_api(image_bytes, params)

    def process(self, image_bytes: bytes, image_type: str, background: str,
                output_size: str = "1000x1000",
                config: Optional[dict] = None) -> Optional[bytes]:
        """이미지 유형에 따라 적절한 처리를 수행한다.

        Args:
            config: settings.yaml에서 읽은 photoroom 설정 dict
        Returns:
            처리된 이미지 바이트, 또는 스킵 시 None
        """
        if not self.should_process(image_type, background):
            logger.info(f"Photoroom 처리 스킵 (유형: {image_type}, 배경: {background})")
            return None

        if config is None:
            config = {}

        params = self._build_params(config, output_size)
        logger.info(f"Photoroom 처리 (유형: {image_type}, 배경: {background})")
        return self._call_api(image_bytes, params)
