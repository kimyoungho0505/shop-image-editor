"""전체 이미지 편집 파이프라인 오케스트레이터."""
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import yaml
from loguru import logger

from .analyzer.vision_client import VisionClient
from .analyzer.openai_vision_client import OpenAIVisionClient
from .analyzer.gemini_vision_client import GeminiVisionClient
from .analyzer.prompt_builder import PromptBuilder
from .analyzer.result_parser import ResultParser, EditInstruction
from .photoroom.client import PhotoroomClient
from .removebg.client import RemoveBgClient
from .claid.client import ClaidClient
from .opencv_enhance.enhancer import OpenCVEnhancer
from .exporter.namer import FileNamer
from .exporter.optimizer import ImageOptimizer
from .utils.image_io import load_image, get_image_files
from .utils.category import CategoryManager
from .sam.client import SamShadowClient


def _add_ground_shadow(image_bytes: bytes) -> bytes:
    """중앙 배치된 이미지에 자연스러운 접지 그림자를 추가한다."""
    from PIL import Image, ImageFilter
    import io

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(img)
    h, w = arr.shape[:2]

    # 배경색 추정: 가장자리 10px 평균 (Claid HDR 후 순백이 아닐 수 있음)
    edge_pixels = np.concatenate([
        arr[:10, :].reshape(-1, 3),
        arr[-10:, :].reshape(-1, 3),
        arr[:, :10].reshape(-1, 3),
        arr[:, -10:].reshape(-1, 3),
    ])
    bg_color = np.median(edge_pixels, axis=0)

    # 제품 영역 감지: 배경색과 30 이상 차이나는 픽셀
    diff = np.abs(arr.astype(np.float32) - bg_color.reshape(1, 1, 3))
    not_bg = np.any(diff > 30, axis=2)

    # 가장자리 5% 무시 (노이즈 방지)
    margin_y = int(h * 0.05)
    margin_x = int(w * 0.05)
    not_bg[:margin_y, :] = False
    not_bg[-margin_y:, :] = False
    not_bg[:, :margin_x] = False
    not_bg[:, -margin_x:] = False

    coords = np.argwhere(not_bg)
    if len(coords) == 0:
        logger.warning("그림자 생성: 제품 영역을 찾을 수 없음")
        return image_bytes

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)
    prod_w = x_max - x_min
    prod_h = y_max - y_min
    prod_cx = (x_min + x_max) / 2.0

    logger.info(f"그림자 생성: 제품 bbox=({x_min},{y_min})-({x_max},{y_max}), "
                f"크기={prod_w}x{prod_h}, 배경색={bg_color.astype(int)}")

    # 탑다운 그림자: 제품 실루엣 바로 아래에 사방으로 퍼지는 접지 그림자
    # 제품 하단부의 실루엣을 기반으로 그림자 마스크 생성
    prod_cy = (y_min + y_max) / 2.0

    # 제품 하단 30% 영역의 비배경 픽셀을 그림자 시드로 사용
    seed_y_start = y_min + int(prod_h * 0.7)
    seed_region = not_bg[seed_y_start:y_max + 1, :]

    # 시드 마스크를 아래로 이동 (제품 바로 아래에 그림자)
    shadow_mask = np.zeros((h, w), dtype=np.float32)
    shift_down = max(3, int(prod_h * 0.02))  # 약간 아래로
    paste_y = min(seed_y_start + shift_down, h - seed_region.shape[0])
    if paste_y + seed_region.shape[0] <= h:
        shadow_mask[paste_y:paste_y + seed_region.shape[0], :] = seed_region.astype(np.float32)

    # 강한 가우시안 블러로 부드럽게 퍼뜨림 (탑다운 느낌)
    blur_radius = max(15, int(prod_w * 0.04))
    shadow_pil = Image.fromarray((shadow_mask * 255).astype(np.uint8), "L")
    shadow_pil = shadow_pil.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    shadow_mask = np.array(shadow_pil).astype(np.float32) / 255.0

    # 제품 영역 내부는 그림자 제외 (제품 위에 그림자 안 생기도록)
    shadow_mask[:y_max - int(prod_h * 0.05), :] = 0

    # 다시 블러 (경계 부드럽게)
    shadow_pil = Image.fromarray((shadow_mask * 255).astype(np.uint8), "L")
    shadow_pil = shadow_pil.filter(ImageFilter.GaussianBlur(radius=blur_radius // 2))
    shadow_mask = np.array(shadow_pil).astype(np.float32) / 255.0

    # 그림자 강도: 최대 15% 어두움
    shadow_intensity = 0.15
    shadow_mask = shadow_mask / max(shadow_mask.max(), 0.001) * shadow_intensity

    # 배경에 그림자 합성
    result = arr.astype(np.float32)
    for c in range(3):
        result[:, :, c] = result[:, :, c] * (1.0 - shadow_mask)

    result_img = Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    result_img.save(buf, format="PNG")
    logger.info(f"그림자 생성 완료: 제품={prod_w}x{prod_h}, blur={blur_radius}")
    return buf.getvalue()


def _preserve_natural_shadow(mask_bytes: bytes, original_bytes: bytes,
                             shadow_direction: str = None,
                             config: dict = None) -> bytes:
    """원본 이미지에서 제품을 제거하고 그림자 그라데이션을 그대로 보존하여 합성한다.

    핵심 원리: threshold로 그림자를 이진 판정하지 않고,
    원본에서 제품 영역을 배경색으로 채운 뒤 레벨 보정으로
    순수 배경 → 흰색, 그림자 → 자연 그라데이션 유지.

    Args:
        mask_bytes: 배경제거 결과 투명 PNG (alpha = 제품 마스크)
        original_bytes: 원본 이미지 바이트
        shadow_direction: (미사용, 호환성 유지)
        config: shadow_extract 설정 dict
            - opacity: 그림자 진하기 (0~100, 기본 90)
            - threshold: 배경 판정 허용 오차 (기본 20)
            - blur: 그림자 블러 정도 (제품 크기 대비 %, 기본 5)
            - search_top: 그림자 탐색 상단 범위 (제품 높이 대비 %, 기본 5)
            - search_bottom: 그림자 탐색 하단 범위 (제품 높이 대비 %, 기본 100)
            - search_sides: 그림자 탐색 좌우 범위 (제품 폭 대비 %, 기본 45)
            - mask_expand: 제품 마스크 확장 (제품 크기 대비 %, 기본 2)
    """
    from PIL import Image, ImageFilter
    import io

    if config is None:
        config = {}

    # 설정 읽기
    opacity = config.get("opacity", 90) / 100.0
    threshold = config.get("threshold", 20)
    blur_pct = config.get("blur", 5) / 100.0
    search_top_pct = config.get("search_top", 5) / 100.0
    search_bottom_pct = config.get("search_bottom", 100) / 100.0
    search_sides_pct = config.get("search_sides", 45) / 100.0
    mask_expand_pct = config.get("mask_expand", 2) / 100.0

    logger.info(f"그림자 추출 설정: opacity={opacity:.0%}, threshold={threshold}, "
                f"blur={blur_pct:.1%}, 탐색=상{search_top_pct:.0%}/하{search_bottom_pct:.0%}"
                f"/좌우{search_sides_pct:.0%}, 마스크확장={mask_expand_pct:.1%}")

    # ── 1. 배경제거 결과에서 제품 마스크 추출 ──
    mask_img = Image.open(io.BytesIO(mask_bytes)).convert("RGBA")
    mask_arr = np.array(mask_img)
    alpha = mask_arr[:, :, 3]
    ph, pw = alpha.shape

    product_pixels = alpha > 128
    coords = np.argwhere(product_pixels)
    if len(coords) == 0:
        logger.warning("그림자 추출: 마스크에서 제품을 찾을 수 없음")
        return mask_bytes

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)
    prod_h = y_max - y_min
    prod_w = x_max - x_min
    logger.info(f"그림자 추출: 제품 bbox=({x_min},{y_min})-({x_max},{y_max}), "
                f"크기={prod_w}x{prod_h}")

    # ── 2. 원본 이미지 로드 & 크기 맞춤 ──
    orig_img = Image.open(io.BytesIO(original_bytes)).convert("RGB")
    orig_w, orig_h = orig_img.size
    if (orig_w, orig_h) != (pw, ph):
        orig_resized = orig_img.resize((pw, ph), Image.LANCZOS)
    else:
        orig_resized = orig_img
    orig_arr = np.array(orig_resized).astype(np.float32)

    # ── 3. 배경색 추정 (원본 이미지 가장자리) ──
    edge_margin = max(10, min(ph, pw) // 50)
    edge_pixels = np.concatenate([
        orig_arr[:edge_margin, :].reshape(-1, 3),
        orig_arr[-edge_margin:, :].reshape(-1, 3),
        orig_arr[:, :edge_margin].reshape(-1, 3),
        orig_arr[:, -edge_margin:].reshape(-1, 3),
    ])
    bg_color = np.median(edge_pixels, axis=0)
    bg_brightness = np.mean(bg_color)
    logger.info(f"그림자 추출: 배경색 추정 = {bg_color.astype(int)}, 밝기={bg_brightness:.0f}")

    # ── 4. 제품 마스크 확장 (제품 → 배경색으로 채우기 위한 영역) ──
    product_mask_uint8 = (alpha > 128).astype(np.uint8) * 255
    product_mask_pil = Image.fromarray(product_mask_uint8, "L")
    dilate_radius = max(3, int(min(prod_w, prod_h) * mask_expand_pct))
    dilated = product_mask_pil.filter(ImageFilter.GaussianBlur(radius=dilate_radius))
    product_mask_dilated = np.array(dilated).astype(np.float32) / 255.0  # 0~1 소프트 마스크

    # ── 5. 원본에서 제품 제거 → 배경+그림자만 남기기 ──
    # 제품 영역을 배경색으로 부드럽게 채움 (소프트 마스크로 자연스러운 경계)
    shadow_layer = orig_arr.copy()
    for c in range(3):
        shadow_layer[:, :, c] = (
            orig_arr[:, :, c] * (1.0 - product_mask_dilated) +
            bg_color[c] * product_mask_dilated
        )

    # ── 6. 레벨 보정: 배경 → 순수 흰색, 그림자 그라데이션 보존 ──
    # 원리: 각 채널을 (pixel / bg_color) * 255로 정규화
    # 배경색과 같은 밝기 → 255(흰), 그보다 어두운 곳 → 비례적으로 어둡게 유지
    white_balanced = np.zeros_like(shadow_layer)
    for c in range(3):
        if bg_color[c] > 1:
            white_balanced[:, :, c] = np.clip(
                shadow_layer[:, :, c] / bg_color[c] * 255.0, 0, 255
            )
        else:
            white_balanced[:, :, c] = 255.0

    # ── 7. 그림자 탐색 범위 제한 (범위 밖은 순수 흰색) ──
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

    # 탐색 범위 경계를 부드럽게 페이드아웃
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
    # 최대 감쇠 거리 = 제품 크기의 60%
    falloff_pct = config.get("distance_falloff", 60) / 100.0
    max_shadow_range = max(30, int(max(prod_w, prod_h) * falloff_pct))
    # 거리 감쇠: 가까울수록 1.0, 멀수록 0.0 (제곱근 커브로 자연스럽게)
    dist_falloff = np.clip(1.0 - (dist / max_shadow_range), 0, 1)
    dist_falloff = np.sqrt(dist_falloff)  # 제곱근 → 급격하지 않은 감쇠
    dist_falloff_3d = dist_falloff[:, :, np.newaxis]

    # 그림자 어두운 정도를 거리에 따라 감쇠
    # canvas가 255에 가까울수록 그림자 없음, 255보다 어두울수록 그림자
    shadow_darkness = 255.0 - canvas  # 그림자 어두운 정도 (0=없음, 양수=그림자)
    shadow_darkness = shadow_darkness * dist_falloff_3d  # 거리 감쇠 적용
    canvas = 255.0 - shadow_darkness  # 다시 밝기로 변환

    # ── 9. opacity 적용: 흰색 ↔ 그림자 레이어 블렌딩 ──
    # opacity=1.0이면 그림자 100% 보존, 0.0이면 순수 흰색
    pure_white = np.full((ph, pw, 3), 255.0, dtype=np.float32)
    canvas = canvas * opacity + pure_white * (1.0 - opacity)

    # threshold로 미세 노이즈 제거: 거의 흰색인 영역은 완전 흰색으로
    canvas_brightness = np.mean(canvas, axis=2)
    near_white = canvas_brightness > (255 - threshold)
    canvas[near_white] = 255.0

    shadow_pixel_count = np.sum(canvas_brightness < 250)
    shadow_min_val = canvas[canvas_brightness < 250].min() if shadow_pixel_count > 0 else 255
    logger.info(f"그림자 추출: 그림자 픽셀={shadow_pixel_count}, "
                f"최소 밝기={shadow_min_val:.0f}")

    # ── 9. 누끼 제품을 위에 알파 합성 ──
    product_rgb = mask_arr[:, :, :3].astype(np.float32)
    product_alpha = alpha.astype(np.float32) / 255.0
    alpha_3d = product_alpha[:, :, np.newaxis]
    canvas = product_rgb * alpha_3d + canvas * (1.0 - alpha_3d)

    result_img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    logger.info(f"그림자 추출+합성 완료 (opacity={opacity:.0%})")

    buf = io.BytesIO()
    result_img.save(buf, format="PNG")
    return buf.getvalue()


def _transplant_natural_shadow(mask_bytes: bytes, original_bytes: bytes,
                               shadow_direction: str = None,
                               config: dict = None) -> bytes:
    """원본 이미지의 그림자를 절대 명암차 방식으로 그대로 이식한다.

    핵심 원리: 레벨보정(비율 변환)이 아닌 절대 명암차를 보존.
    원본에서 (배경색 - 실제픽셀) = 어두워진 양을 구해
    흰 배경에 그대로 적용하여 원본 그림자의 색감/질감을 유지.

    레벨보정과 차이:
      레벨보정: pixel/bg*255 → 비율 변환, 색감 변질 가능
      원본이식: 255-(bg-pixel) → 절대 명암차, 원본 느낌 보존

    Args:
        mask_bytes: 배경제거 결과 투명 PNG (alpha = 제품 마스크)
        original_bytes: 원본 이미지 바이트
        shadow_direction: (미사용, 호환성 유지)
        config: shadow_extract 설정 dict
    """
    from PIL import Image, ImageFilter
    import io

    if config is None:
        config = {}

    opacity = config.get("opacity", 90) / 100.0
    threshold = config.get("threshold", 20)
    blur_pct = config.get("blur", 5) / 100.0
    search_top_pct = config.get("search_top", 5) / 100.0
    search_bottom_pct = config.get("search_bottom", 100) / 100.0
    search_sides_pct = config.get("search_sides", 45) / 100.0
    mask_expand_pct = config.get("mask_expand", 2) / 100.0

    logger.info(f"[원본이식] 그림자 추출 설정: opacity={opacity:.0%}, threshold={threshold}, "
                f"blur={blur_pct:.1%}, 탐색=상{search_top_pct:.0%}/하{search_bottom_pct:.0%}"
                f"/좌우{search_sides_pct:.0%}, 마스크확장={mask_expand_pct:.1%}")

    # ── 1. 배경제거 결과에서 제품 마스크 추출 ──
    mask_img = Image.open(io.BytesIO(mask_bytes)).convert("RGBA")
    mask_arr = np.array(mask_img)
    alpha = mask_arr[:, :, 3]
    ph, pw = alpha.shape

    product_pixels = alpha > 128
    coords = np.argwhere(product_pixels)
    if len(coords) == 0:
        logger.warning("[원본이식] 마스크에서 제품을 찾을 수 없음")
        return mask_bytes

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)
    prod_h = y_max - y_min
    prod_w = x_max - x_min
    logger.info(f"[원본이식] 제품 bbox=({x_min},{y_min})-({x_max},{y_max}), "
                f"크기={prod_w}x{prod_h}")

    # ── 2. 원본 이미지 로드 & 크기 맞춤 ──
    orig_img = Image.open(io.BytesIO(original_bytes)).convert("RGB")
    orig_w, orig_h = orig_img.size
    if (orig_w, orig_h) != (pw, ph):
        orig_resized = orig_img.resize((pw, ph), Image.LANCZOS)
    else:
        orig_resized = orig_img
    orig_arr = np.array(orig_resized).astype(np.float32)

    # ── 3. 배경색 추정 (원본 이미지 가장자리) ──
    edge_margin = max(10, min(ph, pw) // 50)
    edge_pixels = np.concatenate([
        orig_arr[:edge_margin, :].reshape(-1, 3),
        orig_arr[-edge_margin:, :].reshape(-1, 3),
        orig_arr[:, :edge_margin].reshape(-1, 3),
        orig_arr[:, -edge_margin:].reshape(-1, 3),
    ])
    bg_color = np.median(edge_pixels, axis=0)
    logger.info(f"[원본이식] 배경색 추정 = {bg_color.astype(int)}")

    # ── 4. 제품 마스크 확장 ──
    product_mask_uint8 = (alpha > 128).astype(np.uint8) * 255
    product_mask_pil = Image.fromarray(product_mask_uint8, "L")
    dilate_radius = max(3, int(min(prod_w, prod_h) * mask_expand_pct))
    dilated = product_mask_pil.filter(ImageFilter.GaussianBlur(radius=dilate_radius))
    product_mask_dilated = np.array(dilated).astype(np.float32) / 255.0

    # ── 5. 원본에서 제품 제거 → 배경+그림자만 남기기 ──
    shadow_layer = orig_arr.copy()
    for c in range(3):
        shadow_layer[:, :, c] = (
            orig_arr[:, :, c] * (1.0 - product_mask_dilated) +
            bg_color[c] * product_mask_dilated
        )

    # ── 6. 원본이식: 절대 명암차 보존 ──
    # 핵심: darkness = bg_color - pixel (어두워진 양, 양수=그림자)
    # 흰 배경에 적용: result = 255 - darkness
    # → 원본 그림자의 색감/농도/질감이 수학적 변환 없이 그대로 보존됨
    darkness = np.zeros_like(shadow_layer)
    for c in range(3):
        darkness[:, :, c] = np.clip(bg_color[c] - shadow_layer[:, :, c], 0, 255)

    canvas = 255.0 - darkness  # 흰 배경에 그림자 이식

    # ── 7. 그림자 탐색 범위 제한 (범위 밖만 흰색 + 경계 페이드) ──
    search_margin_x = int(prod_w * search_sides_pct)
    search_margin_top = int(prod_h * search_top_pct)
    search_margin_bottom = int(prod_h * search_bottom_pct)
    search_y_min = max(0, y_min - search_margin_top)
    search_y_max = min(ph, y_max + search_margin_bottom)
    search_x_min = max(0, x_min - search_margin_x)
    search_x_max = min(pw, x_max + search_margin_x)

    range_canvas = np.full((ph, pw, 3), 255.0, dtype=np.float32)
    range_canvas[search_y_min:search_y_max, search_x_min:search_x_max] = \
        canvas[search_y_min:search_y_max, search_x_min:search_x_max]
    canvas = range_canvas

    # 탐색 범위 경계를 부드럽게 페이드아웃
    fade_size = max(5, int(min(prod_w, prod_h) * blur_pct))
    fade_mask = np.zeros((ph, pw), dtype=np.float32)
    fade_mask[search_y_min:search_y_max, search_x_min:search_x_max] = 1.0
    fade_pil = Image.fromarray((fade_mask * 255).astype(np.uint8), "L")
    fade_pil = fade_pil.filter(ImageFilter.GaussianBlur(radius=fade_size))
    fade_smooth = np.array(fade_pil).astype(np.float32) / 255.0
    fade_3d = fade_smooth[:, :, np.newaxis]
    canvas = canvas * fade_3d + 255.0 * (1.0 - fade_3d)

    # ── 8. 원본이식: distance_falloff 미적용 ──
    # 원본 그림자에 이미 자연스러운 거리 감쇠가 포함되어 있으므로
    # 인위적인 distance_falloff를 적용하지 않음 (원본 보존 원칙)

    # ── 9. 원본이식: opacity/threshold 최소 적용 ──
    # opacity: 원본 그림자 농도를 그대로 보존 (100% 기본)
    # threshold: 극히 미세한 노이즈만 제거 (3 이하)
    if opacity < 1.0:
        pure_white = np.full((ph, pw, 3), 255.0, dtype=np.float32)
        canvas = canvas * opacity + pure_white * (1.0 - opacity)
        logger.info(f"[원본이식] opacity {opacity:.0%} 적용")

    # 미세 노이즈만 제거 (threshold를 매우 작게 적용)
    noise_th = min(threshold, 5)  # 원본이식에서는 5 이하로 제한
    canvas_brightness = np.mean(canvas, axis=2)
    near_white = canvas_brightness > (255 - noise_th)
    canvas[near_white] = 255.0

    shadow_pixel_count = np.sum(canvas_brightness < 250)
    shadow_min_val = canvas[canvas_brightness < 250].min() if shadow_pixel_count > 0 else 255
    logger.info(f"[원본이식] 그림자 픽셀={shadow_pixel_count}, 최소 밝기={shadow_min_val:.0f}")

    # ── 10. 누끼 제품을 위에 알파 합성 ──
    product_rgb = mask_arr[:, :, :3].astype(np.float32)
    product_alpha = alpha.astype(np.float32) / 255.0
    alpha_3d = product_alpha[:, :, np.newaxis]
    canvas = product_rgb * alpha_3d + canvas * (1.0 - alpha_3d)

    result_img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    logger.info(f"[원본이식] 그림자 추출+합성 완료 (opacity={opacity:.0%})")

    buf = io.BytesIO()
    result_img.save(buf, format="PNG")
    return buf.getvalue()


def _clean_and_recenter_bytes(png_bytes: bytes, output_size: int = 1000,
                              padding: dict = None) -> bytes:
    """Photoroom 결과에서 아티팩트 제거 + 제품 중앙 배치.

    투명 PNG → alpha 기반 감지, 불투명(흰배경+그림자) → 비백색 픽셀 기반 감지.

    Args:
        padding: {"top": px, "bottom": px, "left": px, "right": px}
                 카테고리별 여백 (output_size 기준 픽셀값)
    """
    if padding is None:
        padding = {"top": 80, "bottom": 80, "left": 80, "right": 80}
    from PIL import Image
    from collections import deque
    import io

    img = Image.open(io.BytesIO(png_bytes))

    # RGBA라도 실제 투명 픽셀이 없으면 불투명 모드로 처리
    # (Photoroom이 background.color 설정 시 RGBA+alpha=255로 반환할 수 있음)
    if img.mode == "RGBA":
        alpha = np.array(img)[:, :, 3]
        has_transparency = np.any(alpha < 250)
        if has_transparency:
            return _clean_alpha_mode(img, png_bytes, output_size, padding)
        else:
            logger.info("RGBA이지만 투명 픽셀 없음 → 불투명(그림자) 모드")
            return _clean_opaque_mode(img, png_bytes, output_size, padding)
    else:
        return _clean_opaque_mode(img, png_bytes, output_size, padding)


def _clean_opaque_mode(img, original_bytes: bytes, output_size: int,
                       padding: dict) -> bytes:
    """흰 배경 + 그림자가 합성된 불투명 이미지를 중앙 배치.

    1) BFS로 제품 본체 감지 → 본체 영역 밖 근백색 클린업
    2) 클린업 후 전체 비백색 영역(제품+그림자) bbox 계산
    3) 전체를 캔버스 중앙에 배치
    """
    from PIL import Image
    from collections import deque
    import io

    img_rgb = img.convert("RGB")
    arr = np.array(img_rgb)
    h, w = arr.shape[:2]

    # ── Step 1: BFS로 제품 본체 감지 (아티팩트 분리용) ──
    scale_down = 4
    sh, sw = h // scale_down, w // scale_down
    if sh < 10 or sw < 10:
        return original_bytes

    small = np.array(Image.fromarray(arr).resize((sw, sh), Image.NEAREST))
    binary = np.any(small < 240, axis=2).astype(np.uint8)

    labels = np.zeros((sh, sw), dtype=np.int32)
    label_id = 0
    areas = {}
    bboxes = {}
    for y in range(sh):
        for x in range(sw):
            if binary[y, x] == 1 and labels[y, x] == 0:
                label_id += 1
                queue = deque([(y, x)])
                labels[y, x] = label_id
                area = 0
                min_y, max_y, min_x, max_x = y, y, x, x
                while queue:
                    cy, cx = queue.popleft()
                    area += 1
                    min_y = min(min_y, cy)
                    max_y = max(max_y, cy)
                    min_x = min(min_x, cx)
                    max_x = max(max_x, cx)
                    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < sh and 0 <= nx < sw and binary[ny, nx] == 1 and labels[ny, nx] == 0:
                            labels[ny, nx] = label_id
                            queue.append((ny, nx))
                areas[label_id] = area
                bboxes[label_id] = (min_y, max_y, min_x, max_x)

    if not areas:
        return original_bytes

    largest = max(areas, key=areas.get)
    sy_min, sy_max, sx_min, sx_max = bboxes[largest]

    # 원본 좌표
    p_y_min = sy_min * scale_down
    p_y_max = min(h - 1, (sy_max + 1) * scale_down)
    p_x_min = sx_min * scale_down
    p_x_max = min(w - 1, (sx_max + 1) * scale_down)

    removed = len(areas) - 1
    if removed > 0:
        logger.info(f"불투명 모드 아티팩트 제거: {removed}개 소형 오브젝트 무시")

    # ── Step 2: 클린업 ──
    prod_h = p_y_max - p_y_min
    prod_w = p_x_max - p_x_min

    # 제품 상단 위: 순백색으로 (아티팩트 제거)
    keep_y_min = max(0, p_y_min - int(prod_h * 0.05))
    arr[:keep_y_min, :] = 255

    # 좌우: 제품 폭 + 마진만 보존 (그림자 포함)
    keep_x_min = max(0, p_x_min - int(prod_w * 0.2))
    keep_x_max = min(w, p_x_max + int(prod_w * 0.2))
    arr[:, :keep_x_min] = 255
    arr[:, keep_x_max:] = 255

    # 그림자 탐색: 제품 아래 10%까지 보존
    shadow_limit = min(h, p_y_max + int(prod_h * 0.10))
    arr[shadow_limit:, :] = 255

    # 근백색 클린업: 그림자 영역은 보호
    near_white = np.all(arr > 245, axis=2)
    near_white[p_y_max:shadow_limit, keep_x_min:keep_x_max] = False
    arr[near_white] = 255

    # ── Step 3: 클린업 후 전체 비백색 영역 bbox (제품+그림자) ──
    not_white = np.any(arr < 255, axis=2)
    coords = np.argwhere(not_white)
    if len(coords) == 0:
        return original_bytes

    cy_min, cx_min = coords.min(axis=0)
    cy_max, cx_max = coords.max(axis=0)

    cy_min = max(0, cy_min - 2)
    cy_max = min(h - 1, cy_max + 2)
    cx_min = max(0, cx_min - 2)
    cx_max = min(w - 1, cx_max + 2)

    img_rgb = Image.fromarray(arr)
    cropped = img_rgb.crop((cx_min, cy_min, cx_max + 1, cy_max + 1))

    # ── Step 4: 캔버스 배치 ──
    # 스케일: 제품 본체 크기 기준
    # 배치: 큰 임시 캔버스에 제품 중심 기준 배치 → 최종 크기로 크롭
    canvas_size = output_size
    pad_top = padding["top"]
    pad_bottom = padding["bottom"]
    pad_left = padding["left"]
    pad_right = padding["right"]
    avail_w = canvas_size - pad_left - pad_right
    avail_h = canvas_size - pad_top - pad_bottom

    # 제품 본체 크기 기준으로 스케일 결정
    ratio = min(avail_w / max(prod_w, 1), avail_h / max(prod_h, 1))

    cw, ch_crop = cropped.size
    new_w = int(cw * ratio)
    new_h = int(ch_crop * ratio)
    scaled = cropped.resize((new_w, new_h), Image.LANCZOS)

    # 제품 중심의 크롭 내 상대 좌표
    prod_cx = (p_x_min + p_x_max) / 2.0
    prod_cy = (p_y_min + p_y_max) / 2.0
    rel_prod_cx = prod_cx - cx_min
    rel_prod_cy = prod_cy - cy_min
    scaled_prod_cx = rel_prod_cx * ratio
    scaled_prod_cy = rel_prod_cy * ratio

    # 큰 임시 캔버스에 배치 (음수 좌표 방지)
    margin = max(new_w, new_h)
    big_size = canvas_size + margin * 2
    big_canvas = Image.new("RGB", (big_size, big_size), (255, 255, 255))

    # 제품 중심이 big_canvas 중앙에 오도록 배치
    big_cx = big_size // 2
    big_cy = big_size // 2
    bx = int(big_cx - scaled_prod_cx)
    by = int(big_cy - scaled_prod_cy)
    big_canvas.paste(scaled, (bx, by))

    # 최종 캔버스 영역 크롭 (제품 중심 = 여백 영역 중앙)
    area_cx = pad_left + avail_w // 2
    area_cy = pad_top + avail_h // 2
    crop_x = big_cx - area_cx
    crop_y = big_cy - area_cy
    canvas = big_canvas.crop((crop_x, crop_y, crop_x + canvas_size, crop_y + canvas_size))

    logger.info("불투명 모드: 클린업 → 제품+그림자 중앙 배치 완료")

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _clean_alpha_mode(img, original_bytes: bytes, output_size: int,
                      padding: dict) -> bytes:
    """투명 PNG 모드 - alpha 기반 아티팩트 제거 + 중앙 배치."""
    from PIL import Image
    from collections import deque
    import io

    img_array = np.array(img)
    alpha = img_array[:, :, 3].copy()
    h, w = alpha.shape

    # Step 1: 높은 threshold(128)로 '고체' 컴포넌트 감지 (1/4 축소)
    scale_down = 4
    sh, sw = h // scale_down, w // scale_down
    if sh < 10 or sw < 10:
        return original_bytes

    small_alpha = np.array(
        Image.fromarray(alpha).resize((sw, sh), Image.NEAREST))
    binary = (small_alpha >= 128).astype(np.uint8)

    labels = np.zeros((sh, sw), dtype=np.int32)
    label_id = 0
    areas = {}
    bboxes = {}
    for y in range(sh):
        for x in range(sw):
            if binary[y, x] == 1 and labels[y, x] == 0:
                label_id += 1
                queue = deque([(y, x)])
                labels[y, x] = label_id
                area = 0
                min_y, max_y, min_x, max_x = y, y, x, x
                while queue:
                    cy, cx = queue.popleft()
                    area += 1
                    min_y = min(min_y, cy)
                    max_y = max(max_y, cy)
                    min_x = min(min_x, cx)
                    max_x = max(max_x, cx)
                    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < sh and 0 <= nx < sw and binary[ny, nx] == 1 and labels[ny, nx] == 0:
                            labels[ny, nx] = label_id
                            queue.append((ny, nx))
                areas[label_id] = area
                bboxes[label_id] = (min_y, max_y, min_x, max_x)

    if not areas:
        return original_bytes

    largest = max(areas, key=areas.get)
    sy_min, sy_max, sx_min, sx_max = bboxes[largest]

    prod_y_min = sy_min * scale_down
    prod_y_max = min(h - 1, (sy_max + 1) * scale_down)
    prod_x_min = sx_min * scale_down
    prod_x_max = min(w - 1, (sx_max + 1) * scale_down)
    prod_cx = (prod_x_min + prod_x_max) / 2
    prod_cy = (prod_y_min + prod_y_max) / 2

    # bbox 확장 (아티팩트 제거 목적)
    prod_h = prod_y_max - prod_y_min
    prod_w = prod_x_max - prod_x_min
    margin_v = int(prod_h * 0.25)
    margin_h = int(prod_w * 0.20)

    keep_y_min = max(0, prod_y_min - margin_v)
    keep_y_max = min(h, prod_y_max + margin_v)
    keep_x_min = max(0, prod_x_min - margin_h)
    keep_x_max = min(w, prod_x_max + margin_h)

    new_alpha = np.zeros_like(alpha)
    new_alpha[keep_y_min:keep_y_max, keep_x_min:keep_x_max] = \
        alpha[keep_y_min:keep_y_max, keep_x_min:keep_x_max]
    new_alpha[new_alpha < 10] = 0
    img_array[:, :, 3] = new_alpha

    removed = len(areas) - 1
    if removed > 0:
        logger.info(f"아티팩트 제거: {removed}개 소형 오브젝트 제거")

    img = Image.fromarray(img_array, "RGBA")

    clean_coords = np.argwhere(new_alpha > 0)
    if len(clean_coords) == 0:
        return original_bytes

    cy_min, cx_min = clean_coords.min(axis=0)
    cy_max, cx_max = clean_coords.max(axis=0)
    cropped = img.crop((cx_min, cy_min, cx_max + 1, cy_max + 1))

    rel_prod_cx = prod_cx - cx_min
    rel_prod_cy = prod_cy - cy_min

    canvas_size = output_size
    pad_top = padding["top"]
    pad_bottom = padding["bottom"]
    pad_left = padding["left"]
    pad_right = padding["right"]
    avail_w = canvas_size - pad_left - pad_right
    avail_h = canvas_size - pad_top - pad_bottom

    cw, ch_crop = cropped.size
    ratio = min(avail_w / cw, avail_h / ch_crop)
    new_w = int(cw * ratio)
    new_h = int(ch_crop * ratio)
    cropped = cropped.resize((new_w, new_h), Image.LANCZOS)

    area_cx = pad_left + avail_w / 2
    area_cy = pad_top + avail_h / 2
    scaled_cx = rel_prod_cx * ratio
    scaled_cy = rel_prod_cy * ratio
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
    paste_x = int(area_cx - scaled_cx)
    paste_y = int(area_cy - scaled_cy)
    paste_x = max(0, min(paste_x, canvas_size - new_w))
    paste_y = max(0, min(paste_y, canvas_size - new_h))
    canvas.paste(cropped, (paste_x, paste_y), cropped)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


class ImageEditPipeline:
    """쇼핑몰 이미지 편집 전체 파이프라인."""

    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = str(Path(__file__).parent.parent / "config")

        settings_path = Path(config_dir) / "settings.yaml"
        with open(str(settings_path), "r", encoding="utf-8") as f:
            self._settings = yaml.safe_load(f)

        self._prompt_builder = PromptBuilder(str(Path(config_dir) / "prompts.yaml"))
        self._result_parser = ResultParser()
        self._photoroom = PhotoroomClient()
        self._removebg = RemoveBgClient()
        self._claid = ClaidClient()
        self._opencv_enhance = OpenCVEnhancer()
        self._optimizer = ImageOptimizer()
        self._category_mgr = CategoryManager(str(Path(config_dir) / "categories.yaml"))

        # SAM 그림자 클라이언트 (lazy loaded)
        sam_config = self._settings.get("sam", {})
        self._sam_shadow = SamShadowClient(
            model_variant=sam_config.get("model_variant", "mobile_sam"),
            checkpoint=sam_config.get("checkpoint") or None,
            models_dir=str(Path(config_dir).parent / "models"),
        )

        self._vision_client = None

        # 프로바이더 설정
        providers = self._settings.get("providers", {})
        self._vision_provider = providers.get("vision", "claude")
        self._bg_provider = providers.get("background_removal", "photoroom")
        self._enhance_provider = providers.get("enhancement", "claid")
        self._shadow_provider = providers.get("shadow", "opencv_extract")
        shadow_cfg = self._settings.get("shadow_extract", {})
        self._shadow_method = shadow_cfg.get("method", "level_correction")
        logger.info(f"파이프라인 초기화: 분석={self._vision_provider}, 배경제거={self._bg_provider}, "
                    f"보정={self._enhance_provider}, 그림자={self._shadow_provider} ({self._shadow_method})")

    def _get_vision_client(self):
        if self._vision_client is None:
            if self._vision_provider == "chatgpt":
                openai_config = self._settings.get("openai", {})
                self._vision_client = OpenAIVisionClient(
                    model=openai_config.get("model", "gpt-4o")
                )
            elif self._vision_provider == "gemini":
                gemini_config = self._settings.get("gemini", {})
                self._vision_client = GeminiVisionClient(
                    model=gemini_config.get("model", "gemini-2.5-flash")
                )
            else:
                api_config = self._settings.get("api", {})
                self._vision_client = VisionClient(
                    model=api_config.get("model", "claude-sonnet-4-20250514")
                )
        return self._vision_client

    def _call_bg_removal(self, image_bytes: bytes, image_type: str,
                         background: str, output_size: str = "1000x1000",
                         is_detail: bool = False, include_shadow: bool = False,
                         ai_photoroom_params: dict = None,
                         on_log: Callable = None) -> Optional[bytes]:
        """프로바이더에 따라 배경 제거를 호출한다."""
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        if self._bg_provider == "removebg":
            rb_config = self._settings.get("removebg", {})
            return self._removebg.process(
                image_bytes, image_type, background,
                output_size=output_size, config=rb_config)
        else:
            # Photoroom
            pr_settings = self._settings.get("photoroom", {})
            if is_detail:
                pr_config = dict(pr_settings.get("detail_complex", {}))
            elif image_type == "package":
                pr_config = dict(pr_settings.get("package", {}))
            else:
                pr_config = dict(pr_settings.get("full", {}))

            # AI 추천 Photoroom 파라미터 적용
            if ai_photoroom_params:
                for k, v in ai_photoroom_params.items():
                    if k in pr_config:
                        pr_config[k] = v
                _log(f"  AI 추천 Photoroom 파라미터 적용: {ai_photoroom_params}")

            # shadow.mode 제어: API 그림자 미사용 시 제거
            if not include_shadow:
                pr_config = {k: v for k, v in pr_config.items()
                             if not k.startswith("shadow.")}

            return self._photoroom.process(
                image_bytes, image_type, background,
                output_size=output_size, config=pr_config)

    def _get_category_padding(self, category: str, output_size: int = 1000) -> dict:
        """카테고리별 여백(px)을 반환. padding_860 → output_size 기준으로 스케일."""
        cats_data = {}
        try:
            cats_path = Path(self._category_mgr._config_path)
            with open(str(cats_path), "r", encoding="utf-8") as f:
                cats_data = yaml.safe_load(f)
        except Exception:
            pass

        # 카테고리별 → default → 하드코딩 fallback
        cat_info = cats_data.get("categories", {}).get(category, {})
        pad_860 = cat_info.get("padding_860")
        if not pad_860:
            logger.warning(f"카테고리 '{category}' 여백 없음 → default 사용")
            pad_860 = cats_data.get("default", {}).get("padding_860",
                      {"top": 64, "bottom": 64, "left": 64, "right": 64})
        else:
            logger.info(f"카테고리 '{category}' 여백 적용: {pad_860}")

        # 860 기준 → output_size 기준으로 스케일
        scale = output_size / 860.0
        return {
            "top": int(pad_860.get("top", 64) * scale),
            "bottom": int(pad_860.get("bottom", 64) * scale),
            "left": int(pad_860.get("left", 64) * scale),
            "right": int(pad_860.get("right", 64) * scale),
        }

    def _crop_out_hand(self, image_bytes: bytes, hand_region: dict,
                       product_only_region: dict = None,
                       on_log: Callable = None) -> bytes:
        """사람 손이 포함된 영역을 크롭하여 상품만 최대한 크게 보이도록 한다.

        우선순위:
        1. product_only_region이 있으면 → 상품만 크롭 (손 위치 무관, 가장 정확)
        2. hand_region으로 가장자리 크롭 (기존 로직)
        """
        from PIL import Image
        import io

        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        # ── 방법 1: product_only_region으로 상품 영역만 크롭 ──
        if product_only_region:
            margin = 0.03  # 3% 여유
            px1 = max(0, int((product_only_region["x"] - margin) * w))
            py1 = max(0, int((product_only_region["y"] - margin) * h))
            px2 = min(w, int((product_only_region["x"] + product_only_region["width"] + margin) * w))
            py2 = min(h, int((product_only_region["y"] + product_only_region["height"] + margin) * h))

            crop_w, crop_h = px2 - px1, py2 - py1
            if crop_w > w * 0.3 and crop_h > h * 0.3:
                cropped = img.crop((px1, py1, px2, py2))
                _log(f"  상품 영역 크롭 (손 제외): {w}x{h} → {cropped.size[0]}x{cropped.size[1]}")

                buf = io.BytesIO()
                fmt = "JPEG" if img.mode == "RGB" else "PNG"
                cropped.save(buf, format=fmt, quality=95)
                return buf.getvalue()
            else:
                _log(f"  상품 영역이 너무 작아 크롭 생략")

        # ── 방법 2: hand_region으로 가장자리 크롭 (기존 로직) ──
        hx1 = int(hand_region["x"] * w)
        hy1 = int(hand_region["y"] * h)
        hx2 = hx1 + int(hand_region["width"] * w)
        hy2 = hy1 + int(hand_region["height"] * h)

        _log(f"  사람 손 감지: ({hx1},{hy1})-({hx2},{hy2})")

        edge_margin = 0.05
        touches_left = hx1 < w * edge_margin
        touches_right = hx2 > w * (1 - edge_margin)
        touches_top = hy1 < h * edge_margin
        touches_bottom = hy2 > h * (1 - edge_margin)

        if not (touches_left or touches_right or touches_top or touches_bottom):
            _log(f"  손이 이미지 중앙에 있어 크롭 불가 → Photoroom에서 처리")
            return image_bytes

        x1, y1, x2, y2 = 0, 0, w, h

        if touches_left and not touches_right:
            x1 = hx2
        elif touches_right and not touches_left:
            x2 = hx1

        if touches_top and not touches_bottom:
            y1 = hy2
        elif touches_bottom and not touches_top:
            y2 = hy1

        remaining = (x2 - x1) * (y2 - y1)
        if remaining < w * h * 0.7:
            _log(f"  손 크롭 후 영역이 너무 작아 원본 유지 → Photoroom에서 처리")
            return image_bytes

        cropped = img.crop((x1, y1, x2, y2))
        _log(f"  손 크롭 완료: {w}x{h} → {cropped.size[0]}x{cropped.size[1]}")

        buf = io.BytesIO()
        fmt = "JPEG" if img.mode == "RGB" else "PNG"
        cropped.save(buf, format=fmt, quality=95)
        return buf.getvalue()

    def _crop_detail_cut(self, image_bytes: bytes, instruction,
                         on_log: Callable = None) -> bytes:
        """디테일컷 이미지를 정사각형으로 크롭 + 흰 배경 합성.

        투명 PNG(Photoroom 결과)인 경우 흰 배경 위에 합성.
        focus_area가 있으면 해당 영역 중심, 없으면 피사체 중앙 기준.
        """
        from PIL import Image
        import io

        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        output_w = self._settings.get("output", {}).get("width", 1000)
        output_h = self._settings.get("output", {}).get("height", 1000)

        # 투명 PNG → 피사체 영역 기반 크롭
        if img.mode == "RGBA":
            alpha = np.array(img)[:, :, 3]
            # 피사체 영역 찾기 (alpha > 0)
            coords = np.argwhere(alpha > 0)
            if len(coords) > 0:
                cy_min, cx_min = coords.min(axis=0)
                cy_max, cx_max = coords.max(axis=0)
                # 피사체 중심
                cx = (cx_min + cx_max) // 2
                cy = (cy_min + cy_max) // 2
                # 피사체를 포함하는 정사각형
                obj_w = cx_max - cx_min
                obj_h = cy_max - cy_min
                crop_size = int(max(obj_w, obj_h) * 1.15)  # 15% 여유
                crop_size = min(crop_size, w, h)
            else:
                cx, cy = w // 2, h // 2
                crop_size = min(w, h)

            x1 = max(0, cx - crop_size // 2)
            y1 = max(0, cy - crop_size // 2)
            if x1 + crop_size > w:
                x1 = w - crop_size
            if y1 + crop_size > h:
                y1 = h - crop_size

            cropped = img.crop((x1, y1, x1 + crop_size, y1 + crop_size))
            # 흰 배경 합성
            canvas = Image.new("RGB", (output_w, output_h), (255, 255, 255))
            resized = cropped.resize((output_w, output_h), Image.LANCZOS)
            canvas.paste(resized, (0, 0), resized)  # alpha mask 사용
            _log(f"  디테일컷 크롭 완료 (투명→흰배경): {crop_size}x{crop_size} → {output_w}x{output_h}")
        else:
            # 불투명 이미지 → focus_area 또는 중앙 크롭
            fa = instruction.detail_focus_area
            if fa:
                cx = int(fa["x"] * w)
                cy = int(fa["y"] * h)
                _log(f"  포커스 영역: x={fa['x']:.2f} y={fa['y']:.2f}")
            else:
                cx, cy = w // 2, h // 2

            crop_size = min(w, h)
            x1 = max(0, cx - crop_size // 2)
            y1 = max(0, cy - crop_size // 2)
            if x1 + crop_size > w:
                x1 = w - crop_size
            if y1 + crop_size > h:
                y1 = h - crop_size

            cropped = img.crop((x1, y1, x1 + crop_size, y1 + crop_size))
            canvas = Image.new("RGB", (output_w, output_h), (255, 255, 255))
            resized = cropped.convert("RGB").resize((output_w, output_h), Image.LANCZOS)
            canvas.paste(resized, (0, 0))
            _log(f"  디테일컷 크롭 완료: {crop_size}x{crop_size} → {output_w}x{output_h}")

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()

    def _get_category_list(self) -> list:
        """카테고리 목록을 [{id, display_name}, ...] 형태로 반환."""
        cats = []
        for cat_id in self._category_mgr.list_categories():
            cats.append({
                "id": cat_id,
                "display_name": self._category_mgr.get_display_name(cat_id),
            })
        return cats

    def _collect_sibling_images(self, image_path: str, max_count: int = 3) -> list:
        """같은 폴더에서 카테고리 감지용 참고 이미지를 최대 max_count장 수집한다.

        대상 이미지를 첫 번째로, 나머지는 같은 폴더의 다른 이미지로 채운다.
        BGR numpy 배열 리스트를 반환한다 (vision_client 호환).
        """
        from PIL import Image

        target = Path(image_path)
        folder = target.parent

        extensions = self._settings.get("image", {}).get(
            "supported_formats", [".jpg", ".jpeg", ".png"]
        )
        siblings = get_image_files(str(folder), extensions)

        ordered = [str(target)]
        for s in siblings:
            if len(ordered) >= max_count:
                break
            if Path(s).resolve() != target.resolve():
                ordered.append(s)

        images = []
        for p in ordered:
            try:
                img_pil = Image.open(p)
                h, w = img_pil.size[1], img_pil.size[0]
                if max(h, w) > 1024:
                    scale = 1024 / max(h, w)
                    new_w, new_h = int(w * scale), int(h * scale)
                    img_pil = img_pil.resize((new_w, new_h), Image.LANCZOS)
                img = np.array(img_pil)
                if len(img.shape) == 2:
                    img = np.stack([img, img, img], axis=-1)
                elif img.shape[2] == 4:
                    img = img[:, :, :3]
                # RGB -> BGR (vision_client가 cv2 형식을 기대)
                img = img[:, :, ::-1].copy()
                images.append(img)
            except Exception as e:
                logger.warning(f"참고 이미지 로드 실패: {p} - {e}")

        return images

    def analyze_only(self, image_path: str, category: str,
                     img: "np.ndarray | None" = None,
                     on_log: Callable = None) -> EditInstruction:
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        _log(f"이미지 분석 시작: {Path(image_path).name}")

        if img is None:
            img = load_image(image_path)

        auto_detect = not category
        category_list = self._get_category_list()

        system_prompt = self._prompt_builder.build_system_prompt()
        user_prompt = self._prompt_builder.build_analysis_prompt(
            category_list=category_list
        )

        # Vision 프로바이더별 설정
        vision_provider_names = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini"}
        vision_name = vision_provider_names.get(self._vision_provider, self._vision_provider)
        if self._vision_provider == "chatgpt":
            vision_config = self._settings.get("openai", {})
        elif self._vision_provider == "gemini":
            vision_config = self._settings.get("gemini", {})
        else:
            vision_config = self._settings.get("api", {})
        api_config = self._settings.get("api", {})
        client = self._get_vision_client()

        if auto_detect:
            ref_images = self._collect_sibling_images(image_path, max_count=5)
            _log(f"{vision_name} Vision API 호출 중 ({len(ref_images)}장 참고, "
                 f"모델: {vision_config.get('model', 'unknown')})")
            ref_images[0] = img
            response = client.analyze_images(
                ref_images,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=vision_config.get("max_tokens", 1024),
                temperature=vision_config.get("temperature", 0.1),
            )
        else:
            _log(f"{vision_name} Vision API 호출 중 (모델: {vision_config.get('model', 'unknown')})")
            response = client.analyze_image(
                img,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=vision_config.get("max_tokens", 1024),
                temperature=vision_config.get("temperature", 0.1),
            )

        instruction = self._result_parser.parse(response)

        if auto_detect and instruction.detected_category:
            detected = instruction.detected_category
            known = self._category_mgr.list_categories()
            if detected in known:
                _log(f"카테고리 자동 감지: {detected} "
                     f"({instruction.detected_category_display})", "success")
            else:
                _log(f"새 카테고리 감지: {detected} "
                     f"({instruction.detected_category_display}) "
                     f"- 설정에 등록되지 않은 카테고리입니다. "
                     f"[설정] 탭에서 '{detected}' 카테고리를 추가해주세요.", "warn")

        _log(f"분석 완료 - 유형: {instruction.image_type}, "
             f"배경: {instruction.background}, 확신도: {instruction.confidence:.2f}", "success")
        return instruction

    def process_single(self, image_path: str, category: str, output_dir: str,
                       base_name: str = None, skip_analysis: bool = False,
                       skip_photoroom: bool = False,
                       override_params: dict = None,
                       on_log: Callable = None) -> dict:
        """단일 이미지 처리 - Photoroom + Claid.ai 파이프라인."""
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        fname = Path(image_path).name
        _log(f"처리 시작: {fname}")
        _used_shadow_config = {}
        _used_enhance_config = {}

        # 1. 이미지 파일 바이트 로드
        image_bytes = Path(image_path).read_bytes()
        _log(f"  파일 크기: {len(image_bytes) // 1024}KB")

        # 2. Claude Vision API 분석 (img는 analyze_only에서 필요)
        img = load_image(image_path)

        if not skip_analysis:
            instruction = self.analyze_only(image_path, category, img=img, on_log=on_log)
            if not category and instruction.detected_category:
                category = instruction.detected_category
                _log(f"  자동 감지된 카테고리 적용: {category}")
        else:
            instruction = EditInstruction(
                image_type="full",
                background="clean",
                notes="분석 생략 - 기본 분류값 적용",
            )
            _log(f"  AI 분석 생략 - 기본 분류값 적용")

        image_type = instruction.image_type
        background = instruction.background
        is_detail_cut = instruction.is_detail_cut
        needs_shadow = instruction.needs_shadow

        # ★ 원본 이미지 바닥 영역 밝기로 그림자 유무 재검증
        # 단, 생성형 그림자(gemini_shadow, api_shadow)는 새로 그림자를 만드므로
        # 원본에 그림자가 없어도 무조건 진행
        _is_generative_shadow = self._shadow_provider in ("gemini_shadow", "api_shadow")
        has_real_shadow = self._detect_shadow_in_original(image_bytes)
        if needs_shadow and not has_real_shadow and not _is_generative_shadow:
            _log(f"  ⚠ AI가 그림자 있다고 판단했으나 원본 바닥에 그림자 감지 안 됨 → 그림자 처리 스킵", "warn")
            needs_shadow = False
        elif not needs_shadow and has_real_shadow:
            _log(f"  ⚠ AI가 그림자 없다고 판단했으나 원본 바닥에 그림자 감지됨 → 그림자 처리 진행", "warn")
            needs_shadow = True
        elif not needs_shadow and _is_generative_shadow:
            _log(f"  생성형 그림자 모드({self._shadow_provider}) → 그림자 생성 진행")
            needs_shadow = True

        edit_actions = [f"분류: {image_type} / 배경: {background}"
                        + (" / 디테일컷" if is_detail_cut else "")
                        + (f" / 그림자: {'O' if needs_shadow else 'X'}")]

        # 2.5. 사람 손 감지 시 크롭 (Photoroom 호출 전에 원본에서 제거)
        current_bytes = image_bytes
        if instruction.has_human_hand and instruction.hand_region:
            current_bytes = self._crop_out_hand(
                current_bytes, instruction.hand_region,
                product_only_region=instruction.product_only_region,
                on_log=_log)
            edit_actions.append("사람 손 영역 크롭 제거")
            image_bytes = current_bytes  # Photoroom에도 크롭된 이미지 전달

        # 3. 디테일컷: 배경제거 → 크롭
        if is_detail_cut:
            _log(f"  디테일컷 감지")
            if not skip_photoroom:
                bg_result = self._call_bg_removal(
                    image_bytes, "detail", "complex",
                    output_size="originalImage", is_detail=True, on_log=_log)
                if bg_result:
                    current_bytes = bg_result
                    edit_actions.append(f"{self._bg_provider}: 배경 제거 (디테일컷)")
                    _log(f"  배경제거 완료 ({len(current_bytes) // 1024}KB)", "success")
            current_bytes = self._crop_detail_cut(
                current_bytes, instruction, on_log=_log)
            edit_actions.append("디테일컷: 중앙 정사각 크롭 + 흰 배경")
        elif not skip_photoroom:
            # 일반 이미지: 배경 제거 (프로바이더 선택)
            if PhotoroomClient.should_process(image_type, background):
                output_size = (
                    f"{self._settings.get('output', {}).get('width', 1000)}"
                    f"x{self._settings.get('output', {}).get('height', 1000)}"
                )
                _log(f"  [{self._bg_provider}] 배경제거 중 (유형: {image_type})...")

                # 그림자 방식에 따라 Photoroom shadow.mode 포함 여부 결정
                use_api_shadow = (self._shadow_provider == "api_shadow"
                                  and self._bg_provider == "photoroom"
                                  and needs_shadow)

                pr_auto = self._settings.get("auto_options", {}).get("photoroom", "manual") == "ai_auto"
                ai_pr_params = instruction.photoroom_params if pr_auto and instruction.photoroom_params else None
                bg_result = self._call_bg_removal(
                    image_bytes, image_type, background,
                    output_size=output_size,
                    include_shadow=use_api_shadow,
                    ai_photoroom_params=ai_pr_params, on_log=_log)

                if bg_result:
                    # 그림자 처리
                    if needs_shadow and self._shadow_provider == "opencv_extract":
                        if override_params and "shadow_config" in override_params:
                            shadow_config = dict(override_params["shadow_config"])
                            _log(f"  [자동수정] override shadow_config 적용")
                        else:
                            shadow_config = dict(self._settings.get("shadow_extract", {}))
                        auto_options = self._settings.get("auto_options", {})
                        shadow_auto = auto_options.get("shadow", "manual") == "ai_auto"
                        if not override_params and shadow_auto and instruction.shadow_params:
                            ai_params = instruction.shadow_params
                            for k, v in ai_params.items():
                                if k in shadow_config and isinstance(v, (int, float)):
                                    shadow_config[k] = v
                            _log(f"  AI 추천 그림자 파라미터 적용: {ai_params}")
                        method_name = "원본이식" if self._shadow_method == "transplant" else "레벨보정"
                        _log(f"  원본 그림자 추출+합성 중 ({method_name})... "
                             f"(opacity={shadow_config.get('opacity', 80)}%)")
                        if self._shadow_method == "transplant":
                            current_bytes = _transplant_natural_shadow(
                                bg_result, image_bytes, config=shadow_config)
                        else:
                            current_bytes = _preserve_natural_shadow(
                                bg_result, image_bytes, config=shadow_config)
                        edit_actions.append(f"누끼 합성 ({method_name}): 원본 그림자 추출")
                    elif needs_shadow and self._shadow_provider in ("sam_mobile", "sam_cpu", "sam_gpu", "sam_gpu_b", "sam_gpu_l", "sam_gpu_h"):
                        if override_params and "shadow_config" in override_params:
                            shadow_config = dict(override_params["shadow_config"])
                            _log(f"  [자동수정] override shadow_config 적용")
                        else:
                            shadow_config = dict(self._settings.get("shadow_extract", {}))
                        auto_options = self._settings.get("auto_options", {})
                        shadow_auto = auto_options.get("shadow", "manual") == "ai_auto"
                        if not override_params and shadow_auto and instruction.shadow_params:
                            ai_params = instruction.shadow_params
                            for k, v in ai_params.items():
                                if k in shadow_config and isinstance(v, (int, float)):
                                    shadow_config[k] = v
                            _log(f"  AI 추천 그림자 파라미터 적용: {ai_params}")
                        # 프로바이더명에서 모델/디바이스 결정
                        _sam_map = {
                            "sam_mobile": ("mobile_sam", "cpu"),
                            "sam_cpu": ("sam_vit_b", "cpu"),
                            "sam_gpu": ("sam_vit_b", "cuda"),
                            "sam_gpu_b": ("sam_vit_b", "cuda"),
                            "sam_gpu_l": ("sam_vit_l", "cuda"),
                            "sam_gpu_h": ("sam_vit_h", "cuda"),
                        }
                        variant, device = _sam_map[self._shadow_provider]
                        self._sam_shadow.set_variant(variant, force_device=device)
                        method_name = "원본이식" if self._shadow_method == "transplant" else "레벨보정"
                        _log(f"  SAM 그림자 추출 중 ({variant}, {device}, {method_name})...")
                        shadow_config["method"] = self._shadow_method
                        current_bytes = self._sam_shadow.extract_shadow(
                            bg_result, image_bytes, config=shadow_config)
                        edit_actions.append(f"SAM ({variant} {device} {method_name}): 그림자 추출")
                    elif needs_shadow and self._shadow_provider == "gemini_shadow":
                        gemini_order = self._settings.get("gemini_shadow", {}).get(
                            "order", "after_enhance")
                        if gemini_order == "after_enhance":
                            # 보정 후 그림자 생성 — 여기서는 스킵, 보정 후 처리
                            current_bytes = bg_result
                            _log(f"  Gemini 그림자: 보정 후 생성 모드 (보정 완료 후 진행)")
                        else:
                            _log(f"  Gemini 이미지 편집으로 그림자 생성 중...")
                            gemini_result = self._gemini_add_shadow(
                                bg_result, original_bytes=image_bytes, on_log=_log)
                            if gemini_result:
                                current_bytes = gemini_result
                                edit_actions.append("Gemini AI: 그림자 생성")
                            else:
                                current_bytes = bg_result
                                _log(f"  Gemini 그림자 생성 실패, 그림자 없이 진행", "warn")
                    elif needs_shadow and use_api_shadow:
                        current_bytes = bg_result
                        edit_actions.append("Photoroom API: 그림자 생성")
                    elif needs_shadow and self._shadow_provider == "none":
                        current_bytes = bg_result
                    else:
                        current_bytes = bg_result

                    output_w = self._settings.get("output", {}).get("width", 1000)
                    cat_padding = self._get_category_padding(category, output_w)
                    current_bytes = _clean_and_recenter_bytes(
                        current_bytes, output_size=output_w,
                        padding=cat_padding)
                    _log(f"  카테고리: {category} → 여백: 상{cat_padding['top']} 하{cat_padding['bottom']} "
                         f"좌{cat_padding['left']} 우{cat_padding['right']}px")
                    edit_actions.append(f"{self._bg_provider}: 배경제거 + 중앙 정렬")
                    _log(f"  배경제거 완료 ({len(current_bytes) // 1024}KB)", "success")
            else:
                _log(f"  배경제거 스킵 (유형: {image_type}, 배경: {background})")
        else:
            _log(f"  배경제거 처리 생략")

        # 4. 이미지 보정 (프로바이더 선택: claid / opencv)
        auto_options = self._settings.get("auto_options", {})
        _log(f"  [{self._enhance_provider}] 이미지 보정 중...")
        if self._enhance_provider == "opencv":
            if override_params and "enhance_config" in override_params:
                enhance_config = dict(override_params["enhance_config"])
                _log(f"  [자동수정] override enhance_config 적용")
            else:
                enhance_settings = self._settings.get("opencv_enhance", {})
                enhance_config = dict(enhance_settings.get(image_type, enhance_settings.get("full", {})))
            opencv_auto = auto_options.get("opencv", "manual") == "ai_auto"
            if not override_params and opencv_auto and instruction.enhance_params:
                for k, v in instruction.enhance_params.items():
                    if k in enhance_config and isinstance(v, (int, float)):
                        enhance_config[k] = v
                _log(f"  AI 추천 보정값 적용 (OpenCV): {instruction.enhance_params}")
            _log(f"  OpenCV 보정 (hdr={enhance_config.get('hdr', 20)}, "
                 f"sharpness={enhance_config.get('sharpness', 15)})...")
            current_bytes = self._opencv_enhance.process(
                current_bytes, image_type, config=enhance_config)
            edit_actions.append(f"OpenCV: 로컬 보정 ({image_type})")
            _log(f"  OpenCV 보정 완료 ({len(current_bytes) // 1024}KB)", "success")
        else:
            # Claid.ai API — 10MB 제한 대응: PNG → JPEG 변환
            if len(current_bytes) > 9 * 1024 * 1024:
                from PIL import Image
                import io
                _img = Image.open(io.BytesIO(current_bytes)).convert("RGB")
                _buf = io.BytesIO()
                _img.save(_buf, format="JPEG", quality=95)
                current_bytes = _buf.getvalue()
                _log(f"  Claid 전달용 JPEG 변환 ({len(current_bytes) // 1024}KB)")
            if override_params and "enhance_config" in override_params:
                claid_config = dict(override_params["enhance_config"])
                _log(f"  [자동수정] override enhance_config 적용 (Claid)")
            else:
                claid_settings = self._settings.get("claid", {})
                claid_config = dict(claid_settings.get(image_type, claid_settings.get("full", {})))
            claid_auto = auto_options.get("claid", "manual") == "ai_auto"
            if not override_params and claid_auto and instruction.enhance_params:
                for k, v in instruction.enhance_params.items():
                    if k in claid_config and isinstance(v, (int, float)):
                        claid_config[k] = v
                _log(f"  AI 추천 보정값 적용 (Claid): {instruction.enhance_params}")
            _log(f"  Claid.ai 보정 (hdr={claid_config.get('hdr', 20)}, "
                 f"sharpness={claid_config.get('sharpness', 15)})...")
            claid_result = self._claid.process(current_bytes, image_type, config=claid_config)
            current_bytes = claid_result
            edit_actions.append(f"Claid.ai: 색보정 ({image_type})")
            _log(f"  Claid.ai 완료 ({len(current_bytes) // 1024}KB)", "success")

        # 4.5. Gemini 그림자 — 보정 후 생성 모드
        if (needs_shadow and self._shadow_provider == "gemini_shadow"
                and self._settings.get("gemini_shadow", {}).get(
                    "order", "after_enhance") == "after_enhance"):
            _log(f"  Gemini 이미지 편집으로 그림자 생성 중 (보정 후)...")
            gemini_result = self._gemini_add_shadow(
                current_bytes, original_bytes=image_bytes, on_log=_log)
            if gemini_result:
                current_bytes = gemini_result
                edit_actions.append("Gemini AI: 그림자 생성 (보정 후)")
            else:
                _log(f"  Gemini 그림자 생성 실패, 그림자 없이 진행", "warn")

        # 5. JPEG 최적화 + 저장
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if base_name is None:
            base_name = FileNamer.extract_base_from_path(image_path)
        namer = FileNamer(base_name)

        output_config = self._settings.get("output", {})
        max_size_kb = output_config.get("max_file_size_kb", 2024)

        file_name = namer.next_name(".jpg")
        file_path = output_path / file_name
        if file_path.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            counter = 2
            while True:
                file_path = output_path / f"{stem}_{counter}{suffix}"
                if not file_path.exists():
                    break
                counter += 1
            _log(f"    중복 파일 -> {file_path.name} 으로 저장")

        saved_files = []
        info = self._optimizer.save_from_bytes(current_bytes, str(file_path), max_size_kb)
        saved_files.append(info)
        _log(f"  출력: {file_name} ({info['size_kb']}KB)", "success")

        if edit_actions:
            _log(f"  -- 처리 내역 --")
            for action in edit_actions:
                _log(f"    v {action}", "success")

        _log(f"  처리 완료: {len(saved_files)}개 파일 생성", "success")
        # used_params: shadow_config, enhance_config 수집 (자동수정 루프용)
        try:
            _used_shadow_config = shadow_config
        except UnboundLocalError:
            pass
        try:
            if self._enhance_provider == "opencv":
                _used_enhance_config = enhance_config
            else:
                _used_enhance_config = claid_config
        except UnboundLocalError:
            pass
        return {
            "files": saved_files,
            "instruction": instruction,
            "edit_actions": edit_actions,
            "used_params": {
                "shadow_config": dict(_used_shadow_config),
                "enhance_config": dict(_used_enhance_config),
            },
        }

    def _create_vision_client(self, provider: str):
        """지정된 프로바이더의 Vision 클라이언트를 생성한다."""
        if provider == "chatgpt":
            cfg = self._settings.get("openai", {})
            return OpenAIVisionClient(model=cfg.get("model", "gpt-4o"))
        elif provider == "gemini":
            cfg = self._settings.get("gemini", {})
            return GeminiVisionClient(model=cfg.get("model", "gemini-2.5-flash"))
        else:  # claude
            cfg = self._settings.get("api", {})
            return VisionClient(model=cfg.get("model", "claude-sonnet-4-20250514"))

    def _gemini_add_shadow(self, image_bytes: bytes,
                           original_bytes: bytes = None,
                           on_log: Callable = None) -> Optional[bytes]:
        """Gemini 이미지 편집 API로 자연스러운 그림자를 추가한다.

        Args:
            image_bytes: 배경 제거된 이미지 (PNG/JPEG)
            original_bytes: 원본 이미지 (그림자 참고용)

        Returns:
            그림자가 추가된 이미지 바이트, 실패 시 None
        """
        import os
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        try:
            from google import genai
            from google.genai import types

            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                _log(f"  GEMINI_API_KEY 미설정", "error")
                return None

            client = genai.Client(api_key=api_key)

            # 이미지 편집 모델
            model = self._settings.get("gemini_shadow", {}).get(
                "model", "gemini-3.1-flash-image-preview")

            # mime type 자동 감지
            def _detect_mime(data: bytes) -> str:
                if data[:8].startswith(b'\x89PNG'):
                    return "image/png"
                return "image/jpeg"

            # settings.yaml에서 프롬프트 로드 (없으면 기본값)
            gs_cfg = self._settings.get("gemini_shadow", {})
            ref_prompt = gs_cfg.get("ref_prompt",
                "위 이미지는 원본 제품 사진입니다. 원본에 있는 자연스러운 그림자의 "
                "방향, 농도, 부드러움을 참고하세요.")
            main_prompt = gs_cfg.get("main_prompt",
                "위 이미지는 배경이 제거된 누끼 이미지입니다. "
                "이 누끼 이미지의 바닥에 자연스러운 접지 그림자(ground shadow)를 추가해주세요. "
                "{has_original}"
                "제품 자체는 절대 변경하지 마세요. 배경은 깨끗한 흰색을 유지하세요. "
                "그림자는 제품 바로 아래에 부드럽게 퍼지는 형태로, "
                "럭셔리 이커머스 제품 사진처럼 고급스럽게 만들어주세요. "
                "누끼 이미지를 기반으로 결과를 출력하세요.")
            orig_insert = gs_cfg.get("orig_insert",
                "원본 사진의 그림자를 최대한 동일하게 재현해주세요. ")

            # 원본 이미지가 있으면 함께 전송하여 그림자 참고
            contents = []
            if original_bytes:
                contents.append(types.Part.from_bytes(
                    data=original_bytes, mime_type=_detect_mime(original_bytes)))
                contents.append(ref_prompt)
            contents.append(types.Part.from_bytes(
                data=image_bytes, mime_type=_detect_mime(image_bytes)))
            # {has_original} 치환
            final_prompt = main_prompt.replace(
                "{has_original}", orig_insert if original_bytes else "")
            contents.append(final_prompt)

            _log(f"  Gemini 그림자 요청 (모델: {model}, "
                 f"누끼: {_detect_mime(image_bytes)} {len(image_bytes)//1024}KB, "
                 f"원본 참고: {'O' if original_bytes else 'X'})")

            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            # 응답에서 이미지 추출
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    result_bytes = part.inline_data.data
                    _log(f"  Gemini 그림자 생성 완료 ({len(result_bytes) // 1024}KB)",
                         "success")
                    return result_bytes

            _log(f"  Gemini 응답에 이미지 없음", "warn")
            return None

        except Exception as e:
            _log(f"  Gemini 그림자 생성 오류: {e}", "error")
            logger.exception(f"Gemini shadow error: {e}")
            return None

    def _get_vision_config(self, provider: str) -> dict:
        """프로바이더별 API 설정(max_tokens, temperature 등)을 반환."""
        if provider == "chatgpt":
            return self._settings.get("openai", {})
        elif provider == "gemini":
            return self._settings.get("gemini", {})
        return self._settings.get("api", {})

    def _call_single_vision_api(self, provider: str, images: list,
                                system_prompt: str, user_prompt: str) -> dict:
        """단일 Vision API를 호출하고 JSON 파싱 결과를 반환한다."""
        try:
            client = self._create_vision_client(provider)
            cfg = self._get_vision_config(provider)
            response_text = client.analyze_images(
                images,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=cfg.get("max_tokens", 2048),
                temperature=cfg.get("temperature", 0.1),
            )
            parser = ResultParser()
            json_data = parser._extract_json(response_text)
            if json_data is None:
                return {"evaluator": provider, "error": "파싱 실패", "raw": response_text[:500]}
            json_data["evaluator"] = provider
            return json_data
        except Exception as e:
            logger.error(f"[{provider}] Vision API 호출 실패: {e}")
            return {"evaluator": provider, "error": str(e)}

    def _call_all_vision_apis(self, images: list, system_prompt: str,
                              user_prompt: str, on_log: Callable = None) -> list:
        """3개 Vision API(Claude, ChatGPT, Gemini)를 병렬 호출한다."""
        import concurrent.futures
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        providers = ["claude", "chatgpt", "gemini"]
        provider_names = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini"}
        results = []

        _log(f"  [토론] 3개 AI 동시 호출: {', '.join(provider_names.values())}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(
                    self._call_single_vision_api, p, images, system_prompt, user_prompt
                ): p for p in providers
            }
            for future in concurrent.futures.as_completed(futures):
                p = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    if result.get("error"):
                        _log(f"    {provider_names[p]}: 오류 - {result['error']}", "warn")
                    else:
                        avg = result.get("average_score", "?")
                        verdict = result.get("verdict", "?")
                        _log(f"    {provider_names[p]}: {verdict} (평균 {avg})")
                except Exception as e:
                    _log(f"    {provider_names[p]}: 예외 - {e}", "error")
                    results.append({"evaluator": p, "error": str(e)})

        return results

    def evaluate_result(self, original_path: str, result_path: str,
                        current_params: dict, on_log: Callable = None,
                        on_deliberation: Callable = None,
                        iteration_count: int = 0,
                        is_cancelled: Callable = None,
                        get_user_input: Callable = None) -> dict:
        """6단계 회의 프로세스로 원본 vs 결과를 비교 평가한다.

        Flow:
          1단계: 각자 의견 발의 (독립 평가)
          2단계: 상호 검토 (동의/반박)
          3단계: 문제점 인식 (공통 문제 정리)
          4단계: 각자 해결방법 제시 (5회차+ 시 심화탐색)
          5단계: 해결방법 토론 (동의/반박 반복, 합의까지)
          6단계: 최종 결정

        Args:
            on_deliberation: 실시간 콜백 (phase, provider, data)
            iteration_count: 현재 자동수정 회차 (5 이상이면 심화탐색)
            get_user_input: 사용자 메시지 큐 콜백 () -> list[str]

        Returns:
            {"verdict", "scores", "average_score", "problems",
             "reasoning", "adjusted_params", "code_issues", "deliberation_log"}
        """
        import json as _json
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        _delib = on_deliberation or (lambda phase, provider, data: None)
        _cancelled = is_cancelled or (lambda: False)
        _get_user = get_user_input or (lambda: [])
        pb = self._prompt_builder

        img_original = load_image(original_path)
        img_result = load_image(result_path)
        images = [img_original, img_result]
        deliberation_log = []

        def _valid(results):
            return [r for r in results if not r.get("error")]

        def _mc(msg):
            """사회자(MC) 발언을 콜백으로 전달한다."""
            _delib("mc", "mc", {"speech": msg})

        def _check_stop():
            """중지 요청 시 True 반환."""
            if _cancelled():
                _log(f"  [회의] 사용자에 의해 중지됨", "warn")
                _mc("회의가 중단되었습니다.")
                return True
            return False

        def _inject_user_input(prompt: str) -> str:
            """큐에 쌓인 사용자 메시지를 프롬프트에 추가한다."""
            msgs = _get_user()
            if not msgs:
                return prompt
            user_block = "\n".join(f"- {m}" for m in msgs)
            # 사회자가 사용자 의견을 전달
            _mc(f"회의 참석자(사용자)의 의견이 있습니다:\n{user_block}")
            return (prompt +
                    f"\n\n[회의 참석자(사용자) 의견 — 반드시 고려하세요]:\n{user_block}")

        # ══════════════════════════════════════
        # 1단계: 각자 의견 발의
        # ══════════════════════════════════════
        _log(f"  [회의] ━━ 1단계: 의견 발의 ━━")
        _delib("phase", "system", {"phase": 1, "title": "의견 발의"})
        _mc("안녕하세요, AI 품질 평가 회의를 시작하겠습니다. "
            "먼저 각 패널원께서 원본과 처리 결과를 비교하여 독립적인 의견을 발표해 주세요.")

        p1_prompt = _inject_user_input(pb.build_phase1_prompt(current_params))
        p1_results = self._call_all_vision_apis(
            images, pb.build_phase1_system(), p1_prompt, on_log)

        valid_p1 = _valid(p1_results)
        deliberation_log.append({"phase": 1, "results": p1_results})
        for r in valid_p1:
            _delib(1, r.get("evaluator", "?"), r)

        if not valid_p1:
            _log(f"  [회의] 모든 API 응답 실패", "error")
            return self._empty_eval_result(current_params, deliberation_log)

        if len(valid_p1) == 1:
            _log(f"  [회의] API 1개만 성공, 회의 축소 진행")
            return self._build_final_result(valid_p1[0], current_params,
                                            deliberation_log=deliberation_log)

        # 1단계 요약
        provider_verdicts = [f"{r.get('evaluator','?')}: {r.get('verdict','?')}"
                            for r in valid_p1]
        _mc(f"감사합니다. {len(valid_p1)}분의 의견을 들었습니다 "
            f"({', '.join(provider_verdicts)}). "
            f"이제 서로의 의견을 검토하고 동의 또는 반박해 주세요.")

        if _check_stop():
            return self._build_final_from_phase1(valid_p1, current_params, deliberation_log)

        # ══════════════════════════════════════
        # 2단계: 상호 검토 (동의/반박)
        # ══════════════════════════════════════
        _log(f"  [회의] ━━ 2단계: 상호 검토 ━━")
        _delib("phase", "system", {"phase": 2, "title": "상호 검토 (동의/반박)"})

        all_p1_text = _json.dumps(valid_p1, indent=2, ensure_ascii=False)
        p2_prompt = _inject_user_input(pb.build_phase2_prompt(all_p1_text))
        p2_results = self._call_all_vision_apis(
            images, pb.build_phase2_system(), p2_prompt, on_log)

        valid_p2 = _valid(p2_results)
        deliberation_log.append({"phase": 2, "results": p2_results})
        for r in valid_p2:
            _delib(2, r.get("evaluator", "?"), r)

        # 2단계 마무리
        _mc("상호 검토가 끝났습니다. "
            "이제 토론 내용을 바탕으로 공통된 문제점을 정리하겠습니다.")

        if _check_stop():
            return self._build_final_from_phase1(valid_p1, current_params, deliberation_log)

        # ══════════════════════════════════════
        # 3단계: 문제점 인식
        # ══════════════════════════════════════
        _log(f"  [회의] ━━ 3단계: 문제점 인식 ━━")
        _delib("phase", "system", {"phase": 3, "title": "문제점 인식"})
        _mc("모든 패널원의 의견을 종합하여 공통 문제점을 정리해 주세요.")

        # 1~2단계 전체 결과를 합쳐서 3단계에 전달
        all_so_far = _json.dumps(valid_p1 + (valid_p2 or []),
                                 indent=2, ensure_ascii=False)
        p3_prompt = _inject_user_input(pb.build_phase3_prompt(all_so_far))
        # 3단계는 메인 프로바이더가 정리
        p3_result = self._call_single_vision_api(
            self._vision_provider, images,
            pb.build_phase3_system(), p3_prompt)

        if p3_result.get("error"):
            fallback_provider = valid_p1[0].get("evaluator", "claude")
            p3_result = self._call_single_vision_api(
                fallback_provider, images,
                pb.build_phase3_system(), p3_prompt)

        deliberation_log.append({"phase": 3, "result": p3_result})
        _delib(3, p3_result.get("evaluator", "system"), p3_result)

        # 3단계 마무리
        n_problems = len(p3_result.get("agreed_problems", []))
        n_disputes = len(p3_result.get("disputed_points", []))
        _mc(f"문제 정리 완료: 공통 문제 {n_problems}건, 쟁점 {n_disputes}건. "
            f"이제 각 패널원께서 해결 방법을 제시해 주세요.")

        if _check_stop():
            return self._build_final_from_phase1(valid_p1, current_params, deliberation_log)

        # ══════════════════════════════════════
        # 4단계: 각자 해결방법 제시
        # ══════════════════════════════════════
        _log(f"  [회의] ━━ 4단계: 해결방법 제시 ━━")
        deep = iteration_count >= 5
        if deep:
            _log(f"  [회의] ** 심화 탐색 모드 (5회차 이상 반복) **", "warn")
        _delib("phase", "system", {
            "phase": 4, "title": "해결방법 제시",
            "deep_explore": deep})
        if deep:
            _mc("주의: 이미 5회 이상 수정을 반복했습니다. "
                "기존 방식과 완전히 다른 새로운 접근법을 포함해서 제안해 주세요. "
                "학술 논문, 다른 분야 기법 등 폭넓게 탐색해 주세요.")
        else:
            _mc("파라미터 수정과 코드 변경, 두 가지 방향으로 해결 방법을 제안해 주세요.")

        problem_text = _json.dumps(p3_result, indent=2, ensure_ascii=False)
        p4_prompt = _inject_user_input(
            pb.build_phase4_prompt(problem_text, iteration_count))
        p4_results = self._call_all_vision_apis(
            images, pb.build_phase4_system(), p4_prompt, on_log)

        valid_p4 = _valid(p4_results)
        deliberation_log.append({"phase": 4, "results": p4_results})
        for r in valid_p4:
            _delib(4, r.get("evaluator", "?"), r)

        _mc("해결 방법이 나왔습니다. "
            "서로의 제안을 검토하고 최적의 방법에 합의해 주세요.")

        if _check_stop():
            return self._build_final_from_phase1(valid_p1, current_params, deliberation_log)

        # ══════════════════════════════════════
        # 5단계: 해결방법 토론 (동의/반박 반복)
        # ══════════════════════════════════════
        _log(f"  [회의] ━━ 5단계: 해결방법 토론 ━━")
        _delib("phase", "system", {"phase": 5, "title": "해결방법 토론"})

        latest_solutions = valid_p4 or valid_p1
        max_fix_rounds = 3
        for fix_round in range(1, max_fix_rounds + 1):
            if _check_stop():
                break
            _mc(f"해결방법 토론 {fix_round}차 — 동의/반박 후 최종안을 정리해 주세요.")

            solutions_text = _json.dumps(latest_solutions, indent=2, ensure_ascii=False)
            p5_prompt = _inject_user_input(
                pb.build_phase5_prompt(solutions_text, fix_round))
            p5_results = self._call_all_vision_apis(
                images, pb.build_phase5_system(), p5_prompt, on_log)

            valid_p5 = _valid(p5_results)
            deliberation_log.append({
                "phase": 5, "round": fix_round, "results": p5_results})
            for r in valid_p5:
                _delib(5, r.get("evaluator", "?"), r)

            if valid_p5:
                latest_solutions = valid_p5
                # 5단계 추천 파라미터를 수집 (6단계 fallback용)
                for r in valid_p5:
                    rp = r.get("recommended_params")
                    if rp and isinstance(rp, dict):
                        # adjusted_params로도 전달되도록 복사
                        if "adjusted_params" not in r:
                            r["adjusted_params"] = rp

            # 합의 확인
            consensus_count = sum(
                1 for r in valid_p5 if r.get("consensus_reached", False))
            if consensus_count >= len(valid_p5):
                _mc(f"{fix_round}차 토론에서 해결 방법에 합의가 이루어졌습니다!")
                _log(f"  [회의] 5단계 {fix_round}차에서 해결방법 합의!")
                break

        if _check_stop():
            return self._build_final_from_phase1(valid_p1, current_params, deliberation_log)

        # ══════════════════════════════════════
        # 6단계: 최종 결정
        # ══════════════════════════════════════
        _log(f"  [회의] ━━ 6단계: 최종 결정 ━━")
        _delib("phase", "system", {"phase": 6, "title": "최종 결정"})
        _mc("모든 토론이 끝났습니다. 최종 결정을 내려주세요.")

        final_text = _json.dumps(latest_solutions, indent=2, ensure_ascii=False)
        total_rounds = len([d for d in deliberation_log if d.get("phase") == 5])

        p6_prompt = _inject_user_input(
            pb.build_phase6_prompt(final_text, total_rounds, current_params))
        p6_result = self._call_single_vision_api(
            self._vision_provider, images,
            pb.build_phase6_system(), p6_prompt)

        if p6_result.get("error"):
            _log(f"  [회의] 최종 결정 실패, 토론 결과 평균 사용", "warn")
            p6_result = self._merge_results_fallback(latest_solutions)

        deliberation_log.append({"phase": 6, "result": p6_result})
        _delib(6, p6_result.get("evaluator", "consensus"), p6_result)

        result = self._build_final_result(p6_result, current_params,
                                          deliberation_log=deliberation_log)

        _mc(f"회의 종료 — 최종 판정: {result['verdict']} "
            f"(평균 {result['average_score']:.1f}/10)")

        _log(f"  [회의] 최종: {result['verdict']} (평균 {result['average_score']:.1f}/10)")
        if result.get("code_issues"):
            _log(f"  [회의] 코드 수정 제안 {len(result['code_issues'])}건:")
            for ci in result["code_issues"]:
                _log(f"    [{ci.get('severity', '?')}] {ci.get('description', '')}")

        return result

    def _build_final_from_phase1(self, phase1_results: list,
                                 current_params: dict,
                                 deliberation_log: list) -> dict:
        """중지 시 1단계 결과를 기반으로 최종 결과를 구성한다."""
        merged = self._merge_results_fallback(phase1_results)
        return self._build_final_result(merged, current_params,
                                        deliberation_log=deliberation_log)

    def _empty_eval_result(self, current_params: dict,
                           deliberation_log: list) -> dict:
        return {
            "verdict": "needs_improvement", "scores": {},
            "average_score": 0, "problems": ["모든 API 평가 실패"],
            "reasoning": "3개 Vision API 모두 응답 실패",
            "adjusted_params": dict(current_params),
            "code_issues": [], "deliberation_log": deliberation_log,
        }

    def _build_final_result(self, json_data: dict, current_params: dict,
                            deliberation_log: list = None) -> dict:
        """평가 JSON을 최종 반환 형식으로 변환한다."""
        verdict = json_data.get("verdict", "needs_improvement")
        scores = json_data.get("scores", {})
        avg = json_data.get("average_score", 0)
        if not avg and scores:
            avg = sum(scores.values()) / len(scores)

        adjusted = json_data.get("adjusted_params") or {}
        merged_params = dict(current_params)

        if adjusted.get("shadow_config"):
            sc = dict(merged_params.get("shadow_config", {}))
            for k, v in adjusted["shadow_config"].items():
                if isinstance(v, (int, float)):
                    sc[k] = v
            merged_params["shadow_config"] = sc

        if adjusted.get("enhance_config"):
            ec = dict(merged_params.get("enhance_config", {}))
            for k, v in adjusted["enhance_config"].items():
                if isinstance(v, (int, float)):
                    ec[k] = v
            merged_params["enhance_config"] = ec

        return {
            "verdict": verdict,
            "scores": scores,
            "average_score": avg,
            "problems": json_data.get("problems", []),
            "reasoning": json_data.get("reasoning", ""),
            "adjusted_params": merged_params,
            "code_issues": json_data.get("code_issues", []),
            "deliberation_log": deliberation_log or [],
        }

    def _merge_results_fallback(self, results: list) -> dict:
        """토론 결과들의 평균으로 합의를 대체한다 (fallback)."""
        import statistics
        all_scores = {}
        for r in results:
            for k, v in r.get("scores", {}).items():
                all_scores.setdefault(k, []).append(v)

        median_scores = {k: statistics.median(v) for k, v in all_scores.items()}
        avg = sum(median_scores.values()) / max(len(median_scores), 1)

        # verdict 판정
        min_score = min(median_scores.values()) if median_scores else 0
        if min_score >= 9:
            verdict = "perfect"
        elif min_score >= 6 and avg >= 7:
            verdict = "acceptable"
        else:
            verdict = "needs_improvement"

        # 파라미터: 보수적 병합 — 가장 작은 변경만 채택
        merged_shadow = {}
        merged_enhance = {}
        for r in results:
            adj = r.get("adjusted_params") or {}
            for k, v in (adj.get("shadow_config") or {}).items():
                if isinstance(v, (int, float)):
                    merged_shadow.setdefault(k, []).append(v)
            for k, v in (adj.get("enhance_config") or {}).items():
                if isinstance(v, (int, float)):
                    merged_enhance.setdefault(k, []).append(v)

        shadow_cfg = {k: statistics.median(v) for k, v in merged_shadow.items()} if merged_shadow else None
        enhance_cfg = {k: statistics.median(v) for k, v in merged_enhance.items()} if merged_enhance else None

        # code_issues: 2개 이상 API가 언급한 것만
        from collections import Counter
        issue_descs = Counter()
        issue_map = {}
        for r in results:
            for ci in r.get("code_issues", []):
                desc = ci.get("description", "")
                issue_descs[desc] += 1
                issue_map[desc] = ci
        code_issues = [issue_map[d] for d, cnt in issue_descs.items() if cnt >= 2]

        all_problems = []
        for r in results:
            all_problems.extend(r.get("problems", []))

        return {
            "scores": median_scores,
            "average_score": avg,
            "verdict": verdict,
            "problems": list(set(all_problems)),
            "reasoning": "Fallback: 합의 도출 실패, 토론 결과 중앙값 사용",
            "adjusted_params": {
                "shadow_config": shadow_cfg,
                "enhance_config": enhance_cfg,
            },
            "code_issues": code_issues,
        }

    @staticmethod
    def _detect_shadow_in_original(image_bytes: bytes) -> bool:
        """원본 이미지 바닥 영역을 분석하여 그림자 존재 여부를 판단한다.

        배경(주로 밝은색)과 바닥 영역의 밝기 차이를 비교하여 판단.
        """
        from PIL import Image
        import io
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            arr = np.array(img)
            h, w = arr.shape[:2]

            # 상단 10% (배경 참조)
            top_region = arr[:int(h * 0.1), :].reshape(-1, 3)
            bg_brightness = np.mean(top_region.astype(np.float32))

            # 너무 어두운 배경이면 그림자 판단 불가
            if bg_brightness < 180:
                return False

            # 하단 15% 영역 (그림자가 위치하는 곳)
            bottom_region = arr[int(h * 0.85):, :]
            # 중앙 60%만 (좌우 여백 제외)
            x_start = int(w * 0.2)
            x_end = int(w * 0.8)
            bottom_center = bottom_region[:, x_start:x_end].reshape(-1, 3)
            bottom_brightness = np.mean(bottom_center.astype(np.float32))

            # 배경 대비 바닥 밝기 차이가 10 이상이면 그림자 있음
            diff = bg_brightness - bottom_brightness
            logger.debug(f"그림자 감지: 배경 밝기={bg_brightness:.1f}, "
                         f"바닥 밝기={bottom_brightness:.1f}, 차이={diff:.1f}")
            return diff > 10.0
        except Exception as e:
            logger.warning(f"그림자 감지 실패: {e}")
            return False  # 확신 없으면 AI 판단에 맡김

    @staticmethod
    def _force_param_change(params: dict, problems: list,
                            scores: dict) -> dict:
        """AI가 동일 파라미터를 반환했을 때 문제점 기반으로 강제 조정한다."""
        import copy
        result = copy.deepcopy(params) if params else {}
        sc = result.setdefault("shadow_config", {})
        ec = result.setdefault("enhance_config", {})
        problems_lower = " ".join(problems).lower()

        # 점수가 낮은 항목 기반 자동 조정
        shadow_score = scores.get("shadow_naturalness", 10)
        color_score = scores.get("color_accuracy", 10)
        detail_score = scores.get("detail_preservation", 10)
        bg_score = scores.get("background_cleanliness", 10)

        if shadow_score < 7:
            # 그림자 문제: opacity와 blur 조정
            cur_opacity = sc.get("opacity", 70)
            cur_blur = sc.get("blur", 10.0)
            if "진하" in problems_lower or "어두" in problems_lower or "dark" in problems_lower:
                sc["opacity"] = max(30, cur_opacity - 15)
            elif "흐" in problems_lower or "연" in problems_lower or "faint" in problems_lower:
                sc["opacity"] = min(100, cur_opacity + 15)
            else:
                # 방향 불명: 10% 감소 시도
                sc["opacity"] = max(30, cur_opacity - 10)
            if "부자연" in problems_lower or "sharp" in problems_lower:
                sc["blur"] = round(cur_blur + 3.0, 1)
            elif "흐릿" in problems_lower or "blur" in problems_lower:
                sc["blur"] = round(max(1.0, cur_blur - 3.0), 1)
            logger.info(f"  [강제조정] shadow: opacity {cur_opacity}→{sc['opacity']}, "
                        f"blur {cur_blur}→{sc['blur']}")

        if color_score < 7:
            cur_sat = ec.get("saturation", 0)
            cur_exp = ec.get("exposure", 0)
            if "채도" in problems_lower or "색" in problems_lower:
                ec["saturation"] = cur_sat + (5 if cur_sat >= 0 else -5)
            if "밝" in problems_lower or "어두" in problems_lower:
                ec["exposure"] = cur_exp + (5 if "어두" in problems_lower else -5)
            logger.info(f"  [강제조정] enhance: saturation→{ec.get('saturation')}, "
                        f"exposure→{ec.get('exposure')}")

        if detail_score < 7:
            cur_sharp = ec.get("sharpness", 10)
            cur_hdr = ec.get("hdr", 15)
            if "과" in problems_lower or "over" in problems_lower:
                ec["sharpness"] = max(0, cur_sharp - 5)
                ec["hdr"] = max(0, cur_hdr - 5)
            else:
                ec["sharpness"] = min(30, cur_sharp + 5)
            logger.info(f"  [강제조정] detail: sharpness→{ec.get('sharpness')}, "
                        f"hdr→{ec.get('hdr')}")

        if bg_score < 7:
            # 배경 문제: threshold 조정
            cur_th = sc.get("threshold", 15)
            sc["threshold"] = max(5, cur_th - 5)
            logger.info(f"  [강제조정] bg: threshold {cur_th}→{sc['threshold']}")

        return result

    @staticmethod
    def create_rollback_snapshot(snapshot_dir: str = None) -> str:
        """자동수정 전 소스 코드 스냅샷을 생성한다.

        Returns:
            스냅샷 디렉토리 경로
        """
        import shutil
        src_root = Path(__file__).parent  # src/
        project_root = src_root.parent
        if snapshot_dir is None:
            ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_dir = str(project_root / "backups" / f"rollback_{ts}")

        Path(snapshot_dir).mkdir(parents=True, exist_ok=True)

        # 백업 대상: src/ 전체 + config/
        for target in ["src", "config"]:
            src_path = project_root / target
            dst_path = Path(snapshot_dir) / target
            if src_path.exists():
                shutil.copytree(str(src_path), str(dst_path), dirs_exist_ok=True)

        # 스냅샷 정보 기록
        import json as _j
        info = {
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "project_root": str(project_root),
            "backed_up": ["src", "config"],
        }
        with open(str(Path(snapshot_dir) / "_snapshot_info.json"), "w", encoding="utf-8") as f:
            _j.dump(info, f, ensure_ascii=False, indent=2)

        logger.info(f"롤백 스냅샷 생성: {snapshot_dir}")
        return snapshot_dir

    @staticmethod
    def rollback_from_snapshot(snapshot_dir: str) -> bool:
        """스냅샷에서 소스 코드를 복원한다.

        Args:
            snapshot_dir: create_rollback_snapshot()이 반환한 경로

        Returns:
            성공 여부
        """
        import shutil
        import json as _j

        info_path = Path(snapshot_dir) / "_snapshot_info.json"
        if not info_path.exists():
            logger.error(f"스냅샷 정보 없음: {info_path}")
            return False

        with open(str(info_path), "r", encoding="utf-8") as f:
            info = _j.load(f)

        project_root = Path(info["project_root"])
        backed_up = info.get("backed_up", ["src", "config"])

        for target in backed_up:
            src_path = Path(snapshot_dir) / target
            dst_path = project_root / target
            if src_path.exists():
                # 기존 삭제 후 복원
                if dst_path.exists():
                    shutil.rmtree(str(dst_path))
                shutil.copytree(str(src_path), str(dst_path))

        logger.info(f"롤백 완료: {snapshot_dir} → {project_root}")
        return True

    def process_with_refinement(self, image_path: str, category: str,
                                output_dir: str, max_iterations: int = 3,
                                skip_analysis: bool = False,
                                skip_photoroom: bool = False,
                                on_log: Callable = None,
                                on_iteration: Callable = None,
                                on_deliberation: Callable = None,
                                is_cancelled: Callable = None,
                                get_user_input: Callable = None) -> dict:
        """자동 수정 루프: process_single → evaluate → 파라미터 조정 → 재처리.

        Args:
            max_iterations: 최대 반복 횟수 (1~10)
            on_iteration: 콜백(iteration_num, total)
            on_deliberation: 토론 실시간 콜백(provider, round, data)
            get_user_input: 사용자 메시지 큐 콜백 () -> list[str]

        Returns:
            {"iterations": [...], "final_result": {...}, "best_iteration": int,
             "rollback_snapshot": str}
        """
        import json as _json
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        # ── 롤백 스냅샷 생성 ──
        _log(f"  [롤백] 소스 코드 스냅샷 생성 중...")
        snapshot_dir = self.create_rollback_snapshot()
        _log(f"  [롤백] 스냅샷 저장: {snapshot_dir}")

        base_name = FileNamer.extract_base_from_path(image_path)
        # 자동수정 전용 하위 폴더 생성
        refine_dir = str(Path(output_dir) / "자동수정")
        Path(refine_dir).mkdir(parents=True, exist_ok=True)

        iterations_log = []
        current_params = None
        best_score = 0
        best_iteration = 1

        _log(f"━━━ 자동 수정 시작 (최대 {max_iterations}회) ━━━")
        _log(f"  출력 폴더: {refine_dir}")

        _cancelled = is_cancelled or (lambda: False)

        for i in range(1, max_iterations + 1):
            if _cancelled():
                _log(f"  사용자에 의해 자동 수정 중지됨", "warn")
                break

            _log(f"\n{'─' * 40}")
            _log(f"  [{i}/{max_iterations}회차] 처리 중...")

            if on_iteration:
                on_iteration(i, max_iterations)

            # 회차별 파일명
            iter_base = f"{base_name}_{i}회차"

            # 1. 처리 실행
            result = self.process_single(
                image_path=image_path,
                category=category,
                output_dir=refine_dir,
                base_name=iter_base,
                skip_analysis=(i > 1),  # 2회차부터 분석 스킵
                skip_photoroom=skip_photoroom,
                override_params=current_params,
                on_log=on_log,
            )

            if not result.get("files"):
                _log(f"  [{i}회차] 처리 실패, 중단", "error")
                break

            output_file = result["files"][0]["path"]
            used_params = result.get("used_params", {})

            if _cancelled():
                _log(f"  사용자에 의해 자동 수정 중지됨", "warn")
                break

            # 2. 비교 평가 (3-API 6단계 회의)
            evaluation = self.evaluate_result(
                original_path=image_path,
                result_path=output_file,
                current_params=used_params,
                on_log=on_log,
                on_deliberation=on_deliberation,
                iteration_count=i,
                is_cancelled=is_cancelled,
                get_user_input=get_user_input,
            )

            # 3. 기록
            iteration_record = {
                "iteration": i,
                "params": used_params,
                "scores": evaluation["scores"],
                "average_score": evaluation["average_score"],
                "verdict": evaluation["verdict"],
                "problems": evaluation.get("problems", []),
                "reasoning": evaluation["reasoning"],
                "output_file": output_file,
            }
            iterations_log.append(iteration_record)

            # best 추적
            avg = evaluation.get("average_score", 0)
            if avg > best_score:
                best_score = avg
                best_iteration = i

            _log(f"  [{i}회차] 평가: {evaluation['verdict']} (평균 {avg:.1f}/10)")

            # 4. 종료 조건
            if evaluation["verdict"] in ("perfect", "acceptable"):
                _log(f"  ✓ {evaluation['verdict']} — 자동 수정 완료!", "success")
                break

            # 5. 다음 회차 파라미터 준비
            if i < max_iterations:
                prev_params = current_params
                current_params = evaluation["adjusted_params"]
                # 파라미터 변경 사항 확인
                if prev_params and current_params:
                    changed = []
                    for section in ("shadow_config", "enhance_config"):
                        old_sec = (prev_params or {}).get(section, {})
                        new_sec = (current_params or {}).get(section, {})
                        for k in set(list(old_sec.keys()) + list(new_sec.keys())):
                            ov = old_sec.get(k)
                            nv = new_sec.get(k)
                            if ov != nv:
                                changed.append(f"{section}.{k}: {ov}→{nv}")
                    if changed:
                        _log(f"  → 파라미터 변경: {', '.join(changed)}")
                    else:
                        # ★ 동일 파라미터 반복 방지: 문제점 기반으로 강제 조정
                        _log(f"  ⚠ AI가 동일 값 반환 — 문제 기반 강제 조정", "warn")
                        current_params = self._force_param_change(
                            current_params, evaluation.get("problems", []),
                            evaluation.get("scores", {}))
                _log(f"  → {i + 1}회차 진행...")

        # 파라미터 로그 JSON 저장
        log_path = Path(refine_dir) / f"{base_name}_refinement_log.json"
        with open(log_path, "w", encoding="utf-8") as f:
            _json.dump(iterations_log, f, ensure_ascii=False, indent=2, default=str)
        _log(f"\n  파라미터 로그: {log_path.name}")

        _log(f"━━━ 자동 수정 종료: {len(iterations_log)}회 반복, "
             f"최적={best_iteration}회차 (평균 {best_score:.1f}/10) ━━━")

        return {
            "iterations": iterations_log,
            "final_result": result,
            "best_iteration": best_iteration,
            "best_score": best_score,
            "rollback_snapshot": snapshot_dir,
        }

    def process_batch(self, input_dir: str, category: str, output_dir: str,
                      skip_analysis: bool = False, skip_photoroom: bool = False,
                      on_log: Callable = None,
                      on_progress: Callable = None,
                      is_cancelled: Callable = None) -> list:
        """배치 처리 - process_single 반복 호출."""
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        extensions = self._settings.get("image", {}).get(
            "supported_formats", [".jpg", ".jpeg", ".png"]
        )
        image_files = get_image_files(input_dir, extensions)

        if not image_files:
            _log(f"처리할 이미지가 없습니다: {input_dir}", "warn")
            return []

        total = len(image_files)
        _log(f"배치 처리 시작: {total}개 이미지")
        results = []
        batch_category = category
        detected_on_first = False

        for idx, img_path in enumerate(image_files, 1):
            if is_cancelled and is_cancelled():
                _log("작업이 중지되었습니다.", "warn")
                break

            _log(f"-- [{idx}/{total}] {Path(img_path).name} --")
            if on_progress:
                on_progress(idx, total)

            try:
                base_name = f"{idx:03d}"
                result = self.process_single(
                    image_path=img_path, category=batch_category, output_dir=output_dir,
                    base_name=base_name, skip_analysis=skip_analysis,
                    skip_photoroom=skip_photoroom, on_log=on_log,
                )
                results.append({"path": img_path, "success": True, **result})

                if not detected_on_first and not category and result.get("instruction"):
                    inst = result["instruction"]
                    if inst.detected_category:
                        batch_category = inst.detected_category
                        detected_on_first = True
                        _log(f"== 배치 카테고리 확정: {batch_category} "
                             f"({inst.detected_category_display}) ==", "success")
            except Exception as e:
                _log(f"  실패: {e}", "error")
                results.append({"path": img_path, "success": False, "error": str(e)})

            # API 과부하 방지: 배치 간 1초 대기
            if idx < total and not skip_analysis:
                import time
                time.sleep(1)

        success_count = sum(1 for r in results if r["success"])
        _log(f"배치 완료: 성공 {success_count}/{len(results)}", "success")
        return results
