"""회의 영상 MP4 생성 모듈."""
import os
import tempfile
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# 색상 팔레트 (RGB)
COLORS = {
    "bg": (17, 17, 27),           # #11111b
    "card_bg": (30, 30, 46),      # #1e1e2e
    "text": (205, 214, 244),      # #cdd6f4
    "claude": (166, 227, 161),    # #a6e3a1
    "chatgpt": (137, 180, 250),   # #89b4fa
    "gemini": (250, 179, 135),    # #fab387
    "mc": (245, 224, 220),        # #f5e0dc
    "phase": (245, 194, 231),     # #f5c2e7
    "separator": (69, 71, 90),    # #45475a
    "score": (249, 226, 175),     # #f9e2af
    "header_bg": (24, 24, 37),    # #181825
}

# 아바타 이모지
AVATARS = {
    "claude": "🟢",
    "chatgpt": "🔵",
    "gemini": "🟠",
    "mc": "🎙",
}


def export_deliberation_video(
    frames: list,
    output_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    seconds_per_frame: float = 3.0,
    audio_segments: list = None,
):
    """
    회의 프레임 데이터를 MP4 영상으로 내보내기.

    Args:
        frames: list of dict with keys: provider, name, text, timestamp, phase
        output_path: 출력 MP4 경로
        width, height: 영상 해상도
        fps: 프레임 레이트
        seconds_per_frame: 각 발언이 표시되는 시간(초)
        audio_segments: (선택) 오디오 파일 경로 리스트
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.error("Pillow 미설치. pip install Pillow")
        return None

    try:
        # MoviePy v2
        from moviepy import ImageSequenceClip
        HAS_MOVIEPY = True
    except ImportError:
        try:
            # MoviePy v1
            from moviepy.editor import ImageSequenceClip
            HAS_MOVIEPY = True
        except ImportError:
            HAS_MOVIEPY = False

    if not frames:
        logger.warning("녹화 프레임이 없습니다.")
        return None

    # 폰트 설정
    font_path = _find_korean_font()
    try:
        font_title = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
        font_name = ImageFont.truetype(font_path, 22) if font_path else ImageFont.load_default()
        font_body = ImageFont.truetype(font_path, 18) if font_path else ImageFont.load_default()
        font_meta = ImageFont.truetype(font_path, 14) if font_path else ImageFont.load_default()
    except Exception:
        font_title = font_name = font_body = font_meta = ImageFont.load_default()

    # 이미지 프레임 생성
    img_frames = []
    temp_dir = tempfile.mkdtemp(prefix="delib_video_")
    history = []  # 누적 대화 히스토리

    for fi, frame in enumerate(frames):
        provider = frame.get("provider", "mc")
        name = frame.get("name", "???")
        text = frame.get("text", "")
        ts = frame.get("timestamp", "")
        phase_num = frame.get("phase", 0)

        color = COLORS.get(provider, COLORS["text"])
        avatar = AVATARS.get(provider, "⚪")

        # 히스토리에 추가
        history.append(frame)

        # 이미지 생성
        img = Image.new("RGB", (width, height), COLORS["bg"])
        draw = ImageDraw.Draw(img)

        # 상단 헤더 바
        draw.rectangle([(0, 0), (width, 55)], fill=COLORS["header_bg"])
        draw.text((20, 12), "AI 패널 회의", fill=COLORS["phase"], font=font_title)
        if phase_num > 0:
            phase_text = f"{phase_num}단계 진행 중"
            draw.text((width - 200, 18), phase_text, fill=COLORS["score"], font=font_name)

        # 단계 진행 바
        phase_names = ["1.발의", "2.검토", "3.문제", "4.해결", "5.토론", "6.결정"]
        bar_y = 60
        draw.rectangle([(0, bar_y), (width, bar_y + 30)], fill=COLORS["header_bg"])
        px = 20
        for pi, pname in enumerate(phase_names):
            p = pi + 1
            if p < phase_num:
                pc = COLORS["claude"]  # 완료 = 녹색
            elif p == phase_num:
                pc = COLORS["phase"]   # 현재 = 핑크
            else:
                pc = COLORS["separator"]  # 미도달
            draw.text((px, bar_y + 5), pname, fill=pc, font=font_meta)
            px += 110

        # 현재 발언자 강조 영역
        y = 100
        # 발언자 라인
        draw.rectangle([(15, y), (width - 15, y + 80)], fill=COLORS["card_bg"], outline=COLORS["separator"])
        # 아바타 + 이름
        draw.text((25, y + 8), avatar, fill=color, font=font_name)
        draw.text((55, y + 8), name, fill=color, font=font_name)
        draw.text((55, y + 35), ts, fill=COLORS["separator"], font=font_meta)
        # 현재 발언 텍스트 (자동 줄바꿈)
        _draw_wrapped_text(draw, text, 25, y + 55, width - 50, font_body, color, line_height=24)

        # 이전 대화 히스토리 (아래로 나열)
        hist_y = y + 160
        visible_history = history[max(0, len(history) - 6):-1]  # 최근 5개 (현재 제외)
        for h in reversed(visible_history):
            if hist_y + 60 > height - 30:
                break
            hp = h.get("provider", "mc")
            hc = COLORS.get(hp, COLORS["text"])
            hn = h.get("name", "")
            ht = h.get("text", "")
            ha = AVATARS.get(hp, "⚪")

            # 이전 발언 (더 작게, 어둡게)
            dimmed = tuple(max(0, c - 40) for c in hc)
            draw.text((25, hist_y), f"{ha} {hn}", fill=dimmed, font=font_meta)
            # 텍스트 1줄로 축약
            short = ht[:80] + "..." if len(ht) > 80 else ht
            draw.text((25, hist_y + 18), f'"{short}"', fill=COLORS["separator"], font=font_meta)
            hist_y += 45

        # 하단 워터마크
        draw.text((20, height - 25), "LUXBOY AI Deliberation",
                   fill=COLORS["separator"], font=font_meta)

        # 프레임 저장
        frame_path = os.path.join(temp_dir, f"frame_{fi:04d}.png")
        img.save(frame_path, "PNG")
        img_frames.append(frame_path)

    if not img_frames:
        return None

    # MP4 생성
    if HAS_MOVIEPY:
        try:
            # 각 프레임을 seconds_per_frame초 동안 표시
            durations = [seconds_per_frame] * len(img_frames)
            clip = ImageSequenceClip(img_frames, durations=durations)
            clip.write_videofile(output_path, fps=fps, codec="libx264",
                                audio=False, logger=None)
            clip.close()
            logger.info(f"회의 영상 저장: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"MoviePy 영상 생성 실패: {e}")
            # fallback to ffmpeg
            return _export_with_ffmpeg(img_frames, output_path, fps, seconds_per_frame, temp_dir)
    else:
        # MoviePy 없으면 ffmpeg 시도
        return _export_with_ffmpeg(img_frames, output_path, fps, seconds_per_frame, temp_dir)


def _export_with_ffmpeg(img_frames, output_path, fps, seconds_per_frame, temp_dir):
    """FFmpeg 기반 영상 생성 (fallback)."""
    import subprocess
    import shutil

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        logger.error("ffmpeg 미설치. pip install moviepy 또는 ffmpeg 설치 필요")
        return None

    try:
        # FFmpeg concat demuxer용 파일 리스트
        list_path = os.path.join(temp_dir, "frames.txt")
        with open(list_path, "w") as f:
            for fp in img_frames:
                f.write(f"file '{fp}'\n")
                f.write(f"duration {seconds_per_frame}\n")
            # 마지막 프레임 반복 (FFmpeg concat 요구사항)
            f.write(f"file '{img_frames[-1]}'\n")

        cmd = [
            ffmpeg_path, "-y", "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-vsync", "vfr", "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-crf", "23",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, timeout=120)
        if os.path.exists(output_path):
            logger.info(f"FFmpeg 영상 저장: {output_path}")
            return output_path
    except Exception as e:
        logger.error(f"FFmpeg 영상 생성 실패: {e}")

    return None


def _draw_wrapped_text(draw, text, x, y, max_width, font, color, line_height=20):
    """자동 줄바꿈 텍스트 그리기."""
    words = text
    line = ""
    cy = y
    max_lines = 4  # 최대 4줄

    for char in words:
        test = line + char
        try:
            bbox = font.getbbox(test)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(test) * 12
        if tw > max_width and line:
            draw.text((x, cy), line, fill=color, font=font)
            cy += line_height
            line = char
            max_lines -= 1
            if max_lines <= 0:
                draw.text((x, cy), line + "...", fill=color, font=font)
                return
        else:
            line = test

    if line:
        draw.text((x, cy), line, fill=color, font=font)


def _find_korean_font():
    """시스템에서 한국어 폰트 경로 탐색."""
    import platform
    if platform.system() == "Windows":
        candidates = [
            "C:/Windows/Fonts/malgun.ttf",      # 맑은 고딕
            "C:/Windows/Fonts/NanumGothic.ttf",
            "C:/Windows/Fonts/gulim.ttc",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/System/Library/Fonts/AppleGothic.ttf",
        ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None
