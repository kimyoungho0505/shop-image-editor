"""이미지 입출력 유틸리티."""
import base64
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from loguru import logger


def load_image(path: str) -> np.ndarray:
    """이미지를 BGR numpy 배열로 로드한다.

    Args:
        path: 이미지 파일 경로

    Returns:
        BGR numpy 배열

    Raises:
        FileNotFoundError: 파일이 존재하지 않을 때
        ValueError: 이미지 로드 실패 시
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {path}")

    # 한글 경로 지원을 위해 numpy로 읽기
    img_array = np.fromfile(str(file_path), dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_UNCHANGED)

    if img is None:
        raise ValueError(f"이미지를 로드할 수 없습니다: {path}")

    logger.debug(f"이미지 로드: {path} ({img.shape})")
    return img


def load_image_rgba(path: str) -> np.ndarray:
    """이미지를 BGRA numpy 배열로 로드한다. 알파 채널이 없으면 추가."""
    img = load_image(path)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def save_image(img: np.ndarray, path: str, quality: int = 95) -> None:
    """이미지를 파일로 저장한다.

    Args:
        img: numpy 배열 이미지
        path: 저장 경로
        quality: JPEG 품질 (1-100)
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    ext = file_path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    elif ext == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
    elif ext == ".webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, quality]
    else:
        params = []

    # 한글 경로 지원
    success, encoded = cv2.imencode(ext, img, params)
    if not success:
        raise ValueError(f"이미지 인코딩 실패: {path}")

    encoded.tofile(str(file_path))
    logger.debug(f"이미지 저장: {path}")


def to_base64(img: np.ndarray, fmt: str = ".jpg", max_size: int = 1568) -> str:
    """numpy 이미지를 base64 문자열로 변환한다.

    대용량 이미지는 API 전송 비용/시간 절약을 위해 max_size로 리사이즈 후 인코딩한다.

    Args:
        img: numpy 배열 이미지
        fmt: 인코딩 포맷 (.jpg, .png)
        max_size: 최대 변 길이 (px). 이를 초과하면 비율 유지하며 축소.

    Returns:
        base64 인코딩된 문자열
    """
    # 대용량 이미지 리사이즈
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        logger.debug(f"API 전송용 리사이즈: {w}x{h} -> {new_w}x{new_h}")

    if fmt in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, 90]
    else:
        params = []

    success, buffer = cv2.imencode(fmt, img, params)
    if not success:
        raise ValueError("이미지 base64 인코딩 실패")

    return base64.b64encode(buffer).decode("utf-8")


def from_base64(b64_str: str) -> np.ndarray:
    """base64 문자열을 numpy 이미지로 변환한다."""
    img_bytes = base64.b64decode(b64_str)
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("base64 이미지 디코딩 실패")
    return img


def get_image_files(directory: str, extensions: list = None) -> list:
    """디렉토리에서 이미지 파일 목록을 반환한다.

    Args:
        directory: 검색할 디렉토리 경로
        extensions: 허용할 확장자 목록

    Returns:
        이미지 파일 경로 리스트
    """
    if extensions is None:
        extensions = [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"]

    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise FileNotFoundError(f"디렉토리를 찾을 수 없습니다: {directory}")

    files = []
    for ext in extensions:
        files.extend(dir_path.glob(f"*{ext}"))
        files.extend(dir_path.glob(f"*{ext.upper()}"))

    # 자연수 정렬 (1.jpg, 2.jpg, ..., 10.jpg, 20.jpg 순서)
    import re as _re
    def _natural_key(name: str):
        return [int(s) if s.isdigit() else s.lower()
                for s in _re.split(r"(\d+)", name)]
    files = sorted(set(files), key=lambda f: _natural_key(f.name))
    logger.info(f"디렉토리 '{directory}'에서 이미지 {len(files)}개 발견")
    return [str(f) for f in files]
