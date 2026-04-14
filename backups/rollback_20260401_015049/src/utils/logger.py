"""로깅 설정 모듈."""
import sys
from pathlib import Path
from loguru import logger


def setup_logger(level: str = "INFO", log_file: str = None) -> None:
    """loguru 기반 로거를 설정한다.

    Args:
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
        log_file: 로그 파일 경로. None이면 콘솔만 출력.
    """
    logger.remove()

    # 콘솔 출력
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
    )

    # 파일 출력
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_path),
            level=level,
            rotation="10 MB",
            retention="7 days",
            encoding="utf-8",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
                   "{name}:{function}:{line} - {message}",
        )

    logger.info(f"Logger initialized (level={level})")
