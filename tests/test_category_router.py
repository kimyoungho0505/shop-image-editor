"""category_router 단위 테스트."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.utils.category_router import (
    map_to_category, default_rules_v2, migrate_v1_to_v2, evaluate_v2,
)


class TestMapToCategory:
    def test_barcode_priority_over_all(self):
        # 바코드는 다른 조건 무시하고 최우선
        assert map_to_category(
            image_type="full", detected_category="jewelry",
            barcode_number="9876543210123") == "barcode"

    def test_label_cut(self):
        assert map_to_category(is_label_cut=True) == "label"

    def test_jewelry(self):
        assert map_to_category(detected_category="jewelry") == "jewelry"

    def test_clothing_mannequin(self):
        assert map_to_category(
            image_type="worn", has_mannequin=True) == "clothing_mannequin"

    def test_clothing_model(self):
        assert map_to_category(
            image_type="worn", has_mannequin=False) == "clothing_model"

    def test_clothing_flat(self):
        assert map_to_category(detected_category="clothing") == "clothing_flat"

    def test_bag_acc(self):
        assert map_to_category(detected_category="bag") == "bag_acc"
        assert map_to_category(detected_category="wallet") == "bag_acc"

    def test_detail(self):
        assert map_to_category(image_type="detail") == "detail"

    def test_package(self):
        assert map_to_category(image_type="package") == "package"

    def test_default_fallback(self):
        assert map_to_category(image_type="full") == "default"

    def test_barcode_must_start_with_9_and_13_digits(self):
        # 1로 시작하면 일반
        assert map_to_category(
            image_type="full", barcode_number="1234567890123") == "default"
        # 12자리면 일반
        assert map_to_category(
            image_type="full", barcode_number="987654321012") == "default"


class TestDefaultRulesV2:
    def test_structure(self):
        r = default_rules_v2()
        assert r["version"] == 2
        assert any(x["category"] == "barcode" for x in r["fixed_top"])
        assert any(x["category"] == "label" for x in r["fixed_top"])
        assert any(x["category"] == "default" for x in r["fixed_bottom"])
        cats = [x["category"] for x in r["priority_rules"]]
        assert "jewelry" in cats
        assert "barcode" not in cats  # 고정 상단에만
        assert "default" not in cats  # 고정 하단에만


class TestMigrateV1ToV2:
    def test_v2_passthrough(self):
        v2 = default_rules_v2()
        assert migrate_v1_to_v2(v2) is v2

    def test_empty_returns_default(self):
        assert migrate_v1_to_v2({})["version"] == 2
        assert migrate_v1_to_v2({"rules": []})["version"] == 2

    def test_v1_jewelry_migrated(self):
        v1 = {"rules": [
            {"conditions": {"image_type": "jewelry"},
             "processing": {"nukki": True, "shadow": True, "enhance": True}},
        ]}
        v2 = migrate_v1_to_v2(v1)
        cats = [x["category"] for x in v2["priority_rules"]]
        assert "jewelry" in cats

    def test_v1_label_only_rule_absorbed(self):
        # 라벨컷 전용 규칙은 고정 상단으로 흡수(priority에서 제외)
        v1 = {"rules": [
            {"conditions": {"is_label_cut": True},
             "processing": {"nukki": False, "shadow": False, "enhance": False}},
            {"conditions": {"image_type": "detail"},
             "processing": {"nukki": True, "shadow": False, "enhance": True}},
        ]}
        v2 = migrate_v1_to_v2(v1)
        cats = [x["category"] for x in v2["priority_rules"]]
        assert "detail" in cats
        # 라벨은 fixed_top에 존재
        assert any(x["category"] == "label" for x in v2["fixed_top"])


class TestEvaluateV2:
    def test_barcode_excluded(self):
        r = default_rules_v2()
        res = evaluate_v2(r, "barcode")
        assert res["exclude"] is True

    def test_label_excluded(self):
        r = default_rules_v2()
        res = evaluate_v2(r, "label")
        assert res["exclude"] is True

    def test_jewelry_processing(self):
        r = default_rules_v2()
        res = evaluate_v2(r, "jewelry")
        assert res["exclude"] is False
        assert res["nukki"] is True
        assert res["shadow"] is True
        assert res["enhance"] is True

    def test_clothing_model_no_nukki(self):
        r = default_rules_v2()
        res = evaluate_v2(r, "clothing_model")
        assert res["nukki"] is False
        assert res["enhance"] is True

    def test_unknown_category_falls_to_default(self):
        r = default_rules_v2()
        res = evaluate_v2(r, "default")
        assert res["exclude"] is False
        assert res["matched"] == "default"

    def test_shooting_angle_filter(self):
        # 특정 각도 조건이 있으면 불일치 시 폴백
        r = {
            "version": 2, "fixed_top": [],
            "priority_rules": [
                {"category": "detail", "nukki": False, "shadow": False,
                 "enhance": True, "shooting_angle": "top_down",
                 "background_type": "any"},
            ],
            "fixed_bottom": [
                {"category": "default", "nukki": True, "shadow": True,
                 "enhance": True}],
        }
        # top_down 일치 → detail 규칙 적용
        res = evaluate_v2(r, "detail", shooting_angle="top_down")
        assert res["nukki"] is False and res["matched"] == "detail"
        # front → 불일치 → default 폴백
        res2 = evaluate_v2(r, "detail", shooting_angle="front")
        assert res2["matched"] == "default"
