# 멀티 사이즈 리사이징 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 편집 완료된 2250×2250 이미지를 4종(원본 보존, 1500×1500, 860×860, 1500×2250 크롭)으로 자동 변환하고, 재리사이징 UI(전용 탭 + 뷰파인더 옵션)를 제공한다.

**Architecture:** `src/exporter/resizer.py`에 `BatchCounter`(thread-safe 순번)와 `MultiSizeResizer`(저장)를 신설. `pipeline.process_single_unified_photoroom()`은 최종 bytes만 반환하고 저장은 GUI 측 resizer가 담당. `gui3.py`에 "리사이징" 탭과 뷰파인더 카드 리사이즈 버튼 추가.

**Tech Stack:** Python 3.12, Pillow (LANCZOS), tkinter, PyYAML, loguru, threading.Lock, pytest

**Spec:** `docs/superpowers/specs/2026-05-04-multi-size-resize-design.md`

---

## File Structure

**Create:**
- `src/exporter/resizer.py` (재작성, 기존 deprecated 파일 대체) — `BatchCounter`, `MultiSizeResizer`
- `tests/test_resizer.py` — 단위 테스트
- `gui_pyside/resize_tab.py` — 사용 안 함 (gui3.py 단일 파일 정책)

**Modify:**
- `config/settings.yaml` — `resize:` 섹션 추가
- `src/pipeline.py` — `process_single_unified_photoroom()` 반환값에 `final_bytes` 추가
- `gui3.py`:
  - `_start_unified_processing()` — `BatchCounter`, `MultiSizeResizer` 인스턴스 생성
  - `_process_one()` — 편집 후 resizer 호출
  - `_build_main_tab()` 뒤에 신규 `_build_resize_tab()` 추가
  - `_open_viewfinder()` — 카드에 "리사이즈" 버튼 추가 + 다이얼로그 메서드

---

## Task 1: BatchCounter 클래스 작성 (TDD)

**Files:**
- Create: `src/exporter/resizer.py`
- Test: `tests/test_resizer.py`

- [ ] **Step 1: 테스트 폴더 확인**

```bash
ls D:/CLAUDE_CODE_WORK/shop-image-editor/tests
```
없으면 생성: `mkdir D:/CLAUDE_CODE_WORK/shop-image-editor/tests`

- [ ] **Step 2: 실패 테스트 작성**

`tests/test_resizer.py` 생성:

```python
"""resizer 모듈 단위 테스트."""
import sys
from pathlib import Path
import threading
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.exporter.resizer import BatchCounter


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
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py -v
```
Expected: `ImportError: cannot import name 'BatchCounter'`

- [ ] **Step 4: BatchCounter 구현**

`src/exporter/resizer.py` 작성:

```python
"""멀티 사이즈 리사이징 모듈.

편집 완료된 2250×2250 이미지를 4종 출력으로 변환:
  - output/original/{stem}_1.jpg     (2250 보존)
  - output/1500/{n}.jpg              (1500×1500)
  - output/860/100_{n}.jpg           (860×860)
  - output/crop/main.jpg             (1500×2250, 첫 이미지만)
"""
from __future__ import annotations
import io
import threading
from pathlib import Path
from typing import Callable

from PIL import Image
from loguru import logger


class BatchCounter:
    """배치 단위 thread-safe 순번 카운터.

    GUI에서 배치 시작 시 1개 생성, 모든 워커 스레드에 공유.
    next()는 1, 2, 3 순으로 반환. is_first()는 첫 호출만 True.
    """

    def __init__(self):
        self._n = 0
        self._first_consumed = False
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._n += 1
            return self._n

    def is_first(self) -> bool:
        with self._lock:
            if self._first_consumed:
                return False
            self._first_consumed = True
            return True
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py -v
```
Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add src/exporter/resizer.py tests/test_resizer.py
git commit -m "feat(resizer): BatchCounter — thread-safe 배치 순번 발급기"
```

---

## Task 2: MultiSizeResizer 기본 인터페이스 + save_original (TDD)

**Files:**
- Modify: `src/exporter/resizer.py`
- Modify: `tests/test_resizer.py`

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_resizer.py`에 클래스 추가)

```python
import io
from PIL import Image

def _make_test_image_bytes(size: int = 2250, color=(128, 64, 32)) -> bytes:
    """테스트용 단색 JPEG 바이트 생성."""
    img = Image.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py::TestMultiSizeResizerSaveOriginal -v
```
Expected: `ImportError: cannot import name 'MultiSizeResizer'`

- [ ] **Step 3: MultiSizeResizer 구현 (save_original만)**

`src/exporter/resizer.py` 끝에 추가:

```python
class MultiSizeResizer:
    """편집 완료 이미지(bytes) → 4종 출력 저장.

    settings: dict — config/settings.yaml의 'resize' 섹션
    """

    def __init__(self, output_dir: Path | str, settings: dict):
        self.output_dir = Path(output_dir)
        self.cfg = (settings or {}).get("resize", {})
        self.max_kb = int(self.cfg.get("jpeg_max_size_kb", 2024))
        self.quality = int(self.cfg.get("jpeg_quality", 95))

    # ── 내부 ────────────────────────────────────────────────
    def _save_jpeg(self, img: Image.Image, dest: Path) -> Path:
        """JPEG 저장 — 품질 자동 조정으로 max_kb 이하."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if img.mode != "RGB":
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            else:
                img = img.convert("RGB")

        q = self.quality
        while q >= 60:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=q, optimize=True)
            if buf.tell() / 1024 <= self.max_kb:
                break
            q -= 5

        with open(dest, "wb") as f:
            f.write(buf.getvalue())
        logger.debug(f"[Resizer] 저장: {dest} (품질={q}, {buf.tell()//1024}KB)")
        return dest

    def _bytes_to_image(self, img_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(img_bytes)).copy()

    # ── 공개 메서드 ─────────────────────────────────────────
    def save_original(self, img_bytes: bytes, original_stem: str) -> Path:
        """output/original/{stem}_1.jpg 로 보존."""
        po = self.cfg.get("preserve_original", {})
        if not po.get("enabled", True):
            return None
        sub = po.get("subfolder", "original")
        naming = po.get("naming", "{stem}_1.jpg")
        fname = naming.format(stem=original_stem)
        dest = self.output_dir / sub / fname
        img = self._bytes_to_image(img_bytes)
        return self._save_jpeg(img, dest)
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py -v
```
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add src/exporter/resizer.py tests/test_resizer.py
git commit -m "feat(resizer): MultiSizeResizer.save_original — 편집 원본 보존"
```

---

## Task 3: make_resized_set — 1500/860 리사이즈 (TDD)

**Files:**
- Modify: `src/exporter/resizer.py`
- Modify: `tests/test_resizer.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py::TestMakeResizedSet -v
```
Expected: `AttributeError: 'MultiSizeResizer' object has no attribute 'make_resized_set'`

- [ ] **Step 3: make_resized_set 구현**

`src/exporter/resizer.py` `MultiSizeResizer` 클래스 끝에 추가:

```python
    def _ensure_base_size(self, img: Image.Image) -> Image.Image:
        """입력이 base_size와 다르면 리사이즈 (경고 로그)."""
        base = int(self.cfg.get("base_size", 2250))
        if img.size != (base, base):
            logger.warning(
                f"[Resizer] 입력 사이즈 {img.size} != base {base}×{base} "
                f"— 자동 리사이즈"
            )
            img = img.resize((base, base), Image.LANCZOS)
        return img

    def make_resized_set(
        self,
        img_bytes: bytes,
        seq_n: int,
        is_first: bool,
        on_log: Callable[[str], None] = None,
    ) -> dict:
        """3종 리사이즈 결과 생성.

        Returns: {"size_1500": Path|None, "size_860": Path|None, "crop": Path|None}
        """
        variants = self.cfg.get("variants", {})
        result = {"size_1500": None, "size_860": None, "crop": None}

        img = self._ensure_base_size(self._bytes_to_image(img_bytes))

        # size_1500
        v = variants.get("size_1500", {})
        if v.get("enabled", True):
            target = int(v.get("size", 1500))
            sub = v.get("subfolder", "1500")
            naming = v.get("naming", "{n}.jpg")
            dest = self.output_dir / sub / naming.format(n=seq_n)
            resized = img.resize((target, target), Image.LANCZOS)
            result["size_1500"] = self._save_jpeg(resized, dest)

        # size_860
        v = variants.get("size_860", {})
        if v.get("enabled", True):
            target = int(v.get("size", 860))
            sub = v.get("subfolder", "860")
            naming = v.get("naming", "100_{n}.jpg")
            dest = self.output_dir / sub / naming.format(n=seq_n)
            resized = img.resize((target, target), Image.LANCZOS)
            result["size_860"] = self._save_jpeg(resized, dest)

        # crop_vertical (is_first일 때만 자동 생성)
        v = variants.get("crop_vertical", {})
        if v.get("enabled", True) and (is_first or not v.get("first_only", True)):
            result["crop"] = self._do_crop(img, v)

        return result

    def _do_crop(self, img: Image.Image, v: dict) -> Path:
        """1500×2250 크롭 (좌우 375 절단)."""
        cl = int(v.get("crop_left", 375))
        cr = int(v.get("crop_right", 375))
        w, h = img.size
        cropped = img.crop((cl, 0, w - cr, h))
        sub = v.get("subfolder", "crop")
        fname = v.get("filename", "main.jpg")
        dest = self.output_dir / sub / fname
        return self._save_jpeg(cropped, dest)
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py -v
```
Expected: 9 passed

- [ ] **Step 5: 커밋**

```bash
git add src/exporter/resizer.py tests/test_resizer.py
git commit -m "feat(resizer): make_resized_set — 1500/860 리사이즈"
```

---

## Task 4: 1500×2250 크롭 검증 (TDD)

**Files:**
- Modify: `tests/test_resizer.py`

- [ ] **Step 1: 크롭 검증 테스트 추가**

```python
class TestCropVertical:
    @pytest.fixture
    def full_settings(self):
        # Task 3과 동일 — 복사
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

    def test_crop_pixel_correctness(self, tmp_path, full_settings):
        """좌측 첫 픽셀이 입력의 (375,0) 픽셀과 일치하는지 검증."""
        from src.exporter.resizer import MultiSizeResizer
        # 좌→우 그라데이션 생성: x=0 검정, x=2249 흰색
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
            # 크롭 결과의 (0, 0)은 원본의 (375, 0) 픽셀과 근접
            cropped_left = cropped.getpixel((0, 1125))[0]
            expected = int(255 * 375 / 2249)
            assert abs(cropped_left - expected) <= 5  # JPEG 손실 허용
```

- [ ] **Step 2: 테스트 실행 → 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py -v
```
Expected: 11 passed

- [ ] **Step 3: 커밋**

```bash
git add tests/test_resizer.py
git commit -m "test(resizer): 크롭 사이즈 + 픽셀 위치 검증"
```

---

## Task 5: resize_from_file — 재실행용 메서드 (TDD)

**Files:**
- Modify: `src/exporter/resizer.py`
- Modify: `tests/test_resizer.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
class TestResizeFromFile:
    @pytest.fixture
    def full_settings(self):
        return TestCropVertical.full_settings.__wrapped__(self)

    def test_resize_from_file_loads_and_outputs(self, tmp_path, full_settings):
        from src.exporter.resizer import MultiSizeResizer
        # 입력 파일 작성
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

        assert existing.read_bytes() == b"OLD"  # 덮어쓰기 안 됨
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py::TestResizeFromFile -v
```
Expected: `AttributeError: ... no attribute 'resize_from_file'`

- [ ] **Step 3: resize_from_file 구현**

`MultiSizeResizer` 클래스에 추가:

```python
    def resize_from_file(
        self,
        source_path: Path | str,
        seq_n: int,
        variants: dict[str, bool] = None,
        overwrite: bool = True,
    ) -> dict:
        """기존 파일에서 재리사이징 (재실행 탭, 뷰파인더 재리사이즈용).

        variants: {"size_1500": bool, "size_860": bool, "crop": bool}
        overwrite: False면 기존 파일 그대로 두고 스킵
        """
        if variants is None:
            variants = {"size_1500": True, "size_860": True, "crop": False}

        with open(source_path, "rb") as f:
            img_bytes = f.read()

        # 일시적으로 cfg variants enabled를 사용자 선택으로 덮어쓰기
        v_cfg = self.cfg.get("variants", {})
        result = {"size_1500": None, "size_860": None, "crop": None}

        img = self._ensure_base_size(self._bytes_to_image(img_bytes))

        if variants.get("size_1500") and v_cfg.get("size_1500", {}).get("enabled", True):
            v = v_cfg["size_1500"]
            target = int(v.get("size", 1500))
            dest = self.output_dir / v.get("subfolder", "1500") / v.get("naming", "{n}.jpg").format(n=seq_n)
            if dest.exists() and not overwrite:
                logger.info(f"[Resizer] 스킵(덮어쓰기 OFF): {dest}")
            else:
                result["size_1500"] = self._save_jpeg(img.resize((target, target), Image.LANCZOS), dest)

        if variants.get("size_860") and v_cfg.get("size_860", {}).get("enabled", True):
            v = v_cfg["size_860"]
            target = int(v.get("size", 860))
            dest = self.output_dir / v.get("subfolder", "860") / v.get("naming", "100_{n}.jpg").format(n=seq_n)
            if dest.exists() and not overwrite:
                logger.info(f"[Resizer] 스킵(덮어쓰기 OFF): {dest}")
            else:
                result["size_860"] = self._save_jpeg(img.resize((target, target), Image.LANCZOS), dest)

        if variants.get("crop") and v_cfg.get("crop_vertical", {}).get("enabled", True):
            v = v_cfg["crop_vertical"]
            dest = self.output_dir / v.get("subfolder", "crop") / v.get("filename", "main.jpg")
            if dest.exists() and not overwrite:
                logger.info(f"[Resizer] 스킵(덮어쓰기 OFF): {dest}")
            else:
                result["crop"] = self._do_crop(img, v)

        return result
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/test_resizer.py -v
```
Expected: 13 passed

- [ ] **Step 5: 커밋**

```bash
git add src/exporter/resizer.py tests/test_resizer.py
git commit -m "feat(resizer): resize_from_file — 재실행용 파일 입력"
```

---

## Task 6: settings.yaml에 resize 섹션 추가

**Files:**
- Modify: `config/settings.yaml`

- [ ] **Step 1: 현재 settings.yaml 읽기**

```bash
cat D:/CLAUDE_CODE_WORK/shop-image-editor/config/settings.yaml | head -20
```

- [ ] **Step 2: resize 섹션 추가** (파일 끝에 append)

`config/settings.yaml`에 추가:

```yaml

# ─────────────────────────────────────────────────────
# 멀티 사이즈 리사이징 (편집 완료 후 자동 변환)
# ─────────────────────────────────────────────────────
resize:
  enabled: true
  base_size: 2250          # 편집 결과물 기준 사이즈 (정사각형)

  variants:
    size_1500:
      enabled: true
      size: 1500
      subfolder: "1500"
      naming: "{n}.jpg"           # {n} = 배치 통합 순번

    size_860:
      enabled: true
      size: 860
      subfolder: "860"
      naming: "100_{n}.jpg"

    crop_vertical:
      enabled: true
      width: 1500
      height: 2250
      crop_left: 375
      crop_right: 375
      subfolder: "crop"
      filename: "main.jpg"
      first_only: true             # 배치의 첫 이미지에서만 자동 생성

  preserve_original:
    enabled: true
    subfolder: "original"
    naming: "{stem}_1.jpg"         # {stem} = 원본 파일 stem

  jpeg_max_size_kb: 2024
  jpeg_quality: 95
```

- [ ] **Step 3: YAML 파싱 검증**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import yaml; d = yaml.safe_load(open('config/settings.yaml', encoding='utf-8')); assert d['resize']['enabled'] == True; assert d['resize']['variants']['size_1500']['size'] == 1500; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: 커밋**

```bash
git add config/settings.yaml
git commit -m "feat(config): resize 섹션 추가 — 1500/860/crop/original 설정"
```

---

## Task 7: pipeline.py에 final_bytes 반환 추가

**Files:**
- Modify: `src/pipeline.py` (`process_single_unified_photoroom` 함수 마지막 return)

- [ ] **Step 1: 해당 라인 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import re; t=open('src/pipeline.py',encoding='utf-8').read(); m=re.search(r'\"shooting_angle\":\s*shooting_angle,', t); print(t[m.start()-200:m.end()+200])"
```

- [ ] **Step 2: 반환값에 `final_bytes`, `original_stem` 추가**

`src/pipeline.py`에서 `process_single_unified_photoroom`의 마지막 return 직전에 다음과 같이 수정. 정확한 패턴은:

```python
return {
    "success": True, "files": [info], "path": image_path,
    "image_type": image_type, "background": background,
    "shooting_angle": shooting_angle,
    "is_label_cut": is_label_cut,
}
```

→

```python
return {
    "success": True, "files": [info], "path": image_path,
    "final_bytes": current_bytes,                # 신규
    "original_stem": Path(image_path).stem,      # 신규
    "image_type": image_type, "background": background,
    "shooting_angle": shooting_angle,
    "is_label_cut": is_label_cut,
}
```

`Edit` 도구 사용. `current_bytes`는 함수 내 이미 존재하는 변수.

- [ ] **Step 3: 문법 검증**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('src/pipeline.py', encoding='utf-8').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: 기존 테스트 깨지지 않는지 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/ -v -x
```
Expected: 13 passed (resizer만, pipeline 테스트는 없음)

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline.py
git commit -m "feat(pipeline): process_single_unified_photoroom — final_bytes/original_stem 반환"
```

---

## Task 8: gui3.py — 배치 시작 시 BatchCounter + MultiSizeResizer 생성

**Files:**
- Modify: `gui3.py` `_start_unified_processing` 메서드 (~ line 1593-1622)

- [ ] **Step 1: 현재 코드 확인**

`gui3.py:1595-1625` 범위 Read.

- [ ] **Step 2: counter / resizer 인스턴스 생성 코드 추가**

`gui3.py` `_start_unified_processing`에서 `Path(output_dir).mkdir(...)` 직후, `# UI 초기화` 위에 다음 코드 추가:

```python
        # ── 배치 카운터 + 리사이저 (멀티 사이즈 출력용) ───────────
        from src.exporter.resizer import BatchCounter, MultiSizeResizer
        from src.utils.config_loader import load_yaml as _load_yaml
        try:
            _settings = _load_yaml(SETTINGS_PATH)
        except Exception:
            _settings = {}
        self._batch_counter = BatchCounter()
        self._batch_resizer = MultiSizeResizer(output_dir, _settings)
        self._log_unified(
            f"📐 멀티사이즈 출력 활성화 — original/1500/860/crop"
            if _settings.get("resize", {}).get("enabled", True)
            else "📐 멀티사이즈 출력 비활성화"
        )
```

`_load_yaml` 임포트 경로 확인 — 기존 코드에서 어떻게 YAML을 로드하는지:

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import re; t=open('gui3.py',encoding='utf-8').read(); m=re.findall(r'load_yaml.*', t); print('\n'.join(m[:5]))"
```

찾은 임포트 경로를 그대로 사용.

- [ ] **Step 3: 문법 검증**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: 커밋**

```bash
git add gui3.py
git commit -m "feat(gui): _start_unified_processing — BatchCounter+MultiSizeResizer 생성"
```

---

## Task 9: gui3.py — _process_one에서 리사이저 호출

**Files:**
- Modify: `gui3.py` `_process_one` 함수 (성공 시 분기)

- [ ] **Step 1: 현재 성공 처리 라인 확인**

`gui3.py:1644` 부근의 result 사용 영역. 다음 패턴을 찾는다:

```python
            try:
                from src.pipeline import (
                    ImageEditPipeline, ClaidNoCreditError, PhotoroomNoCreditError)
                pl = ImageEditPipeline(config_dir=str(CONFIG_DIR))
                pl._vision_provider = vision_provider
                result = pl.process_single_unified_photoroom(
                    ...
                )
            except (ClaidNoCreditError, ...):
```

- [ ] **Step 2: result 사용부에 리사이저 호출 추가**

`result = pl.process_single_unified_photoroom(...)` 호출 직후, `except (ClaidNoCreditError, ...)` 직전에 다음 블록 추가:

```python
                # ── 멀티 사이즈 리사이즈 ─────────────────────────
                if result.get("success") and result.get("final_bytes"):
                    try:
                        stem = result.get("original_stem") or Path(img_path).stem
                        self._batch_resizer.save_original(
                            result["final_bytes"], stem)
                        n = self._batch_counter.next()
                        is_first = self._batch_counter.is_first()
                        rs = self._batch_resizer.make_resized_set(
                            result["final_bytes"], seq_n=n, is_first=is_first)
                        result["resized"] = {
                            "size_1500": str(rs["size_1500"]) if rs["size_1500"] else None,
                            "size_860":  str(rs["size_860"])  if rs["size_860"]  else None,
                            "crop":      str(rs["crop"])      if rs["crop"]      else None,
                        }
                        self._log_unified(
                            f"  📐 멀티 출력: 1500/{n}.jpg, 860/100_{n}.jpg"
                            + (", crop/main.jpg" if is_first else ""),
                            "success")
                    except Exception as _re:
                        self._log_unified(f"  ⚠️ 리사이즈 실패: {_re}", "warning")
                        # 편집은 성공이므로 result["success"]는 유지
```

- [ ] **Step 3: 문법 검증**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: 커밋**

```bash
git add gui3.py
git commit -m "feat(gui): _process_one — 편집 직후 리사이저 호출"
```

---

## Task 10: 통합 구동 테스트 (편집 + 리사이즈)

**Files:**
- 실제 이미지 5장 사용

- [ ] **Step 1: 테스트 이미지 준비 안내**

사용자에게 안내:
"임의 이미지 5장이 있는 폴더 경로를 알려주세요. 또는 `tests/fixtures/sample_images/` 폴더에 5장 배치하세요."

- [ ] **Step 2: GUI 실행**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python gui3.py
```

체크리스트:
- [ ] 폴더 선택 → 이미지 인식
- [ ] "처리 시작" 클릭
- [ ] 처리 완료 후 다음 폴더 구조 확인:
  - `OUTPUT/original/{원본명}_1.jpg` × 5
  - `OUTPUT/1500/1.jpg, 2.jpg, 3.jpg, 4.jpg, 5.jpg`
  - `OUTPUT/860/100_1.jpg, 100_2.jpg, ...`
  - `OUTPUT/crop/main.jpg` × 1

- [ ] **Step 3: 음성 알림**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import pyttsx3; e=pyttsx3.init(); e.say('편집 + 리사이즈 통합 테스트 완료되었습니다'); e.runAndWait()"
```

- [ ] **Step 4: 커밋 (있다면)**

테스트 중 발견한 버그 수정만 커밋. 없으면 스킵.

---

## Task 11: 리사이징 전용 탭 — UI 구성

**Files:**
- Modify: `gui3.py` (notebook 탭 추가 + 빌더 메서드)

- [ ] **Step 1: 탭 등록 추가**

`gui3.py:660-680`의 `self.notebook` 영역에서 탭 등록 코드 직후에 추가:

```python
        # 리사이징 전용 탭
        self.tab_resize = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_resize, text="  리사이징  ")
```

탭 추가 위치: 기존 "조건" 탭 뒤, "설정" 탭 앞.

- [ ] **Step 2: _build_resize_tab() 메서드 작성**

`_build_main_tab()` 메서드 정의를 찾고 그 바로 뒤에 다음 메서드 추가:

```python
    def _build_resize_tab(self):
        """리사이징 전용 탭 — 이미 편집된 폴더에서 사이즈만 재생성."""
        f = self.tab_resize
        # 폴더 선택
        row = tk.Frame(f); row.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(row, text="입력 폴더:", width=10, anchor="w").pack(side="left")
        self.var_resize_input = tk.StringVar()
        tk.Entry(row, textvariable=self.var_resize_input).pack(
            side="left", fill="x", expand=True)
        tk.Button(row, text="폴더 선택",
                  command=self._resize_pick_input).pack(side="left", padx=(6, 0))

        # 출력 폴더
        row = tk.Frame(f); row.pack(fill="x", padx=12, pady=6)
        tk.Label(row, text="출력 폴더:", width=10, anchor="w").pack(side="left")
        self.var_resize_output = tk.StringVar()
        tk.Entry(row, textvariable=self.var_resize_output).pack(
            side="left", fill="x", expand=True)
        tk.Button(row, text="폴더 선택",
                  command=self._resize_pick_output).pack(side="left", padx=(6, 0))

        # 사이즈 옵션
        opts = tk.LabelFrame(f, text="출력 사이즈", padx=10, pady=8)
        opts.pack(fill="x", padx=12, pady=10)
        self.var_resize_1500 = tk.BooleanVar(value=True)
        self.var_resize_860 = tk.BooleanVar(value=True)
        self.var_resize_crop = tk.BooleanVar(value=True)
        tk.Checkbutton(opts, text="1500×1500 (output/1500/{n}.jpg)",
                       variable=self.var_resize_1500).pack(anchor="w")
        tk.Checkbutton(opts, text="860×860 (output/860/100_{n}.jpg)",
                       variable=self.var_resize_860).pack(anchor="w")
        tk.Checkbutton(opts, text="1500×2250 크롭 (output/crop/main.jpg, 첫 이미지만)",
                       variable=self.var_resize_crop).pack(anchor="w")

        # 덮어쓰기
        row = tk.Frame(f); row.pack(fill="x", padx=12, pady=4)
        self.var_resize_overwrite = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text="기존 파일 덮어쓰기",
                       variable=self.var_resize_overwrite).pack(anchor="w")

        # 실행 버튼 + 진행률
        row = tk.Frame(f); row.pack(fill="x", padx=12, pady=10)
        self.btn_resize_run = tk.Button(
            row, text="리사이징 시작", command=self._resize_run,
            font=("맑은 고딕", 11, "bold"), bg="#3498db", fg="white",
            padx=20, pady=8)
        self.btn_resize_run.pack(side="left")

        self.var_resize_progress = tk.IntVar(value=0)
        ttk.Progressbar(f, variable=self.var_resize_progress, maximum=100).pack(
            fill="x", padx=12, pady=4)

        # 로그
        self.resize_log = scrolledtext.ScrolledText(
            f, height=15, font=("Consolas", 9))
        self.resize_log.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.resize_log.config(state="disabled")
```

- [ ] **Step 3: __init__에서 탭 빌더 호출**

`_build_main_tab()` 호출 위치를 찾아 바로 뒤에 추가:

```python
        self._build_resize_tab()
```

- [ ] **Step 4: 문법 검증 + 실행 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('OK')"
cd D:/CLAUDE_CODE_WORK/shop-image-editor && timeout 3 python gui3.py
```
Expected: GUI 창이 열리고 "리사이징" 탭이 보임. 3초 후 자동 종료.

- [ ] **Step 5: 커밋**

```bash
git add gui3.py
git commit -m "feat(gui): 리사이징 전용 탭 UI 구성"
```

---

## Task 12: 리사이징 전용 탭 — 핸들러 메서드 구현

**Files:**
- Modify: `gui3.py` (3개 신규 메서드)

- [ ] **Step 1: 핸들러 메서드 추가**

`_build_resize_tab` 메서드 바로 뒤에 다음 3개 메서드 추가:

```python
    def _resize_pick_input(self):
        path = filedialog.askdirectory(title="리사이징 입력 폴더 선택")
        if path:
            self.var_resize_input.set(path)

    def _resize_pick_output(self):
        path = filedialog.askdirectory(title="리사이징 출력 폴더 선택")
        if path:
            self.var_resize_output.set(path)

    def _resize_log(self, msg: str):
        self.resize_log.config(state="normal")
        self.resize_log.insert("end", msg + "\n")
        self.resize_log.see("end")
        self.resize_log.config(state="disabled")

    def _resize_run(self):
        """리사이징 전용 실행 — 별도 스레드."""
        in_dir = self.var_resize_input.get().strip()
        out_dir = self.var_resize_output.get().strip() or in_dir
        if not in_dir or not Path(in_dir).is_dir():
            messagebox.showerror("오류", "입력 폴더를 선택하세요.")
            return

        # 자연순 정렬
        import re as _re
        def _natural_key(p):
            return [int(s) if s.isdigit() else s.lower()
                    for s in _re.split(r"(\d+)", p.name)]
        files = sorted(
            [p for p in Path(in_dir).iterdir()
             if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png")],
            key=_natural_key,
        )
        if not files:
            messagebox.showwarning("경고", "이미지 파일이 없습니다.")
            return

        v_1500 = self.var_resize_1500.get()
        v_860 = self.var_resize_860.get()
        v_crop = self.var_resize_crop.get()
        if not (v_1500 or v_860 or v_crop):
            messagebox.showwarning("경고", "최소 한 개 사이즈를 선택하세요.")
            return

        overwrite = self.var_resize_overwrite.get()
        total = len(files)
        self.btn_resize_run.config(state="disabled")
        self.resize_log.config(state="normal")
        self.resize_log.delete("1.0", "end")
        self.resize_log.config(state="disabled")
        self._resize_log(f"📐 리사이징 시작 — {total}장")

        def _run():
            try:
                from src.exporter.resizer import BatchCounter, MultiSizeResizer
                from src.utils.config_loader import load_yaml as _ly
                try:
                    settings = _ly(SETTINGS_PATH)
                except Exception:
                    settings = {}
                resizer = MultiSizeResizer(out_dir, settings)
                counter = BatchCounter()

                for i, src in enumerate(files, 1):
                    n = counter.next()
                    is_first = counter.is_first()
                    variants = {
                        "size_1500": v_1500,
                        "size_860": v_860,
                        "crop": v_crop and is_first,
                    }
                    try:
                        resizer.resize_from_file(
                            src, seq_n=n, variants=variants, overwrite=overwrite)
                        self.after(0, lambda s=src.name, n=n:
                                   self._resize_log(f"  ✓ [{i}/{total}] {s} → 순번 {n}"))
                    except Exception as e:
                        self.after(0, lambda s=src.name, err=str(e):
                                   self._resize_log(f"  ❌ [{i}/{total}] {s}: {err}"))
                    pct = int(i * 100 / total)
                    self.after(0, lambda p=pct: self.var_resize_progress.set(p))

                self.after(0, lambda: self._resize_log(f"✅ 완료 — {total}장 처리"))
            finally:
                self.after(0, lambda: self.btn_resize_run.config(state="normal"))

        threading.Thread(target=_run, daemon=True, name="resize-runner").start()
```

- [ ] **Step 2: 문법 검증**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: 실 구동 테스트**

GUI 실행 → 리사이징 탭 → 폴더 선택 (이전 Task 10에서 생성된 OUTPUT/original 폴더) → 시작 → 진행률 100% + 결과 폴더 생성 확인.

- [ ] **Step 4: 커밋**

```bash
git add gui3.py
git commit -m "feat(gui): 리사이징 전용 탭 — 폴더 선택/실행/진행률"
```

---

## Task 13: 뷰파인더 카드에 리사이즈 버튼 추가

**Files:**
- Modify: `gui3.py` `_open_viewfinder` 메서드 + 카드 렌더링부

- [ ] **Step 1: 카드 렌더링 위치 확인**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import re; t=open('gui3.py',encoding='utf-8').read(); m=re.search(r'def _vf_render_card', t) or re.search(r'_vf_card', t); print('found at line', t[:m.start()].count(chr(10))+1 if m else 'NOT FOUND')"
```

`_vf_render_card`가 없으면 `_open_viewfinder` 내부에서 카드를 만드는 코드를 찾는다 (line 2414~).

- [ ] **Step 2: 카드 하단 버튼 영역에 "리사이즈" 추가**

뷰파인더 카드의 버튼 행에 다음 버튼 추가 (정확한 위치는 카드 코드에 따라 달라짐):

```python
                tk.Button(
                    btn_row, text="리사이즈",
                    command=lambda i=vf_idx: self._vf_open_resize_dialog(i),
                    font=("맑은 고딕", 8),
                    bg="#34495e", fg="white", padx=6,
                ).pack(side="left", padx=2)
```

- [ ] **Step 3: 다이얼로그 메서드 작성**

`_open_viewfinder` 메서드 뒤에 추가:

```python
    def _vf_open_resize_dialog(self, vf_idx: int):
        """뷰파인더에서 개별 이미지 재리사이즈 다이얼로그."""
        if vf_idx >= len(self._viewfinder_pairs):
            return
        item = self._viewfinder_pairs[vf_idx]
        # original 경로 확보
        orig = None
        if item.get("resized") and item["resized"].get("original"):
            orig = Path(item["resized"]["original"])
        if orig is None:
            # output_dir/original/{stem}_1.jpg
            in_path = Path(item["input_path"])
            stem = in_path.stem
            for cand in [
                in_path.parent / "OUTPUT" / "original" / f"{stem}_1.jpg",
                Path(item.get("output_files", [{}])[0].get("path", "")).parent.parent / "original" / f"{stem}_1.jpg",
            ]:
                if cand.exists():
                    orig = cand; break
        if not orig or not orig.exists():
            messagebox.showerror("오류",
                                 "원본 보존 파일을 찾을 수 없습니다.\n"
                                 "먼저 편집을 실행해 주세요.", parent=self._vf_dlg)
            return

        dlg = tk.Toplevel(self._vf_dlg)
        dlg.title(f"리사이즈 — {orig.name}")
        dlg.resizable(False, False)
        dlg.grab_set()

        f = tk.Frame(dlg, padx=18, pady=14); f.pack()
        tk.Label(f, text=f"대상: {orig.name}",
                 font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(0, 8))

        v_1500 = tk.BooleanVar(value=True)
        v_860 = tk.BooleanVar(value=True)
        v_crop = tk.BooleanVar(value=False)
        v_over = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="1500×1500", variable=v_1500).pack(anchor="w")
        tk.Checkbutton(f, text="860×860", variable=v_860).pack(anchor="w")
        tk.Checkbutton(f, text="1500×2250 크롭", variable=v_crop).pack(anchor="w")
        tk.Checkbutton(f, text="기존 파일 덮어쓰기",
                       variable=v_over).pack(anchor="w", pady=(8, 0))

        def _run():
            from src.exporter.resizer import MultiSizeResizer
            from src.utils.config_loader import load_yaml as _ly
            try:
                settings = _ly(SETTINGS_PATH)
            except Exception:
                settings = {}
            out_dir = orig.parent.parent  # OUTPUT
            resizer = MultiSizeResizer(out_dir, settings)
            seq_n = vf_idx + 1
            try:
                resizer.resize_from_file(
                    orig, seq_n=seq_n,
                    variants={"size_1500": v_1500.get(),
                              "size_860": v_860.get(),
                              "crop": v_crop.get()},
                    overwrite=v_over.get(),
                )
                dlg.destroy()
                messagebox.showinfo("완료", f"리사이즈 완료 — 순번 {seq_n}",
                                    parent=self._vf_dlg)
            except Exception as e:
                messagebox.showerror("오류", f"리사이즈 실패:\n{e}",
                                     parent=dlg)

        btn_row = tk.Frame(f); btn_row.pack(pady=(12, 0))
        tk.Button(btn_row, text="실행", command=_run,
                  bg="#3498db", fg="white", padx=14, pady=4).pack(side="left", padx=4)
        tk.Button(btn_row, text="취소", command=dlg.destroy,
                  padx=14, pady=4).pack(side="left", padx=4)
```

- [ ] **Step 4: 문법 검증**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import ast; ast.parse(open('gui3.py', encoding='utf-8').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 5: 실 구동 테스트**

GUI → 편집 1장 실행 → 뷰파인더 → "리사이즈" 버튼 → 다이얼로그 → 실행 → 결과 파일 생성 확인.

- [ ] **Step 6: 커밋**

```bash
git add gui3.py
git commit -m "feat(viewfinder): 카드별 리사이즈 버튼 + 다이얼로그"
```

---

## Task 14: 통합 회귀 테스트 + 음성 완료 알림

**Files:**
- 실 이미지 + 종합 시나리오

- [ ] **Step 1: 회귀 시나리오 정의 & 실행**

체크리스트:
- [ ] **시나리오 A — 신규 배치**
  - 5장 이미지 폴더 선택 → 처리 시작 → OUTPUT 안에 4개 폴더 모두 생성, 파일 수 정확
- [ ] **시나리오 B — 리사이징 전용 탭**
  - 이전 OUTPUT/original 폴더 선택 → 1500×1500만 체크 → 실행 → OUTPUT/1500/만 갱신, 다른 폴더 변동 없음
- [ ] **시나리오 C — 뷰파인더 재리사이즈**
  - 처리 후 뷰파인더 → 3번째 카드 → 리사이즈 → 1500×2250 크롭만 체크 → 실행 → OUTPUT/crop/main.jpg 갱신
- [ ] **시나리오 D — 크레딧 부족 회귀**
  - 의도적으로 잘못된 Photoroom 키 → 처리 → 즉시 중단 + 한글 팝업 표시 (기존 기능)

- [ ] **Step 2: 모든 단위 테스트 재실행**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -m pytest tests/ -v
```
Expected: 13 passed

- [ ] **Step 3: 음성 완료 알림**

```bash
cd D:/CLAUDE_CODE_WORK/shop-image-editor && python -c "import pyttsx3; e=pyttsx3.init(); e.say('멀티 사이즈 리사이징 기능 개발 완료되었습니다'); e.runAndWait()"
```

- [ ] **Step 4: history.md 업데이트**

`history.md`에 8차(또는 다음 차수) 섹션 추가:

```markdown
## 2026-05-04 (8차) — 멀티 사이즈 리사이징

### 추가된 기능
- **편집 후 자동 멀티 사이즈 출력** (4종)
  - `output/original/` — 편집 원본 보존 (2250×2250, `{원본명}_1.jpg`)
  - `output/1500/` — 1500×1500 (`{n}.jpg`, 배치 통합 순번)
  - `output/860/` — 860×860 (`100_{n}.jpg`)
  - `output/crop/` — 1500×2250 센터크롭 (`main.jpg`, 첫 이미지만)
- **리사이징 전용 탭**: 편집 없이 폴더의 이미지들을 사이즈만 재변환
- **뷰파인더 카드 리사이즈 버튼**: 개별 이미지 사이즈 재생성

### 기술
- `src/exporter/resizer.py` 신설: `BatchCounter`(thread-safe 순번) + `MultiSizeResizer`
- `config/settings.yaml`에 `resize:` 섹션 추가 (사이즈/명명/경로 모두 설정화)
- 13개 단위 테스트 (`tests/test_resizer.py`)
```

- [ ] **Step 5: 최종 커밋 & 푸시**

```bash
git add history.md
git commit -m "docs: history.md — 8차 멀티 사이즈 리사이징 기능 추가"
git push origin main
```

---

## 자체 검토 결과

✅ **Spec 커버리지**
- 4종 출력 → Task 1~5
- 배치 통합 순번 → Task 1 (BatchCounter)
- 첫 이미지만 1500×2250 → Task 4 (`is_first`)
- 원본 보존 → Task 2 (`save_original`)
- 리사이징 전용 탭 → Task 11~12
- 뷰파인더 리사이즈 옵션 → Task 13
- 설정 YAML화 → Task 6
- 실 구동 테스트 + 음성 → Task 10, 14

✅ **타입 일관성**
- `BatchCounter.next() -> int`, `is_first() -> bool` — Task 1, 9에서 동일 사용
- `MultiSizeResizer.save_original(bytes, str) -> Path` — Task 2, 9에서 동일
- `make_resized_set(bytes, int, bool) -> dict{size_1500, size_860, crop}` — Task 3, 9에서 동일
- `resize_from_file(Path|str, int, dict, bool) -> dict` — Task 5, 12, 13에서 동일

✅ **No Placeholders** — 모든 코드 블록은 완전 구현, "TODO" 없음

✅ **Frequent commits** — Task 당 커밋 1회 (~14회)

---

**Plan 완료 — `docs/superpowers/plans/2026-05-04-multi-size-resize-plan.md`에 저장됨.**
