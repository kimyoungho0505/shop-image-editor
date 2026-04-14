"""Claid.ai API 클라이언트."""
import json
import os

import requests
from loguru import logger
from typing import Optional


class ClaidClient:
    """Claid.ai API를 통한 이미지 보정, 업스케일, 리사이즈."""

    API_URL = "https://api.claid.ai/v1-beta1/image/edit/upload"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("CLAID_API_KEY", "")
        if not self.api_key:
            logger.warning("CLAID_API_KEY가 설정되지 않았습니다")

    def _call_api(self, image_bytes: bytes, operations: dict) -> bytes:
        """Claid.ai API 호출하여 보정된 이미지 바이트를 반환."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        files = {
            "file": ("image.png", image_bytes, "image/png"),
        }

        payload = {
            "data": json.dumps({"operations": operations}),
        }

        logger.info(f"Claid.ai API 호출 중... (operations: {operations})")

        response = requests.post(
            self.API_URL,
            headers=headers,
            files=files,
            data=payload,
            timeout=120,
        )

        if response.status_code != 200:
            error_msg = f"Claid.ai API 오류: {response.status_code} - {response.text[:200]}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            result = response.json()
            output_url = result.get("data", {}).get("output", {}).get("tmp_url")
            if output_url:
                logger.info("Claid.ai 결과 다운로드 중...")
                img_response = requests.get(output_url, timeout=60)
                if img_response.status_code == 200:
                    logger.info(f"Claid.ai 완료 ({len(img_response.content)} bytes)")
                    return img_response.content
                raise RuntimeError(f"Claid.ai 결과 다운로드 실패: {img_response.status_code}")
            raise RuntimeError(f"Claid.ai 응답에 output URL 없음: {result}")

        logger.info(f"Claid.ai 완료 ({len(response.content)} bytes)")
        return response.content

    def process(self, image_bytes: bytes, image_type: str,
                config: Optional[dict] = None,
                width: int = 1000, height: int = 1000) -> bytes:
        """이미지 유형에 따라 적절한 보정을 수행한다.

        Args:
            config: settings.yaml에서 읽은 claid 설정 dict
        """
        if config is None:
            config = {}

        hdr = int(config.get("hdr", 20))
        sharpness = int(config.get("sharpness", 15))
        upscale = config.get("upscale")

        operations = {}

        # 업스케일 (설정에 있을 때만)
        if upscale:
            operations["restorations"] = {"upscale": str(upscale)}

        # 색보정
        operations["adjustments"] = {
            "hdr": hdr,
            "sharpness": sharpness,
        }

        # 디테일/착용컷 리사이즈
        if image_type == "detail":
            fit = config.get("fit", "canvas")
            operations["resizing"] = {
                "width": config.get("width", width),
                "height": config.get("height", height),
                "fit": fit,
            }
            bg_color = config.get("background_color")
            if bg_color:
                operations["background"] = {"color": bg_color}
        elif image_type == "worn":
            fit = config.get("fit", "bounds")
            operations["resizing"] = {
                "width": config.get("width", width),
                "height": "auto",
                "fit": fit,
            }

        logger.info(f"Claid.ai 처리 (유형: {image_type}, hdr={hdr}, sharpness={sharpness})")
        return self._call_api(image_bytes, operations)
