"""파일명 생성 모듈."""
from pathlib import Path
from loguru import logger


class FileNamer:
    """쇼핑몰 규칙에 맞는 파일명을 생성한다.

    규칙: {base_number}_{sequence}
    예: 100_1.jpg, 100_2.jpg, ..., 100_list.jpg
    """

    def __init__(self, base_number: str = "100"):
        """
        Args:
            base_number: 기본 번호 (예: "100")
        """
        self._base = base_number
        self._counter = 0

    def set_base(self, base_number: str) -> None:
        """기본 번호를 설정한다."""
        self._base = base_number
        self._counter = 0

    def next_name(self, ext: str = ".jpg") -> str:
        """다음 순번 파일명을 생성한다.

        Returns:
            "{base}_{counter}{ext}" 형태 파일명
        """
        self._counter += 1
        name = f"{self._base}_{self._counter}{ext}"
        logger.debug(f"파일명 생성: {name}")
        return name

    def list_name(self, ext: str = ".jpg") -> str:
        """리스트 이미지 파일명을 생성한다.

        Returns:
            "{base}_list{ext}" 형태 파일명
        """
        name = f"{self._base}_list{ext}"
        logger.debug(f"리스트 파일명 생성: {name}")
        return name

    def thumbnail_name(self, ext: str = ".jpg") -> str:
        """썸네일 파일명을 생성한다.

        Returns:
            "{base}_thumb{ext}" 형태 파일명
        """
        name = f"{self._base}_thumb{ext}"
        logger.debug(f"썸네일 파일명 생성: {name}")
        return name

    def generate_names(
        self,
        count: int,
        include_list: bool = True,
        include_thumbnail: bool = True,
        ext: str = ".jpg",
    ) -> dict:
        """전체 파일명 세트를 생성한다.

        Args:
            count: 일반 이미지 수
            include_list: 리스트 이미지 포함 여부
            include_thumbnail: 썸네일 포함 여부
            ext: 파일 확장자

        Returns:
            {"images": [...], "list": str, "thumbnail": str}
        """
        self._counter = 0
        result = {
            "images": [self.next_name(ext) for _ in range(count)],
        }
        if include_list:
            result["list"] = self.list_name(ext)
        if include_thumbnail:
            result["thumbnail"] = self.thumbnail_name(ext)

        logger.info(
            f"파일명 세트 생성: 이미지 {count}개"
            + (", 리스트 1개" if include_list else "")
            + (", 썸네일 1개" if include_thumbnail else "")
        )
        return result

    @staticmethod
    def extract_base_from_path(file_path: str) -> str:
        """파일 경로에서 기본 번호를 추출한다.

        예: "photo_001.jpg" -> "photo_001"
        """
        stem = Path(file_path).stem
        return stem
