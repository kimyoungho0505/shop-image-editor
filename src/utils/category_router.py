"""카테고리 우선순위 기반 라우팅 (v2 스키마).

Vision 분석 결과(image_type, detected_category, has_mannequin, is_label_cut,
barcode_number)를 '복합 카테고리'로 매핑하고, 우선순위 규칙에 따라
처리 플래그(nukki/shadow/enhance) 또는 '제외'를 결정한다.

스키마 v2 (routing_rules.yaml):
    version: 2
    fixed_top:        # 항상 최우선 (순서 불변)
      - {category: barcode, action: exclude}
      - {category: label,   action: exclude}
    priority_rules:   # 사용자 정렬 (순서 = 우선순위)
      - {category: jewelry, nukki: true, shadow: true, enhance: true,
         shooting_angle: any, background_type: any}
      - ...
    fixed_bottom:
      - {category: default, nukki: true, shadow: true, enhance: true}
"""
from __future__ import annotations


# 복합 카테고리 정의 — (키, 한글 표시명, 기본 처리)
COMPOSITE_CATEGORIES = [
    ("barcode",            "바코드 감지",   None),               # 제외 (고정)
    ("label",              "라벨/바코드컷", None),               # 제외 (고정)
    ("jewelry",            "주얼리",        (True,  True,  True)),
    ("clothing_mannequin", "의류-마네킹",   (True,  False, True)),
    ("clothing_model",     "의류-모델",     (False, False, True)),
    ("clothing_flat",      "의류-평면",     (True,  False, True)),
    ("bag_acc",            "가방/잡화",     (True,  True,  True)),
    ("detail",             "디테일컷",      (True,  False, True)),
    ("package",            "패키지",        (True,  False, True)),
    ("default",            "기본 (폴백)",   (True,  True,  True)),  # 최후 (고정)
]

# 표시명 조회용
CATEGORY_LABELS = {k: label for k, label, _ in COMPOSITE_CATEGORIES}

# 자동 감지 조건 설명 (고정 상단 카드에 표시)
CATEGORY_DETECT_DESC = {
    "barcode": "9로 시작하는 13자리 EAN-13 바코드가 감지된 이미지",
    "label":   "제품 본체 없이 라벨/태그/바코드만 찍힌 컷으로 감지된 이미지",
}

# 사용자가 우선순위로 정렬 가능한 카테고리 (고정 상/하단 제외)
SORTABLE_CATEGORIES = [
    k for k, _, _ in COMPOSITE_CATEGORIES
    if k not in ("barcode", "label", "default")
]


def category_label(key: str, custom_categories: list = None) -> str:
    """카테고리 키 → 한글 표시명 (빌트인 + 커스텀)."""
    if key in CATEGORY_LABELS:
        return CATEGORY_LABELS[key]
    for c in (custom_categories or []):
        if c.get("key") == key:
            return c.get("label", key)
    return key


def slugify_category(label: str, existing_keys: set = None) -> str:
    """카테고리 한글 이름 → 고유 키 생성 (custom_ 접두)."""
    import re
    base = re.sub(r"[^a-z0-9]+", "_", (label or "").strip().lower()).strip("_")
    if not base:
        base = "cat"
    key = f"custom_{base}"
    existing = existing_keys or set()
    if key not in existing:
        return key
    i = 2
    while f"{key}_{i}" in existing:
        i += 1
    return f"{key}_{i}"


def map_to_category(image_type: str = "", detected_category: str = "",
                    has_mannequin: bool = False, is_label_cut: bool = False,
                    barcode_number: str = "",
                    custom_categories: list = None) -> str:
    """Vision 결과 → 복합 카테고리 키.

    우선순위:
      1. 9시작 13자리 바코드 → barcode
      2. 라벨컷 → label
      3. 주얼리 → jewelry
      4. 착용샷(worn) + 마네킹 → clothing_mannequin
      5. 착용샷(worn) + 사람모델 → clothing_model
      6. 의류 카테고리 → clothing_flat
      7. 가방/잡화 → bag_acc
      8. 디테일 → detail
      9. 패키지 → package
      10. 그 외 → default
    """
    image_type = (image_type or "").lower()
    detected_category = (detected_category or "").lower()

    bc = (barcode_number or "").strip()
    if bc.startswith("9") and len(bc) == 13:
        return "barcode"
    if is_label_cut:
        return "label"

    # 사용자 정의 커스텀 카테고리 (Vision detected_category 값으로 매칭)
    # 빌트인보다 우선 — 사용자가 명시한 세부 분류가 더 구체적
    for c in (custom_categories or []):
        match_val = str(c.get("match_detected_category", "")).strip().lower()
        if match_val and detected_category == match_val:
            return c.get("key", "")

    if detected_category == "jewelry":
        return "jewelry"
    if image_type == "worn":
        return "clothing_mannequin" if has_mannequin else "clothing_model"
    if detected_category == "clothing":
        return "clothing_flat"
    if detected_category in ("bag", "accessory", "accessories", "wallet"):
        return "bag_acc"
    if image_type == "detail":
        return "detail"
    if image_type == "package":
        return "package"
    return "default"


def default_rules_v2() -> dict:
    """기본 v2 규칙셋."""
    priority = []
    for k, _, proc in COMPOSITE_CATEGORIES:
        if k in ("barcode", "label", "default"):
            continue
        n, s, e = proc
        priority.append({
            "category": k, "nukki": n, "shadow": s, "enhance": e,
            "shooting_angle": "any", "background_type": "any",
        })
    return {
        "version": 2,
        "fixed_top": [
            {"category": "barcode", "action": "exclude"},
            {"category": "label", "action": "exclude"},
        ],
        "priority_rules": priority,
        "fixed_bottom": [
            {"category": "default", "nukki": True, "shadow": True, "enhance": True},
        ],
    }


def migrate_v1_to_v2(v1_data: dict) -> dict:
    """v1 (rules: [...]) → v2 스키마 변환.

    v1 규칙의 image_type/조건을 복합 카테고리로 best-effort 매핑.
    매핑 불가하거나 비면 기본 v2 반환.
    """
    if not isinstance(v1_data, dict):
        return default_rules_v2()
    if v1_data.get("version") == 2:
        return v1_data  # 이미 v2
    rules = v1_data.get("rules")
    if not rules:
        return default_rules_v2()

    # v1 image_type → 복합 카테고리 매핑
    it_map = {
        "jewelry": "jewelry",
        "mannequin": "clothing_mannequin",
        "model": "clothing_model",
        "clothing": "clothing_flat",
        "detail": "detail",
        "package": "package",
        "full": "default",
        "worn": "clothing_model",
    }
    priority = []
    seen = set()
    for r in rules:
        cond = r.get("conditions", {}) or {}
        proc = r.get("processing", {}) or {}
        # 라벨컷 전용 규칙은 고정 상단으로 흡수 (스킵)
        if cond.get("is_label_cut") is True and not cond.get("image_type"):
            continue
        it = cond.get("image_type")
        cat = it_map.get(it) if it else None
        if cat is None or cat in seen:
            continue
        seen.add(cat)
        priority.append({
            "category": cat,
            "nukki": bool(proc.get("nukki", True)),
            "shadow": bool(proc.get("shadow", False)),
            "enhance": bool(proc.get("enhance", True)),
            "shooting_angle": cond.get("shooting_angle", "any"),
            "background_type": cond.get("background_type", "any"),
        })

    if not priority:
        return default_rules_v2()

    base = default_rules_v2()
    base["priority_rules"] = priority
    return base


def evaluate_v2(rules_v2: dict, category: str,
                shooting_angle: str = "", background_type: str = "") -> dict:
    """복합 카테고리 → 처리 결정.

    Returns:
        {"exclude": True}  또는
        {"nukki": bool, "shadow": bool, "enhance": bool, "matched": category}
    """
    if not isinstance(rules_v2, dict):
        rules_v2 = default_rules_v2()

    # 1. 고정 상단 (barcode/label) — 제외 또는 사용자 지정 처리
    for r in rules_v2.get("fixed_top", []):
        if r.get("category") != category:
            continue
        if r.get("action", "exclude") == "exclude":
            return {"exclude": True, "matched": category}
        return {
            "exclude": False,
            "nukki": bool(r.get("nukki", True)),
            "shadow": bool(r.get("shadow", False)),
            "enhance": bool(r.get("enhance", True)),
            "matched": category,
        }

    # 2. 우선순위 규칙 (위에서부터)
    for r in rules_v2.get("priority_rules", []):
        if r.get("category") != category:
            continue
        # 세부 조건 필터
        sa = r.get("shooting_angle", "any")
        if sa not in ("any", "", None) and sa != shooting_angle:
            continue
        bt = r.get("background_type", "any")
        if bt not in ("any", "", None) and bt != background_type:
            continue
        return {
            "exclude": False,
            "nukki": bool(r.get("nukki", True)),
            "shadow": bool(r.get("shadow", False)),
            "enhance": bool(r.get("enhance", True)),
            "matched": category,
        }

    # 3. 고정 하단 (default 폴백)
    for r in rules_v2.get("fixed_bottom", []):
        return {
            "exclude": False,
            "nukki": bool(r.get("nukki", True)),
            "shadow": bool(r.get("shadow", True)),
            "enhance": bool(r.get("enhance", True)),
            "matched": "default",
        }

    # 폴백도 없으면 기본 처리
    return {"exclude": False, "nukki": True, "shadow": True,
            "enhance": True, "matched": "default"}
