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
