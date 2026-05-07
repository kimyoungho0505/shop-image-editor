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

    def _do_crop(self, img: Image.Image, v: dict) -> Path:
        """제품 전체를 보존하는 1500×2250 출력.

        알고리즘:
          1. 제품 바운딩 박스 감지
          2. 약간의 여유 패딩 추가
          3. 1500:2250 (2:3) 비율로 박스 확장 (콘텐츠 절대 손실 없음)
          4. 박스가 이미지 경계 밖이면 흰배경 캔버스로 합성
          5. 최종 1500×2250으로 LANCZOS 리사이즈
        """
        target_w = int(v.get("width", 1500))
        target_h = int(v.get("height", 2250))
        white_thr = int(v.get("white_threshold", 235))
        # 콘텐츠 주변 여유 비율 (콘텐츠 폭/높이 대비 %)
        margin_ratio = float(v.get("margin_ratio", 0.05))
        # 행/열별 콘텐츠 인정 비율 (JPEG 노이즈 무시용)
        min_ratio = float(v.get("content_min_ratio", 0.005))
        w, h = img.size

        # 1) 콘텐츠 바운딩 박스
        x_min, y_min, x_max, y_max = self._detect_content_bbox(
            img, white_thr, min_ratio)
        bw = x_max - x_min + 1
        bh = y_max - y_min + 1

        # 2) 여유 패딩 추가
        pad = int(max(bw, bh) * margin_ratio)
        x_min_p = x_min - pad
        y_min_p = y_min - pad
        x_max_p = x_max + pad
        y_max_p = y_max + pad
        bw_p = x_max_p - x_min_p + 1
        bh_p = y_max_p - y_min_p + 1

        # 3) 목표 비율 (target_w : target_h, 보통 2:3)에 맞춰 박스 확장
        # 현재 box ratio = bw_p / bh_p, target ratio = target_w / target_h
        # ratio 비교로 가로/세로 중 어느 쪽을 늘릴지 결정
        if bw_p * target_h > bh_p * target_w:
            # 박스가 너무 가로로 김 → 세로를 늘려 비율 맞춤
            new_h = int(round(bw_p * target_h / target_w))
            extra = new_h - bh_p
            y_min_p -= extra // 2
            y_max_p += extra - extra // 2
        else:
            # 박스가 너무 세로로 김 → 가로를 늘려 비율 맞춤
            new_w = int(round(bh_p * target_w / target_h))
            extra = new_w - bw_p
            x_min_p -= extra // 2
            x_max_p += extra - extra // 2

        win_w = x_max_p - x_min_p + 1
        win_h = y_max_p - y_min_p + 1

        # 4) 흰배경 캔버스에 콘텐츠 부분 합성 (박스가 이미지 밖이어도 안전)
        canvas = Image.new("RGB", (win_w, win_h), (255, 255, 255))
        # 이미지에서 실제로 가져올 영역
        src_l = max(0, x_min_p)
        src_t = max(0, y_min_p)
        src_r = min(w, x_max_p + 1)
        src_b = min(h, y_max_p + 1)
        # 캔버스 내 붙일 위치
        dst_l = src_l - x_min_p
        dst_t = src_t - y_min_p

        if src_r > src_l and src_b > src_t:
            patch = img.crop((src_l, src_t, src_r, src_b))
            if img.mode == "RGBA":
                canvas.paste(patch.convert("RGBA"), (dst_l, dst_t),
                             mask=patch.split()[3] if patch.mode == "RGBA" else None)
            else:
                canvas.paste(patch.convert("RGB"), (dst_l, dst_t))

        # 5) 최종 1500×2250로 리사이즈
        final = canvas.resize((target_w, target_h), Image.LANCZOS)

        logger.info(
            f"[Resizer] 스마트 크롭: 콘텐츠 bbox=({bw}×{bh}) "
            f"→ 패딩 박스 ({win_w}×{win_h}) → 리사이즈 ({target_w}×{target_h})")

        sub = v.get("subfolder", "crop")
        fname = v.get("filename", "main.jpg")
        dest = self.output_dir / sub / fname
        return self._save_jpeg(final, dest)

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
