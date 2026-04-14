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

    # ── Deliberation 6단계 회의 프롬프트 ──

    def _delib(self, key: str) -> str:
        return self._prompts["deliberation"][key].strip()

    # 1단계: 의견 발의
    def build_phase1_system(self) -> str:
        return self._delib("phase1_system")

    def build_phase1_prompt(self, current_params: dict) -> str:
        template = self._prompts["deliberation"]["phase1_user"]
        params_str = json.dumps(current_params, indent=2, ensure_ascii=False)
        return template.replace("{current_params}", params_str)

    # 2단계: 상호 검토 (동의/반박)
    def build_phase2_system(self) -> str:
        return self._delib("phase2_system")

    def build_phase2_prompt(self, all_evaluations: str) -> str:
        template = self._prompts["deliberation"]["phase2_user"]
        return template.replace("{all_evaluations}", all_evaluations)

    # 3단계: 문제점 인식
    def build_phase3_system(self) -> str:
        return self._delib("phase3_system")

    def build_phase3_prompt(self, all_evaluations: str) -> str:
        template = self._prompts["deliberation"]["phase3_user"]
        return template.replace("{all_evaluations}", all_evaluations)

    # 4단계: 해결방법 제시
    def build_phase4_system(self) -> str:
        return self._delib("phase4_system")

    def build_phase4_prompt(self, problem_summary: str,
                            iteration_count: int = 0) -> str:
        template = self._prompts["deliberation"]["phase4_user"]
        deep = ""
        if iteration_count >= 5:
            deep = self._prompts["deliberation"]["deep_explore_instruction"]
        return (template
                .replace("{problem_summary}", problem_summary)
                .replace("{deep_explore_instruction}", deep))

    # 5단계: 해결방법 토론
    def build_phase5_system(self) -> str:
        return self._delib("phase5_system")

    def build_phase5_prompt(self, all_solutions: str, round_num: int) -> str:
        template = self._prompts["deliberation"]["phase5_user"]
        return (template
                .replace("{all_solutions}", all_solutions)
                .replace("{round_num}", str(round_num)))

    # 6단계: 최종 결정
    def build_phase6_system(self) -> str:
        return self._delib("phase6_system")

    def build_phase6_prompt(self, final_evaluations: str,
                            total_rounds: int,
                            current_params: dict = None) -> str:
        template = self._prompts["deliberation"]["phase6_user"]
        params_str = json.dumps(current_params or {}, indent=2, ensure_ascii=False)
        return (template
                .replace("{current_params}", params_str)
                .replace("{final_evaluations}", final_evaluations)
                .replace("{total_rounds}", str(total_rounds)))
