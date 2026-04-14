"""카테고리 관리 모듈."""
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger


class CategoryManager:
    """카테고리별 여백 규칙을 관리한다."""

    def __init__(self, config_path: str = None):
        """
        Args:
            config_path: categories.yaml 경로
        """
        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent / "config" / "categories.yaml"
            )
        with open(config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f)

        self._categories = self._config.get("categories", {})
        self._default = self._config.get("default", {})
        logger.debug(f"카테고리 {len(self._categories)}개 로드됨")

    def list_categories(self) -> list:
        """사용 가능한 카테고리 이름 목록을 반환한다."""
        return list(self._categories.keys())

    def get_padding(self, category: str, base_size: int = 860) -> dict:
        """카테고리에 해당하는 여백(padding)을 반환한다.

        Args:
            category: 카테고리 이름
            base_size: 기준 사이즈 (860px)

        Returns:
            {"top": int, "bottom": int, "left": int, "right": int}
        """
        cat_config = self._categories.get(category, self._default)
        padding = cat_config.get("padding_860", self._default.get("padding_860"))
        if padding is None:
            logger.warning(f"카테고리 '{category}'의 여백 설정을 찾을 수 없어 기본값 사용")
            padding = {"top": 64, "bottom": 64, "left": 64, "right": 64}
        return padding

    def get_thumbnail_padding(self, category: str) -> dict:
        """카테고리의 썸네일 여백을 반환한다.

        Returns:
            {"top": int, "bottom": int, "left": int, "right": int}
        """
        cat_config = self._categories.get(category, self._default)
        padding = cat_config.get(
            "thumbnail_padding", self._default.get("thumbnail_padding")
        )
        if padding is None:
            logger.warning(f"카테고리 '{category}'의 썸네일 여백 설정을 찾을 수 없어 기본값 사용")
            padding = {"top": 359, "bottom": 359, "left": 148, "right": 148}
        return padding

    def get_scaled_padding(self, category: str, target_size: int) -> dict:
        """target_size에 맞게 스케일링된 여백을 반환한다.

        860px 기준 여백을 target_size에 비례하여 스케일링.

        Args:
            category: 카테고리 이름
            target_size: 목표 크기 (px)

        Returns:
            스케일링된 padding dict
        """
        base_padding = self.get_padding(category, 860)
        scale = target_size / 860.0
        return {
            key: int(round(val * scale))
            for key, val in base_padding.items()
        }

    def get_display_name(self, category: str) -> str:
        """카테고리의 표시명을 반환한다."""
        cat_config = self._categories.get(category, {})
        return cat_config.get("display_name", category)
