"""회의 영상 MP4 생성 모듈 — 만화/비주얼 노벨 스타일."""
import os
import tempfile
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# 색상 팔레트 (RGB)
COLORS = {
    "bg": (17, 17, 27),
    "card_bg": (30, 30, 46),
    "text": (205, 214, 244),
    "claude": (166, 227, 161),
    "chatgpt": (137, 180, 250),
    "gemini": (250, 179, 135),
    "mc": (245, 224, 220),
    "phase": (245, 194, 231),
    "separator": (69, 71, 90),
    "score": (249, 226, 175),
    "header_bg": (24, 24, 37),
    "bubble_bg": (40, 40, 58),
    "white": (255, 255, 255),
}

PHASE_NAMES = ["1.발의", "2.검토", "3.문제", "4.해결", "5.토론", "6.결정"]


def export_deliberation_video(
    frames: list,
    output_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    seconds_per_frame: float = 3.0,
    audio_segments: list = None,
):
    """회의 프레임 데이터를 만화 스타일 MP4 영상으로 내보내기."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.error("Pillow 미설치")
        return None

    try:
        from moviepy import ImageSequenceClip
        HAS_MOVIEPY = True
    except ImportError:
        try:
            from moviepy.editor import ImageSequenceClip
            HAS_MOVIEPY = True
        except ImportError:
            HAS_MOVIEPY = False

    if not frames:
        return None

    from src.video.avatars import generate_avatar

    # 폰트
    font_path = _find_korean_font()
    try:
        font_title = ImageFont.truetype(font_path, 26) if font_path else ImageFont.load_default()
        font_name = ImageFont.truetype(font_path, 22) if font_path else ImageFont.load_default()
        font_body = ImageFont.truetype(font_path, 18) if font_path else ImageFont.load_default()
        font_small = ImageFont.truetype(font_path, 14) if font_path else ImageFont.load_default()
    except Exception:
        font_title = font_name = font_body = font_small = ImageFont.load_default()

    # 아바타 미리 생성 (크기별)
    avatar_large = {}
    avatar_small = {}
    for p in ("claude", "chatgpt", "gemini", "mc"):
        avatar_large[p] = generate_avatar(p, 160)
        avatar_small[p] = generate_avatar(p, 50)

    temp_dir = tempfile.mkdtemp(prefix="delib_video_")
    img_frames = []
    history = []

    for fi, frame in enumerate(frames):
        provider = frame.get("provider", "mc")
        name = frame.get("name", "???")
        text = frame.get("text", "")
        ts = frame.get("timestamp", "")
        phase_num = frame.get("phase", 0)
        color = COLORS.get(provider, COLORS["text"])

        history.append(frame)

        img = Image.new("RGB", (width, height), COLORS["bg"])
        d = ImageDraw.Draw(img)

        # ── 상단: 단계 진행 바 ──
        bar_h = 45
        d.rectangle([(0, 0), (width, bar_h)], fill=COLORS["header_bg"])
        d.text((15, 10), "AI 패널 회의", fill=COLORS["phase"], font=font_title)

        # 단계 표시
        px = width - 680
        for pi, pname in enumerate(PHASE_NAMES):
            p = pi + 1
            if p < phase_num:
                pc = COLORS["claude"]
                # 완료 표시
                d.rounded_rectangle([px-2, 8, px+75, 36], radius=5, fill=(26,46,26))
            elif p == phase_num:
                pc = COLORS["bg"]
                d.rounded_rectangle([px-2, 8, px+75, 36], radius=5, fill=COLORS["phase"])
            else:
                pc = COLORS["separator"]
            d.text((px+5, 11), pname, fill=pc, font=font_small)
            px += 82

        # ── 좌우 배치 결정 (홀수=왼쪽, 짝수=오른쪽) ──
        is_left = (fi % 2 == 0)

        # ── 발언자 아바타 (큰 이미지) ──
        avatar_img = avatar_large.get(provider, avatar_large["mc"])
        avatar_y = bar_h + 30
        if is_left:
            avatar_x = 40
            bubble_x = 220
            bubble_w = width - 260
        else:
            avatar_x = width - 200
            bubble_x = 30
            bubble_w = width - 260

        # 아바타 배경 글로우
        glow_r = 90
        glow_cx = avatar_x + 80
        glow_cy = avatar_y + 80
        for gr in range(glow_r, 0, -3):
            alpha_ratio = gr / glow_r
            glow_color = tuple(int(c * (1 - alpha_ratio) * 0.3) for c in color)
            d.ellipse([glow_cx-gr, glow_cy-gr, glow_cx+gr, glow_cy+gr],
                      fill=tuple(max(0, COLORS["bg"][i] + glow_color[i]) for i in range(3)))

        img.paste(avatar_img, (avatar_x, avatar_y), avatar_img)

        # 이름표
        name_x = avatar_x
        name_y = avatar_y + 170
        d.rounded_rectangle([name_x, name_y, name_x+160, name_y+30],
                             radius=5, fill=COLORS["card_bg"], outline=color, width=2)
        # 이름 가운데 정렬
        try:
            bbox = font_name.getbbox(name)
            nw = bbox[2] - bbox[0]
        except:
            nw = len(name) * 14
        d.text((name_x + (160 - nw) // 2, name_y + 3), name, fill=color, font=font_name)

        # ── 말풍선 ──
        bubble_y = bar_h + 40
        bubble_h = 200
        _draw_speech_bubble(d, bubble_x, bubble_y, bubble_w, bubble_h,
                            color, tail_side="left" if not is_left else "right")

        # 말풍선 안 텍스트
        text_x = bubble_x + 25
        text_y = bubble_y + 20
        text_max_w = bubble_w - 50
        _draw_wrapped_text(d, text, text_x, text_y, text_max_w,
                           font_body, COLORS["text"], line_height=26, max_lines=6)

        # 타임스탬프
        d.text((bubble_x + bubble_w - 80, bubble_y + bubble_h - 30),
               ts, fill=COLORS["separator"], font=font_small)

        # ── 하단: 다른 참가자 미니 아바타 + 최근 대화 ──
        bottom_y = height - 180
        d.rectangle([(0, bottom_y - 10), (width, height)], fill=COLORS["header_bg"])
        d.line([(0, bottom_y - 10), (width, bottom_y - 10)], fill=COLORS["separator"], width=1)

        # 미니 아바타 패널
        others = [p for p in ("claude", "chatgpt", "gemini", "mc") if p != provider]
        mini_x = 20
        for op in others:
            mini_avatar = avatar_small.get(op, avatar_small["mc"])
            img.paste(mini_avatar, (mini_x, bottom_y), mini_avatar)
            mini_x += 60

        # 최근 대화 히스토리 (작은 글씨)
        hist_x = mini_x + 20
        hist_y = bottom_y + 5
        recent = history[max(0, len(history) - 4):-1]
        for h in recent:
            hp = h.get("provider", "mc")
            hn = h.get("name", "")
            ht = h.get("text", "")
            hc = COLORS.get(hp, COLORS["text"])
            short = ht[:50] + "..." if len(ht) > 50 else ht
            d.text((hist_x, hist_y), f"{hn}: ", fill=hc, font=font_small)
            try:
                nw = font_small.getbbox(f"{hn}: ")[2]
            except:
                nw = len(hn) * 8 + 16
            d.text((hist_x + nw, hist_y), short, fill=COLORS["separator"], font=font_small)
            hist_y += 22
            if hist_y > height - 20:
                break

        # 워터마크
        d.text((width - 220, height - 20), "LUXBOY AI Deliberation",
               fill=COLORS["separator"], font=font_small)

        # 프레임 저장
        frame_path = os.path.join(temp_dir, f"frame_{fi:04d}.png")
        img.save(frame_path, "PNG")
        img_frames.append(frame_path)

    if not img_frames:
        return None

    # MP4 생성
    if HAS_MOVIEPY:
        try:
            clip = ImageSequenceClip(img_frames, durations=[seconds_per_frame] * len(img_frames))
            clip.write_videofile(output_path, fps=fps, codec="libx264",
                                audio=False, logger=None)
            clip.close()
            logger.info(f"회의 영상 저장: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"MoviePy 실패: {e}")
            return _export_with_ffmpeg(img_frames, output_path, fps, seconds_per_frame, temp_dir)
    else:
        return _export_with_ffmpeg(img_frames, output_path, fps, seconds_per_frame, temp_dir)


def _draw_speech_bubble(d, x, y, w, h, color, tail_side="left"):
    """말풍선 그리기."""
    # 메인 버블
    radius = 15
    bg = COLORS["bubble_bg"]
    border = color

    d.rounded_rectangle([x, y, x+w, y+h], radius=radius,
                         fill=bg, outline=border, width=2)

    # 꼬리 삼각형
    tail_h = 20
    if tail_side == "left":
        tx = x + 30
        pts = [(tx, y+h), (tx+15, y+h), (tx-10, y+h+tail_h)]
    else:
        tx = x + w - 30
        pts = [(tx, y+h), (tx-15, y+h), (tx+10, y+h+tail_h)]
    d.polygon(pts, fill=bg, outline=border)
    # 꼬리 윗부분 경계 지우기
    d.line([(pts[0][0]+1, pts[0][1]-1), (pts[1][0]-1, pts[1][1]-1)],
           fill=bg, width=3)


def _draw_wrapped_text(d, text, x, y, max_width, font, color,
                       line_height=22, max_lines=6):
    """자동 줄바꿈 텍스트."""
    line = ""
    cy = y
    lines_drawn = 0

    for char in text:
        test = line + char
        try:
            tw = font.getbbox(test)[2] - font.getbbox(test)[0]
        except:
            tw = len(test) * 12
        if tw > max_width and line:
            d.text((x, cy), line, fill=color, font=font)
            cy += line_height
            line = char
            lines_drawn += 1
            if lines_drawn >= max_lines - 1:
                d.text((x, cy), line + "...", fill=color, font=font)
                return
        else:
            line = test
    if line:
        d.text((x, cy), line, fill=color, font=font)


def _export_with_ffmpeg(img_frames, output_path, fps, seconds_per_frame, temp_dir):
    """FFmpeg fallback."""
    import subprocess, shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        logger.error("ffmpeg 미설치. pip install moviepy 또는 ffmpeg 설치 필요")
        return None
    try:
        list_path = os.path.join(temp_dir, "frames.txt")
        with open(list_path, "w") as f:
            for fp in img_frames:
                f.write(f"file '{fp}'\n")
                f.write(f"duration {seconds_per_frame}\n")
            f.write(f"file '{img_frames[-1]}'\n")
        cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0",
               "-i", list_path, "-vsync", "vfr", "-pix_fmt", "yuv420p",
               "-c:v", "libx264", "-crf", "23", output_path]
        subprocess.run(cmd, capture_output=True, timeout=120)
        if os.path.exists(output_path):
            return output_path
    except Exception as e:
        logger.error(f"FFmpeg 실패: {e}")
    return None


def _find_korean_font():
    """한국어 폰트 경로 탐색."""
    import platform
    if platform.system() == "Windows":
        candidates = [
            "C:/Windows/Fonts/malgun.ttf",
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
