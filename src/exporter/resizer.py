"""멀티 사이즈 리사이징 모듈.

편집 완료된 2250×2250 이미지를 4종 출력으로 변환:
  - output/original/{stem}_1.jpg     (2250 보존)
  - output/1500/{n}.jpg              (1500×1500)
  - output/860/100_{n}.jpg           (860×860)
  - output/crop/100_list.jpg         (1500×2250, 첫 이미지만)
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

    @staticmethod
    def _detect_content_bbox(
        img: Image.Image,
        white_threshold: int = 235,
        min_ratio: float = 0.005,
    ) -> tuple[int, int, int, int]:
        """비어있지 않은(흰배경 아닌) 영역의 바운딩 박스 (x_min, y_min, x_max, y_max) 반환.

        JPEG 압축 노이즈에 강건하도록:
        - 행/열별 콘텐츠 픽셀 비율이 min_ratio 이상일 때만 '콘텐츠 행/열'로 인정
        - 임계값을 235로 설정하여 약간 어두운 흰배경도 배경으로 간주

        모든 픽셀이 흰배경이면 이미지 전체 반환.
        """
        w, h = img.size
        try:
            import numpy as np
        except ImportError:
            return 0, 0, w - 1, h - 1

        if img.mode == "RGBA":
            arr = np.array(img.split()[3])
            mask = arr > 32  # 알파 32 이상이어야 콘텐츠 (반투명 안티앨리어싱 무시)
        else:
            arr = np.array(img.convert("RGB"))
            # min(R,G,B) < threshold면 콘텐츠 — JPEG 노이즈에 강건하도록 235로
            mask = arr.min(axis=2) < white_threshold

        # 행/열별 콘텐츠 픽셀 수
        col_counts = mask.sum(axis=0)  # shape (W,)
        row_counts = mask.sum(axis=1)  # shape (H,)
        # 일정 비율 이상이어야 진짜 콘텐츠 행/열로 인정 (JPEG 노이즈 무시)
        col_thr = max(2, int(h * min_ratio))
        row_thr = max(2, int(w * min_ratio))
        cols = col_counts >= col_thr
        rows = row_counts >= row_thr

        if not cols.any() or not rows.any():
            return 0, 0, w - 1, h - 1

        x_min = int(np.argmax(cols))
        x_max = int(w - 1 - np.argmax(cols[::-1]))
        y_min = int(np.argmax(rows))
        y_max = int(h - 1 - np.argmax(rows[::-1]))
        return x_min, y_min, x_max, y_max

    def _do_crop_photoroom(self, img: Image.Image, v: dict, dest: Path) -> Path | None:
        """Photoroom API로 정확한 비율 크롭 — 제품 변형 없이 fit + padding.

        실패 시 None 반환 (호출자가 fit-and-letterbox로 폴백).
        """
        try:
            from src.photoroom.client import PhotoroomClient
        except ImportError:
            return None

        target_w = int(v.get("width", 1500))
        target_h = int(v.get("height", 2250))
        padding = float(v.get("photoroom_padding", 0.05))

        # PIL Image → bytes
        if img.mode != "RGB":
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            else:
                img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        img_bytes = buf.getvalue()

        try:
            client = PhotoroomClient()
            result_bytes = client.crop_to_aspect(
                image_bytes=img_bytes,
                output_size=f"{target_w}x{target_h}",
                padding=padding,
                keep_background=True,
                background_color="FFFFFF",
            )
        except Exception as e:
            logger.warning(
                f"[Resizer] Photoroom 크롭 실패 → fit-and-letterbox 폴백: {e}")
            return None

        # 결과 저장
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(result_bytes)
        logger.info(
            f"[Resizer] Photoroom 크롭 성공: outputSize={target_w}x{target_h}, "
            f"padding={padding}, {len(result_bytes)//1024}KB")
        return dest

    def _do_crop(self, img: Image.Image, v: dict) -> Path:
        """크롭 진입점 — Photoroom 옵션이 켜져 있으면 우선 시도, 실패 시 로컬 폴백.

        설정: v["use_photoroom"] = True/False (settings.yaml crop_vertical)
        """
        sub = v.get("subfolder", "crop")
        fname = v.get("filename", "100_list.jpg")
        dest = self.output_dir / sub / fname

        # Photoroom 옵션 우선 시도
        if bool(v.get("use_photoroom", False)):
            result = self._do_crop_photoroom(img, v, dest)
            if result is not None:
                return result
            # 실패 시 폴백

        return self._do_crop_local(img, v, dest)

    def _do_crop_local(self, img: Image.Image, v: dict, dest: Path) -> Path:
        """안전한 fit-and-letterbox: 콘텐츠 절대 잘리지 않음.

        알고리즘 (콘텐츠 손실 0 보장):
          1. 콘텐츠 bbox 감지 (선택적 — 실패해도 안전)
          2. bbox + 여유 마진을 이미지 경계 안에서 크롭 (흰 여백만 제거, 콘텐츠 보존)
          3. 비율 유지로 목표 사이즈 안에 들어가도록 축소 (fit)
          4. 흰배경 캔버스에 중앙 배치 (letterbox)

        bbox 감지가 실패하더라도 (3)+(4)는 단순 fit-and-letterbox로 동작 → 안전.
        """
        target_w = int(v.get("width", 1500))
        target_h = int(v.get("height", 2250))
        white_thr = int(v.get("white_threshold", 235))
        margin_ratio = float(v.get("margin_ratio", 0.12))
        min_ratio = float(v.get("content_min_ratio", 0.005))
        w, h = img.size

        # RGBA → RGB 흰배경 합성 (검출/리사이즈 일관성)
        if img.mode != "RGB":
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            else:
                img = img.convert("RGB")

        # 1) 콘텐츠 bbox 감지
        x_min, y_min, x_max, y_max = self._detect_content_bbox(
            img, white_thr, min_ratio)
        bw = x_max - x_min + 1
        bh = y_max - y_min + 1

        # 2) bbox + 마진 → 이미지 경계 안에서 크롭 (흰 여백만 제거)
        pad = int(max(bw, bh) * margin_ratio)
        cx_min = max(0, x_min - pad)
        cy_min = max(0, y_min - pad)
        cx_max = min(w - 1, x_max + pad)
        cy_max = min(h - 1, y_max + pad)
        # 안전망: 검출이 너무 좁게 잡혔으면 전체 이미지 사용
        if (cx_max - cx_min + 1) < w * 0.3 or (cy_max - cy_min + 1) < h * 0.3:
            cx_min, cy_min = 0, 0
            cx_max, cy_max = w - 1, h - 1
        cropped = img.crop((cx_min, cy_min, cx_max + 1, cy_max + 1))
        cw, ch = cropped.size

        # 3) 비율 유지로 목표 사이즈 안에 들어가도록 축소 (fit)
        scale = min(target_w / cw, target_h / ch)
        new_w = max(1, int(round(cw * scale)))
        new_h = max(1, int(round(ch * scale)))
        resized = cropped.resize((new_w, new_h), Image.LANCZOS)

        # 4) 흰배경 캔버스에 중앙 배치 (letterbox)
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        offset_x = (target_w - new_w) // 2
        offset_y = (target_h - new_h) // 2
        canvas.paste(resized, (offset_x, offset_y))

        logger.info(
            f"[Resizer] fit-and-letterbox: bbox=({bw}×{bh}) → "
            f"crop=({cw}×{ch}) → fit=({new_w}×{new_h}) "
            f"→ canvas=({target_w}×{target_h}, offset={offset_x},{offset_y})")

        return self._save_jpeg(canvas, dest)

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
            dest = self.output_dir / v.get("subfolder", "crop") / v.get("filename", "100_list.jpg")
            if dest.exists() and not overwrite:
                logger.info(f"[Resizer] 스킵(덮어쓰기 OFF): {dest}")
            else:
                result["crop"] = self._do_crop(img, v)

        return result
