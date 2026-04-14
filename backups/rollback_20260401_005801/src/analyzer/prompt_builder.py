"""프롬프트 동적 생성 모듈."""
import json
from pathlib import Path

import yaml
from loguru import logger


class PromptBuilder:
    """prompts.yaml 템플릿을 기반으로 프롬프트를 생성한다."""

    def __init__(self, prompts_path: str = None):
        if prompts_path is None:
            prompts_path = str(
                Path(__file__).parent.parent.parent / "config" / "prompts.yaml"
            )
        with open(prompts_path, "r", encoding="utf-8") as f:
            self._prompts = yaml.safe_load(f)
        logger.debug("프롬프트 템플릿 로드 완료")

    def build_system_prompt(self) -> str:
        """시스템 프롬프트를 반환한다."""
        return self._prompts["analysis"]["system"].strip()

    def build_analysis_prompt(self, category_list: list = None) -> str:
        """이미지 분류용 사용자 프롬프트를 생성한다.

        Args:
            category_list: 사용 가능한 카테고리 목록 [{id, display_name}, ...]

        Returns:
            완성된 사용자 프롬프트 문자열
        """
        prompt = self._prompts["analysis"]["user_template"]

        if category_list:
            cat_lines = ", ".join(
                f'"{c["id"]}" ({c["display_name"]})' for c in category_list
            )
            prompt += (
                f"\n\nAvailable product categories: [{cat_lines}]. "
                f"Use one of these for the \"category\" field if applicable, "
                f"or suggest a new category ID (lowercase_snake_case) with a Korean display name."
            )

        logger.debug("분류 프롬프트 생성 완료")
        return prompt

    def build_refinement_system_prompt(self) -> str:
        """자동 수정 비교 평가용 시스템 프롬프트를 반환한다."""
        return self._prompts["refinement"]["system"].strip()

    def build_refinement_prompt(self, current_params: dict) -> str:
        """자동 수정 비교 평가용 사용자 프롬프트를 생성한다.

        Args:
            current_params: 현재 처리에 사용된 파라미터 dict

        Returns:
            완성된 비교 평가 프롬프트
        """
        template = self._prompts["refinement"]["user_template"]
        params_str = json.dumps(current_params, indent=2, ensure_ascii=False)
        prompt = template.replace("{current_params}", params_str)
        logger.debug("자동 수정 비교 프롬프트 생성 완료")
        return prompt

    # ── Deliberation (3-API 토론) 프롬프트 ──

    def build_deliberation_system_prompt(self) -> str:
        """3-API 토론용 초기 평가 시스템 프롬프트."""
        return self._prompts["deliberation"]["initial_system"].strip()

    def build_deliberation_initial_prompt(self, current_params: dict) -> str:
        """3-API 토론용 초기 독립 평가 사용자 프롬프트."""
        template = self._prompts["deliberation"]["initial_user_template"]
        params_str = json.dumps(current_params, indent=2, ensure_ascii=False)
        return template.replace("{current_params}", params_str)

    def build_discussion_system_prompt(self) -> str:
        """토론 라운드용 시스템 프롬프트."""
        return self._prompts["deliberation"]["discussion_system"].strip()

    def build_discussion_prompt(self, all_evaluations: str,
                                round_num: int, max_rounds: int) -> str:
        """토론 라운드용 사용자 프롬프트."""
        template = self._prompts["deliberation"]["discussion_user_template"]
        return (template
                .replace("{all_evaluations}", all_evaluations)
                .replace("{round_num}", str(round_num))
                .replace("{max_rounds}", str(max_rounds)))

    def build_consensus_system_prompt(self) -> str:
        """최종 합의 도출용 시스템 프롬프트."""
        return self._prompts["deliberation"]["consensus_system"].strip()

    def build_consensus_prompt(self, final_evaluations: str,
                               total_rounds: int) -> str:
        """최종 합의 도출용 사용자 프롬프트."""
        template = self._prompts["deliberation"]["consensus_user_template"]
        return (template
                .replace("{final_evaluations}", final_evaluations)
                .replace("{total_rounds}", str(total_rounds)))
