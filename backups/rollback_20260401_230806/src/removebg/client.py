"""Remove.bg API 클라이언트."""
import os
import requests
from loguru import logger
from typing import Optional


class RemoveBgClient:
    """Remove.bg API를 통한 배경 제거."""

    API_URL = "https://api.remove.bg/v1.0/removebg"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("REMOVEBG_API_KEY", "")
        if not self.api_key:
            logger.warning("REMOVEBG_API_KEY가 설정되지 않았습니다")

    def _call_api(self, image_bytes: bytes, params: dict) -> bytes:
        """Remove.bg API 호출하여 처리된 이미지 바이트를 반환."""
        headers = {"X-Api-Key": self.api_key}
        files = {"image_file": ("image.jpg", image_bytes, "image/jpeg")}

        logger.info(f"Remove.bg API 호출 중... (파라미터: {params})")

        response = requests.post(
            self.API_URL,
            headers=headers,
            files=files,
            data=params,
            timeout=60,
        )

        if response.status_code != 200:
            error_msg = f"Remove.bg API 오류: {response.status_code} - {response.text[:200]}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        logger.info(f"Remove.bg API 완료 ({len(response.content)} bytes)")
        return response.content

    def _build_params(self, config: dict, output_size: str) -> dict:
        """settings.yaml의 config를 Remove.bg API 파라미터로 변환."""
        params = {
            "size": config.get("size", "auto"),
            "type": config.get("type", "product"),
            "format": config.get("format", "png"),
        }

        bg_color = config.get("bg_color")
        if bg_color:
            params["bg_color"] = bg_color

        return params

    @staticmethod
    def should_process(image_type: str, background: str) -> bool:
        """Remove.bg 처리 여부를 판단한다."""
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
            config: settings.yaml에서 읽은 removebg 설정 dict
        Returns:
            처리된 이미지 바이트, 또는 스킵 시 None
        """
        if not self.should_process(image_type, background):
            logger.info(f"Remove.bg 처리 스킵 (유형: {image_type}, 배경: {background})")
            return None

        if config is None:
            config = {}

        params = self._build_params(config, output_size)
        logger.info(f"Remove.bg 처리 (유형: {image_type}, 배경: {background})")
        return self._call_api(image_bytes, params)
