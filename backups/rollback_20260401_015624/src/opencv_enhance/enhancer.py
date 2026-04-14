"""OpenCV/Pillow 기반 로컬 이미지 보정 모듈. Claid.ai 대체."""
import io
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageEnhance
from loguru import logger


class OpenCVEnhancer:
    """로컬 OpenCV/Pillow 처리로 이미지를 보정한다. ClaidClient와 동일 인터페이스."""

    def process(self, image_bytes: bytes, image_type: str,
                config: Optional[dict] = None,
                width: int = 1000, height: int = 1000) -> bytes:
        if config is None:
            config = {}

        hdr = config.get("hdr", 20)
        sharpness = config.get("sharpness", 15)
        exposure = config.get("exposure", 0)
        saturation = config.get("saturation", 0)
        contrast = config.get("contrast", 0)

        logger.info(
            f"OpenCV 보정 시작 (유형: {image_type}, "
            f"hdr={hdr}, sharpness={sharpness}, exposure={exposure}, "
            f"saturation={saturation}, contrast={contrast})"
        )

        img_format = self._detect_format(image_bytes)
        img = self._bytes_to_cv2(image_bytes)

        # 처리 순서: HDR -> Exposure -> Contrast -> Saturation -> Sharpness
        img = self._apply_hdr(img, hdr)
        img = self._apply_exposure(img, exposure)
        img = self._apply_contrast(img, contrast)
        img = self._apply_saturation(img, saturation)
        img = self._apply_sharpness(img, sharpness)

        result = self._cv2_to_bytes(img, img_format)
        logger.info(f"OpenCV 보정 완료 ({len(result)} bytes, format={img_format})")
        return result

    def _detect_format(self, image_bytes: bytes) -> str:
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return "PNG"
        if image_bytes[:2] == b'\xff\xd8':
            return "JPEG"
        if image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
            return "WEBP"
        return "PNG"

    def _bytes_to_cv2(self, image_bytes: bytes) -> np.ndarray:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError("이미지 디코딩 실패")
        return img

    def _cv2_to_bytes(self, img: np.ndarray, fmt: str) -> bytes:
        if fmt == "PNG":
            _, buf = cv2.imencode(".png", img)
        elif fmt == "WEBP":
            _, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 95])
        else:
            _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return buf.tobytes()

    def _apply_hdr(self, img: np.ndarray, value: int) -> np.ndarray:
        """CLAHE 기반 HDR. value 0-100 -> clipLimit 1.0-4.0."""
        if value <= 0:
            return img

        clip_limit = 1.0 + (value / 100.0) * 3.0

        has_alpha = img.shape[2] == 4 if len(img.shape) == 3 else False
        if has_alpha:
            bgr = img[:, :, :3]
            alpha = img[:, :, 3]
        else:
            bgr = img

        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        l_ch = clahe.apply(l_ch)

        lab = cv2.merge([l_ch, a_ch, b_ch])
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

        if has_alpha:
            return np.dstack([bgr, alpha])
        return bgr

    def _apply_exposure(self, img: np.ndarray, value: int) -> np.ndarray:
        """LAB L채널 밝기 조정. value -100~100, 0=변경없음."""
        offset = value * 0.3  # -100→-30, 100→+30
        if abs(offset) < 0.5:
            return img

        has_alpha = img.shape[2] == 4 if len(img.shape) == 3 else False
        if has_alpha:
            bgr = img[:, :, :3]
            alpha = img[:, :, 3]
        else:
            bgr = img

        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)

        l_float = l_ch.astype(np.float32) + offset
        l_ch = np.clip(l_float, 0, 255).astype(np.uint8)

        lab = cv2.merge([l_ch, a_ch, b_ch])
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

        if has_alpha:
            return np.dstack([bgr, alpha])
        return bgr

    def _apply_contrast(self, img: np.ndarray, value: int) -> np.ndarray:
        """PIL Contrast. value -100~100, 0=변경없음. 양수=강화, 음수=감소."""
        factor = 1.0 + value / 100.0 * 0.5  # -100→0.5, 0→1.0, 100→1.5
        if abs(factor - 1.0) < 0.01:
            return img

        has_alpha = img.shape[2] == 4 if len(img.shape) == 3 else False
        if has_alpha:
            bgr = img[:, :, :3]
            alpha = img[:, :, 3]
        else:
            bgr = img

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        pil_img = ImageEnhance.Contrast(pil_img).enhance(factor)
        bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        if has_alpha:
            return np.dstack([bgr, alpha])
        return bgr

    def _apply_saturation(self, img: np.ndarray, value: int) -> np.ndarray:
        """HSV S채널 스케일링. value -100~100, 0=변경없음. 양수=강화, 음수=감소."""
        scale = 1.0 + value / 100.0 * 0.5  # -100→0.5, 0→1.0, 100→1.5
        if abs(scale - 1.0) < 0.01:
            return img

        has_alpha = img.shape[2] == 4 if len(img.shape) == 3 else False
        if has_alpha:
            bgr = img[:, :, :3]
            alpha = img[:, :, 3]
        else:
            bgr = img

        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)

        s_float = s.astype(np.float32) * scale
        s = np.clip(s_float, 0, 255).astype(np.uint8)

        hsv = cv2.merge([h, s, v])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        if has_alpha:
            return np.dstack([bgr, alpha])
        return bgr

    def _apply_sharpness(self, img: np.ndarray, value: int) -> np.ndarray:
        """Unsharp Mask. value 0-100 -> amount 0.0-2.0."""
        amount = (value / 100.0) * 2.0
        if amount < 0.01:
            return img

        has_alpha = img.shape[2] == 4 if len(img.shape) == 3 else False
        if has_alpha:
            bgr = img[:, :, :3]
            alpha = img[:, :, 3]
        else:
            bgr = img

        blurred = cv2.GaussianBlur(bgr, (0, 0), sigmaX=3)
        sharpened = cv2.addWeighted(bgr, 1.0 + amount, blurred, -amount, 0)

        if has_alpha:
            return np.dstack([sharpened, alpha])
        return sharpened
