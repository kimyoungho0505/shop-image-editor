"""핵심 모듈 유닛 테스트."""
import json
import numpy as np
import pytest


class TestResultParser:
    """ResultParser 테스트."""

    def test_parse_valid_json(self):
        from src.analyzer.result_parser import ResultParser

        parser = ResultParser()
        response = json.dumps({
            "brightness": 10.5,
            "contrast": -5.0,
            "sharpness": 120,
            "rotation_angle": 1.2,
            "crop_suggestion": {"top": 0, "bottom": 0, "left": 0, "right": 0},
            "dust_spots": [{"x": 100, "y": 200, "radius": 5}],
            "overall_quality": 75,
            "needs_editing": True,
            "confidence": 0.85,
            "notes": "Slightly overexposed",
        })

        instruction = parser.parse(response)
        assert instruction.brightness == 10.5
        assert instruction.contrast == -5.0
        assert instruction.sharpness == 120
        assert instruction.rotation_angle == 1.2
        assert len(instruction.dust_spots) == 1
        assert instruction.needs_editing is True
        assert instruction.confidence == 0.85

    def test_parse_json_in_codeblock(self):
        from src.analyzer.result_parser import ResultParser

        parser = ResultParser()
        response = '```json\n{"brightness": 0, "contrast": 0, "sharpness": 100, "needs_editing": false, "confidence": 0.9, "overall_quality": 90, "notes": "good"}\n```'

        instruction = parser.parse(response)
        assert instruction.needs_editing is False
        assert instruction.overall_quality == 90

    def test_parse_invalid_json(self):
        from src.analyzer.result_parser import ResultParser

        parser = ResultParser()
        instruction = parser.parse("This is not JSON at all")
        assert instruction.needs_editing is False
        assert "파싱 실패" in instruction.notes


class TestImageAdjuster:
    """ImageAdjuster 테스트."""

    def test_no_adjustment(self):
        from src.editor.adjuster import ImageAdjuster

        adjuster = ImageAdjuster()
        img = np.full((100, 100, 3), 128, dtype=np.uint8)
        result = adjuster.apply_all(img, brightness=0, contrast=0, sharpness=100)
        np.testing.assert_array_equal(result, img)

    def test_brightness_increase(self):
        from src.editor.adjuster import ImageAdjuster

        adjuster = ImageAdjuster()
        img = np.full((100, 100, 3), 100, dtype=np.uint8)
        result = adjuster.adjust_brightness_contrast(img, brightness=50, contrast=0)
        assert result.mean() > img.mean()

    def test_sharpness_increase(self):
        from src.editor.adjuster import ImageAdjuster

        adjuster = ImageAdjuster()
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        result = adjuster.adjust_sharpness(img, sharpness=150)
        assert result.shape == img.shape


class TestImageCropper:
    """ImageCropper 테스트."""

    def test_fit_to_square(self):
        from src.editor.cropper import ImageCropper

        cropper = ImageCropper()
        img = np.full((200, 300, 3), 128, dtype=np.uint8)
        padding = {"top": 50, "bottom": 50, "left": 50, "right": 50}
        result = cropper.fit_to_square(img, 860, padding)
        assert result.shape == (860, 860, 3)

    def test_fit_to_thumbnail(self):
        from src.editor.cropper import ImageCropper

        cropper = ImageCropper()
        img = np.full((200, 300, 3), 128, dtype=np.uint8)
        padding = {"top": 359, "bottom": 359, "left": 148, "right": 148}
        result = cropper.fit_to_thumbnail(img, 1500, 2250, padding)
        assert result.shape == (2250, 1500, 3)


class TestImageAligner:
    """ImageAligner 테스트."""

    def test_no_rotation(self):
        from src.editor.aligner import ImageAligner

        aligner = ImageAligner()
        img = np.full((100, 100, 3), 128, dtype=np.uint8)
        result = aligner.rotate(img, 0.0)
        assert result.shape == img.shape

    def test_small_rotation(self):
        from src.editor.aligner import ImageAligner

        aligner = ImageAligner()
        img = np.full((100, 100, 3), 128, dtype=np.uint8)
        result = aligner.rotate(img, 5.0)
        assert result is not None
        assert result.shape[2] == 3


class TestCategoryManager:
    """CategoryManager 테스트."""

    def test_list_categories(self):
        from src.utils.category import CategoryManager

        mgr = CategoryManager()
        cats = mgr.list_categories()
        assert "accessories" in cats
        assert "shoes" in cats

    def test_get_padding(self):
        from src.utils.category import CategoryManager

        mgr = CategoryManager()
        padding = mgr.get_padding("accessories")
        assert padding["top"] == 64
        assert padding["left"] == 64

    def test_get_scaled_padding(self):
        from src.utils.category import CategoryManager

        mgr = CategoryManager()
        scaled = mgr.get_scaled_padding("accessories", 1500)
        # 1500/860 * 64 ≈ 112
        assert scaled["top"] > 64


class TestFileNamer:
    """FileNamer 테스트."""

    def test_sequential_names(self):
        from src.exporter.namer import FileNamer

        namer = FileNamer("100")
        assert namer.next_name() == "100_1.jpg"
        assert namer.next_name() == "100_2.jpg"
        assert namer.list_name() == "100_list.jpg"
        assert namer.thumbnail_name() == "100_thumb.jpg"

    def test_generate_names(self):
        from src.exporter.namer import FileNamer

        namer = FileNamer("200")
        names = namer.generate_names(3)
        assert len(names["images"]) == 3
        assert names["images"][0] == "200_1.jpg"
        assert names["list"] == "200_list.jpg"
        assert names["thumbnail"] == "200_thumb.jpg"


class TestImageOptimizer:
    """ImageOptimizer 테스트."""

    def test_optimize_small_image(self):
        from src.exporter.optimizer import ImageOptimizer

        optimizer = ImageOptimizer()
        img = np.full((100, 100, 3), 200, dtype=np.uint8)
        encoded, quality = optimizer.optimize_jpeg(img, max_size_kb=1024)
        assert len(encoded) < 1024 * 1024
        assert quality == 95  # 작은 이미지는 초기 품질 유지


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
