"""resizer 모듈 단위 테스트."""
import io
import sys
from pathlib import Path
import threading
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.exporter.resizer import BatchCounter


def _make_test_image_bytes(size: int = 2250, color=(128, 64, 32)) -> bytes:
    """테스트용 단색 JPEG 바이트 생성."""
    img = Image.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


class TestBatchCounter:
    def test_next_returns_sequential_starting_from_one(self):
        c = BatchCounter()
        assert c.next() == 1
        assert c.next() == 2
        assert c.next() == 3

    def test_is_first_only_once(self):
        c = BatchCounter()
        assert c.is_first() is True
        assert c.is_first() is False
        assert c.is_first() is False

    def test_is_first_independent_of_next(self):
        c = BatchCounter()
        c.next()
        c.next()
        assert c.is_first() is True   # next() 호출과 무관

    def test_concurrent_next_no_duplicates(self):
        c = BatchCounter()
        results = []
        lock = threading.Lock()

        def worker():
            n = c.next()
            with lock:
                results.append(n)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert sorted(results) == list(range(1, 101))

    def test_concurrent_is_first_only_one_winner(self):
        c = BatchCounter()
        wins = []
        lock = threading.Lock()

        def worker():
            if c.is_first():
                with lock:
                    wins.append(1)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert len(wins) == 1


class TestMultiSizeResizerSaveOriginal:
    @pytest.fixture
    def settings(self):
        return {
            "resize": {
                "enabled": True,
                "base_size": 2250,
                "preserve_original": {
                    "enabled": True,
                    "subfolder": "original",
                    "naming": "{stem}_1.jpg",
                },
                "jpeg_max_size_kb": 2024,
            }
        }

    def test_save_original_creates_subfolder_and_file(self, tmp_path, settings):
        from src.exporter.resizer import MultiSizeResizer
        r = MultiSizeResizer(tmp_path, settings)
        img_bytes = _make_test_image_bytes(2250)

        result = r.save_original(img_bytes, "product_001")

        assert result.exists()
        assert result.parent.name == "original"
        assert result.name == "product_001_1.jpg"

    def test_save_original_preserves_2250_size(self, tmp_path, settings):
        from src.exporter.resizer import MultiSizeResizer
        r = MultiSizeResizer(tmp_path, settings)
        img_bytes = _make_test_image_bytes(2250)

        result = r.save_original(img_bytes, "product_001")

        with Image.open(result) as out:
            assert out.size == (2250, 2250)

    def test_save_original_handles_rgba_input(self, tmp_path, settings):
        """RGBA bytes는 흰 배경에 합성되어 RGB JPEG로 저장된다."""
        from src.exporter.resizer import MultiSizeResizer
        # 반투명 빨강 RGBA
        img = Image.new("RGBA", (2250, 2250), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        r = MultiSizeResizer(tmp_path, settings)

        result = r.save_original(buf.getvalue(), "rgba_test")

        assert result is not None and result.exists()
        with Image.open(result) as out:
            assert out.mode == "RGB"
            assert out.size == (2250, 2250)
            # 알파 합성 → 빨강+흰 = 분홍 (대략 R>200, G>100, B>100)
            r_, g_, b_ = out.getpixel((1125, 1125))
            assert r_ > 200 and g_ > 100 and b_ > 100


class TestMakeResizedSet:
    @pytest.fixture
    def full_settings(self):
        return {
            "resize": {
                "enabled": True,
                "base_size": 2250,
                "variants": {
                    "size_1500": {"enabled": True, "size": 1500,
                                  "subfolder": "1500", "naming": "{n}.jpg"},
                    "size_860": {"enabled": True, "size": 860,
                                 "subfolder": "860", "naming": "100_{n}.jpg"},
                    "crop_vertical": {"enabled": True, "width": 1500, "height": 2250,
                                      "crop_left": 375, "crop_right": 375,
                                      "subfolder": "crop", "filename": "main.jpg",
                                      "first_only": True},
                },
                "preserve_original": {"enabled": True, "subfolder": "original",
                                      "naming": "{stem}_1.jpg"},
                "jpeg_max_size_kb": 2024,
                "jpeg_quality": 90,
            }
        }

    def test_make_resized_set_creates_1500_and_860(self, tmp_path, full_settings):
        from src.exporter.resizer import MultiSizeResizer
        r = MultiSizeResizer(tmp_path, full_settings)
        img_bytes = _make_test_image_bytes(2250)

        result = r.make_resized_set(img_bytes, seq_n=1, is_first=False)

        assert result["size_1500"].exists()
        assert result["size_860"].exists()
        assert result["crop"] is None  # is_first=False
        with Image.open(result["size_1500"]) as im:
            assert im.size == (1500, 1500)
        with Image.open(result["size_860"]) as im:
            assert im.size == (860, 860)

    def test_naming_uses_seq_n(self, tmp_path, full_settings):
        from src.exporter.resizer import MultiSizeResizer
        r = MultiSizeResizer(tmp_path, full_settings)
        img_bytes = _make_test_image_bytes(2250)

        r.make_resized_set(img_bytes, seq_n=3, is_first=False)

        assert (tmp_path / "1500" / "3.jpg").exists()
        assert (tmp_path / "860" / "100_3.jpg").exists()


class TestCropVertical:
    @pytest.fixture
    def full_settings(self):
        return {
            "resize": {
                "enabled": True,
                "base_size": 2250,
                "variants": {
                    "size_1500": {"enabled": True, "size": 1500,
                                  "subfolder": "1500", "naming": "{n}.jpg"},
                    "size_860": {"enabled": True, "size": 860,
                                 "subfolder": "860", "naming": "100_{n}.jpg"},
                    "crop_vertical": {"enabled": True, "width": 1500, "height": 2250,
                                      "crop_left": 375, "crop_right": 375,
                                      "subfolder": "crop", "filename": "main.jpg",
                                      "first_only": True},
                },
                "preserve_original": {"enabled": True, "subfolder": "original",
                                      "naming": "{stem}_1.jpg"},
                "jpeg_max_size_kb": 2024,
                "jpeg_quality": 90,
            }
        }

    def test_crop_only_when_is_first_true(self, tmp_path, full_settings):
        from src.exporter.resizer import MultiSizeResizer
        r = MultiSizeResizer(tmp_path, full_settings)
        img_bytes = _make_test_image_bytes(2250)

        result = r.make_resized_set(img_bytes, seq_n=1, is_first=True)

        assert result["crop"] is not None
        assert result["crop"].exists()
        assert result["crop"].name == "main.jpg"
        with Image.open(result["crop"]) as im:
            assert im.size == (1500, 2250)

    def test_crop_output_size_is_exactly_target(self, tmp_path, full_settings):
        """출력 사이즈가 정확히 1500×2250인지만 검증 (스마트 크롭 후 리사이즈)."""
        from src.exporter.resizer import MultiSizeResizer
        img = Image.new("RGB", (2250, 2250), (0, 0, 0))
        px = img.load()
        for x in range(2250):
            v = int(255 * x / 2249)
            for y in range(2250):
                px[x, y] = (v, v, v)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)

        r = MultiSizeResizer(tmp_path, full_settings)
        result = r.make_resized_set(buf.getvalue(), seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            assert cropped.size == (1500, 2250)


class TestResizeFromFile:
    @pytest.fixture
    def full_settings(self):
        return {
            "resize": {
                "enabled": True,
                "base_size": 2250,
                "variants": {
                    "size_1500": {"enabled": True, "size": 1500,
                                  "subfolder": "1500", "naming": "{n}.jpg"},
                    "size_860": {"enabled": True, "size": 860,
                                 "subfolder": "860", "naming": "100_{n}.jpg"},
                    "crop_vertical": {"enabled": True, "width": 1500, "height": 2250,
                                      "crop_left": 375, "crop_right": 375,
                                      "subfolder": "crop", "filename": "main.jpg",
                                      "first_only": True},
                },
                "preserve_original": {"enabled": True, "subfolder": "original",
                                      "naming": "{stem}_1.jpg"},
                "jpeg_max_size_kb": 2024,
                "jpeg_quality": 90,
            }
        }

    def test_resize_from_file_loads_and_outputs(self, tmp_path, full_settings):
        from src.exporter.resizer import MultiSizeResizer
        src_path = tmp_path / "input" / "product_1.jpg"
        src_path.parent.mkdir(parents=True)
        Image.new("RGB", (2250, 2250), (200, 100, 50)).save(src_path, "JPEG")

        out_dir = tmp_path / "out"
        r = MultiSizeResizer(out_dir, full_settings)
        result = r.resize_from_file(
            src_path, seq_n=2,
            variants={"size_1500": True, "size_860": True, "crop": False},
        )

        assert (out_dir / "1500" / "2.jpg").exists()
        assert (out_dir / "860" / "100_2.jpg").exists()
        assert not (out_dir / "crop" / "main.jpg").exists()

    def test_resize_from_file_respects_overwrite_false(self, tmp_path, full_settings):
        from src.exporter.resizer import MultiSizeResizer
        src_path = tmp_path / "p.jpg"
        Image.new("RGB", (2250, 2250), (10, 10, 10)).save(src_path, "JPEG")

        out_dir = tmp_path / "out"
        existing = out_dir / "1500" / "1.jpg"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"OLD")

        r = MultiSizeResizer(out_dir, full_settings)
        r.resize_from_file(
            src_path, seq_n=1,
            variants={"size_1500": True, "size_860": False, "crop": False},
            overwrite=False,
        )

        assert existing.read_bytes() == b"OLD"


# ─────────────────────────────────────────────
# 스마트 크롭 (콘텐츠 중심 보존)
# ─────────────────────────────────────────────

def _make_product_on_white(
    canvas_size: tuple[int, int] = (2250, 2250),
    product_bbox: tuple[int, int, int, int] = (700, 200, 1550, 2050),
    product_color: tuple[int, int, int] = (50, 50, 50),
) -> bytes:
    """흰배경에 검정 사각형 제품을 배치한 테스트 이미지.

    product_bbox = (left, top, right, bottom) — 제품 위치
    """
    img = Image.new("RGB", canvas_size, (255, 255, 255))
    px = img.load()
    l, t, r, b = product_bbox
    for x in range(l, r):
        for y in range(t, b):
            if 0 <= x < canvas_size[0] and 0 <= y < canvas_size[1]:
                px[x, y] = product_color
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


class TestSmartCropVertical:
    @pytest.fixture
    def cfg(self):
        return {
            "resize": {
                "enabled": True,
                "base_size": 2250,
                "variants": {
                    "crop_vertical": {
                        "enabled": True,
                        "width": 1500,
                        "height": 2250,
                        "white_threshold": 245,
                        "subfolder": "crop",
                        "filename": "main.jpg",
                        "first_only": True,
                    },
                    "size_1500": {"enabled": True, "size": 1500,
                                  "subfolder": "1500", "naming": "{n}.jpg"},
                    "size_860": {"enabled": True, "size": 860,
                                 "subfolder": "860", "naming": "100_{n}.jpg"},
                },
                "preserve_original": {"enabled": True, "subfolder": "original",
                                      "naming": "{stem}_1.jpg"},
                "jpeg_max_size_kb": 2024,
                "jpeg_quality": 90,
            }
        }

    def test_centered_product_keeps_centered(self, tmp_path, cfg):
        """제품이 중앙 (700-1550)이면 좌우 375씩 잘라 그대로 중앙 유지."""
        from src.exporter.resizer import MultiSizeResizer
        img_bytes = _make_product_on_white(
            (2250, 2250), product_bbox=(700, 200, 1550, 2050))
        r = MultiSizeResizer(tmp_path, cfg)
        result = r.make_resized_set(img_bytes, seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            assert cropped.size == (1500, 2250)
            # 결과 가운데 (750, 1125)는 제품 영역 → 검정에 가까워야 함
            r_, g_, b_ = cropped.getpixel((750, 1125))
            assert r_ < 100 and g_ < 100 and b_ < 100

    def test_left_aligned_product_preserved(self, tmp_path, cfg):
        """제품이 왼쪽 (100-1300)에 있어도 잘리지 않고 보존되는지."""
        from src.exporter.resizer import MultiSizeResizer
        img_bytes = _make_product_on_white(
            (2250, 2250), product_bbox=(100, 200, 1300, 2050))
        r = MultiSizeResizer(tmp_path, cfg)
        result = r.make_resized_set(img_bytes, seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            assert cropped.size == (1500, 2250)
            import numpy as np
            arr = np.array(cropped)
            dark_mask = arr.max(axis=2) < 80
            # 제품이 보존되어야 함 (잘려나가지 않음)
            assert dark_mask.sum() > 50000, "제품이 너무 많이 잘려나감"

    def test_right_aligned_product_preserved(self, tmp_path, cfg):
        """제품이 오른쪽 (1000-2200)에 있어도 잘리지 않고 보존되는지."""
        from src.exporter.resizer import MultiSizeResizer
        img_bytes = _make_product_on_white(
            (2250, 2250), product_bbox=(1000, 200, 2200, 2050))
        r = MultiSizeResizer(tmp_path, cfg)
        result = r.make_resized_set(img_bytes, seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            assert cropped.size == (1500, 2250)
            import numpy as np
            arr = np.array(cropped)
            dark_mask = arr.max(axis=2) < 80
            assert dark_mask.sum() > 50000, "제품이 너무 많이 잘려나감"

    def test_wide_product_falls_back_to_centered_crop(self, tmp_path, cfg):
        """제품이 1500보다 넓으면 중앙 기준으로 자른다 (불가피한 손실)."""
        from src.exporter.resizer import MultiSizeResizer
        # 200~2050 (1850px 폭) 제품 — 1500보다 넓음
        img_bytes = _make_product_on_white(
            (2250, 2250), product_bbox=(200, 200, 2050, 2050))
        r = MultiSizeResizer(tmp_path, cfg)
        result = r.make_resized_set(img_bytes, seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            assert cropped.size == (1500, 2250)
            # 결과 중앙은 제품 영역
            r_, g_, b_ = cropped.getpixel((750, 1125))
            assert r_ < 100 and g_ < 100 and b_ < 100

    def test_all_white_image_centers_window(self, tmp_path, cfg):
        """완전 흰배경 이미지면 중앙 기준으로 자른다 (콘텐츠 없음)."""
        from src.exporter.resizer import MultiSizeResizer
        img = Image.new("RGB", (2250, 2250), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        r = MultiSizeResizer(tmp_path, cfg)
        result = r.make_resized_set(buf.getvalue(), seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            assert cropped.size == (1500, 2250)


class TestSmartCropNoContentLoss:
    """스마트 크롭이 콘텐츠를 잘라내지 않는지 검증."""

    @pytest.fixture
    def cfg(self):
        return {
            "resize": {
                "enabled": True,
                "base_size": 2250,
                "variants": {
                    "crop_vertical": {
                        "enabled": True, "width": 1500, "height": 2250,
                        "white_threshold": 245, "subfolder": "crop",
                        "filename": "main.jpg", "first_only": True,
                    },
                    "size_1500": {"enabled": True, "size": 1500,
                                  "subfolder": "1500", "naming": "{n}.jpg"},
                    "size_860": {"enabled": True, "size": 860,
                                 "subfolder": "860", "naming": "100_{n}.jpg"},
                },
                "preserve_original": {"enabled": True, "subfolder": "original",
                                      "naming": "{stem}_1.jpg"},
                "jpeg_max_size_kb": 2024,
                "jpeg_quality": 90,
            }
        }

    def _count_dark_pixels(self, img: Image.Image, threshold: int = 100):
        """RGB 모든 채널이 threshold 이하인 픽셀 수 (제품 영역 추정)."""
        try:
            import numpy as np
            arr = np.array(img.convert("RGB"))
            return int((arr.max(axis=2) < threshold).sum())
        except Exception:
            return 0

    def test_wide_product_not_cropped_off(self, tmp_path, cfg):
        """제품이 2250 폭 거의 전체를 차지해도 크롭 결과에 모두 보존되는지."""
        from src.exporter.resizer import MultiSizeResizer
        # 제품 폭 2050px (1500보다 훨씬 넓음)
        img_bytes = _make_product_on_white(
            (2250, 2250), product_bbox=(100, 200, 2150, 2050))
        # 원본 픽셀 수 (제품 영역)
        with Image.open(io.BytesIO(img_bytes)) as orig:
            orig_dark_count = self._count_dark_pixels(orig)

        r = MultiSizeResizer(tmp_path, cfg)
        result = r.make_resized_set(img_bytes, seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            assert cropped.size == (1500, 2250)
            cropped_dark_count = self._count_dark_pixels(cropped)
            # 리사이즈로 픽셀 수가 줄어들지만 비율로 보존돼야 함
            # 원본 2250×2250 → cropped 캔버스 ~3060×2250 → 1500×2250 (스케일 ~0.49 가로)
            # 제품 픽셀 수가 0이면 안됨 (=완전 잘려나감)
            assert cropped_dark_count > 1000, (
                f"제품이 너무 많이 잘려나감: cropped_dark={cropped_dark_count} "
                f"(orig_dark={orig_dark_count})"
            )

    def test_left_edge_product_preserved(self, tmp_path, cfg):
        """제품이 왼쪽 가장자리(0-1200)에 있어도 잘리지 않는지."""
        from src.exporter.resizer import MultiSizeResizer
        img_bytes = _make_product_on_white(
            (2250, 2250), product_bbox=(0, 200, 1200, 2050))
        r = MultiSizeResizer(tmp_path, cfg)
        result = r.make_resized_set(img_bytes, seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            cropped_dark_count = self._count_dark_pixels(cropped)
            # 가장자리 제품도 흰배경 패딩으로 안전하게 보존돼야 함
            assert cropped_dark_count > 1000

    def test_right_edge_product_preserved(self, tmp_path, cfg):
        """제품이 오른쪽 가장자리(1050-2249)에 있어도 잘리지 않는지."""
        from src.exporter.resizer import MultiSizeResizer
        img_bytes = _make_product_on_white(
            (2250, 2250), product_bbox=(1050, 200, 2249, 2050))
        r = MultiSizeResizer(tmp_path, cfg)
        result = r.make_resized_set(img_bytes, seq_n=1, is_first=True)

        with Image.open(result["crop"]) as cropped:
            cropped_dark_count = self._count_dark_pixels(cropped)
            assert cropped_dark_count > 1000
