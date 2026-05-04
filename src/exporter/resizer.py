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

        q = max(int(self.quality), 60)
        buf = io.BytesIO()
        while q >= 60:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=q, optimize=True)
            if buf.tell() / 1024 <= self.max_kb:
                break
            q -= 5

        size_kb = buf.tell() // 1024
        if size_kb > self.max_kb:
            logger.warning(
                f"[Resizer] {dest.name}: 최소 품질(60)에서도 한도 초과 "
                f"({size_kb}KB > {self.max_kb}KB)")

        with open(dest, "wb") as f:
            f.write(buf.getvalue())
        logger.debug(f"[Resizer] 저장: {dest} (품질={q}, {size_kb}KB)")
        return dest

    def _bytes_to_image(self, img_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(img_bytes)).copy()

    # ── 공개 메서드 ─────────────────────────────────────────
    def save_original(self, img_bytes: bytes, original_stem: str) -> Path | None:
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

    def _save_simple_resize(self, img: Image.Image, v_cfg: dict, seq_n: int) -> Path:
        """단일 사이즈 정사각형 리사이즈 저장 (1500/860 공통)."""
        target = int(v_cfg.get("size"))
        sub = v_cfg.get("subfolder")
        naming = v_cfg.get("naming")
        dest = self.output_dir / sub / naming.format(n=seq_n)
        resized = img.resize((target, target), Image.LANCZOS)
        return self._save_jpeg(resized, dest)

    def make_resized_set(
        self,
        img_bytes: bytes,
        seq_n: int,
        is_first: bool,
    ) -> dict:
        """3종 리사이즈 결과 생성.

        주의: 호출자(BatchCounter)가 seq_n의 유일성과 is_first=True의 단일성을
        보장해야 한다. 같은 seq_n을 두 번 넘기면 출력 파일이 덮어써진다.

        Returns: {"size_1500": Path|None, "size_860": Path|None, "crop": Path|None}
        """
        variants = self.cfg.get("variants", {})
        result = {"size_1500": None, "size_860": None, "crop": None}

        img = self._ensure_base_size(self._bytes_to_image(img_bytes))

        v = variants.get("size_1500", {})
        if v.get("enabled", True):
            result["size_1500"] = self._save_simple_resize(img, v, seq_n)

        v = variants.get("size_860", {})
        if v.get("enabled", True):
            result["size_860"] = self._save_simple_resize(img, v, seq_n)

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

        v_cfg = self.cfg.get("variants", {})
        result = {"size_1500": None, "size_860": None, "crop": None}

        img = self._ensure_base_size(self._bytes_to_image(img_bytes))

        for key in ("size_1500", "size_860"):
            if not variants.get(key):
                continue
            v = v_cfg.get(key, {})
            if not v.get("enabled", True):
                continue
            naming = v.get("naming", "{n}.jpg")
            dest = self.output_dir / v.get("subfolder", key) / naming.format(n=seq_n)
            if dest.exists() and not overwrite:
                logger.info(f"[Resizer] 스킵(덮어쓰기 OFF): {dest}")
                continue
            result[key] = self._save_simple_resize(img, v, seq_n)

        if variants.get("crop") and v_cfg.get("crop_vertical", {}).get("enabled", True):
            v = v_cfg["crop_vertical"]
            dest = self.output_dir / v.get("subfolder", "crop") / v.get("filename", "main.jpg")
            if dest.exists() and not overwrite:
                logger.info(f"[Resizer] 스킵(덮어쓰기 OFF): {dest}")
            else:
                result["crop"] = self._do_crop(img, v)

        return result
