"""이미지 최적화 모듈 - 파일 용량 관리."""
import cv2
import numpy as np
from loguru import logger


class ImageOptimizer:
    """JPEG 품질 조정으로 파일 용량을 제한한다."""

    def optimize_jpeg(
        self,
        img: np.ndarray,
        max_size_kb: int = 1024,
        initial_quality: int = 95,
        min_quality: int = 60,
        step: int = 5,
    ) -> tuple:
        """JPEG 품질을 조정하여 목표 용량 이하로 최적화한다.

        Args:
            img: BGR 입력 이미지
            max_size_kb: 최대 파일 크기 (KB)
            initial_quality: 초기 JPEG 품질
            min_quality: 최소 JPEG 품질
            step: 품질 감소 단위

        Returns:
            (인코딩된 바이트, 최종 품질) 튜플
        """
        quality = initial_quality

        last_encoded = None
        while quality >= min_quality:
            success, encoded = cv2.imencode(
                ".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if not success:
                raise ValueError("JPEG 인코딩 실패")

            size_kb = len(encoded) / 1024
            logger.debug(f"JPEG 품질 {quality}: {size_kb:.1f}KB")

            if size_kb <= max_size_kb:
                logger.info(
                    f"최적화 완료: 품질={quality}, 용량={size_kb:.1f}KB "
                    f"(한도={max_size_kb}KB)"
                )
                return bytes(encoded), quality

            last_encoded = encoded

            if quality == min_quality:
                break
            quality = max(quality - step, min_quality)

        # 최소 품질에서도 초과하면 그냥 반환 + 경고
        if last_encoded is None:
            # min_quality > initial_quality 등 예외 케이스
            success, last_encoded = cv2.imencode(
                ".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, min_quality]
            )
        size_kb = len(last_encoded) / 1024
        logger.warning(
            f"최소 품질({min_quality})에서도 용량 초과: {size_kb:.1f}KB > {max_size_kb}KB"
        )
        return bytes(last_encoded), min_quality

    def save_optimized(
        self,
        img: np.ndarray,
        path: str,
        max_size_kb: int = 1024,
        initial_quality: int = 95,
    ) -> dict:
        """최적화하여 파일로 저장한다.

        Args:
            img: BGR 입력 이미지
            path: 저장 경로
            max_size_kb: 최대 파일 크기 (KB)
            initial_quality: 초기 JPEG 품질

        Returns:
            {"path": str, "quality": int, "size_kb": float}
        """
        from pathlib import Path as PathLib
        file_path = PathLib(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        encoded_bytes, quality = self.optimize_jpeg(
            img, max_size_kb=max_size_kb, initial_quality=initial_quality
        )

        with open(str(file_path), "wb") as f:
            f.write(encoded_bytes)

        size_kb = len(encoded_bytes) / 1024
        logger.info(f"저장 완료: {path} (품질={quality}, {size_kb:.1f}KB)")

        return {
            "path": str(file_path),
            "quality": quality,
            "size_kb": round(size_kb, 1),
        }

    def save_from_bytes(self, image_bytes: bytes, output_path: str,
                        max_size_kb: int = 2024) -> dict:
        """API 결과 바이트를 JPEG로 최적화하여 저장한다."""
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes))
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        quality = 95
        size_kb = 0
        buffer = io.BytesIO()
        while quality >= 60:
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            size_kb = buffer.tell() / 1024
            if size_kb <= max_size_kb:
                break
            quality -= 5

        from pathlib import Path as PathLib
        file_path = PathLib(output_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'wb') as f:
            f.write(buffer.getvalue())

        size_kb = round(size_kb, 1)
        logger.info(f"저장 완료: {output_path} (품질={quality}, {size_kb}KB)")

        return {
            "path": output_path,
            "quality": quality,
            "size_kb": size_kb,
        }
