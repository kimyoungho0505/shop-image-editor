"""Photoroom API 클라이언트."""
import os
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
        files = {"imageFile": ("image.jpg", image_bytes, "image/jpeg")}

        logger.info(f"Photoroom API 호출 중... (파라미터: {params})")

        response = requests.post(
            self.API_URL,
            headers=headers,
            files=files,
            data=params,
            timeout=60,
        )

        if response.status_code != 200:
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

        # 그림자 모드 (설정에 있으면 적용)
        shadow_mode = config.get("shadow.mode")
        if shadow_mode:
            params["shadow.mode"] = str(shadow_mode)
            # 그림자가 있으면 흰 배경으로 합성 → alpha 후처리 불필요
            params["background.color"] = "FFFFFF"
            # 그림자 강도 (설정에 있으면 적용)
            shadow_opacity = config.get("shadow.opacity")
            if shadow_opacity is not None:
                params["shadow.opacity"] = str(shadow_opacity)

        return params

    @staticmethod
    def should_process(image_type: str, background: str) -> bool:
        """Photoroom 처리 여부를 판단한다."""
        if image_type == "full":
            return True
        if image_type == "package":
            return True
        if image_type == "detail" and background == "complex":
            return True
        # 착용샷(worn): 배경이 완전한 흰색이 아닐 수 있으므로 누끼 처리
        if image_type == "worn":
            return True
        return False

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
