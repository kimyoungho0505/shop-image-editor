"""전체 이미지 편집 파이프라인 오케스트레이터."""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import yaml
from loguru import logger


def _update_progress_log(output_dir: str, source_filename: str, success: bool) -> None:
    """OUTPUT/.shop_progress.json 에 처리 결과를 기록한다.

    Args:
        output_dir:       출력 폴더 경로 (예: D:/photos/OUTPUT)
        source_filename:  원본 파일명 (예: IMG_001.jpg)
        success:          처리 성공 여부
    """
    try:
        log_path = Path(output_dir) / ".shop_progress.json"
        if log_path.exists():
            try:
                data = json.loads(log_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        data.setdefault("completed", [])
        data.setdefault("failed", [])
        data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if success:
            if source_filename not in data["completed"]:
                data["completed"].append(source_filename)
            # 재처리 성공 시 실패 목록에서 제거
            data["failed"] = [f for f in data["failed"] if f != source_filename]
        else:
            if source_filename not in data["failed"]:
                data["failed"].append(source_filename)

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"진행 로그 기록 실패: {e}")

from .analyzer.vision_client import VisionClient
from .analyzer.openai_vision_client import OpenAIVisionClient
from .analyzer.gemini_vision_client import GeminiVisionClient
from .analyzer.grok_vision_client import GrokVisionClient
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


def _shrink_bytes(image_bytes: bytes, max_px: int = 3000) -> bytes:
    """이미지 바이트가 max_px 초과 시 비율 유지하며 JPEG로 축소 반환.
    API 전송 전 메모리·처리 비용 절감 목적."""
    from PIL import Image
    import io
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            w, h = img.size
            if max(w, h) <= max_px:
                return image_bytes
            scale = max_px / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = img.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=92)
            resized.close()
            return buf.getvalue()
    except Exception:
        return image_bytes


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

    # 그림자 탐색: 제품 윤곽 하단을 따라가는 contour-following + 그라데이션 페이드
    shadow_margin = int(prod_h * 0.25)
    fade_ratio = 0.4  # 하단 40%는 페이드

    # 각 열(column)마다 제품 하단 경계를 찾아 그 아래로 shadow_margin만큼 보존
    import cv2 as _cv2
    gray = np.mean(arr, axis=2)
    product_pixels_raw = gray < 248  # 제품 영역 (임계값 완화: 245→248)
    # 제품 마스크 팽창: 밝은 가장자리(흰 테이프 등) 포함
    _kernel = np.ones((5, 5), dtype=np.uint8)
    product_pixels = _cv2.dilate(
        product_pixels_raw.astype(np.uint8), _kernel, iterations=1
    ).astype(bool)

    # 열별 제품 하단 경계 계산
    overlap = 5  # 제품-그림자 겹침 (흰 틈 방지)
    col_bottoms = np.full(w, p_y_max, dtype=int)
    for col in range(keep_x_min, keep_x_max):
        col_rows = np.where(product_pixels[:, col])[0]
        if len(col_rows) > 0:
            col_bottoms[col] = col_rows[-1]

    # 그림자 보존 마스크 생성 (contour-following + overlap)
    shadow_preserve = np.zeros((h, w), dtype=bool)
    for col in range(keep_x_min, keep_x_max):
        cb = col_bottoms[col]
        zone_start = max(0, cb - overlap)
        zone_end = min(h, cb + shadow_margin)
        shadow_preserve[zone_start:zone_end, col] = True

    # 제품 영역 위: 순백
    arr[:max(0, p_y_min - int(prod_h * 0.05)), :] = 255
    # 제품+그림자 밖의 하단: 순백
    overall_limit = min(h, p_y_max + shadow_margin)
    arr[overall_limit:, :] = 255
    # 좌우 밖: 순백 (이미 위에서 처리됨)

    # 그림자 보존 영역 하단부 그라데이션 페이드 (contour-following)
    fade_pixels = int(shadow_margin * fade_ratio)
    for col in range(keep_x_min, keep_x_max):
        cb = col_bottoms[col]
        zone_end = min(h, cb + shadow_margin)
        fade_start = zone_end - fade_pixels
        if fade_start > cb:
            for y in range(fade_start, zone_end):
                alpha = (y - fade_start) / (zone_end - fade_start)
                arr[y, col] = (
                    arr[y, col].astype(np.float32) * (1 - alpha)
                    + 255.0 * alpha
                ).astype(np.uint8)

    # 근백색 클린업: 제품+그림자 보존 영역은 보호 (임계값 완화: 250)
    near_white = np.all(arr > 250, axis=2)
    combined_preserve = product_pixels | shadow_preserve
    near_white[combined_preserve] = False
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


class ClaidNoCreditError(RuntimeError):
    """Claid.ai API 크레딧 부족 오류 — 처리 중단 신호."""
    pass


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
        self._claid_no_credits = False   # True이면 이 세션에서 Claid 스킵
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
        self._last_bg_provider = self._bg_provider  # hybrid 모드에서 실제 사용 프로바이더 추적
        self._enhance_provider = providers.get("enhancement", "claid")
        self._shadow_provider = providers.get("shadow", "opencv_extract")
        shadow_cfg = self._settings.get("shadow_extract", {})
        self._shadow_method = shadow_cfg.get("method", "level_correction")
        self._shadow_judge_mode = self._settings.get("shadow_judge_mode", "auto")
        logger.info(f"파이프라인 초기화: 분석={self._vision_provider}, 배경제거={self._bg_provider}, "
                    f"보정={self._enhance_provider}, 그림자={self._shadow_provider} ({self._shadow_method})")

    def _claid_process_safe(self, image_bytes: bytes, image_type: str,
                            config: dict = None, fallback: bytes = None,
                            on_log=None) -> bytes:
        """Claid.ai 보정 호출 — 크레딧 부족 시 ClaidNoCreditError 발생, 일반 오류 시 fallback 반환."""
        _log = on_log or (lambda msg, tag="info": None)
        try:
            result = self._claid.process(image_bytes, image_type, config=config)
            if not result:
                _log("  Claid 응답 없음 → fallback 사용", "warn")
                return fallback if fallback is not None else image_bytes
            return result
        except RuntimeError as e:
            msg = str(e)
            if "402" in msg or "billing" in msg or "12017" in msg or "credits" in msg.lower():
                _log("  ❌ Claid.ai 크레딧 부족 — 처리를 중지합니다", "error")
                raise ClaidNoCreditError(
                    "Claid.ai API 크레딧이 부족합니다.\n"
                    "크레딧을 충전한 후 다시 시작하세요."
                ) from e
            _log(f"  ❌ Claid 오류: {e}", "error")
            return fallback if fallback is not None else image_bytes

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
            elif self._vision_provider == "grok":
                grok_config = self._settings.get("grok", {})
                self._vision_client = GrokVisionClient(
                    model=grok_config.get("model", "grok-4-fast-non-reasoning")
                )
            else:
                api_config = self._settings.get("api", {})
                self._vision_client = VisionClient(
                    model=api_config.get("model", "claude-sonnet-4-20250514")
                )
        return self._vision_client

    def _check_nukki_quality(self, original_bytes: bytes, nukki_bytes: bytes,
                             image_type: str, on_log: Callable = None) -> tuple:
        """Vision API로 누끼(배경 제거) 품질을 검증한다.

        원본과 누끼 결과를 비교하여 배경 제거 품질을 판정.
        Returns:
            (True, "") if quality is acceptable
            (False, reason_string) if quality is poor
        """
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        try:
            _log("  [hybrid] Vision API 누끼 품질 검증 중...")
            vision_client = self._get_vision_client()
            vision_config = self._get_vision_config(self._vision_provider)

            system_prompt = (
                "당신은 상품 이미지 배경 제거(누끼) 품질 검수 전문가입니다. "
                "원본 이미지와 배경 제거 결과를 비교하여 품질을 판정하세요."
            )
            user_prompt = (
                f"상품 유형: {image_type}\n\n"
                "첫 번째 이미지가 원본, 두 번째 이미지가 배경 제거(누끼) 결과입니다.\n\n"
                "다음 항목을 검사하세요:\n"
                "1. 상품 보존: 상품의 일부가 잘리거나 훼손되지 않았는가?\n"
                "2. 배경 제거: 배경이 깨끗하게 제거되었는가? (잔여물 없음)\n"
                "3. 엣지 품질: 상품 경계가 자연스러운가? (계단현상, 헤일로 없음)\n\n"
                "반드시 아래 JSON 형식으로만 응답하세요:\n"
                '{"pass": true/false, "reason": "판정 사유 (한국어, 1줄)"}'
            )

            images = [original_bytes, nukki_bytes]
            max_tokens = vision_config.get("max_tokens", 1024)
            temperature = vision_config.get("temperature", 0.1)

            response_text = vision_client.analyze_images(
                images, user_prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature
            )

            # JSON 파싱
            import json as _json
            import re as _re
            json_match = _re.search(r'\{[^}]+\}', response_text or "")
            if json_match:
                result = _json.loads(json_match.group())
                is_pass = result.get("pass", False)
                reason = result.get("reason", "")
                if is_pass:
                    _log(f"  [hybrid] Vision 검증 통과: {reason}")
                    return True, ""
                else:
                    _log(f"  [hybrid] Vision 검증 불합격: {reason}")
                    return False, reason
            else:
                _log(f"  [hybrid] Vision 응답 파싱 실패: {(response_text or '')[:200]}")
                # 파싱 실패 시 Photoroom 결과 채택 (보수적)
                return True, ""

        except Exception as e:
            _log(f"  [hybrid] Vision 검증 오류: {e} → Photoroom 결과 채택")
            # Vision API 오류 시 Photoroom 결과 채택 (비용 절약 우선)
            return True, ""

    def _call_photoroom(self, image_bytes: bytes, image_type: str,
                        background: str, output_size: str,
                        is_detail: bool, include_shadow: bool,
                        ai_photoroom_params: dict, on_log: Callable) -> Optional[bytes]:
        """Photoroom 배경 제거 호출 (내부 헬퍼)."""
        pr_settings = self._settings.get("photoroom", {})
        if is_detail:
            pr_config = dict(pr_settings.get("detail_complex", {}))
        elif image_type == "package":
            pr_config = dict(pr_settings.get("package", {}))
        else:
            pr_config = dict(pr_settings.get("full", {}))

        if ai_photoroom_params:
            for k, v in ai_photoroom_params.items():
                if k in pr_config:
                    pr_config[k] = v
            on_log(f"  AI 추천 Photoroom 파라미터 적용: {ai_photoroom_params}")

        if not include_shadow:
            pr_config = {k: v for k, v in pr_config.items()
                         if not k.startswith("shadow.")}

        return self._photoroom.process(
            image_bytes, image_type, background,
            output_size=output_size, config=pr_config)

    def _call_bg_removal(self, image_bytes: bytes, image_type: str,
                         background: str, output_size: str = "1000x1000",
                         is_detail: bool = False, include_shadow: bool = False,
                         ai_photoroom_params: dict = None,
                         on_log: Callable = None) -> Optional[bytes]:
        """프로바이더에 따라 배경 제거를 호출한다."""
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        if self._bg_provider == "removebg":
            self._last_bg_provider = "removebg"
            rb_config = self._settings.get("removebg", {})
            return self._removebg.process(
                image_bytes, image_type, background,
                output_size=output_size, config=rb_config)

        elif self._bg_provider == "hybrid":
            # 1차: Photoroom 시도
            _log("  [hybrid] 1차: Photoroom 배경 제거 시도...")
            try:
                pr_result = self._call_photoroom(
                    image_bytes, image_type, background, output_size,
                    is_detail, include_shadow, ai_photoroom_params, _log)

                if pr_result:
                    is_ok, reason = self._check_nukki_quality(
                        image_bytes, pr_result, image_type, _log)
                    if is_ok:
                        self._last_bg_provider = "photoroom"
                        _log("  [hybrid] Photoroom 결과 채택 ✓")
                        return pr_result
                    else:
                        _log(f"  [hybrid] Photoroom 품질 불량: {reason}")
                else:
                    _log("  [hybrid] Photoroom 반환값 없음")
            except Exception as e:
                _log(f"  [hybrid] Photoroom 오류: {e}")

            # 2차: remove.bg 폴백
            _log("  [hybrid] 2차: remove.bg 폴백 실행...")
            self._last_bg_provider = "removebg"
            rb_config = self._settings.get("removebg", {})
            return self._removebg.process(
                image_bytes, image_type, background,
                output_size=output_size, config=rb_config)

        else:
            # Photoroom 단독
            self._last_bg_provider = "photoroom"
            return self._call_photoroom(
                image_bytes, image_type, background, output_size,
                is_detail, include_shadow, ai_photoroom_params, _log)

    def _get_category_padding(self, category: str, output_size: int = 1000) -> dict:
        """카테고리별 여백(px)을 반환. padding_percent(%) → output_size 기준 px 변환.

        여백 %는 출력 캔버스 크기 대비 비율.
        예: output_size=1000, padding=10% → 100px
        """
        cats_data = {}
        try:
            cats_path = Path(self._category_mgr._config_path)
            with open(str(cats_path), "r", encoding="utf-8") as f:
                cats_data = yaml.safe_load(f)
        except Exception:
            pass

        default_pct = {"top": 10, "bottom": 10, "left": 10, "right": 10}

        # 카테고리별 → default → 하드코딩 fallback
        cat_info = cats_data.get("categories", {}).get(category, {})

        # 새 형식(padding_percent) 우선, 구 형식(padding_860) fallback
        pad_pct = cat_info.get("padding_percent")
        if not pad_pct:
            # 구 형식 호환: padding_860이 있으면 860 기준 px → % 자동 변환
            pad_860 = cat_info.get("padding_860")
            if pad_860:
                pad_pct = {
                    k: round(v / 860.0 * 100, 1)
                    for k, v in pad_860.items()
                }
                logger.info(f"카테고리 '{category}' 구 형식(padding_860) → % 변환: {pad_pct}")
            else:
                pad_pct = cats_data.get("default", {}).get("padding_percent")
                if not pad_pct:
                    pad_860 = cats_data.get("default", {}).get("padding_860")
                    if pad_860:
                        pad_pct = {
                            k: round(v / 860.0 * 100, 1)
                            for k, v in pad_860.items()
                        }
                    else:
                        pad_pct = default_pct
                logger.warning(f"카테고리 '{category}' 여백 없음 → default {pad_pct}%")
        else:
            logger.info(f"카테고리 '{category}' 여백 적용: {pad_pct}%")

        # % → output_size 기준 px 변환
        return {
            "top": int(output_size * pad_pct.get("top", 10) / 100),
            "bottom": int(output_size * pad_pct.get("bottom", 10) / 100),
            "left": int(output_size * pad_pct.get("left", 10) / 100),
            "right": int(output_size * pad_pct.get("right", 10) / 100),
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
        # hand_region이 있으면 손 영역과 겹치는 쪽을 추가로 잘라낸다
        if product_only_region:
            margin = 0.03  # 3% 여유
            px1 = max(0, int((product_only_region["x"] - margin) * w))
            py1 = max(0, int((product_only_region["y"] - margin) * h))
            px2 = min(w, int((product_only_region["x"] + product_only_region["width"] + margin) * w))
            py2 = min(h, int((product_only_region["y"] + product_only_region["height"] + margin) * h))

            # 손 영역과 겹치는 쪽을 더 공격적으로 크롭
            if hand_region:
                hx1 = int(hand_region["x"] * w)
                hy1 = int(hand_region["y"] * h)
                hx2 = hx1 + int(hand_region["width"] * w)
                hy2 = hy1 + int(hand_region["height"] * h)
                h_cx = (hx1 + hx2) / 2  # 손 중심 x
                p_cx = (px1 + px2) / 2   # 상품 중심 x

                hand_margin = int(max(w, h) * 0.04)  # 손 쪽 추가 4% 여유

                # 손이 상품 왼쪽에 있으면 → 왼쪽 경계를 손 오른쪽 끝 + 여유로
                if h_cx < p_cx and hx2 > px1:
                    new_px1 = min(hx2 + hand_margin, px1 + int((px2 - px1) * 0.3))
                    _log(f"  손(왼쪽) 겹침 제거: x1 {px1}→{new_px1} (+{hand_margin}px 여유)")
                    px1 = new_px1
                # 손이 상품 오른쪽에 있으면 → 오른쪽 경계를 손 왼쪽 끝 - 여유로
                elif h_cx >= p_cx and hx1 < px2:
                    new_px2 = max(hx1 - hand_margin, px2 - int((px2 - px1) * 0.3))
                    _log(f"  손(오른쪽) 겹침 제거: x2 {px2}→{new_px2} (+{hand_margin}px 여유)")
                    px2 = new_px2

                h_cy = (hy1 + hy2) / 2  # 손 중심 y
                p_cy = (py1 + py2) / 2   # 상품 중심 y

                # 손이 상품 위쪽에 있으면
                if h_cy < p_cy and hy2 > py1:
                    new_py1 = min(hy2 + hand_margin, py1 + int((py2 - py1) * 0.3))
                    _log(f"  손(위쪽) 겹침 제거: y1 {py1}→{new_py1} (+{hand_margin}px 여유)")
                    py1 = new_py1
                # 손이 상품 아래쪽에 있으면
                elif h_cy >= p_cy and hy1 < py2:
                    new_py2 = max(hy1 - hand_margin, py2 - int((py2 - py1) * 0.3))
                    _log(f"  손(아래쪽) 겹침 제거: y2 {py2}→{new_py2} (+{hand_margin}px 여유)")
                    py2 = new_py2

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

    @staticmethod
    def _detect_background_margin(image_bytes: bytes, on_log: Callable = None,
                                   edge_px: int = 15, threshold: int = 200,
                                   min_ratio: float = 0.4) -> bool:
        """이미지 가장자리를 분석하여 배경 여백이 있는지 판단.

        가장자리 edge_px 픽셀을 샘플링하여, threshold 이상인 밝은 픽셀 비율이
        min_ratio 이상이면 배경 여백이 있다고 판단한다.
        """
        from PIL import Image
        import io

        _log = on_log or (lambda msg, tag="info": None)
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            w, h = img.size
            arr = np.array(img)

            # 4변 가장자리 픽셀 수집 (edge_px 두께)
            top = arr[:edge_px, :, :]
            bottom = arr[-edge_px:, :, :]
            left = arr[edge_px:-edge_px, :edge_px, :]
            right = arr[edge_px:-edge_px, -edge_px:, :]

            edges = np.concatenate([
                top.reshape(-1, 3),
                bottom.reshape(-1, 3),
                left.reshape(-1, 3),
                right.reshape(-1, 3)
            ], axis=0)

            # 밝은 픽셀 비율 (R, G, B 모두 threshold 이상)
            bright = np.all(edges >= threshold, axis=1)
            ratio = bright.sum() / len(bright)

            # 가장자리 색상 균일도 체크 (배경은 균일, 피사체는 다양)
            # 표준편차가 낮으면 균일한 배경일 가능성 높음
            edge_std = edges.std(axis=0).mean()
            is_uniform = edge_std < 30

            has_margin = ratio >= min_ratio or (ratio >= 0.2 and is_uniform)
            _log(f"  여백 감지: 밝은 {ratio:.1%} (기준 {min_ratio:.0%}), "
                 f"균일도 std={edge_std:.1f} → {'여백 있음' if has_margin else '피사체 꽉 참'}")
            return has_margin
        except Exception:
            return True  # 판단 실패 시 안전하게 배경제거 실행

    def _crop_detail_cut(self, image_bytes: bytes, instruction,
                         on_log: Callable = None) -> bytes:
        """디테일컷 이미지를 정사각형으로 크롭 + 흰 배경 합성.

        투명 PNG(Photoroom 결과)인 경우 흰 배경 위에 합성.
        focus_area가 있으면 해당 영역 중심, 없으면 피사체 중앙 기준.
        손이 감지된 경우 손 반대쪽으로 크롭 중심을 이동하여 손을 최대한 제외.
        """
        from PIL import Image
        import io

        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        output_w = self._settings.get("output", {}).get("width", 1000)
        output_h = self._settings.get("output", {}).get("height", 1000)

        # 손 영역 정보 (크롭 중심 조정에 사용)
        hand = instruction.hand_region if instruction.has_human_hand else None

        # 투명 PNG → 피사체 영역 기반 크롭
        if img.mode == "RGBA":
            alpha = np.array(img)[:, :, 3]

            # 손 감지 시 alpha에서 손 영역을 마스킹하여 제외
            if hand:
                mask_alpha = alpha.copy()
                hx1 = max(0, int((hand["x"] - 0.02) * w))
                hy1 = max(0, int((hand["y"] - 0.02) * h))
                hx2 = min(w, int((hand["x"] + hand["width"] + 0.02) * w))
                hy2 = min(h, int((hand["y"] + hand["height"] + 0.02) * h))
                mask_alpha[hy1:hy2, hx1:hx2] = 0
                _log(f"  손 영역 alpha 마스킹: ({hx1},{hy1})-({hx2},{hy2})")
            else:
                mask_alpha = alpha

            # 피사체 영역 찾기 (손 제외)
            coords = np.argwhere(mask_alpha > 0)
            if len(coords) > 0:
                cy_min, cx_min = coords.min(axis=0)
                cy_max, cx_max = coords.max(axis=0)
                # 피사체 중심 (손 제외 기준)
                cx = (cx_min + cx_max) // 2
                cy = (cy_min + cy_max) // 2
                # 피사체를 포함하는 정사각형
                obj_w = cx_max - cx_min
                obj_h = cy_max - cy_min
                crop_size = int(max(obj_w, obj_h) * 1.30)  # 30% 여유 (여백 확보)
                crop_size = min(crop_size, w, h)
            else:
                # 손 마스킹 후 피사체가 없으면 원본 alpha로 폴백
                coords = np.argwhere(alpha > 0)
                if len(coords) > 0:
                    cy_min, cx_min = coords.min(axis=0)
                    cy_max, cx_max = coords.max(axis=0)
                    cx = (cx_min + cx_max) // 2
                    cy = (cy_min + cy_max) // 2
                    obj_w = cx_max - cx_min
                    obj_h = cy_max - cy_min
                    crop_size = int(max(obj_w, obj_h) * 1.30)
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

            # 손 감지 시 크롭 중심을 손 반대쪽으로 이동
            if hand:
                cx, cy, crop_size = self._adjust_crop_away_from_hand(
                    cx, cy, crop_size, w, h, hand, _log)

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

    @staticmethod
    def _adjust_crop_away_from_hand(cx, cy, crop_size, w, h, hand, _log):
        """손 영역을 피하도록 크롭 중심과 크기를 조정한다.

        손이 있는 방향의 반대쪽으로 크롭 중심을 밀어서
        정사각형 크롭에 손이 포함되지 않도록 한다.
        """
        hx = hand["x"]
        hy = hand["y"]
        hw = hand["width"]
        hh = hand["height"]
        h_cx = (hx + hw / 2)  # 손 중심 x (정규화)
        h_cy = (hy + hh / 2)  # 손 중심 y (정규화)
        p_cx = cx / w         # 피사체 중심 x (정규화)
        p_cy = cy / h         # 피사체 중심 y (정규화)

        shift_x = 0
        shift_y = 0

        # 손이 왼쪽에 있으면 → 크롭 중심을 오른쪽으로
        if h_cx < p_cx:
            # 손의 오른쪽 끝에서 15% 여유를 두고 밀기
            push_to = int((hx + hw + 0.04) * w)
            if push_to > cx - crop_size // 2:
                shift_x = push_to - (cx - crop_size // 2)
        # 손이 오른쪽에 있으면 → 크롭 중심을 왼쪽으로
        elif h_cx > p_cx:
            push_to = int((hx - 0.04) * w)
            crop_right = cx + crop_size // 2
            if push_to < crop_right:
                shift_x = push_to - crop_right

        # 손이 위쪽에 있으면 → 크롭 중심을 아래로
        if h_cy < p_cy:
            push_to = int((hy + hh + 0.04) * h)
            if push_to > cy - crop_size // 2:
                shift_y = push_to - (cy - crop_size // 2)
        # 손이 아래쪽에 있으면 → 크롭 중심을 위로
        elif h_cy > p_cy:
            push_to = int((hy - 0.04) * h)
            crop_bottom = cy + crop_size // 2
            if push_to < crop_bottom:
                shift_y = push_to - crop_bottom

        if shift_x != 0 or shift_y != 0:
            new_cx = cx + shift_x
            new_cy = cy + shift_y
            # 경계 체크
            new_cx = max(crop_size // 2, min(w - crop_size // 2, new_cx))
            new_cy = max(crop_size // 2, min(h - crop_size // 2, new_cy))
            _log(f"  손 회피 크롭: 중심 ({cx},{cy})→({new_cx},{new_cy}), shift=({shift_x},{shift_y})")
            cx, cy = new_cx, new_cy

        return cx, cy, crop_size

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
                     pre_cropped: bool = False,
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

        _base_max_tokens = vision_config.get("max_tokens", 2048)

        if auto_detect:
            # 크롭 완료 이미지는 참고 이미지 1장만 (본인만, 비용 절감)
            _ref_count = 1 if pre_cropped else 2
            ref_images = self._collect_sibling_images(image_path, max_count=_ref_count)
            _log(f"{vision_name} Vision API 호출 중 ({len(ref_images)}장 참고, "
                 f"모델: {vision_config.get('model', 'unknown')})")
            ref_images[0] = img
            response = client.analyze_images(
                ref_images,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=_base_max_tokens,
                temperature=vision_config.get("temperature", 0.1),
            )
        else:
            _log(f"{vision_name} Vision API 호출 중 (모델: {vision_config.get('model', 'unknown')})")
            response = client.analyze_image(
                img,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=_base_max_tokens,
                temperature=vision_config.get("temperature", 0.1),
            )

        # MAX_TOKENS로 JSON이 잘린 경우 → 토큰 2배로 재시도
        if response and response.rstrip().endswith((',', '"', ':', '{')):
            _retry_tokens = min(_base_max_tokens * 2, 8192)
            _log(f"  응답이 잘린 것으로 감지 → {_retry_tokens} 토큰으로 재시도", "warn")
            if auto_detect:
                response = client.analyze_images(
                    ref_images, system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=_retry_tokens,
                    temperature=vision_config.get("temperature", 0.1),
                )
            else:
                response = client.analyze_image(
                    img, system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=_retry_tokens,
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
                       pre_cropped: bool = False,
                       override_params: dict = None,
                       on_log: Callable = None,
                       on_stage_image: Callable = None) -> dict:
        """단일 이미지 처리 - Photoroom + Claid.ai 파이프라인."""
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        _stage_img = on_stage_image or (lambda stage, data: None)
        fname = Path(image_path).name
        _log(f"처리 시작: {fname}")
        _used_shadow_config = {}
        _used_enhance_config = {}
        _pre_shadow_bytes = None  # 그림자 재시도용 백업

        # 1. 이미지 파일 바이트 로드
        image_bytes = Path(image_path).read_bytes()
        _log(f"  파일 크기: {len(image_bytes) // 1024}KB")

        # 원본이 3000px 초과 시 API 전송·처리용으로 축소 (메모리 절약)
        image_bytes = _shrink_bytes(image_bytes, max_px=3000)
        if len(image_bytes) < Path(image_path).stat().st_size:
            _log(f"  원본 축소 완료: {len(image_bytes) // 1024}KB")

        # ★ 단계 이미지 저장: 원본
        _stage_img("원본", image_bytes)

        # 2. Claude Vision API 분석 (img는 analyze_only에서 필요)
        img = load_image(image_path)

        if not skip_analysis:
            instruction = self.analyze_only(image_path, category, img=img,
                                            pre_cropped=pre_cropped, on_log=on_log)
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

        # 분석 완료 → numpy 배열 즉시 해제 (비압축 상태로 메모리 점유 큼)
        del img
        import gc as _gc
        _gc.collect()

        image_type = instruction.image_type
        background = instruction.background
        is_detail_cut = instruction.is_detail_cut or (image_type == "detail")
        needs_shadow = instruction.needs_shadow
        shooting_angle = getattr(instruction, "shooting_angle", "front")
        floor_visible = getattr(instruction, "floor_visible", True)
        shadow_confidence = getattr(instruction, "shadow_confidence", 0.5)

        _is_generative_shadow = self._shadow_provider in ("gemini_shadow", "grok_shadow", "api_shadow")
        has_real_shadow = self._detect_shadow_in_original(image_bytes)

        # ★ 그림자 판단 모드 확인 (GUI 설정: auto / always / never)
        _shadow_judge_mode = getattr(self, "_shadow_judge_mode", "auto")

        # 그림자 판단 근거 로그
        _shadow_reason = ""

        if _shadow_judge_mode == "always":
            needs_shadow = True
            _shadow_reason = "수동설정=항상생성"
            _log(f"  그림자 판단: ON (수동 설정 — 항상 생성)")
        elif _shadow_judge_mode == "never":
            needs_shadow = False
            _shadow_reason = "수동설정=항상스킵"
            _log(f"  그림자 판단: OFF (수동 설정 — 항상 스킵)")
        else:
            # ★ AI 자동 판단 모드 — 촬영 각도/바닥 가시성 기반 스마트 판단
            _log(f"  촬영분석: 각도={shooting_angle}, 바닥={floor_visible}, AI그림자={needs_shadow}, 확신도={shadow_confidence:.1f}")

            # RULE 1: 손 감지 → 강제 OFF (최우선)
            if instruction.has_human_hand:
                if needs_shadow:
                    _log(f"  ⚠ 사람 손 감지 → 그림자 강제 비활성화", "warn")
                needs_shadow = False
                _shadow_reason = "손감지→OFF"

            # RULE 2: 촬영 각도가 top_down / held → 강제 OFF
            #         detail은 의류가 아니고 바닥 표시+풀샷이면 그림자 허용
            elif shooting_angle in ("top_down", "held"):
                if needs_shadow:
                    _log(f"  ⚠ 촬영각도={shooting_angle} → 그림자 불필요, 강제 OFF", "warn")
                needs_shadow = False
                _shadow_reason = f"촬영각도={shooting_angle}→OFF"

            elif shooting_angle == "detail":
                is_clothing = category in ("clothing",) or image_type == "worn"
                if not is_clothing and floor_visible:
                    # 의류 아닌 제품의 디테일 각도 + 바닥 표시 → 그림자 허용
                    if not needs_shadow and _is_generative_shadow:
                        needs_shadow = True
                        _shadow_reason = f"디테일각도+비의류+바닥표시+생성형→ON"
                        _log(f"  디테일 각도지만 비의류+바닥표시 → 생성형 그림자 진행")
                    elif needs_shadow:
                        _shadow_reason = f"디테일각도+비의류+바닥표시→ON(AI)"
                    else:
                        _shadow_reason = f"디테일각도+비의류+AI판단→OFF"
                else:
                    if needs_shadow:
                        _log(f"  ⚠ 촬영각도=detail → 그림자 불필요, 강제 OFF", "warn")
                    needs_shadow = False
                    _shadow_reason = f"촬영각도=detail→OFF"

            # RULE 3: 바닥 미표시 → 강제 OFF (마네킹 예외)
            elif not floor_visible and not instruction.has_mannequin:
                if needs_shadow:
                    _log(f"  ⚠ 바닥 미표시(floor_visible=false) → 그림자 불필요, 강제 OFF", "warn")
                needs_shadow = False
                _shadow_reason = "바닥미표시→OFF"

            # RULE 4: 마네킹 → 그림자 OFF (마네킹컷은 바닥 그림자 불필요)
            elif instruction.has_mannequin:
                if needs_shadow:
                    _log(f"  ⚠ 마네킹 감지 → 그림자 불필요, 강제 OFF", "warn")
                needs_shadow = False
                _shadow_reason = "마네킹→OFF"

            # RULE 5: 정면/하이앵글/측면 + 바닥 표시 + 바닥에 놓임 → ON
            # 단, 의류 정면샷에서 풀샷(신발 보임)이 아니면 → OFF
            # 단, shadow_confidence가 낮으면(≤0.5) AI 판단 신뢰하지 않음
            elif shooting_angle in ("front", "high_angle", "side") and floor_visible:
                is_clothing = category in ("clothing",) or image_type == "worn"
                is_full = getattr(instruction, "is_full_body", None)
                if is_clothing and not is_full:
                    needs_shadow = False
                    _shadow_reason = f"의류+{shooting_angle}+풀샷아님→OFF"
                    _log(f"  의류 {shooting_angle}샷 (풀샷 아님) → 그림자 불필요, OFF")
                elif shadow_confidence <= 0.5:
                    needs_shadow = False
                    _shadow_reason = f"촬영각도={shooting_angle}+확신도낮음({shadow_confidence})→OFF"
                    _log(f"  그림자 확신도 낮음({shadow_confidence:.1f}≤0.5) → 그림자 OFF")
                elif not needs_shadow and _is_generative_shadow:
                    _log(f"  촬영각도={shooting_angle}, 바닥표시 → 생성형 그림자 진행")
                    needs_shadow = True
                    _shadow_reason = f"촬영각도={shooting_angle}+바닥표시+생성형→ON"
                elif needs_shadow:
                    _shadow_reason = f"촬영각도={shooting_angle}+바닥표시→ON(AI)"
                else:
                    _shadow_reason = f"촬영각도={shooting_angle}+AI판단→OFF"

            # RULE 6: 의류 착용(worn) → 풀샷(전신+바닥)만 그림자 ON
            elif shooting_angle == "worn" or image_type == "worn":
                is_full = getattr(instruction, "is_full_body", None)
                if is_full and floor_visible:
                    needs_shadow = True
                    _shadow_reason = "착용샷+풀샷+바닥표시→ON"
                    _log(f"  착용샷 풀샷(전신+바닥 보임) → 접지 그림자 생성")
                else:
                    needs_shadow = False
                    reason_detail = "풀샷아님" if not is_full else "바닥미표시"
                    _shadow_reason = f"착용샷+{reason_detail}→OFF"
                    _log(f"  착용샷 ({reason_detail}) → 그림자 불필요, OFF")

            # RULE 7: OpenCV 보조 판단 (비생성형만)
            else:
                if needs_shadow and not has_real_shadow and not _is_generative_shadow:
                    _log(f"  ⚠ AI=ON이나 원본 그림자 미감지 → 스킵", "warn")
                    needs_shadow = False
                    _shadow_reason = "AI=ON+OpenCV=NO→OFF"
                elif not needs_shadow and has_real_shadow and image_type not in ("worn",) and not instruction.has_human_hand:
                    _log(f"  ⚠ AI=OFF이나 원본 그림자 감지 → 진행", "warn")
                    needs_shadow = True
                    _shadow_reason = "AI=OFF+OpenCV=YES→ON"
                else:
                    _shadow_reason = f"AI판단={'ON' if needs_shadow else 'OFF'}유지"

        # 판단 근거를 instruction에 저장 (뷰파인더 표시용)
        instruction._shadow_reason = _shadow_reason

        _log(f"  ▶ 최종 그림자 판단: {'O' if needs_shadow else 'X'} ({_shadow_reason})")

        edit_actions = [f"분류: {image_type} / 배경: {background}"
                        + (" / 디테일컷" if is_detail_cut else "")
                        + (f" / 그림자: {'O' if needs_shadow else 'X'} ({_shadow_reason})")]

        # 2.5. 사람 손 감지 시 크롭 (Photoroom 호출 전에 원본에서 제거)
        # 디테일컷: product_only_region이 너무 좁을 수 있으므로 가장자리 크롭만 사용
        current_bytes = image_bytes
        _rgba_nukki_bytes = None  # RGBA 누끼 원본 (그림자 레이어 분리용)
        if instruction.has_human_hand and instruction.hand_region:
            current_bytes = self._crop_out_hand(
                current_bytes, instruction.hand_region,
                product_only_region=None if is_detail_cut else instruction.product_only_region,
                on_log=_log)
            edit_actions.append("사람 손 영역 크롭 제거")
            image_bytes = current_bytes  # Photoroom에도 크롭된 이미지 전달

        # 3. 디테일컷: 배경제거 → 크롭
        if is_detail_cut and not pre_cropped:
            _log(f"  디테일컷 감지")
            has_margin = self._detect_background_margin(image_bytes, on_log=_log)
            if not skip_photoroom and has_margin:
                bg_result = self._call_bg_removal(
                    image_bytes, "detail", "complex",
                    output_size="originalImage", is_detail=True, on_log=_log)
                if bg_result:
                    current_bytes = bg_result
                    edit_actions.append(f"{self._last_bg_provider}: 배경 제거 (디테일컷)")
                    _log(f"  배경제거 완료 ({len(current_bytes) // 1024}KB)", "success")
            elif not has_margin:
                _log(f"  디테일컷: 피사체가 프레임을 채움 → 배경제거 스킵 (피사체 보호)")
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
                _log(f"  [{self._bg_provider}] 배경제거 중 (유형: {image_type})...", "info")

                # 그림자 방식에 따라 Photoroom shadow.mode 포함 여부 결정
                # hybrid 모드: Photoroom 성공 시에만 api_shadow 사용 가능
                use_api_shadow = (self._shadow_provider == "api_shadow"
                                  and self._bg_provider in ("photoroom", "hybrid")
                                  and needs_shadow)

                pr_auto = self._settings.get("auto_options", {}).get("photoroom", "manual") == "ai_auto"
                ai_pr_params = instruction.photoroom_params if pr_auto and instruction.photoroom_params else None
                bg_result = self._call_bg_removal(
                    image_bytes, image_type, background,
                    output_size=output_size,
                    include_shadow=use_api_shadow,
                    ai_photoroom_params=ai_pr_params, on_log=_log)
                # ★ RGBA PNG 누끼 원본 보존: 그림자 레이어 분리용
                # bg_result는 이후 current_bytes로 복사/변환되지만,
                # _rgba_nukki_bytes는 원본 RGBA PNG를 그대로 유지
                _rgba_nukki_bytes = bg_result
                if _rgba_nukki_bytes:
                    try:
                        from PIL import Image as _chk
                        import io as _chk_io
                        _chk_img = _chk.open(_chk_io.BytesIO(_rgba_nukki_bytes))
                        _log(f"  누끼 원본 보존: {_chk_img.mode} {_chk_img.size} ({len(_rgba_nukki_bytes)//1024}KB)")
                    except Exception:
                        pass

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
                            # ★ 그림자 적용 전 상태 백업 (재시도용)
                            _pre_shadow_bytes = bg_result
                            _log(f"  Gemini 이미지 편집으로 그림자 생성 중...")
                            gemini_result = self._gemini_add_shadow(
                                bg_result, original_bytes=image_bytes,
                                has_mannequin=instruction.has_mannequin, on_log=_log,
                                shooting_angle=shooting_angle,
                                nukki_png_bytes=_rgba_nukki_bytes,
                                category=category, image_type=image_type)
                            if gemini_result:
                                current_bytes = gemini_result
                                edit_actions.append("Gemini AI: 그림자 생성")
                            else:
                                current_bytes = bg_result
                                _log(f"  Gemini 그림자 생성 실패, 그림자 없이 진행", "warn")
                    elif needs_shadow and self._shadow_provider == "grok_shadow":
                        grok_order = self._settings.get("grok_shadow", {}).get(
                            "order", "after_enhance")
                        if grok_order == "after_enhance":
                            current_bytes = bg_result
                            _log(f"  Grok 그림자: 보정 후 생성 모드 (보정 완료 후 진행)")
                        else:
                            _pre_shadow_bytes = bg_result
                            _log(f"  Grok 이미지 편집으로 그림자 생성 중...")
                            grok_result = self._grok_add_shadow(
                                bg_result, original_bytes=image_bytes,
                                has_mannequin=instruction.has_mannequin, on_log=_log,
                                shooting_angle=shooting_angle,
                                category=category, image_type=image_type)
                            if grok_result:
                                current_bytes = grok_result
                                edit_actions.append("Grok AI: 그림자 생성")
                            else:
                                current_bytes = bg_result
                                _log(f"  Grok 그림자 생성 실패, 그림자 없이 진행", "warn")
                    elif needs_shadow and use_api_shadow:
                        current_bytes = bg_result
                        edit_actions.append("Photoroom API: 그림자 생성")
                    elif needs_shadow and self._shadow_provider == "none":
                        current_bytes = bg_result
                    else:
                        current_bytes = bg_result

                    if pre_cropped:
                        # 크롭 완료 이미지: 중앙 정렬/패딩 스킵
                        _log(f"  크롭 완료 모드 → 중앙 정렬/여백 적용 스킵")
                        edit_actions.append(f"{self._last_bg_provider}: 배경제거 (크롭 완료)")
                    elif is_detail_cut:
                        # 디테일컷: 여백 없이 배경만 제거 (_crop_detail_cut에서 자체 크롭)
                        _log(f"  디테일컷 → 여백 적용 스킵 (디테일 크롭에서 처리)")
                        edit_actions.append(f"{self._last_bg_provider}: 배경 제거 (디테일컷)")
                    else:
                        output_w = self._settings.get("output", {}).get("width", 1000)
                        cat_padding = self._get_category_padding(category, output_w)
                        current_bytes = _clean_and_recenter_bytes(
                            current_bytes, output_size=output_w,
                            padding=cat_padding)
                        _log(f"  카테고리: {category} → 여백: 상{cat_padding['top']}px 하{cat_padding['bottom']}px "
                             f"좌{cat_padding['left']}px 우{cat_padding['right']}px "
                             f"(캔버스 {output_w}px 대비)")
                        edit_actions.append(f"{self._last_bg_provider}: 배경제거 + 중앙 정렬")
                    _log(f"  배경제거 완료 ({len(current_bytes) // 1024}KB)", "success")
            else:
                _log(f"  배경제거 스킵 (유형: {image_type}, 배경: {background})")
        else:
            _log(f"  배경제거 처리 생략")

        # ★ 단계 이미지 저장: 누끼 완료
        _stage_img("누끼", current_bytes)

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
                with Image.open(io.BytesIO(current_bytes)) as _img:
                    if _img.mode == "RGBA":
                        _bg = Image.new("RGB", _img.size, (255, 255, 255))
                        _bg.paste(_img, mask=_img.split()[3])
                    else:
                        _bg = _img.convert("RGB")
                _buf = io.BytesIO()
                _bg.save(_buf, format="JPEG", quality=95)
                _bg.close()
                current_bytes = _buf.getvalue()
                del _buf
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
            # RGBA 투명 배경 → 흰 배경 변환 (Claid에 투명 PNG 전달 시 검정 배경 방지)
            try:
                from PIL import Image as _PILImage
                import io as _io
                with _PILImage.open(_io.BytesIO(current_bytes)) as _check:
                    if _check.mode == "RGBA":
                        _wbg = _PILImage.new("RGB", _check.size, (255, 255, 255))
                        _wbg.paste(_check, mask=_check.split()[3])
                        _wbuf = _io.BytesIO()
                        _wbg.save(_wbuf, format="PNG")
                        _wbg.close()
                        current_bytes = _wbuf.getvalue()
                        del _wbuf
                        _log(f"  RGBA→흰배경 변환 완료 ({len(current_bytes) // 1024}KB)")
            except Exception:
                pass
            _log(f"  Claid.ai 보정 (hdr={claid_config.get('hdr', 20)}, "
                 f"sharpness={claid_config.get('sharpness', 15)})...")
            claid_result = self._claid_process_safe(
                current_bytes, image_type, config=claid_config,
                fallback=current_bytes, on_log=_log)
            if claid_result is not current_bytes:
                edit_actions.append(f"Claid.ai: 색보정 ({image_type})")
                _log(f"  Claid.ai 완료 ({len(claid_result) // 1024}KB)", "success")
            current_bytes = claid_result

        # ★ 단계 이미지 저장: 보정 완료
        _stage_img("보정", current_bytes)

        # 4.5. Gemini 그림자 — 보정 후 생성 모드
        # ★ 그림자 적용 전 상태 백업 (재시도용)
        _pre_shadow_bytes = current_bytes
        if (needs_shadow and self._shadow_provider == "gemini_shadow"
                and self._settings.get("gemini_shadow", {}).get(
                    "order", "after_enhance") == "after_enhance"):
            _log(f"  Gemini 이미지 편집으로 그림자 생성 중 (보정 후)...")
            gemini_result = self._gemini_add_shadow(
                current_bytes, original_bytes=image_bytes,
                has_mannequin=instruction.has_mannequin, on_log=_log,
                shooting_angle=shooting_angle,
                nukki_png_bytes=_rgba_nukki_bytes,
                category=category, image_type=image_type)
            if gemini_result:
                current_bytes = gemini_result
                edit_actions.append("Gemini AI: 그림자 생성 (보정 후)")
            else:
                _log(f"  Gemini 그림자 생성 실패, 그림자 없이 진행", "warn")

        # 4.6. Grok 그림자 — 보정 후 생성 모드
        if (needs_shadow and self._shadow_provider == "grok_shadow"
                and self._settings.get("grok_shadow", {}).get(
                    "order", "after_enhance") == "after_enhance"):
            _log(f"  Grok 이미지 편집으로 그림자 생성 중 (보정 후)...")
            grok_result = self._grok_add_shadow(
                current_bytes, original_bytes=image_bytes,
                has_mannequin=instruction.has_mannequin, on_log=_log,
                shooting_angle=shooting_angle,
                category=category, image_type=image_type)
            if grok_result:
                current_bytes = grok_result
                edit_actions.append("Grok AI: 그림자 생성 (보정 후)")
            else:
                _log(f"  Grok 그림자 생성 실패, 그림자 없이 진행", "warn")

        # ★ 단계 이미지 저장: 그림자 완료
        _stage_img("그림자", current_bytes)

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

        # 6. 품질 검증 (Vision API)
        validation = self._validate_result(
            image_bytes, current_bytes, image_type, needs_shadow, on_log=_log,
            category=category, shooting_angle=shooting_angle)

        # 6.5. 그림자 검증 불합격 시 1회 재시도 (Gemini 생성형만)
        if (not validation.get("overall", True)
                and not validation.get("shadow", {}).get("pass", True)
                and needs_shadow
                and self._shadow_provider == "gemini_shadow"
                and _pre_shadow_bytes is not None):
            _log(f"  ★ 그림자 검증 불합격 → Gemini 그림자 1회 재시도", "warn")
            retry_result = self._gemini_add_shadow(
                _pre_shadow_bytes, original_bytes=image_bytes,
                has_mannequin=instruction.has_mannequin, on_log=_log,
                shooting_angle=shooting_angle,
                nukki_png_bytes=_rgba_nukki_bytes,
                category=category, image_type=image_type)
            if retry_result:
                current_bytes = retry_result
                # 재저장
                import os as _os
                for sf in saved_files:
                    try:
                        _os.remove(sf["path"])
                    except Exception:
                        pass
                saved_files = []
                info = self._optimizer.save_from_bytes(
                    current_bytes, str(file_path), max_size_kb)
                saved_files.append(info)
                _log(f"  재저장: {file_path.name} ({info['size_kb']}KB)", "success")
                # 재검증
                validation = self._validate_result(
                    image_bytes, current_bytes, image_type, needs_shadow, on_log=_log,
                    category=category, shooting_angle=shooting_angle)
                if not validation.get("overall", True):
                    _log(f"  재시도 후에도 불합격 → 결과 확정", "warn")
                else:
                    _log(f"  재시도 성공 → 합격", "success")
            else:
                _log(f"  재시도 실패 (Gemini 응답 없음) → 기존 결과 확정", "warn")

        # 6.8. 독립 품질 평가 — 검증 결과와 무관하게 항상 수행
        independent_eval = self._evaluate_independent(
            current_bytes, image_type, needs_shadow,
            original_bytes=image_bytes, on_log=_log)

        # ★ 단계 이미지 저장: 최종
        _stage_img("최종", current_bytes)

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
            "validation": validation,
            "independent_eval": independent_eval,
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
        elif provider == "grok":
            cfg = self._settings.get("grok", {})
            return GrokVisionClient(model=cfg.get("model", "grok-4-fast-non-reasoning"))
        else:  # claude
            cfg = self._settings.get("api", {})
            return VisionClient(model=cfg.get("model", "claude-sonnet-4-20250514"))

    def _evaluate_independent(self, result_bytes: bytes,
                              image_type: str, needs_shadow: bool,
                              original_bytes: bytes = None,
                              on_log: Callable = None) -> dict:
        """독립 이미지 평가 — 원본과 결과물을 비교하여 비판적 품질 평가.

        원본 이미지를 함께 전달하여 원본에 이미 존재하는 결함(얼룩, 자국 등)을
        편집 결함으로 오인하지 않도록 합니다.

        - 합격/불합격이 아닌 점수제 (1~10)
        - 5가지 세부 기준으로 평가

        Returns:
            {
                "shadow_natural": {"score": int, "issues": list},
                "background_clean": {"score": int, "issues": list},
                "edge_quality": {"score": int, "issues": list},
                "product_integrity": {"score": int, "issues": list},
                "commercial_quality": {"score": int, "issues": list},
                "overall_score": float,
                "critical_issues": list,
                "recommendation": str,
            }
        """
        import json as _json
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        _log(f"  독립 품질 평가 시작 (5항목 점수제)")

        default_result = {
            "shadow_natural": {"score": 0, "issues": ["평가 실패"]},
            "background_clean": {"score": 0, "issues": ["평가 실패"]},
            "edge_quality": {"score": 0, "issues": ["평가 실패"]},
            "product_integrity": {"score": 0, "issues": ["평가 실패"]},
            "commercial_quality": {"score": 0, "issues": ["평가 실패"]},
            "overall_score": 0,
            "critical_issues": ["평가 실패"],
            "recommendation": "평가를 수행할 수 없습니다",
        }

        try:
            import cv2
            import io

            result_arr = np.frombuffer(result_bytes, dtype=np.uint8)
            result_img = cv2.imdecode(result_arr, cv2.IMREAD_COLOR)
            if result_img is None:
                _log(f"  독립 평가: 이미지 디코딩 실패 → 스킵", "warn")
                return default_result

            # 원본 이미지 디코딩 (있으면)
            original_img = None
            if original_bytes:
                orig_arr = np.frombuffer(original_bytes, dtype=np.uint8)
                original_img = cv2.imdecode(orig_arr, cv2.IMREAD_COLOR)

            vision_client = self._get_vision_client()

            eval_prompts = {}
            try:
                eval_prompts = self._prompt_builder._prompts.get("independent_evaluation", {})
            except Exception:
                pass

            system_prompt = eval_prompts.get("system",
                "당신은 럭셔리 이커머스 플랫폼의 이미지 품질 감독관입니다. "
                "반드시 JSON만 출력하세요.").strip()

            user_prompt_template = eval_prompts.get("prompt", "").strip()
            if not user_prompt_template:
                _log(f"  독립 평가: 프롬프트 미설정 → 스킵", "warn")
                return default_result

            shadow_hint = ""
            if not needs_shadow:
                shadow_hint = "\n\n[참고] 이 이미지는 그림자가 불필요한 유형(탑다운/디테일컷/착용샷 등)입니다. 그림자가 없는 것이 정상입니다. shadow_natural 항목에서 그림자 부재를 감점하지 마세요."

            user_prompt = user_prompt_template + shadow_hint

            # 원본+결과 2장 전달 (원본이 있으면) / 없으면 결과만
            if original_img is not None:
                images = [original_img, result_img]
            else:
                images = [result_img]

            response_text = vision_client.analyze_images(
                images,
                system_prompt,
                user_prompt,
                max_tokens=4096,
                temperature=0.1,
            )

            text = (response_text or "").strip()
            if not text:
                _log(f"  독립 평가: Vision API 빈 응답 → 스킵", "warn")
                return default_result

            if "```" in text:
                import re
                m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
                if m:
                    text = m.group(1).strip()
                else:
                    m2 = re.search(r'```(?:json)?\s*([\s\S]*)', text)
                    if m2:
                        text = m2.group(1).strip()

            try:
                parsed = _json.loads(text)
            except _json.JSONDecodeError:
                repaired = text
                open_braces = repaired.count('{') - repaired.count('}')
                open_brackets = repaired.count('[') - repaired.count(']')
                repaired += ']' * max(0, open_brackets)
                repaired += '}' * max(0, open_braces)
                try:
                    parsed = _json.loads(repaired)
                except _json.JSONDecodeError:
                    _log(f"  독립 평가: JSON 파싱 실패 → 스킵", "warn")
                    return default_result

            categories = ["shadow_natural", "background_clean", "edge_quality",
                          "product_integrity", "commercial_quality"]
            scores = []
            for cat in categories:
                item = parsed.get(cat, {})
                score = int(item.get("score", 0))
                issues = item.get("issues", [])
                if not isinstance(issues, list):
                    issues = [str(issues)] if issues else []
                parsed[cat] = {"score": score, "issues": issues}
                scores.append(score)

                label_map = {
                    "shadow_natural": "그림자",
                    "background_clean": "배경",
                    "edge_quality": "경계선",
                    "product_integrity": "원형보존",
                    "commercial_quality": "상업성",
                }
                label = label_map.get(cat, cat)
                score_tag = "success" if score >= 7 else "warn" if score >= 5 else "error"
                issues_str = ", ".join(issues) if issues else "없음"
                _log(f"  평가 [{label}]: {score}/10 — {issues_str}", score_tag)

            overall = parsed.get("overall_score", 0)
            if not overall and scores:
                overall = round(sum(scores) / len(scores), 1)
            parsed["overall_score"] = overall

            critical = parsed.get("critical_issues", [])
            if not isinstance(critical, list):
                critical = [str(critical)] if critical else []
            parsed["critical_issues"] = critical

            recommendation = parsed.get("recommendation", "")
            parsed["recommendation"] = str(recommendation)

            overall_tag = "success" if overall >= 7 else "warn" if overall >= 5 else "error"
            _log(f"  독립 평가 완료: {overall}/10", overall_tag)
            if critical:
                for issue in critical:
                    _log(f"  ⚠ {issue}", "warn")
            if recommendation:
                _log(f"  💡 {recommendation}")

            return parsed

        except Exception as e:
            _log(f"  독립 평가 오류: {e} → 스킵", "warn")
            return default_result

    def _ask_ai_for_hint(self, provider: str, problem_description: str,
                         current_hint: str, main_prompt: str,
                         on_log: Callable = None) -> str:
        """해당 AI에게 직접 질문하여 최적의 프롬프트 힌트를 받는다.

        SKILL.md 규칙 1: "해당 AI에게 직접 물어서 프롬프트 작성"
        Gemini에게는 Gemini API로, Grok에게는 Grok API로 직접 질문한다.

        Returns:
            AI가 추천한 힌트 텍스트. 실패 시 빈 문자열.
        """
        import os
        _log = on_log or (lambda msg, tag="info": None)

        question = (
            f"당신은 이미지 편집 AI입니다. 지금 당신에게 제품 사진의 그림자를 생성하라는 "
            f"프롬프트를 전달하면, 아래와 같은 문제가 발생합니다.\n\n"
            f"[문제]\n{problem_description}\n\n"
            f"[현재 공통 규칙]\n{main_prompt[:500]}\n\n"
            f"[현재 보충 지시]\n{current_hint or '(없음)'}\n\n"
            f"위 문제를 방지하기 위해, 당신에게 전달할 '보충 지시'를 작성해주세요.\n"
            f"보충 지시는 공통 규칙 뒤에 추가되는 것이므로, 공통 규칙과 중복되지 않게 "
            f"이 상품 유형에 특화된 지시만 작성하세요.\n"
            f"보충 지시 텍스트만 출력하세요. 다른 설명은 불필요합니다."
        )

        prov = provider.replace("_shadow", "")
        try:
            if prov == "gemini":
                from google import genai
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    return ""
                client = genai.Client(api_key=api_key)
                gemini_cfg = self._settings.get("gemini", {})
                text_model = gemini_cfg.get("model", "gemini-2.5-flash")
                response = client.models.generate_content(
                    model=text_model,
                    contents=question,
                )
                result = response.text.strip() if response.text else ""
                _log(f"  Gemini 자가 추천 힌트: {result[:80]}...")
                return result

            elif prov == "grok":
                import requests as _requests
                api_key = os.getenv("XAI_API_KEY")
                if not api_key:
                    return ""
                grok_cfg = self._settings.get("grok", {})
                text_model = grok_cfg.get("model", "grok-4-fast-non-reasoning")
                resp = _requests.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": text_model,
                        "messages": [{"role": "user", "content": question}],
                        "max_tokens": 2048,
                        "temperature": 0.1,
                    },
                    timeout=60,
                )
                if resp.status_code == 200:
                    result = resp.json()["choices"][0]["message"]["content"].strip()
                    _log(f"  Grok 자가 추천 힌트: {result[:80]}...")
                    return result
                return ""

            else:
                return ""

        except Exception as e:
            _log(f"  {prov} 힌트 질문 실패: {e}", "warn")
            return ""

    def preview_prompt_fix(self, evaluation: dict, user_feedback: str = "",
                          image_type: str = "full", category: str = "",
                          shooting_angle: str = "front",
                          on_log: Callable = None) -> dict:
        """프롬프트 변경 미리보기: AI에게 질문만 하고 실제 재생성은 하지 않는다.

        Returns:
            {
                "suggested_hint": str,  # AI 추천 프롬프트
                "current_hint": str,    # 현재 프롬프트
                "hint_key": str,        # 저장될 키
                "provider": str,        # gemini_shadow / grok_shadow
                "problem_description": str,
            }
        """
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        shadow_provider = self._shadow_provider
        prov_name = shadow_provider.replace("_shadow", "").upper()
        prov_cfg_key = shadow_provider.replace("_shadow", "") + "_shadow"
        main_prompt = self._settings.get(prov_cfg_key, {}).get("main_prompt", "")

        prov_prefix = shadow_provider.replace("_shadow", "")
        if category and shooting_angle and image_type:
            base_key = f"{category}/{shooting_angle}/{image_type}"
        elif category and shooting_angle:
            base_key = f"{category}/{shooting_angle}"
        elif shooting_angle and image_type:
            base_key = f"{shooting_angle}/{image_type}"
        elif category:
            base_key = category
        else:
            base_key = shooting_angle or image_type or "default"
        hint_key = f"{prov_prefix}/{base_key}"

        current_hint, matched_key = self._get_shadow_hint(
            category, shooting_angle, image_type,
            provider=shadow_provider, on_log=_log)

        # 문제 설명
        eval_issues = []
        for cat_key in ["shadow_natural", "background_clean", "edge_quality",
                         "product_integrity", "commercial_quality"]:
            item = evaluation.get(cat_key, {})
            score = item.get("score", 0)
            issues = item.get("issues", [])
            if score < 7 and issues:
                eval_issues.extend(issues)
        critical = evaluation.get("critical_issues", [])
        rec = evaluation.get("recommendation", "")
        problem_parts = eval_issues + critical
        if user_feedback:
            problem_parts.append(f"사용자 피드백: {user_feedback}")
        if rec:
            problem_parts.append(f"개선 제안: {rec}")
        problem_description = "\n".join(f"- {p}" for p in problem_parts) if problem_parts else "그림자 품질 미달"
        problem_description += f"\n\n상품: {category or '미분류'}, 촬영: {shooting_angle}, 유형: {image_type}"

        _log(f"  {prov_name}에 프롬프트 추천 요청 중...", "info")

        suggested_hint = self._ask_ai_for_hint(
            provider=shadow_provider,
            problem_description=problem_description,
            current_hint=current_hint,
            main_prompt=main_prompt,
            on_log=_log,
        )

        return {
            "suggested_hint": suggested_hint,
            "current_hint": current_hint,
            "hint_key": hint_key,
            "matched_key": matched_key,
            "provider": shadow_provider,
            "provider_name": prov_name,
            "problem_description": problem_description,
            "main_prompt": main_prompt[:300] + "..." if len(main_prompt) > 300 else main_prompt,
        }

    def apply_prompt_and_regenerate(self, pre_shadow_bytes: bytes,
                                     original_bytes: bytes,
                                     nukki_png_bytes: bytes,
                                     suggested_hint: str,
                                     hint_key: str,
                                     evaluation: dict,
                                     image_type: str = "full",
                                     category: str = "",
                                     shooting_angle: str = "front",
                                     has_mannequin: bool = False,
                                     needs_shadow: bool = True,
                                     on_log: Callable = None) -> dict:
        """확정된 프롬프트로 그림자만 재생성한다 (사용자 확인 후 호출).

        Returns:
            {
                "success": bool,
                "result_bytes": bytes or None,
                "new_eval": dict,
            }
        """
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        shadow_provider = self._shadow_provider

        # 힌트 저장
        self._save_shadow_hint(hint_key, suggested_hint, on_log=_log)
        _log(f"  힌트 저장 완료: {hint_key}", "success")

        # 그림자 재생성
        _log(f"  변경된 프롬프트로 그림자 재생성 중...")
        if shadow_provider == "gemini_shadow":
            new_result = self._gemini_add_shadow(
                pre_shadow_bytes, original_bytes=original_bytes,
                has_mannequin=has_mannequin, on_log=_log,
                shooting_angle=shooting_angle,
                nukki_png_bytes=nukki_png_bytes,
                category=category, image_type=image_type)
        elif shadow_provider == "grok_shadow":
            new_result = self._grok_add_shadow(
                pre_shadow_bytes, original_bytes=original_bytes,
                has_mannequin=has_mannequin, on_log=_log,
                shooting_angle=shooting_angle,
                category=category, image_type=image_type)
        else:
            new_result = None

        if not new_result:
            _log(f"  그림자 재생성 실패", "error")
            return {"success": False, "result_bytes": None, "new_eval": {}}

        # 재평가
        _log(f"  재평가 중...")
        new_eval = self._evaluate_independent(
            new_result, image_type, needs_shadow,
            original_bytes=original_bytes, on_log=_log)
        new_score = new_eval.get("overall_score", 0)
        old_score = evaluation.get("overall_score", 0)
        _log(f"  재평가 완료: {old_score:.0f} → {new_score:.0f}/10",
             "success" if new_score > old_score else "warn")

        return {
            "success": True,
            "result_bytes": new_result,
            "new_eval": new_eval,
        }

    def preview_shadow_only(self, pre_shadow_bytes: bytes,
                            original_bytes: bytes,
                            nukki_png_bytes: bytes,
                            temp_hint: str,
                            image_type: str = "full",
                            category: str = "",
                            shooting_angle: str = "front",
                            has_mannequin: bool = False,
                            on_log: Callable = None) -> bytes | None:
        """프롬프트를 저장하지 않고 그림자만 생성하여 미리보기용 bytes를 반환한다."""
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        shadow_provider = self._shadow_provider

        # 임시로 힌트를 메모리에만 설정 (저장 X)
        _log(f"  미리보기: 임시 힌트로 그림자 생성 중...")
        # _shadow_hints에 임시 저장 후 복원
        prov_prefix = shadow_provider.replace("_shadow", "")
        if category and shooting_angle and image_type:
            temp_key = f"{prov_prefix}/{category}/{shooting_angle}/{image_type}"
        elif category and shooting_angle:
            temp_key = f"{prov_prefix}/{category}/{shooting_angle}"
        else:
            temp_key = f"{prov_prefix}/default"

        old_val = self._shadow_hints.get(temp_key)
        self._shadow_hints[temp_key] = temp_hint

        try:
            if shadow_provider == "gemini_shadow":
                result = self._gemini_add_shadow(
                    pre_shadow_bytes, original_bytes=original_bytes,
                    has_mannequin=has_mannequin, on_log=_log,
                    shooting_angle=shooting_angle,
                    nukki_png_bytes=nukki_png_bytes,
                    category=category, image_type=image_type)
            elif shadow_provider == "grok_shadow":
                result = self._grok_add_shadow(
                    pre_shadow_bytes, original_bytes=original_bytes,
                    has_mannequin=has_mannequin, on_log=_log,
                    shooting_angle=shooting_angle,
                    category=category, image_type=image_type)
            else:
                result = None
        finally:
            # 힌트 복원
            if old_val is not None:
                self._shadow_hints[temp_key] = old_val
            else:
                self._shadow_hints.pop(temp_key, None)

        return result

    def _auto_fix_shadow(self, pre_shadow_bytes: bytes, original_bytes: bytes,
                         nukki_png_bytes: bytes, evaluation: dict,
                         user_feedback: str = "", image_type: str = "full",
                         category: str = "", shooting_angle: str = "front",
                         has_mannequin: bool = False, needs_shadow: bool = True,
                         max_retries: int = 3, on_log: Callable = None) -> dict:
        """독립 평가 결과를 바탕으로 그림자 프롬프트를 자동 수정하고 재처리.

        SKILL.md 규칙 1 적용: 해당 AI에게 직접 질문하여 프롬프트를 받는다.
        - Gemini 모드 → Gemini 텍스트 API에 질문 → 추천 힌트로 Gemini 이미지 재생성
        - Grok 모드 → Grok 텍스트 API에 질문 → 추천 힌트로 Grok 이미지 재생성
        프로바이더별 힌트를 shadow_hints.yaml에 저장하므로 다른 상품에 영향 없음.

        Returns:
            {
                "success": bool,
                "result_bytes": bytes or None,
                "final_eval": dict,
                "attempts": list,
                "best_hint": str,
                "hint_key": str,
            }
        """
        import os
        import json as _json
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        shadow_provider = self._shadow_provider  # "gemini_shadow" or "grok_shadow"
        prov_name = shadow_provider.replace("_shadow", "").upper()

        attempts = []
        best_score = evaluation.get("overall_score", 0)
        best_bytes = None
        best_eval = evaluation
        best_hint = ""

        # 프로바이더별 main_prompt
        prov_cfg_key = shadow_provider.replace("_shadow", "") + "_shadow"
        main_prompt = self._settings.get(prov_cfg_key, {}).get("main_prompt", "")

        # 힌트 키 결정
        prov_prefix = shadow_provider.replace("_shadow", "")
        if category and shooting_angle and image_type:
            base_key = f"{category}/{shooting_angle}/{image_type}"
        elif category and shooting_angle:
            base_key = f"{category}/{shooting_angle}"
        elif shooting_angle and image_type:
            base_key = f"{shooting_angle}/{image_type}"
        elif category:
            base_key = category
        else:
            base_key = shooting_angle or image_type or "default"
        hint_key = f"{prov_prefix}/{base_key}"

        current_hint, matched_key = self._get_shadow_hint(
            category, shooting_angle, image_type,
            provider=shadow_provider, on_log=_log)

        # 문제 설명 구성
        eval_issues = []
        for cat_key in ["shadow_natural", "background_clean", "edge_quality",
                         "product_integrity", "commercial_quality"]:
            item = evaluation.get(cat_key, {})
            score = item.get("score", 0)
            issues = item.get("issues", [])
            if score < 7 and issues:
                eval_issues.extend(issues)
        critical = evaluation.get("critical_issues", [])
        rec = evaluation.get("recommendation", "")
        problem_parts = eval_issues + critical
        if user_feedback:
            problem_parts.append(f"사용자 피드백: {user_feedback}")
        if rec:
            problem_parts.append(f"개선 제안: {rec}")
        problem_description = "\n".join(f"- {p}" for p in problem_parts) if problem_parts else "그림자 품질 미달"
        problem_description += f"\n\n상품: {category or '미분류'}, 촬영: {shooting_angle}, 유형: {image_type}"

        _log(f"  ━━━ 자동 수정 시작 ({prov_name}, 점수: {best_score}/10, 최대 {max_retries}회) ━━━", "warn")

        for attempt in range(1, max_retries + 1):
            _log(f"  [{prov_name} 시도 {attempt}/{max_retries}] 해당 AI에 직접 질문 중...")

            try:
                # ★ 핵심: 해당 AI에게 직접 질문
                suggested_hint = self._ask_ai_for_hint(
                    provider=shadow_provider,
                    problem_description=problem_description,
                    current_hint=current_hint,
                    main_prompt=main_prompt,
                    on_log=_log,
                )

                if not suggested_hint:
                    _log(f"  [시도 {attempt}] {prov_name} 추천 힌트 없음 → 중단", "warn")
                    break

                # 프로바이더별 힌트 키로 저장
                self._save_shadow_hint(hint_key, suggested_hint, on_log=_log)
                current_hint = suggested_hint

                # 그림자 재생성 (프로바이더에 따라 Gemini 또는 Grok)
                _log(f"  [시도 {attempt}] {prov_name} 추천 힌트로 그림자 재생성 중...")
                if shadow_provider == "gemini_shadow":
                    new_result = self._gemini_add_shadow(
                        pre_shadow_bytes, original_bytes=original_bytes,
                        has_mannequin=has_mannequin, on_log=_log,
                        shooting_angle=shooting_angle,
                        nukki_png_bytes=nukki_png_bytes,
                        category=category, image_type=image_type)
                elif shadow_provider == "grok_shadow":
                    new_result = self._grok_add_shadow(
                        pre_shadow_bytes, original_bytes=original_bytes,
                        has_mannequin=has_mannequin, on_log=_log,
                        shooting_angle=shooting_angle,
                        category=category, image_type=image_type)
                else:
                    new_result = None

                if not new_result:
                    _log(f"  [시도 {attempt}] {prov_name} 응답 없음 → 다음 시도", "warn")
                    attempts.append({"attempt": attempt, "score": 0, "status": "ai_fail"})
                    continue

                # 재평가
                new_eval = self._evaluate_independent(
                    new_result, image_type, needs_shadow,
                    original_bytes=original_bytes, on_log=_log)
                new_score = new_eval.get("overall_score", 0)

                attempts.append({
                    "attempt": attempt,
                    "score": new_score,
                    "hint": suggested_hint[:200] + "..." if len(suggested_hint) > 200 else suggested_hint,
                    "hint_key": hint_key,
                    "provider": prov_name,
                    "status": "improved" if new_score > best_score else "no_improvement",
                })

                _log(f"  [시도 {attempt}] {prov_name} 점수: {best_score:.1f} → {new_score:.1f} "
                     f"({'개선' if new_score > best_score else '미개선'})",
                     "success" if new_score > best_score else "warn")

                # 다음 질문에 이전 결과 문제를 업데이트
                if new_score <= best_score:
                    problem_description += f"\n\n이전 시도에서 추천한 힌트가 효과 없었습니다: {suggested_hint[:100]}"

                if new_score > best_score:
                    best_score = new_score
                    best_bytes = new_result
                    best_eval = new_eval
                    best_hint = suggested_hint

                if new_score >= 8.0:
                    _log(f"  [시도 {attempt}] 8점 이상 달성 → 조기 종료", "success")
                    break

            except Exception as e:
                _log(f"  [시도 {attempt}] 자동 수정 오류: {e}", "error")
                attempts.append({"attempt": attempt, "score": 0, "status": f"error: {e}"})
                continue

        success = best_bytes is not None and best_score > evaluation.get("overall_score", 0)

        # 실패 시 최선의 힌트도 없으면 원래 힌트 복원
        if not success and not best_hint:
            # 시도 전 힌트 복원
            pass

        _log(f"  ━━━ 자동 수정 {'성공' if success else '실패'} "
             f"({prov_name}, 최종: {best_score:.1f}/10, {len(attempts)}회) ━━━",
             "success" if success else "warn")

        return {
            "success": success,
            "result_bytes": best_bytes,
            "final_eval": best_eval,
            "attempts": attempts,
            "best_hint": best_hint,
            "hint_key": hint_key,
        }

    @staticmethod
    def _build_claude_report(input_path: str, output_path: str,
                             evaluation: dict, validation: dict,
                             auto_fix_result: dict,
                             user_feedback: str, log_text: str,
                             settings_snapshot: dict = None) -> str:
        """Claude Code에 붙여넣을 문제 보고서를 생성한다.

        Returns:
            클립보드에 복사할 수 있는 포맷팅된 텍스트
        """
        lines = []
        lines.append("═══ 이미지 편집 파이프라인 문제 보고 ═══")
        lines.append("")
        lines.append(f"■ 원본 이미지: {input_path}")
        lines.append(f"■ 결과 이미지: {output_path}")
        lines.append("")

        # 검증 결과
        lines.append("■ 검증 결과:")
        for key, label in [("background", "배경"), ("shadow", "그림자"), ("integrity", "원형보존")]:
            item = validation.get(key, {})
            mark = "합격" if item.get("pass", True) else "불합격"
            detail = item.get("detail", "")
            lines.append(f"  {label}: {mark} — {detail}")
        lines.append("")

        # 독립 평가
        lines.append("■ 독립 평가 결과:")
        label_map = {
            "shadow_natural": "그림자",
            "background_clean": "배경",
            "edge_quality": "경계선",
            "product_integrity": "원형보존",
            "commercial_quality": "상업성",
        }
        for cat_key, label in label_map.items():
            item = evaluation.get(cat_key, {})
            score = item.get("score", 0)
            issues = item.get("issues", [])
            issues_str = ", ".join(issues) if issues else "없음"
            lines.append(f"  {label}: {score}/10 — {issues_str}")
        lines.append(f"  종합: {evaluation.get('overall_score', 0)}/10")
        if evaluation.get("critical_issues"):
            lines.append(f"  핵심문제: {', '.join(evaluation['critical_issues'])}")
        if evaluation.get("recommendation"):
            lines.append(f"  개선제안: {evaluation['recommendation']}")
        lines.append("")

        # 자동 수정 시도 결과
        if auto_fix_result and auto_fix_result.get("attempts"):
            lines.append("■ 자동 수정 시도:")
            for a in auto_fix_result["attempts"]:
                status = a.get("status", "")
                score = a.get("score", 0)
                changes = ", ".join(a.get("changes", [])[:3])
                lines.append(f"  시도{a['attempt']}: {score:.1f}/10 ({status}) — {changes}")
            if auto_fix_result.get("success"):
                lines.append(f"  → 자동 수정으로 개선됨 (프롬프트 변경)")
            else:
                lines.append(f"  → 자동 수정으로 해결 안됨 → 소스 코드 수정 필요")
            lines.append("")

        # 사용자 의견
        lines.append("■ 사용자 의견:")
        lines.append(f"  {user_feedback if user_feedback else '(없음)'}")
        lines.append("")

        # 현재 설정
        if settings_snapshot:
            lines.append("■ 현재 설정:")
            for k, v in settings_snapshot.items():
                val_str = str(v)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                lines.append(f"  {k}: {val_str}")
            lines.append("")

        # 처리 로그
        lines.append("■ 처리 로그:")
        if log_text:
            for line in log_text.strip().split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append("  (로그 없음)")
        lines.append("")

        lines.append("═══════════════════════════════════════")
        lines.append("위 내용을 Claude Code에 붙여넣으세요.")

        return "\n".join(lines)

    def _validate_result(self, original_bytes: bytes, result_bytes: bytes,
                         image_type: str, needs_shadow: bool,
                         on_log: Callable = None,
                         category: str = "", shooting_angle: str = "") -> dict:
        """처리 결과 품질 검증 — Vision API로 3가지 항목 체크.

        Returns:
            {
                "background": {"pass": bool, "detail": str},
                "shadow": {"pass": bool, "detail": str},
                "integrity": {"pass": bool, "detail": str},
                "overall": bool,  # 3개 모두 통과 시 True
            }
        """
        import json as _json
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        _log(f"  품질 검증 시작 (배경/그림자/원형보존)")

        # 기본 PASS 결과 (검증 실패 시 fallback)
        default_result = {
            "background": {"pass": True, "detail": "검증 스킵"},
            "shadow": {"pass": True, "detail": "검증 스킵"},
            "integrity": {"pass": True, "detail": "검증 스킵"},
            "overall": True,
        }

        try:
            import cv2
            import io

            # numpy 이미지로 변환 (Vision API 입력)
            orig_arr = np.frombuffer(original_bytes, dtype=np.uint8)
            orig_img = cv2.imdecode(orig_arr, cv2.IMREAD_COLOR)
            result_arr = np.frombuffer(result_bytes, dtype=np.uint8)
            result_img = cv2.imdecode(result_arr, cv2.IMREAD_COLOR)

            if orig_img is None or result_img is None:
                _log(f"  품질 검증: 이미지 디코딩 실패 → 스킵", "warn")
                return default_result

            vision_client = self._get_vision_client()

            # prompts.yaml에서 검증 프롬프트 로드 (최신 편집 반영)
            try:
                import yaml as _yaml
                prompts_path = Path(__file__).parent.parent / "config" / "prompts.yaml"
                with open(prompts_path, "r", encoding="utf-8") as f:
                    _all_prompts = _yaml.safe_load(f)
                val_prompts = _all_prompts.get("validation", {})
            except Exception:
                val_prompts = self._prompt_builder._prompts.get("validation", {})

            # 카테고리별 검증 기준 조회
            category_validation, val_key = self._get_validation_hint(
                category=category, shooting_angle=shooting_angle,
                image_type=image_type, on_log=_log)

            if needs_shadow:
                shadow_context = val_prompts.get("shadow_needed",
                    "이 이미지는 그림자가 반드시 있어야 하는 이미지입니다.").strip()
            else:
                shadow_context = val_prompts.get("shadow_not_needed",
                    "이 이미지는 그림자가 불필요한 이미지입니다. 그림자 항목은 PASS로 판정하세요.").strip()

            system_prompt = val_prompts.get("system",
                "당신은 상품 이미지 품질 검수 전문가입니다. 반드시 JSON만 출력하세요.").strip()

            user_template = val_prompts.get("user_template", "").strip()
            if user_template:
                user_prompt = user_template.format(
                    image_type=image_type,
                    shadow_context=shadow_context,
                )
            else:
                user_prompt = (
                    f"첫 번째 이미지는 원본, 두 번째 이미지는 처리 결과입니다.\n"
                    f"상품 유형: {image_type}\n{shadow_context}\n\n"
                    "배경/그림자/원형보존 3항목을 검증하고 JSON으로 응답하세요."
                )

            # 카테고리별 검증 기준이 있으면 프롬프트에 추가
            if category_validation:
                user_prompt += (
                    f"\n\n[카테고리별 추가 검증 기준]\n{category_validation}"
                )

            response_text = vision_client.analyze_images(
                [orig_img, result_img],
                system_prompt,
                user_prompt,
                max_tokens=8192,
                temperature=0.1,
            )

            # JSON 파싱
            text = (response_text or "").strip()
            if not text:
                _log(f"  품질 검증: Vision API 빈 응답 → 스킵", "warn")
                return default_result
            # ```json ... ``` 블록 제거
            if "```" in text:
                import re
                m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
                if m:
                    text = m.group(1).strip()
                else:
                    # 닫는 ``` 없이 잘린 경우 — ```json 이후 내용만 추출
                    m2 = re.search(r'```(?:json)?\s*([\s\S]*)', text)
                    if m2:
                        text = m2.group(1).strip()

            try:
                parsed = _json.loads(text)
            except _json.JSONDecodeError:
                # 불완전 JSON 복구 시도 — 닫는 괄호 보충
                _log(f"  품질 검증: 불완전 JSON 복구 시도", "warn")
                logger.debug(f"Incomplete JSON: {text[:300]}")
                repaired = text
                open_braces = repaired.count('{') - repaired.count('}')
                open_brackets = repaired.count('[') - repaired.count(']')
                repaired += ']' * max(0, open_brackets)
                repaired += '}' * max(0, open_braces)
                try:
                    parsed = _json.loads(repaired)
                except _json.JSONDecodeError:
                    _log(f"  품질 검증: JSON 파싱 실패 → 스킵", "warn")
                    return default_result

            result = {}
            for key in ["background", "shadow", "integrity"]:
                item = parsed.get(key, {})
                is_pass = bool(item.get("pass", True))
                detail = str(item.get("detail", ""))
                result[key] = {"pass": is_pass, "detail": detail}
                status = "합격" if is_pass else "불합격"
                tag = "success" if is_pass else "warn"
                label = {"background": "배경", "shadow": "그림자", "integrity": "원형보존"}[key]
                _log(f"  검증 [{label}]: {status} - {detail}", tag)

            result["overall"] = all(v["pass"] for v in result.values() if isinstance(v, dict))
            overall_str = "합격" if result["overall"] else "불합격"
            overall_tag = "success" if result["overall"] else "warn"
            _log(f"  품질 검증 완료: {overall_str}", overall_tag)
            return result

        except Exception as e:
            _log(f"  품질 검증 오류: {e} → 스킵", "warn")
            return default_result

    @staticmethod
    def _remove_reflection(image_bytes: bytes, nukki_bytes: bytes,
                           on_log: Callable = None,
                           pre_shadow_bytes: bytes = None) -> bytes:
        """배경 영역의 반사/오염을 제거한다.

        두 가지 모드:
        1. 누끼에 알파가 있으면 → 알파 기반으로 제품/배경 분리
        2. 알파 없으면 → 그림자 생성 전 이미지(pre_shadow)와 비교하여 반사 감지
        """
        from PIL import Image
        import io
        import numpy as np

        _log = on_log or (lambda msg, tag="info": None)
        try:
            result = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            nukki = Image.open(io.BytesIO(nukki_bytes))
            arr = np.array(result)
            h, w = arr.shape[:2]

            has_alpha = nukki.mode == "RGBA"

            if has_alpha:
                # ── 알파 기반 모드 ──
                alpha = np.array(nukki.resize((w, h), Image.LANCZOS).split()[3])
                product_mask = alpha > 250
            elif pre_shadow_bytes:
                # ── 비교 기반 모드: 그림자 생성 전/후 비교 ──
                pre = Image.open(io.BytesIO(pre_shadow_bytes)).convert("RGB")
                if pre.size != (w, h):
                    pre = pre.resize((w, h), Image.LANCZOS)
                pre_arr = np.array(pre)

                # 그림자 전 이미지에서 제품 영역 = 흰색이 아닌 곳
                pre_gray = np.mean(pre_arr, axis=2)
                product_mask = pre_gray < 240
            else:
                return image_bytes

            # product_mask 팽창: 경계 픽셀 누락 방지 (흰색 틈 제거)
            import cv2
            kernel = np.ones((7, 7), dtype=np.uint8)
            product_mask_expanded = cv2.dilate(
                product_mask.astype(np.uint8), kernel, iterations=1
            ).astype(bool)

            # 제품 하단/좌우 경계 찾기
            row_has_product = product_mask_expanded.any(axis=1)
            product_rows = np.where(row_has_product)[0]
            if len(product_rows) == 0:
                return image_bytes
            product_bottom = product_rows[-1]

            col_has_product = product_mask_expanded.any(axis=0)
            product_cols = np.where(col_has_product)[0]
            product_left = max(0, product_cols[0] - 10)
            product_right = min(w, product_cols[-1] + 10)

            # 그림자 허용 영역: 제품 하단 윤곽을 따라가는 contour-following 방식
            shadow_margin = 60  # 제품 하단 윤곽에서 아래로 허용할 픽셀 수
            fade_margin = 25    # 그라데이션 페이드 영역
            overlap = 8         # 제품 경계와 그림자 존 겹침 (흰색 틈 방지)
            shadow_zone = np.zeros((h, w), dtype=bool)

            # 각 열(column)마다 제품 하단 경계를 찾아서 그 위 overlap부터 아래 shadow_margin까지 허용
            for col in range(product_left, product_right):
                col_product = np.where(product_mask_expanded[:, col])[0]
                if len(col_product) > 0:
                    col_bottom = col_product[-1]
                    zone_start = max(0, col_bottom - overlap)
                    zone_end = min(h, col_bottom + shadow_margin)
                    shadow_zone[zone_start:zone_end, col] = True

            # 비제품 영역 = 제품도 아니고 그림자 존도 아닌 곳
            non_product = ~product_mask & ~shadow_zone
            non_product_pixels = arr[non_product]
            if non_product_pixels.size == 0:
                return image_bytes

            # 비제품 영역에서 비백색 비율 확인
            not_white = np.any(non_product_pixels < 245, axis=1)
            ratio = not_white.mean()

            if ratio < 0.02:
                return image_bytes

            _log(f"  ⚠ 배경 오염/반사 감지: 비백색 {ratio:.0%} → 순백 보정", "warn")

            # 비제품 영역 전부 → 순백
            arr[non_product] = 255

            # 그림자 존 하단부 그라데이션 페이드 (일자 잘림 방지)
            for col in range(product_left, product_right):
                col_product = np.where(product_mask[:, col])[0]
                if len(col_product) > 0:
                    col_bottom = col_product[-1]
                    fade_start = col_bottom + shadow_margin - fade_margin
                    fade_end = min(h, col_bottom + shadow_margin)
                    if fade_end > fade_start and fade_start > col_bottom:
                        for y in range(fade_start, fade_end):
                            alpha = (y - fade_start) / (fade_end - fade_start)
                            arr[y, col] = (
                                arr[y, col].astype(np.float32) * (1 - alpha)
                                + 255.0 * alpha
                            ).astype(np.uint8)

            # 그림자 존에서도 밝기 150 미만(확실한 반사)만 흰색으로
            shadow_non_product = ~product_mask & shadow_zone
            shadow_pixels = arr[shadow_non_product]
            if shadow_pixels.size > 0:
                too_dark = np.any(shadow_pixels < 150, axis=1)
                if too_dark.any():
                    indices = np.where(shadow_non_product)
                    arr[indices[0][too_dark], indices[1][too_dark]] = 255

            result = Image.fromarray(arr)
            buf = io.BytesIO()
            result.save(buf, format="JPEG", quality=95)
            _log(f"  배경/반사 복원 완료 ({len(buf.getvalue()) // 1024}KB)")
            return buf.getvalue()
        except Exception as e:
            _log(f"  배경 복원 실패: {e}", "warn")
            return image_bytes

    @staticmethod
    def _protect_product_pixels(nukki_bytes: bytes, gemini_bytes: bytes,
                                on_log: Callable = None) -> bytes:
        """누끼 PNG의 불투명 영역은 원본 유지, 투명 영역만 Gemini 그림자 사용.

        누끼(PNG alpha)에서 제품이 있는 곳은 원본 픽셀을 100% 보존하고,
        투명한 배경 영역만 Gemini가 생성한 그림자를 가져온다.
        """
        from PIL import Image
        import io

        _log = on_log or (lambda msg, tag="info": None)
        try:
            nukki = Image.open(io.BytesIO(nukki_bytes))
            gemini = Image.open(io.BytesIO(gemini_bytes)).convert("RGB")

            # 누끼가 RGBA가 아니면 알파 채널이 없으므로 보호 불가 → Gemini 결과 그대로
            if nukki.mode != "RGBA":
                _log(f"  제품 보호: 누끼에 알파 없음 → AI 결과 그대로 사용")
                return gemini_bytes

            # 크기 맞추기
            if nukki.size != gemini.size:
                gemini = gemini.resize(nukki.size, Image.LANCZOS)

            nukki_rgba = nukki
            alpha = nukki_rgba.split()[3]  # 알파 채널
            nukki_rgb = nukki_rgba.convert("RGB")

            # 흰 배경 캔버스에 AI 그림자 합성
            result = gemini.copy()

            # 알파가 있는 곳(제품)은 원본 누끼 픽셀로 덮어쓰기
            result.paste(nukki_rgb, mask=alpha)

            buf = io.BytesIO()
            result.save(buf, format="JPEG", quality=95)
            protected_bytes = buf.getvalue()
            _log(f"  제품 보호(오버레이): 원본 픽셀 보존 완료 ({len(protected_bytes) // 1024}KB)")
            return protected_bytes
        except Exception as e:
            _log(f"  제품 보호 실패: {e} → AI 결과 그대로 사용", "warn")
            return gemini_bytes

    @staticmethod
    def _extract_shadow_layer(nukki_bytes: bytes, ai_result_bytes: bytes,
                              on_log: Callable = None) -> bytes:
        """AI 결과에서 그림자만 추출하여 원본 누끼와 합성 (그림자 레이어 분리 방식).

        1. 누끼 + 흰배경 = 기준 이미지 (그림자 없는 상태)
        2. 기준 이미지 vs AI 결과 비교 → 어두워진 부분 = 순수 그림자
        3. 흰배경에 그림자만 적용 + 원본 누끼 합성 = 최종

        기존 오버레이 방식과 달리, AI가 제품을 변형해도 그림자 차이값만
        사용하므로 제품 픽셀이 100% 보존됨. 반투명 경계면 문제도 해결.
        """
        from PIL import Image
        import io

        _log = on_log or (lambda msg, tag="info": None)
        try:
            nukki = Image.open(io.BytesIO(nukki_bytes))
            ai_result = Image.open(io.BytesIO(ai_result_bytes)).convert("RGB")

            if nukki.mode != "RGBA":
                _log(f"  그림자 추출: 누끼에 알파 없음 → AI 결과 그대로 사용")
                return ai_result_bytes

            # 크기 맞추기
            if nukki.size != ai_result.size:
                ai_result = ai_result.resize(nukki.size, Image.LANCZOS)

            alpha = nukki.split()[3]

            # Step 1: 기준 이미지 생성 (흰배경 + 누끼 합성 = 그림자 없는 상태)
            reference = Image.new("RGB", nukki.size, (255, 255, 255))
            reference.paste(nukki, mask=alpha)

            # Step 2: 그림자 차이값 계산 (배경 영역에서만)
            ref_arr = np.array(reference, dtype=np.float32)
            ai_arr = np.array(ai_result, dtype=np.float32)
            alpha_arr = np.array(alpha, dtype=np.float32)

            # 그림자 = 기준보다 어두워진 정도 (양수 = 그림자 추가됨)
            shadow_diff = ref_arr - ai_arr
            shadow_diff = np.clip(shadow_diff, 0, 255)

            # 배경 마스크: 알파가 낮은 영역에서만 그림자 적용
            # alpha < 10: 완전 배경 (그림자 100% 적용)
            # alpha 10~200: 전환 영역 (그라데이션)
            # alpha > 200: 제품 영역 (그림자 0%)
            bg_weight = np.clip((200.0 - alpha_arr) / 190.0, 0, 1)
            bg_weight_3ch = bg_weight[:, :, np.newaxis]

            # 배경 영역의 그림자만 추출
            shadow_masked = shadow_diff * bg_weight_3ch

            # Step 3: 흰배경에 그림자 적용
            final_arr = np.full_like(ref_arr, 255.0)
            final_arr = final_arr - shadow_masked
            final_arr = np.clip(final_arr, 0, 255).astype(np.uint8)
            final = Image.fromarray(final_arr)

            # Step 4: 원본 누끼를 위에 합성
            final.paste(nukki, mask=alpha)

            buf = io.BytesIO()
            final.save(buf, format="JPEG", quality=95)
            result_bytes = buf.getvalue()

            # 그림자 강도 로그
            shadow_intensity = np.mean(shadow_masked[shadow_masked > 1])
            shadow_pixels = np.sum(shadow_masked > 1)
            _log(f"  그림자 추출(레이어 분리): 그림자 픽셀 {shadow_pixels:,}개, "
                 f"평균 강도 {shadow_intensity:.1f}, 결과 {len(result_bytes)//1024}KB")
            return result_bytes

        except Exception as e:
            _log(f"  그림자 추출 실패: {e} → AI 결과 그대로 사용", "warn")
            return ai_result_bytes

    def _load_shadow_hints(self) -> dict:
        """shadow_hints.yaml 로드. 캐시 사용."""
        if not hasattr(self, '_shadow_hints_cache') or self._shadow_hints_cache is None:
            hints_path = Path(__file__).parent.parent / "config" / "shadow_hints.yaml"
            try:
                with open(str(hints_path), "r", encoding="utf-8") as f:
                    self._shadow_hints_cache = yaml.safe_load(f) or {}
            except Exception:
                self._shadow_hints_cache = {}
        return self._shadow_hints_cache

    def _get_shadow_hint(self, category: str = "", shooting_angle: str = "",
                         image_type: str = "", provider: str = "",
                         on_log: Callable = None) -> tuple:
        """조건별 그림자 프롬프트 보충 지시를 조회한다.

        조회 우선순위 (프로바이더 전용 > 공통, 가장 구체적인 것 우선):
          1. {provider}/category/angle/type  (프로바이더 전용 — 최우선)
          2. {provider}/category/angle
          3. {provider}/category
          4. category/angle/type             (공통)
          5. category/angle
          6. category
          7. {provider}/angle/type
          8. {provider}/angle
          9. angle/type
          10. angle
          11. type
          12. default

        Returns:
            (hint_text, matched_key) 튜플
        """
        _log = on_log or (lambda msg, tag="info": None)
        hints = self._load_shadow_hints()

        # 프로바이더명 정규화 (gemini_shadow → gemini, grok_shadow → grok)
        prov = provider.replace("_shadow", "") if provider else ""

        keys = []
        # 프로바이더 전용 키 (최우선)
        if prov:
            if category and shooting_angle and image_type:
                keys.append(f"{prov}/{category}/{shooting_angle}/{image_type}")
            if category and shooting_angle:
                keys.append(f"{prov}/{category}/{shooting_angle}")
            if category:
                keys.append(f"{prov}/{category}")
        # 공통 키
        if category and shooting_angle and image_type:
            keys.append(f"{category}/{shooting_angle}/{image_type}")
        if category and shooting_angle:
            keys.append(f"{category}/{shooting_angle}")
        if category:
            keys.append(category)
        # 프로바이더 전용 angle
        if prov:
            if shooting_angle and image_type:
                keys.append(f"{prov}/{shooting_angle}/{image_type}")
            if shooting_angle:
                keys.append(f"{prov}/{shooting_angle}")
        # 공통 angle/type
        if shooting_angle and image_type:
            keys.append(f"{shooting_angle}/{image_type}")
        if shooting_angle:
            keys.append(shooting_angle)
        if image_type:
            keys.append(image_type)
        keys.append("default")

        for key in keys:
            if key in hints and hints[key]:
                val = hints[key]
                # 새 형식: {shadow_hint: ..., validation: ...}
                if isinstance(val, dict):
                    hint_text = str(val.get("shadow_hint", "")).strip()
                else:
                    hint_text = str(val).strip()
                if hint_text:
                    _log(f"  그림자 힌트: [{key}] 적용")
                    return (hint_text, key)

        return ("", "none")

    def _get_validation_hint(self, category: str = "", shooting_angle: str = "",
                             image_type: str = "", on_log: Callable = None) -> tuple:
        """카테고리별 검증 기준을 조회한다.

        shadow_hints.yaml에서 {shadow_hint, validation} 딕셔너리 형식의
        validation 필드를 우선순위에 따라 조회.

        Returns:
            (validation_text, matched_key) 튜플
        """
        _log = on_log or (lambda msg, tag="info": None)
        hints = self._load_shadow_hints()

        keys = []
        if category and shooting_angle and image_type:
            keys.append(f"{category}/{shooting_angle}/{image_type}")
        if category and shooting_angle:
            keys.append(f"{category}/{shooting_angle}")
        if category:
            keys.append(category)
        if shooting_angle and image_type:
            keys.append(f"{shooting_angle}/{image_type}")
        if shooting_angle:
            keys.append(shooting_angle)
        if image_type:
            keys.append(image_type)
        keys.append("default")

        for key in keys:
            if key in hints and isinstance(hints[key], dict):
                val_text = str(hints[key].get("validation", "")).strip()
                if val_text:
                    _log(f"  검증 기준: [{key}] 적용")
                    return (val_text, key)

        return ("", "none")

    def _save_shadow_hint(self, key: str, hint_text: str, on_log: Callable = None):
        """shadow_hints.yaml에 특정 키의 힌트를 저장/업데이트한다."""
        _log = on_log or (lambda msg, tag="info": None)
        hints_path = Path(__file__).parent.parent / "config" / "shadow_hints.yaml"

        try:
            try:
                with open(str(hints_path), "r", encoding="utf-8") as f:
                    hints = yaml.safe_load(f) or {}
            except Exception:
                hints = {}

            hints[key] = hint_text

            # 캐시 무효화
            self._shadow_hints_cache = None

            with open(str(hints_path), "w", encoding="utf-8") as f:
                f.write("# 카테고리/촬영각도/촬영유형 조합별 그림자 프롬프트 보충 지시\n")
                f.write("# 자동 생성/수정됨 — 독립 평가에서 문제 발견 시 자동 추가\n")
                f.write("# 키 형식: {category}/{shooting_angle}/{image_type}\n")
                f.write("# 조회 우선순위: category/angle/type > category/angle > category > angle/type > angle > type > default\n\n")
                yaml.dump(hints, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            _log(f"  그림자 힌트 저장: [{key}]", "success")
        except Exception as e:
            _log(f"  그림자 힌트 저장 실패: {e}", "error")

    def _gemini_add_shadow(self, image_bytes: bytes,
                           original_bytes: bytes = None,
                           has_mannequin: bool = False,
                           on_log: Callable = None,
                           shooting_angle: str = "front",
                           nukki_png_bytes: bytes = None,
                           category: str = "",
                           image_type: str = "full") -> Optional[bytes]:
        """Gemini 이미지 편집 API로 자연스러운 그림자를 추가한다.

        Args:
            image_bytes: 배경 제거된 이미지 (PNG/JPEG)
            original_bytes: 원본 이미지 (그림자 참고용)
            nukki_png_bytes: RGBA 누끼 PNG (반사 제거 시 정확한 제품 마스크용)
            has_mannequin: 마네킹 잔여물 제거 필요 여부
            shooting_angle: 촬영 각도 (front, high_angle, side 등)

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

            # settings.yaml에서 프롬프트 로드 (통합 3개 키, 하위호환 포함)
            gs_cfg = self._settings.get("gemini_shadow", {})

            main_prompt = gs_cfg.get("main_prompt",
                "(가장 중요) 제공된 PNG 이미지의 알파 채널과 제품의 모든 픽셀 위치, "
                "스케일(크기)을 0.001%의 변경도 없이 100% 그대로 고정하세요. "
                "제품의 크기를 키우거나 위치를 옮기는 행위를 최우선으로 금지합니다.\n"
                "1. 배경 및 경계 보존: 배경은 결점 없는 순백색(#FFFFFF)을 유지하되, "
                "제품 바닥면과 배경이 만나는 경계선(Edge)이 조명에 의해 날아가지 않도록 "
                "선명하게 보존하세요. 하단 경계가 배경과 동화되는 현상을 엄격히 금지합니다.\n"
                "2. 입체적 조명 처리: 제품의 질감과 색조를 보호하면서, 특히 제품 하단부에 "
                "아주 미세하고 자연스러운 음영(Contact Occlusion)을 남겨 제품이 바닥에 "
                "견고하게 놓여 있는 느낌을 구현하세요.\n"
                "3. 그림자 생성: 제품의 전체 하단 실루엣이 아닌, 제품이 바닥과 실제로 맞닿는 "
                "접지면(contact surface)에만 아주 연한 투명 그레이 접지 그림자를 추가하세요. "
                "바닥에 닿지 않는 부분에는 그림자를 만들지 마세요.\n"
                "4. 금지 사항: (a) 제품을 확대하거나 위치를 옮기는 행위, "
                "(b) 경계선을 뭉개는 인공적인 블러(Blur) 처리나 과도한 화이트닝, "
                "(c) 제품의 디테일을 보여주기 위해 스케일을 확대하는 행위, "
                "(d) ★ 바닥 반사(reflection/mirror effect) 생성을 엄격히 금지합니다. "
                "그림자는 오직 불투명한 접지 그림자(contact shadow)만 허용됩니다. "
                "제품이 바닥에 비치는 거울 반사 효과는 절대 추가하지 마세요.")

            # 하위호환: 기존 ref_prompt + orig_insert → original_prompt로 마이그레이션
            if "original_prompt" in gs_cfg:
                original_prompt = gs_cfg["original_prompt"]
            elif "ref_prompt" in gs_cfg:
                original_prompt = gs_cfg["ref_prompt"] + "\n" + gs_cfg.get("orig_insert", "")
            else:
                original_prompt = (
                    "위 이미지는 원본 제품 사진입니다. 원본에 있는 자연스러운 그림자의 "
                    "방향, 농도, 부드러움을 참고하세요.\n"
                    "원본 사진의 그림자를 최대한 동일하게 재현해주세요. "
                    "그림자의 방향이 같도록 해주세요. 피사체의 사이즈는 변경하지 말아주세요.")

            # 하위호환: 기존 mannequin_full_prompt → mannequin_prompt로 마이그레이션
            if "mannequin_prompt" in gs_cfg and "mannequin_full_prompt" not in gs_cfg:
                mannequin_prompt = gs_cfg["mannequin_prompt"]
            elif "mannequin_full_prompt" in gs_cfg:
                mannequin_prompt = gs_cfg["mannequin_full_prompt"]
            else:
                mannequin_prompt = (
                    "위 이미지는 마네킹에 착용된 의류 원본 사진입니다. "
                    "다음 작업을 수행해주세요:\n"
                    "1. 배경을 완전히 제거하고 깨끗한 흰색(#FFFFFF)으로 교체하세요.\n"
                    "2. 마네킹/토르소/스탠드를 완전히 제거하세요.\n"
                    "3. 마네킹 제거 후 의류의 자연스러운 마감선(밑단, 소매 등)을 복원하세요.\n"
                    "그림자는 추가하지 마세요. 배경은 순백색을 유지하세요.\n"
                    "의류 자체(색상, 질감, 로고, 지퍼 등)는 절대 변경하지 마세요.")

            contents = []

            if has_mannequin and original_bytes:
                # ★ 마네킹 모드: 원본 이미지를 메인으로 전송
                contents.append(types.Part.from_bytes(
                    data=original_bytes, mime_type=_detect_mime(original_bytes)))
                contents.append(mannequin_prompt)
                _log(f"  마네킹 모드: 원본 이미지를 메인으로 전송 (누끼 잔여물 우회)")
            else:
                # 일반 모드: 원본 참고 + 누끼 메인
                if original_bytes:
                    contents.append(types.Part.from_bytes(
                        data=original_bytes, mime_type=_detect_mime(original_bytes)))
                    contents.append(original_prompt)
                contents.append(types.Part.from_bytes(
                    data=image_bytes, mime_type=_detect_mime(image_bytes)))

                # ★ 계층적 그림자 힌트 조회 (shadow_hints.yaml)
                shadow_hint, hint_key = self._get_shadow_hint(
                    category=category,
                    shooting_angle=shooting_angle,
                    image_type=image_type,
                    provider="gemini_shadow",
                    on_log=_log)
                if shadow_hint:
                    main_prompt = main_prompt + "\n\n[상품별 보충 지시]\n" + shadow_hint

                contents.append(main_prompt)

            _main_img = original_bytes if (has_mannequin and original_bytes) else image_bytes
            _log(f"  Gemini 그림자 요청 (모델: {model}, "
                 f"메인: {_detect_mime(_main_img)} {len(_main_img)//1024}KB, "
                 f"마네킹 모드: {'O' if has_mannequin else 'X'}, "
                 f"원본 참고: {'O' if original_bytes and not has_mannequin else 'X'})")

            import time as _time
            from PIL import Image as _PILImg
            import io as _io

            # ★ 폴백 모델 체인: 현재 모델 → 폴백 모델 (서버 과부하 시 자동 전환)
            fallback_model = gs_cfg.get(
                "fallback_model", "gemini-3-pro-image-preview")
            FALLBACK_MODELS = [
                model,          # 설정된 기본 모델 (예: gemini-3.1-flash-image-preview)
                fallback_model,  # 폴백 모델 (예: gemini-3-pro-image-preview)
            ]
            # 중복 제거 (이미 Pro 모델이 기본이면 폴백 불필요)
            seen = set()
            fallback_chain = []
            for m in FALLBACK_MODELS:
                if m not in seen:
                    seen.add(m)
                    fallback_chain.append(m)

            max_retries = 3

            for model_idx, current_model in enumerate(fallback_chain):
                is_fallback = model_idx > 0
                if is_fallback:
                    _log(f"  ★ 폴백 모델로 전환: {current_model}", "warn")

                for attempt in range(1, max_retries + 1):
                    try:
                        response = client.models.generate_content(
                            model=current_model,
                            contents=contents,
                            config=types.GenerateContentConfig(
                                response_modalities=["IMAGE", "TEXT"],
                                temperature=0.2,
                            ),
                        )

                        # 응답에서 이미지 추출
                        for part in response.candidates[0].content.parts:
                            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                                result_bytes = part.inline_data.data
                                model_label = current_model
                                if is_fallback:
                                    model_label += " (폴백)"
                                _log(f"  Gemini 그림자 생성 완료 — {model_label} "
                                     f"({len(result_bytes) // 1024}KB)", "success")
                                # ★ 제품 보호: 설정에 따라 오버레이 or 레이어 분리
                                composite = self._settings.get(
                                    "shadow_composite_method", "overlay")
                                _layer_extract_used = False
                                if composite == "layer_extract":
                                    # RGBA 누끼가 있으면 정확한 레이어 분리 가능
                                    _nukki_for_extract = nukki_png_bytes if nukki_png_bytes else image_bytes
                                    # RGBA 누끼인지 확인
                                    _check_nukki = _PILImg.open(_io.BytesIO(_nukki_for_extract))
                                    if _check_nukki.mode == "RGBA":
                                        result_bytes = self._extract_shadow_layer(
                                            _nukki_for_extract, result_bytes, on_log=_log)
                                        _layer_extract_used = True
                                    else:
                                        result_bytes = self._extract_shadow_layer(
                                            _nukki_for_extract, result_bytes, on_log=_log)
                                else:
                                    result_bytes = self._protect_product_pixels(
                                        image_bytes, result_bytes, on_log=_log)
                                # ★ 반사(reflection) 후처리: layer_extract가 RGBA로 정상 동작한 경우 스킵
                                if _layer_extract_used:
                                    _log(f"  레이어 분리 완료 → 반사 제거 스킵 (그림자 보존)")
                                else:
                                    _nukki_for_ref = nukki_png_bytes if nukki_png_bytes else image_bytes
                                    result_bytes = self._remove_reflection(
                                        result_bytes, _nukki_for_ref, on_log=_log,
                                        pre_shadow_bytes=image_bytes)
                                return result_bytes

                        _log(f"  Gemini 응답에 이미지 없음 ({current_model})", "warn")
                        return None

                    except Exception as retry_err:
                        err_str = str(retry_err)
                        is_server_error = any(k in err_str for k in
                                              ["500", "503", "INTERNAL", "UNAVAILABLE",
                                               "overloaded", "high demand"])
                        if is_server_error and attempt < max_retries:
                            wait = attempt * 3
                            _log(f"  Gemini 서버 오류 (시도 {attempt}/{max_retries}, "
                                 f"모델: {current_model}), "
                                 f"{wait}초 후 재시도: {retry_err}", "warn")
                            _time.sleep(wait)
                            continue
                        # 마지막 재시도까지 실패 — 폴백 모델이 남아있으면 전환
                        if is_server_error and model_idx < len(fallback_chain) - 1:
                            _log(f"  ★ {current_model} 서버 과부하 ({max_retries}회 실패) "
                                 f"→ 폴백 모델로 전환 시도", "warn")
                            break  # 다음 모델로
                        raise

            # 모든 모델 + 재시도 소진
            _log(f"  모든 Gemini 모델 실패 (폴백 포함)", "error")
            return None

        except Exception as e:
            _log(f"  Gemini 그림자 생성 오류: {e}", "error")
            logger.exception(f"Gemini shadow error: {e}")
            return None

    def _grok_add_shadow(self, image_bytes: bytes,
                         original_bytes: bytes = None,
                         has_mannequin: bool = False,
                         on_log: Callable = None,
                         shooting_angle: str = "front",
                         category: str = "",
                         image_type: str = "full") -> Optional[bytes]:
        """Grok (xAI) Images Edit API로 자연스러운 그림자를 추가한다.

        xAI /v1/images/edits 엔드포인트를 사용하여 이미지 편집.
        OpenAI SDK를 사용할 수 없으므로 (multipart vs JSON 차이) requests로 직접 호출.

        Args:
            image_bytes: 배경 제거된 이미지 (PNG/JPEG)
            original_bytes: 원본 이미지 (그림자 참고용)
            has_mannequin: 마네킹 잔여물 제거 필요 여부
            shooting_angle: 촬영 각도
            category: 상품 카테고리
            image_type: 촬영 유형 (full, detail, worn 등)

        Returns:
            그림자가 추가된 이미지 바이트, 실패 시 None
        """
        import os
        import base64
        import requests as _requests
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        try:
            api_key = os.getenv("XAI_API_KEY")
            if not api_key:
                _log(f"  XAI_API_KEY 미설정", "error")
                return None

            # settings.yaml에서 프롬프트 로드 (통합 3개 키, 하위호환 포함)
            gs_cfg = self._settings.get("grok_shadow", {})
            model = gs_cfg.get("model", "grok-imagine-image")

            main_prompt = gs_cfg.get("main_prompt",
                "위 이미지는 배경이 제거된 누끼 이미지입니다. "
                "이 누끼 이미지의 바닥에 자연스러운 접지 그림자(ground shadow)를 추가해주세요. "
                "제품 자체는 절대 변경하지 마세요. 배경은 깨끗한 흰색을 유지하세요. "
                "그림자는 제품 바로 아래에 부드럽게 퍼지는 형태로, "
                "럭셔리 이커머스 제품 사진처럼 고급스럽게 만들어주세요. "
                "누끼 이미지를 기반으로 결과를 출력하세요.")

            # 하위호환: 기존 ref_prompt + orig_insert → original_prompt
            if "original_prompt" in gs_cfg:
                original_prompt = gs_cfg["original_prompt"]
            elif "ref_prompt" in gs_cfg:
                original_prompt = gs_cfg["ref_prompt"] + "\n" + gs_cfg.get("orig_insert", "")
            else:
                original_prompt = (
                    "위 이미지는 원본 제품 사진입니다. 원본에 있는 자연스러운 그림자의 "
                    "방향, 농도, 부드러움을 참고하세요.\n"
                    "원본 사진의 그림자를 최대한 동일하게 재현해주세요.")

            # 하위호환: 기존 mannequin_full_prompt → mannequin_prompt
            if "mannequin_prompt" in gs_cfg and "mannequin_full_prompt" not in gs_cfg:
                mannequin_prompt = gs_cfg["mannequin_prompt"]
            elif "mannequin_full_prompt" in gs_cfg:
                mannequin_prompt = gs_cfg["mannequin_full_prompt"]
            else:
                mannequin_prompt = (
                    "위 이미지는 마네킹에 착용된 의류 원본 사진입니다. 다음 작업을 수행해주세요:\n"
                    "1. 배경을 완전히 제거하고 깨끗한 흰색(#FFFFFF)으로 교체하세요.\n"
                    "2. 마네킹/토르소/스탠드를 완전히 제거하세요.\n"
                    "3. 마네킹 제거 후 의류의 자연스러운 마감선(밑단, 소매 등)을 복원하세요.\n"
                    "4. 의류 하단에 자연스러운 접지 그림자를 추가하세요.\n"
                    "의류 자체(색상, 질감, 로고, 지퍼 등)는 절대 변경하지 마세요. "
                    "럭셔리 이커머스 제품 사진처럼 고급스럽게 만들어주세요.")

            def _detect_mime(data: bytes) -> str:
                if data[:8].startswith(b'\x89PNG'):
                    return "image/png"
                return "image/jpeg"

            def _to_data_uri(data: bytes) -> str:
                mime = _detect_mime(data)
                b64 = base64.b64encode(data).decode("utf-8")
                return f"data:{mime};base64,{b64}"

            # 카테고리/촬영각도/유형별 보충 힌트 조회
            shadow_hint, hint_key = self._get_shadow_hint(
                category=category, shooting_angle=shooting_angle,
                image_type=image_type, provider="grok_shadow",
                on_log=_log)
            if shadow_hint:
                main_prompt = main_prompt + "\n\n[상품별 보충 지시]\n" + shadow_hint

            # 프롬프트 구성
            if has_mannequin and original_bytes:
                # 마네킹 모드: 원본 이미지를 편집 대상으로 전송
                main_image = original_bytes
                full_prompt = mannequin_prompt
                _log(f"  마네킹 모드: 원본 이미지를 메인으로 전송")
            else:
                # 일반 모드: 누끼 이미지를 편집 대상으로 전송
                main_image = image_bytes
                if original_bytes:
                    full_prompt = f"{original_prompt}\n\n{main_prompt}"
                else:
                    full_prompt = main_prompt

            _log(f"  Grok 그림자 요청 (모델: {model}, "
                 f"메인: {_detect_mime(main_image)} {len(main_image)//1024}KB, "
                 f"마네킹: {'O' if has_mannequin else 'X'}, "
                 f"원본 참고: {'O' if original_bytes and not has_mannequin else 'X'}")

            # xAI /v1/images/edits — JSON, image는 ImageUrl 객체 {url, type}
            main_data_uri = _to_data_uri(main_image)

            payload = {
                "model": model,
                "prompt": full_prompt,
                "image": {
                    "url": main_data_uri,
                    "type": "image_url",
                },
                "n": 1,
                "response_format": "b64_json",
            }

            resp = _requests.post(
                "https://api.x.ai/v1/images/edits",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )

            if resp.status_code != 200:
                err_msg = resp.text[:500]
                _log(f"  Grok API 오류 ({resp.status_code}): {err_msg}", "error")
                logger.error(f"Grok shadow API error {resp.status_code}: {err_msg}")
                return None

            result = resp.json()
            data_list = result.get("data", [])
            if not data_list:
                _log(f"  Grok 응답에 이미지 없음", "warn")
                return None

            # b64_json 형식에서 이미지 추출
            b64_data = data_list[0].get("b64_json")
            raw_bytes = None
            if b64_data:
                raw_bytes = base64.b64decode(b64_data)
                _log(f"  Grok 그림자 생성 완료 ({len(raw_bytes)//1024}KB)")
            else:
                # URL 형식 fallback
                img_url = data_list[0].get("url")
                if img_url:
                    _log(f"  Grok 이미지 URL 수신, 다운로드 중...")
                    dl_resp = _requests.get(img_url, timeout=60)
                    if dl_resp.status_code == 200:
                        raw_bytes = dl_resp.content
                        _log(f"  Grok 그림자 생성 완료 ({len(raw_bytes)//1024}KB)")

            if raw_bytes:
                # ★ 제품 보호: 설정에 따라 오버레이 or 레이어 분리
                composite = self._settings.get(
                    "shadow_composite_method", "overlay")
                _layer_extract_used = False
                if composite == "layer_extract":
                    # RGBA 누끼인지 확인
                    from PIL import Image as _PILImg
                    import io as _io
                    _check_nukki = _PILImg.open(_io.BytesIO(image_bytes))
                    if _check_nukki.mode == "RGBA":
                        result_bytes = self._extract_shadow_layer(
                            image_bytes, raw_bytes, on_log=_log)
                        _layer_extract_used = True
                    else:
                        result_bytes = self._extract_shadow_layer(
                            image_bytes, raw_bytes, on_log=_log)
                else:
                    result_bytes = self._protect_product_pixels(
                        image_bytes, raw_bytes, on_log=_log)
                # ★ 반사(reflection) 후처리: layer_extract가 RGBA로 정상 동작한 경우 스킵
                if _layer_extract_used:
                    _log(f"  레이어 분리 완료 → 반사 제거 스킵 (그림자 보존)")
                else:
                    result_bytes = self._remove_reflection(
                        result_bytes, image_bytes, on_log=_log,
                        pre_shadow_bytes=image_bytes)
                return result_bytes

            _log(f"  Grok 응답에서 이미지를 추출할 수 없음", "warn")
            return None

        except Exception as e:
            _log(f"  Grok 그림자 생성 오류: {e}", "error")
            logger.exception(f"Grok shadow error: {e}")
            return None

    def _get_vision_config(self, provider: str) -> dict:
        """프로바이더별 API 설정(max_tokens, temperature 등)을 반환."""
        if provider == "chatgpt":
            return self._settings.get("openai", {})
        elif provider == "gemini":
            return self._settings.get("gemini", {})
        elif provider == "grok":
            return self._settings.get("grok", {})
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
                # fallback: 여러 JSON 블록이 있을 경우 가장 큰 것 사용
                import re as _re
                blocks = _re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response_text, _re.DOTALL)
                for block in sorted(blocks, key=len, reverse=True):
                    try:
                        import json as _json
                        json_data = _json.loads(block)
                        if isinstance(json_data, dict) and len(json_data) >= 2:
                            break
                        json_data = None
                    except Exception:
                        json_data = None
                if json_data is None:
                    return {"evaluator": provider, "error": "파싱 실패",
                            "raw": response_text[:500]}
            json_data["evaluator"] = provider
            return json_data
        except Exception as e:
            logger.error(f"[{provider}] Vision API 호출 실패: {e}")
            return {"evaluator": provider, "error": str(e)}

    def _call_all_vision_apis(self, images: list, system_prompt: str,
                              user_prompt: str, on_log: Callable = None) -> list:
        """Vision API(Claude, ChatGPT, Gemini, Grok)를 병렬 호출한다."""
        import concurrent.futures
        _log = on_log or (lambda msg, tag="info": logger.info(msg))

        providers = ["claude", "chatgpt", "gemini", "grok"]
        provider_names = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini", "grok": "Grok"}
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
            # phase 5 결과에 scores가 없으면 phase 1 scores를 포함시킨다
            fallback_inputs = list(latest_solutions)
            has_scores = any(r.get("scores") for r in fallback_inputs)
            if not has_scores and valid_p1:
                fallback_inputs = valid_p1 + fallback_inputs
            p6_result = self._merge_results_fallback(fallback_inputs)

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
                                pre_cropped: bool = False,
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
                pre_cropped=pre_cropped,
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

    # ──────────────────────────────────────────────────────────────
    # 포토룸 배경+그림자 통합 방식 (임시 옵션 탭용)
    # ──────────────────────────────────────────────────────────────

    def process_single_unified_photoroom(
        self,
        image_path: str,
        output_dir: str,
        shadow_mode: str = "ai.soft",
        bg_color: str = "FFFFFF",
        shadow_opacity: int = 20,
        on_log: Callable = None,
        idx: int = 1,
        routing_rules: list = None,
    ) -> dict:
        """Vision 분류 → 자동 분기 처리.

        full shot           → Photoroom(배경+그림자) → Claid
        detail + 흰배경     → Photoroom(배경만)      → Claid
        detail + 비흰배경   → Claid만
        """
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        try:
            original_bytes = Path(image_path).read_bytes()  # 원본 무압축 보존
            image_bytes = _shrink_bytes(original_bytes, max_px=3000)
            _log(f"  원본 로드: {len(original_bytes)//1024}KB")

            # 1. Vision 분류 (image_type + background)
            _log("  [Vision] 이미지 분류 중...")
            try:
                instruction = self.analyze_only(image_path, category="", on_log=_log)
                image_type = instruction.image_type   # full / detail / package / worn
                background = instruction.background   # clean / colored / gradient ...
                shooting_angle = instruction.shooting_angle  # front / top_down / side / ...
                is_label_cut = instruction.is_label_cut  # 바코드/모델명 태그 확대컷
            except Exception as ve:
                import traceback as _tb
                _log(f"  Vision 분류 실패 → full/clean 으로 가정: {ve}", "warn")
                _log(_tb.format_exc(), "warn")
                image_type, background, shooting_angle, is_label_cut = "full", "clean", "front", False

            is_detail = image_type == "detail"
            is_clean_bg = background in ("clean", "white", "")
            is_top_down = shooting_angle == "top_down"
            _log(f"  분류 결과: {image_type} / 배경={background} / 각도={shooting_angle}"
                 + (" / 라벨컷" if is_label_cut else ""))

            # 라우팅 규칙 평가
            do_nukki, do_shadow, do_enhance = None, None, None
            if routing_rules:
                bg_type = "clean" if is_clean_bg else "colored"
                for rule in routing_rules:
                    cond = rule.get("conditions", {})
                    if cond.get("is_label_cut") is True and not is_label_cut:
                        continue
                    if cond.get("is_label_cut") is False and is_label_cut:
                        continue
                    if "shooting_angle" in cond and cond["shooting_angle"] != shooting_angle:
                        continue
                    if "image_type" in cond and cond["image_type"] != image_type:
                        continue
                    if "background_type" in cond and cond["background_type"] != bg_type:
                        continue
                    proc = rule.get("processing", {})
                    do_nukki   = proc.get("nukki",   True)
                    do_shadow  = proc.get("shadow",  True)
                    do_enhance = proc.get("enhance", True)
                    _log(f"  [라우팅규칙] '{rule.get('name','?')}' 적용 → 누끼={do_nukki} 그림자={do_shadow} 보정={do_enhance}")
                    break

            claid_settings = self._settings.get("claid", {})
            claid_config = dict(claid_settings.get(image_type, claid_settings.get("full", {})))
            output_config = self._settings.get("output", {})
            max_size_kb = output_config.get("max_file_size_kb", 2024)

            # ── 처리 플래그 결정 (라우팅 규칙 없으면 기존 하드코딩) ──
            if do_nukki is None:
                # 기존 하드코딩 로직
                if is_label_cut:
                    do_nukki, do_shadow, do_enhance = False, False, False
                elif is_top_down:
                    do_nukki, do_shadow, do_enhance = False, False, True
                elif is_detail and not is_clean_bg:
                    do_nukki, do_shadow, do_enhance = False, False, True
                elif is_detail and is_clean_bg:
                    do_nukki, do_shadow, do_enhance = True, False, True
                else:
                    do_nukki, do_shadow, do_enhance = True, True, True

            # ── 처리 실행 ──
            if not do_nukki and not do_enhance:
                # 아무 처리 없음 → 원본 그대로
                _log("  [경로] 처리 없음 → 원본 저장", "info")
                current_bytes = original_bytes

            elif not do_nukki and do_enhance:
                # 보정만
                _log("  [경로] 보정만 수행 (누끼 없음)", "info")
                current_bytes = self._claid_process_safe(
                    image_bytes, image_type, config=claid_config,
                    fallback=image_bytes, on_log=_log)
                if current_bytes is not image_bytes:
                    _log(f"  Claid 완료 ({len(current_bytes)//1024}KB)", "success")

            else:
                # 누끼 포함 (Photoroom 호출)
                pr_config = {
                    "background.color": bg_color,
                    "export.format": "jpg",
                    "outputSize": "1000x1000",
                    "padding": "0.1",
                    "scaling": "fit",
                }
                if do_shadow:
                    _log(f"  [경로] Photoroom 배경+그림자({shadow_mode})", "info")
                    pr_config["shadow.mode"] = shadow_mode
                    pr_config["shadow.opacity"] = str(shadow_opacity)
                else:
                    _log("  [경로] Photoroom 배경만 (그림자 없음)", "info")

                result_bytes = self._photoroom.process(
                    image_bytes, image_type, background,
                    output_size="1000x1000", config=pr_config,
                )
                if not result_bytes:
                    return {"success": False, "error": "Photoroom 응답 없음", "path": image_path}
                _log(f"  Photoroom 완료 ({len(result_bytes)//1024}KB)", "success")

                if do_enhance:
                    claid_input = result_bytes
                    if is_detail:
                        _log("  [검증] 누끼 품질 확인 중...", "info")
                        nukki_ok, nukki_reason = self._check_detail_nukki_quality(
                            result_bytes, on_log=_log)
                        if nukki_ok:
                            _log(f"  누끼 품질 양호 → Claid 처리", "success")
                        else:
                            _log(f"  누끼 품질 불량 ({nukki_reason}) → 원본으로 대체 후 Claid", "warn")
                            claid_input = image_bytes
                    current_bytes = self._claid_process_safe(
                        claid_input, image_type, config=claid_config,
                        fallback=result_bytes, on_log=_log)
                    if current_bytes is not result_bytes:
                        _log(f"  Claid 완료 ({len(current_bytes)//1024}KB)", "success")
                else:
                    current_bytes = result_bytes

            # 저장
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            namer = FileNamer(FileNamer.extract_base_from_path(image_path))
            file_name = namer.next_name(".jpg")
            file_path = output_path / file_name
            info = self._optimizer.save_from_bytes(current_bytes, str(file_path), max_size_kb)
            _log(f"  출력: {file_name} ({info['size_kb']}KB)", "success")
            # 진행 로그 기록 (성공)
            _update_progress_log(output_dir, Path(image_path).name, True)
            return {
                "success": True, "files": [info], "path": image_path,
                "image_type": image_type, "background": background,
                "shooting_angle": shooting_angle,
                "is_label_cut": is_label_cut,
            }

        except ClaidNoCreditError:
            raise   # GUI로 전파 — 처리 중단 신호

        except Exception as e:
            import traceback
            _log(f"  오류: {e}", "error")
            _log(traceback.format_exc(), "error")
            # 진행 로그 기록 (실패)
            try:
                _update_progress_log(output_dir, Path(image_path).name, False)
            except Exception:
                pass
            return {"success": False, "error": str(e), "path": image_path}

    def _check_detail_nukki_quality(self, result_bytes: bytes,
                                    on_log=None) -> tuple:
        """OpenCV로 누끼 결과에 내부 구멍이 있는지 검사한다.

        배경색이 흰색인 JPEG 결과에서, 이미지 경계에 닿지 않는 흰색 연결 영역
        (= 상품 내부 구멍)을 찾아 품질을 판정한다.

        Returns:
            (is_ok: bool, reason: str)
        """
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        try:
            import io as _io
            import numpy as _np
            import cv2 as _cv2
            from PIL import Image as _Image

            with _Image.open(_io.BytesIO(result_bytes)) as _img:
                arr = _np.array(_img.convert("RGB"))

            h, w = arr.shape[:2]

            # 흰색 마스크 (R>240, G>240, B>240)
            white_mask = (_np.all(arr > 240, axis=2)).astype(_np.uint8) * 255

            # 테두리에서 flood fill로 외부 흰색 마킹
            # → 외부와 연결되지 않은 흰색 = 상품 내부 구멍
            padded = _cv2.copyMakeBorder(
                white_mask, 1, 1, 1, 1, _cv2.BORDER_CONSTANT, value=255)
            flood = padded.copy()
            _cv2.floodFill(flood, None, (0, 0), 128)  # 외부 흰색 → 128로 마킹
            flood = flood[1:-1, 1:-1]  # 패딩 제거

            # 여전히 255인 픽셀 = 외부와 연결 안 된 내부 구멍
            interior = (flood == 255)
            interior_ratio = float(interior.sum()) / (h * w)

            if interior_ratio > 0.0005:  # 0.05% 이상
                # 구멍 위치 파악
                ys, xs = _np.where(interior)
                cx, cy = int(xs.mean()), int(ys.mean())
                _log(f"  내부 흰색 구멍 감지 (면적 {interior_ratio:.1%}, "
                     f"중심 x={cx} y={cy})", "warn")
                return False, f"상품 내부 흰색 구멍 (면적 {interior_ratio:.1%})"

            return True, "이상 없음"
        except Exception as e:
            _log(f"  누끼 검증 실패 → 결과 그대로 사용: {e}", "warn")
            return True, str(e)

    def process_batch_unified_photoroom(
        self,
        input_dir: str,
        output_dir: str,
        shadow_mode: str = "ai.soft",
        bg_color: str = "FFFFFF",
        shadow_opacity: int = 80,
        on_log: Callable = None,
        on_progress: Callable = None,
        is_cancelled: Callable = None,
    ) -> list:
        """포토룸 통합 방식 배치 처리."""
        _log = on_log or (lambda msg, tag="info": logger.info(msg))
        extensions = self._settings.get("image", {}).get(
            "supported_formats", [".jpg", ".jpeg", ".png"]
        )
        image_files = get_image_files(input_dir, extensions)
        if not image_files:
            _log(f"처리할 이미지가 없습니다: {input_dir}", "warn")
            return []

        total = len(image_files)
        _log(f"━━━ 포토룸 통합 배치 시작: {total}개 이미지 ━━━")
        results = []
        for idx, img_path in enumerate(image_files, 1):
            if is_cancelled and is_cancelled():
                _log("작업이 중지되었습니다.", "warn")
                break
            fname = Path(img_path).name
            _log(f"-- [{idx}/{total}] {fname} --")
            if on_progress:
                on_progress(idx, total)
            result = self.process_single_unified_photoroom(
                image_path=img_path, output_dir=output_dir,
                shadow_mode=shadow_mode, bg_color=bg_color,
                shadow_opacity=shadow_opacity, on_log=on_log, idx=idx,
            )
            results.append(result)

        success_count = sum(1 for r in results if r.get("success"))
        _log(f"━━━ 포토룸 통합 배치 완료: 성공 {success_count}/{len(results)} ━━━", "success")
        return results

    def process_batch(self, input_dir: str, category: str, output_dir: str,
                      skip_analysis: bool = False, skip_photoroom: bool = False,
                      pre_cropped: bool = False,
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
                    skip_photoroom=skip_photoroom, pre_cropped=pre_cropped,
                    on_log=on_log,
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
