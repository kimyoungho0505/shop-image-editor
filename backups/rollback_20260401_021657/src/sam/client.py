"""SAM 기반 전경 마스크 생성 및 그림자 추출 클라이언트.

지원 모델:
  - sam_vit_h / sam_vit_l / sam_vit_b  (원본 SAM, GPU 권장)
  - mobile_sam  (MobileSAM, CPU에서도 빠름)
"""
import io
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger
from PIL import Image, ImageFilter


# 체크포인트 자동 경로 매핑
_CHECKPOINT_URLS = {
    "sam_vit_h": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
    "sam_vit_l": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth",
    "sam_vit_b": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth",
    "mobile_sam": "https://raw.githubusercontent.com/ChaoningZhang/MobileSAM/master/weights/mobile_sam.pt",
}

_CHECKPOINT_FILES = {
    "sam_vit_h": "sam_vit_h_4b8939.pth",
    "sam_vit_l": "sam_vit_l_0b3195.pth",
    "sam_vit_b": "sam_vit_b_01ec64.pth",
    "mobile_sam": "mobile_sam.pt",
}

# SAM 모델 타입 → segment_anything registry key
_SAM_REGISTRY_KEY = {
    "sam_vit_h": "vit_h",
    "sam_vit_l": "vit_l",
    "sam_vit_b": "vit_b",
    "mobile_sam": "vit_t",
}


class SamShadowClient:
    """SAM 기반 전경 마스크 → 그림자 추출 통합 클라이언트."""

    def __init__(self, model_variant: str = "mobile_sam",
                 checkpoint: Optional[str] = None,
                 models_dir: Optional[str] = None,
                 force_device: Optional[str] = None):
        self._model_variant = model_variant
        self._models_dir = models_dir or str(
            Path(__file__).resolve().parent.parent.parent / "models")
        self._checkpoint = checkpoint
        self._force_device = force_device  # "cpu" or "cuda" or None(auto)
        self._predictor = None
        self._device = None
        self._loaded_variant = None  # 현재 로드된 모델 추적

    def _resolve_checkpoint(self) -> str:
        """체크포인트 경로 결정. 지정값 > models/ 폴더 자동 탐색."""
        if self._checkpoint and os.path.isfile(self._checkpoint):
            return self._checkpoint

        filename = _CHECKPOINT_FILES.get(self._model_variant)
        if not filename:
            raise FileNotFoundError(
                f"알 수 없는 모델: {self._model_variant}. "
                f"지원: {list(_CHECKPOINT_FILES.keys())}")

        auto_path = os.path.join(self._models_dir, filename)
        if os.path.isfile(auto_path):
            return auto_path

        # 자동 다운로드 시도
        url = _CHECKPOINT_URLS.get(self._model_variant, "")
        if url:
            logger.info(f"체크포인트 자동 다운로드: {filename} ...")
            os.makedirs(self._models_dir, exist_ok=True)
            try:
                import requests
                resp = requests.get(url, stream=True, timeout=30)
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(auto_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = downloaded / total * 100
                            logger.info(f"  다운로드 중... {downloaded // (1024*1024)}MB / {total // (1024*1024)}MB ({pct:.0f}%)")
                logger.info(f"체크포인트 다운로드 완료: {auto_path}")
                return auto_path
            except Exception as e:
                # 다운로드 실패 시 불완전 파일 삭제
                if os.path.isfile(auto_path):
                    os.remove(auto_path)
                raise FileNotFoundError(
                    f"체크포인트 자동 다운로드 실패: {e}\n"
                    f"수동 다운로드: {url}\n"
                    f"다운로드 후 models/ 폴더에 저장하세요.")

        raise FileNotFoundError(
            f"체크포인트 파일을 찾을 수 없습니다: {auto_path}")

    def set_variant(self, model_variant: str, force_device: Optional[str] = None):
        """모델 변경 시 기존 모델 언로드."""
        if model_variant != self._model_variant or force_device != self._force_device:
            self._model_variant = model_variant
            self._force_device = force_device
            self._predictor = None
            self._loaded_variant = None

    def _ensure_loaded(self):
        """모델을 lazy load한다."""
        # 모델이 변경되었으면 다시 로드
        if (self._predictor is not None
                and self._loaded_variant == self._model_variant):
            return

        import torch

        # 디바이스 결정
        if self._force_device:
            self._device = self._force_device
        elif torch.cuda.is_available():
            self._device = "cuda"
        else:
            self._device = "cpu"

        checkpoint_path = self._resolve_checkpoint()
        registry_key = _SAM_REGISTRY_KEY.get(self._model_variant)

        logger.info(f"SAM 모델 로딩: {self._model_variant} ({registry_key}) "
                    f"on {self._device}...")
        t0 = time.time()

        if self._model_variant == "mobile_sam":
            from mobile_sam import sam_model_registry, SamPredictor
        else:
            from segment_anything import sam_model_registry, SamPredictor

        model = sam_model_registry[registry_key](checkpoint=checkpoint_path)
        model.to(self._device)
        model.eval()
        self._predictor = SamPredictor(model)
        self._loaded_variant = self._model_variant

        elapsed = time.time() - t0
        logger.info(f"SAM 모델 로드 완료 ({elapsed:.1f}s, device={self._device})")

    @staticmethod
    def detect_gpu_capability() -> dict:
        """GPU 정보와 사용 가능한 모델 목록을 반환한다.

        CPU 모델 (항상 사용 가능):
          - mobile_sam (CPU): 경량 모델, 3~5초
          - sam_vit_b (CPU): 원본 SAM, 10~30초

        GPU 모델 (VRAM 충분 시 추가):
          - sam_vit_b (GPU), sam_vit_l (GPU), sam_vit_h (GPU)
        """
        # CPU 모델은 항상 포함
        cpu_models = [
            "mobile_sam (CPU)",
            "sam_vit_b (CPU)",
        ]

        try:
            import torch
            if not torch.cuda.is_available():
                return {
                    "has_gpu": False,
                    "gpu_name": "",
                    "vram_gb": 0,
                    "models": cpu_models,
                }
            props = torch.cuda.get_device_properties(0)
            vram_gb = getattr(props, "total_memory", getattr(props, "total_mem", 0)) / 1e9
            name = torch.cuda.get_device_name(0)
            gpu_models = []
            if vram_gb >= 2:
                gpu_models.append("sam_vit_b (GPU)")
            if vram_gb >= 4:
                gpu_models.append("sam_vit_l (GPU)")
            if vram_gb >= 6:
                gpu_models.append("sam_vit_h (GPU)")
            return {
                "has_gpu": True,
                "gpu_name": name,
                "vram_gb": round(vram_gb, 1),
                "models": cpu_models + gpu_models,
            }
        except ImportError:
            return {
                "has_gpu": False,
                "gpu_name": "",
                "vram_gb": 0,
                "models": cpu_models,
            }

    @staticmethod
    def parse_variant_selection(selection: str) -> tuple:
        """GUI 선택값에서 모델명과 디바이스를 분리한다.

        Returns:
            (model_variant, device): 예) ("mobile_sam", "cpu"), ("sam_vit_b", "cuda")
        """
        selection = selection.strip()
        if "(GPU)" in selection:
            variant = selection.replace("(GPU)", "").strip()
            return variant, "cuda"
        else:
            variant = selection.replace("(CPU)", "").strip()
            return variant, "cpu"

    def generate_mask(self, image_rgb: np.ndarray) -> np.ndarray:
        """이미지에서 전경 마스크를 생성한다.

        Args:
            image_rgb: HxWx3 RGB uint8 배열

        Returns:
            HxW bool 배열 (True = 전경)
        """
        self._ensure_loaded()

        h, w = image_rgb.shape[:2]
        self._predictor.set_image(image_rgb)

        # 자동 프롬프트: 중앙 3점 (positive) + 모서리 4점 (negative)
        point_coords = np.array([
            [w // 2, h // 2],        # 중앙
            [w // 2, h // 3],        # 상단 1/3
            [w // 2, 2 * h // 3],    # 하단 2/3
            [int(w * 0.05), int(h * 0.05)],   # 좌상 (배경)
            [int(w * 0.95), int(h * 0.05)],   # 우상 (배경)
            [int(w * 0.05), int(h * 0.95)],   # 좌하 (배경)
            [int(w * 0.95), int(h * 0.95)],   # 우하 (배경)
        ])
        point_labels = np.array([1, 1, 1, 0, 0, 0, 0])

        masks, scores, _ = self._predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            multimask_output=True,
        )

        # 최고 IoU 마스크 선택
        best_idx = int(np.argmax(scores))
        best_mask = masks[best_idx]
        best_score = scores[best_idx]

        logger.info(f"SAM 마스크 생성: score={best_score:.3f}, "
                    f"전경 비율={best_mask.sum() / best_mask.size:.1%}")

        return best_mask

    def extract_shadow(self, mask_bytes: bytes, original_bytes: bytes,
                       config: dict = None) -> bytes:
        """SAM 마스크를 사용하여 그림자를 추출하고 합성한다.

        기존 _preserve_natural_shadow와 동일한 입출력 형태.

        Args:
            mask_bytes: 배경제거 결과 투명 PNG (alpha = 제품 마스크)
            original_bytes: 원본 이미지 바이트
            config: shadow_extract 설정 dict

        Returns:
            합성된 PNG 바이트 (RGB, 불투명)
        """
        if config is None:
            config = {}

        opacity = config.get("opacity", 90) / 100.0
        threshold = config.get("threshold", 20)
        blur_pct = config.get("blur", 5) / 100.0
        search_top_pct = config.get("search_top", 5) / 100.0
        search_bottom_pct = config.get("search_bottom", 100) / 100.0
        search_sides_pct = config.get("search_sides", 45) / 100.0
        mask_expand_pct = config.get("mask_expand", 2) / 100.0

        # ── 1. 누끼 결과에서 제품 마스크 추출 ──
        mask_img = Image.open(io.BytesIO(mask_bytes)).convert("RGBA")
        mask_arr = np.array(mask_img)
        alpha = mask_arr[:, :, 3]
        ph, pw = alpha.shape

        product_pixels = alpha > 128
        coords = np.argwhere(product_pixels)
        if len(coords) == 0:
            logger.warning("SAM 그림자: 마스크에서 제품을 찾을 수 없음")
            return mask_bytes

        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
        prod_h = y_max - y_min
        prod_w = x_max - x_min

        # ── 2. 원본 이미지 로드 ──
        orig_img = Image.open(io.BytesIO(original_bytes)).convert("RGB")
        if orig_img.size != (pw, ph):
            orig_img = orig_img.resize((pw, ph), Image.LANCZOS)
        orig_arr = np.array(orig_img).astype(np.float32)

        # ── 3. SAM으로 정밀 전경 마스크 생성 ──
        logger.info("SAM 전경 마스크 생성 중...")
        t0 = time.time()
        orig_rgb = np.array(orig_img)  # uint8 RGB
        sam_mask = self.generate_mask(orig_rgb)  # HxW bool
        sam_time = time.time() - t0
        logger.info(f"SAM 마스크 생성 완료 ({sam_time:.1f}s)")

        # SAM 마스크를 제품 마스크로 사용 (원본 alpha보다 정밀)
        product_mask_uint8 = (sam_mask.astype(np.uint8)) * 255

        # ── 4. 배경색 추정 ──
        edge_margin = max(10, min(ph, pw) // 50)
        edge_pixels = np.concatenate([
            orig_arr[:edge_margin, :].reshape(-1, 3),
            orig_arr[-edge_margin:, :].reshape(-1, 3),
            orig_arr[:, :edge_margin].reshape(-1, 3),
            orig_arr[:, -edge_margin:].reshape(-1, 3),
        ])
        bg_color = np.median(edge_pixels, axis=0)

        # ── 5. 제품 마스크 확장 → 제품 제거 ──
        product_mask_pil = Image.fromarray(product_mask_uint8, "L")
        dilate_radius = max(3, int(min(prod_w, prod_h) * mask_expand_pct))
        dilated = product_mask_pil.filter(
            ImageFilter.GaussianBlur(radius=dilate_radius))
        product_mask_dilated = np.array(dilated).astype(np.float32) / 255.0

        shadow_layer = orig_arr.copy()
        for c in range(3):
            shadow_layer[:, :, c] = (
                orig_arr[:, :, c] * (1.0 - product_mask_dilated) +
                bg_color[c] * product_mask_dilated
            )

        # ── 6. 그림자 추출 (method에 따라 분기) ──
        method = config.get("method", "level_correction")
        if method == "transplant":
            # 원본이식: 절대 명암차 보존 (255 - (bg - pixel))
            darkness = np.zeros_like(shadow_layer)
            for c in range(3):
                darkness[:, :, c] = np.clip(bg_color[c] - shadow_layer[:, :, c], 0, 255)
            white_balanced = 255.0 - darkness
            logger.info("SAM 그림자: 원본이식 방식 적용")
        else:
            # 레벨보정: 비율 정규화 (pixel / bg * 255)
            white_balanced = np.zeros_like(shadow_layer)
            for c in range(3):
                if bg_color[c] > 1:
                    white_balanced[:, :, c] = np.clip(
                        shadow_layer[:, :, c] / bg_color[c] * 255.0, 0, 255)
                else:
                    white_balanced[:, :, c] = 255.0

        # ── 7. 그림자 탐색 범위 제한 ──
        search_margin_x = int(prod_w * search_sides_pct)
        search_margin_top = int(prod_h * search_top_pct)
        search_margin_bottom = int(prod_h * search_bottom_pct)
        search_y_min = max(0, y_min - search_margin_top)
        search_y_max = min(ph, y_max + search_margin_bottom)
        search_x_min = max(0, x_min - search_margin_x)
        search_x_max = min(pw, x_max + search_margin_x)

        canvas = np.full((ph, pw, 3), 255.0, dtype=np.float32)
        canvas[search_y_min:search_y_max, search_x_min:search_x_max] = \
            white_balanced[search_y_min:search_y_max, search_x_min:search_x_max]

        # 경계 페이드아웃
        fade_size = max(5, int(min(prod_w, prod_h) * blur_pct))
        fade_mask = np.zeros((ph, pw), dtype=np.float32)
        fade_mask[search_y_min:search_y_max, search_x_min:search_x_max] = 1.0
        fade_pil = Image.fromarray((fade_mask * 255).astype(np.uint8), "L")
        fade_pil = fade_pil.filter(ImageFilter.GaussianBlur(radius=fade_size))
        fade_smooth = np.array(fade_pil).astype(np.float32) / 255.0
        fade_3d = fade_smooth[:, :, np.newaxis]
        canvas = canvas * fade_3d + 255.0 * (1.0 - fade_3d)

        # ── 8. 거리 기반 감쇠: 피사체 가까이는 진하게, 멀어질수록 옅게 ──
        import cv2 as _cv2
        dist = _cv2.distanceTransform(
            255 - product_mask_uint8, _cv2.DIST_L2, 5
        ).astype(np.float32)
        falloff_pct = config.get("distance_falloff", 60) / 100.0
        max_shadow_range = max(30, int(max(prod_w, prod_h) * falloff_pct))
        dist_falloff = np.clip(1.0 - (dist / max_shadow_range), 0, 1)
        dist_falloff = np.sqrt(dist_falloff)
        dist_falloff_3d = dist_falloff[:, :, np.newaxis]

        shadow_darkness = 255.0 - canvas
        shadow_darkness = shadow_darkness * dist_falloff_3d
        canvas = 255.0 - shadow_darkness

        # ── 9. opacity 적용 ──
        pure_white = np.full((ph, pw, 3), 255.0, dtype=np.float32)
        canvas = canvas * opacity + pure_white * (1.0 - opacity)

        # threshold 노이즈 제거
        canvas_brightness = np.mean(canvas, axis=2)
        near_white = canvas_brightness > (255 - threshold)
        canvas[near_white] = 255.0

        # ── 9. 누끼 제품을 위에 합성 ──
        product_rgb = mask_arr[:, :, :3].astype(np.float32)
        product_alpha = alpha.astype(np.float32) / 255.0
        alpha_3d = product_alpha[:, :, np.newaxis]
        canvas = product_rgb * alpha_3d + canvas * (1.0 - alpha_3d)

        result_img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
        logger.info(f"SAM 그림자 추출+합성 완료 (opacity={opacity:.0%})")

        buf = io.BytesIO()
        result_img.save(buf, format="PNG")
        return buf.getvalue()
