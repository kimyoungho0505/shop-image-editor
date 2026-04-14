"""쇼핑몰 이미지 자동 편집 도구 - CLI 진입점."""
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from loguru import logger

# .env 파일 로드
env_path = Path(__file__).parent / ".env"
load_dotenv(str(env_path))

from src.pipeline import ImageEditPipeline
from src.utils.logger import setup_logger
from src.utils.category import CategoryManager


def _get_categories() -> list:
    """사용 가능한 카테고리 목록을 반환한다."""
    try:
        mgr = CategoryManager()
        return mgr.list_categories()
    except Exception:
        return []


@click.group()
@click.option("--debug", is_flag=True, help="디버그 모드 활성화")
def cli(debug):
    """쇼핑몰 판매용 이미지 자동 편집 도구.

    Claude Vision API를 활용한 이미지 품질 분석 및 자동 편집.
    """
    level = "DEBUG" if debug else "INFO"
    setup_logger(level=level, log_file="logs/editor.log")


@cli.command()
@click.option(
    "--input", "-i", "input_path", required=True,
    help="입력 이미지 파일 또는 디렉토리 경로",
)
@click.option(
    "--category", "-c", required=True,
    help="상품 카테고리 (accessories, wallet, kids_nukki, clothing, "
         "clothing_model, shoes, belt 등)",
)
@click.option(
    "--output", "-o", "output_dir", default="output/",
    help="출력 디렉토리 (기본: output/)",
)
@click.option(
    "--skip-analysis", is_flag=True,
    help="Claude API 분석 생략 (편집 없이 규격 변환만)",
)
@click.option(
    "--skip-photoroom", is_flag=True,
    help="Photoroom 처리 생략",
)
@click.option(
    "--base-name", default=None,
    help="출력 파일 기본 번호 (예: 100)",
)
def process(input_path, category, output_dir, skip_analysis, skip_photoroom, base_name):
    """단일 이미지 또는 디렉토리를 처리한다.

    예시:
      python main.py process --input "test sample/model_1" --category clothing_model --output output/
    """
    _validate_category(category)
    pipeline = ImageEditPipeline()

    input_p = Path(input_path)
    if input_p.is_dir():
        # 디렉토리면 첫 번째 이미지만 처리
        from src.utils.image_io import get_image_files
        files = get_image_files(str(input_p))
        if not files:
            logger.error(f"이미지를 찾을 수 없습니다: {input_path}")
            sys.exit(1)
        image_path = files[0]
        logger.info(f"디렉토리에서 첫 번째 이미지 선택: {image_path}")
    else:
        image_path = str(input_p)

    try:
        result = pipeline.process_single(
            image_path=image_path,
            category=category,
            output_dir=output_dir,
            base_name=base_name,
            skip_analysis=skip_analysis,
            skip_photoroom=skip_photoroom,
        )
        _print_result(result)
    except Exception as e:
        logger.error(f"처리 실패: {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--input", "-i", "input_path", required=True,
    help="분석할 이미지 파일 경로",
)
@click.option(
    "--category", "-c", required=True,
    help="상품 카테고리",
)
def analyze(input_path, category):
    """이미지를 분석만 한다 (편집 없이).

    Claude Vision API로 이미지 품질을 분석하고 편집 지시를 출력한다.

    예시:
      python main.py analyze --input image.jpg --category clothing_model
    """
    _validate_category(category)
    pipeline = ImageEditPipeline()

    try:
        instruction = pipeline.analyze_only(input_path, category)
        click.echo("\n" + "=" * 60)
        click.echo("  이미지 분석 결과")
        click.echo("=" * 60)
        click.echo(f"  이미지 유형: {instruction.image_type}")
        click.echo(f"  배경 상태:   {instruction.background}")
        click.echo(f"  카테고리:    {instruction.detected_category} ({instruction.detected_category_display})")
        click.echo(f"  피사체 위치: {instruction.subject_position}")
        click.echo(f"  확신도:      {instruction.confidence:.2f}")
        click.echo(f"  디테일 컷:   {'예' if instruction.is_detail_cut else '아니오'}")
        click.echo(f"  비고:        {instruction.notes}")
        click.echo("=" * 60)
    except Exception as e:
        logger.error(f"분석 실패: {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--input", "-i", "input_dir", required=True,
    help="입력 디렉토리 경로",
)
@click.option(
    "--category", "-c", required=True,
    help="상품 카테고리",
)
@click.option(
    "--output", "-o", "output_dir", default="output/",
    help="출력 디렉토리 (기본: output/)",
)
@click.option(
    "--skip-analysis", is_flag=True,
    help="Claude API 분석 생략",
)
@click.option(
    "--skip-photoroom", is_flag=True,
    help="Photoroom 처리 생략",
)
def batch(input_dir, category, output_dir, skip_analysis, skip_photoroom):
    """디렉토리 내 모든 이미지를 배치 처리한다.

    예시:
      python main.py batch --input "test sample" --category clothing_model
    """
    _validate_category(category)
    pipeline = ImageEditPipeline()

    try:
        results = pipeline.process_batch(
            input_dir=input_dir,
            category=category,
            output_dir=output_dir,
            skip_analysis=skip_analysis,
            skip_photoroom=skip_photoroom,
        )
        _print_batch_results(results)
    except Exception as e:
        logger.error(f"배치 처리 실패: {e}")
        sys.exit(1)


@cli.command("categories")
def list_categories():
    """사용 가능한 카테고리 목록을 출력한다."""
    mgr = CategoryManager()
    categories = mgr.list_categories()

    click.echo("\n사용 가능한 카테고리:")
    click.echo("-" * 40)
    for cat in categories:
        display = mgr.get_display_name(cat)
        padding = mgr.get_padding(cat)
        click.echo(f"  {cat:25s} ({display})")
        click.echo(f"    860px 여백: 상{padding['top']} 하{padding['bottom']} "
                    f"좌{padding['left']} 우{padding['right']}")
    click.echo()


def _validate_category(category: str) -> None:
    """카테고리 유효성을 확인한다."""
    valid = _get_categories()
    if valid and category not in valid:
        logger.warning(
            f"알 수 없는 카테고리 '{category}'. "
            f"사용 가능: {', '.join(valid)}. 기본 여백을 적용합니다."
        )


def _print_result(result: dict) -> None:
    """처리 결과를 출력한다."""
    click.echo("\n" + "=" * 60)
    click.echo("  처리 완료")
    click.echo("=" * 60)

    instruction = result.get("instruction")
    if instruction:
        click.echo(f"  분석: {instruction.summary()}")

    files = result.get("files", [])
    click.echo(f"\n  생성된 파일 ({len(files)}개):")
    for f in files:
        click.echo(f"    - {f['path']} ({f['size_kb']}KB, Q={f['quality']})")
    click.echo("=" * 60)


def _print_batch_results(results: list) -> None:
    """배치 처리 결과를 출력한다."""
    click.echo("\n" + "=" * 60)
    click.echo("  배치 처리 결과")
    click.echo("=" * 60)

    success = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]

    click.echo(f"  전체: {len(results)}개 | 성공: {len(success)}개 | 실패: {len(failed)}개")

    if failed:
        click.echo("\n  실패 목록:")
        for r in failed:
            click.echo(f"    - {r['path']}: {r.get('error', 'unknown')}")

    total_files = sum(len(r.get("files", [])) for r in success)
    click.echo(f"\n  총 생성 파일: {total_files}개")
    click.echo("=" * 60)


if __name__ == "__main__":
    cli()
