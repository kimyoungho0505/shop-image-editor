"""Claude API 응답 파서."""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from loguru import logger


@dataclass
class EditInstruction:
    """이미지 분류 결과 데이터클래스."""

    image_type: str = "full"  # full, detail, worn, package
    background: str = "clean"  # clean, complex, none
    detected_category: str = ""
    detected_category_display: str = ""
    subject_position: str = "center"
    is_detail_cut: bool = False
    detail_focus_area: Optional[dict] = None
    shooting_angle: str = "front"  # front, top_down, side, detail, held, worn
    is_full_body: Optional[bool] = None  # worn일 때만: 전신(발 포함) 여부
    floor_visible: bool = True
    needs_shadow: bool = True
    shadow_direction: Optional[str] = None
    shadow_confidence: float = 0.5
    shadow_params: Optional[dict] = None
    has_human_hand: bool = False
    hand_region: Optional[dict] = None
    product_only_region: Optional[dict] = None
    has_mannequin: bool = False
    mannequin_position: str = "none"  # "bottom" | "full" | "none"
    enhance_params: Optional[dict] = None
    photoroom_params: Optional[dict] = None
    confidence: float = 0.0
    notes: str = ""
    is_label_cut: bool = False  # 바코드/모델명/태그 확대 컷 → 누끼·보정 불필요

    def summary(self) -> str:
        parts = [f"유형: {self.image_type}", f"배경: {self.background}"]
        if self.detected_category:
            parts.append(f"카테고리: {self.detected_category_display or self.detected_category}")
        if self.is_detail_cut and self.detail_focus_area:
            parts.append("포커스영역: 있음")
        return " | ".join(parts)


class ResultParser:
    """Claude Vision API 응답에서 EditInstruction을 추출한다."""

    def parse(self, response_text: str) -> EditInstruction:
        """API 응답 텍스트를 파싱하여 EditInstruction을 생성한다.

        Args:
            response_text: Claude API 응답 텍스트

        Returns:
            EditInstruction 인스턴스
        """
        json_data = self._extract_json(response_text)
        if json_data is None:
            logger.warning("JSON 파싱 실패, 기본 EditInstruction 반환")
            return EditInstruction(notes="JSON 파싱 실패")

        return self._to_instruction(json_data)

    def _extract_json(self, text: str) -> Optional[dict]:
        """텍스트에서 JSON 객체를 추출한다."""
        # 방법 1: 전체를 JSON으로 파싱 시도
        try:
            result = json.loads(text.strip())
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                # Gemini 등이 배열로 응답하는 경우 첫 번째 dict 사용
                for item in result:
                    if isinstance(item, dict):
                        return item
        except json.JSONDecodeError:
            pass

        # 방법 2: ```json ... ``` 코드 블록에서 추출
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 방법 3: 첫 번째 { ... } 블록 추출
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # 방법 4: 잘린 JSON 복구 시도 (max_tokens 초과로 끊긴 경우)
        match = re.search(r"\{.*", text, re.DOTALL)
        if match:
            partial = match.group(0).rstrip()
            # 닫히지 않은 중괄호 수만큼 } 추가
            open_count = partial.count("{") - partial.count("}")
            if open_count > 0:
                # 마지막 완전한 필드까지 자르기 (쉼표 또는 값 뒤)
                last_good = max(partial.rfind(","), partial.rfind("}"),
                                partial.rfind("null"), partial.rfind("false"),
                                partial.rfind("true"))
                if last_good > 0:
                    partial = partial[:last_good + 1].rstrip(",")
                partial += "}" * open_count
                try:
                    result = json.loads(partial)
                    logger.warning(f"잘린 JSON 복구 성공 (필드 일부 누락 가능)")
                    return result
                except json.JSONDecodeError:
                    pass

        logger.error(f"JSON을 추출할 수 없습니다: {text[:200]}...")
        return None

    def _parse_focus_area(self, raw) -> Optional[dict]:
        """detail_focus_area 필드를 파싱하여 정규화된 좌표 dict를 반환한다."""
        if not isinstance(raw, dict):
            return None
        try:
            area = {
                "x": max(0.0, min(1.0, float(raw.get("x", 0)))),
                "y": max(0.0, min(1.0, float(raw.get("y", 0)))),
                "width": max(0.01, min(1.0, float(raw.get("width", 1.0)))),
                "height": max(0.01, min(1.0, float(raw.get("height", 1.0)))),
            }
            area["width"] = min(area["width"], 1.0 - area["x"])
            area["height"] = min(area["height"], 1.0 - area["y"])
            return area
        except (ValueError, TypeError):
            logger.warning("detail_focus_area 파싱 실패, 무시합니다")
            return None

    def _to_instruction(self, data: dict) -> EditInstruction:
        """JSON 딕셔너리를 EditInstruction으로 변환한다."""
        instruction = EditInstruction(
            image_type=str(data.get("image_type", "full")),
            background=str(data.get("background", "clean")),
            detected_category=str(data.get("category", data.get("detected_category", ""))),
            detected_category_display=str(data.get("category_display", data.get("detected_category_display", ""))),
            subject_position=str(data.get("subject_position", "center")),
            is_detail_cut=bool(data.get("is_detail_cut", False)),
            detail_focus_area=self._parse_focus_area(data.get("detail_focus_area")),
            shooting_angle=str(data.get("shooting_angle", "front")),
            is_full_body=data.get("is_full_body"),  # None if not worn
            floor_visible=bool(data.get("floor_visible", True)),
            needs_shadow=bool(data.get("needs_shadow", True)),
            shadow_direction=data.get("shadow_direction"),
            shadow_confidence=float(data.get("shadow_confidence", 0.5)),
            shadow_params=data.get("shadow_params") if isinstance(data.get("shadow_params"), dict) else None,
            has_human_hand=bool(data.get("has_human_hand", False)),
            hand_region=self._parse_focus_area(data.get("hand_region")),
            product_only_region=self._parse_focus_area(data.get("product_only_region")),
            has_mannequin=bool(data.get("has_mannequin", False)),
            mannequin_position=str(data.get("mannequin_position", "none")),
            enhance_params=data.get("enhance_params") if isinstance(data.get("enhance_params"), dict) else None,
            photoroom_params=data.get("photoroom_params") if isinstance(data.get("photoroom_params"), dict) else None,
            confidence=float(data.get("confidence", 0)),
            notes=str(data.get("notes", "")),
            is_label_cut=bool(data.get("is_label_cut", False)),
        )

        logger.info(f"분류 결과 파싱 완료: {instruction.summary()}")
        logger.debug(f"  확신도={instruction.confidence:.2f}")
        return instruction
