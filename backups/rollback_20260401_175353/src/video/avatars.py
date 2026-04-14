"""AI 회의 참가자 아바타 생성 모듈 - 브랜드 로고 버전."""
import io
import math
import os

from PIL import Image, ImageDraw

CHAR_COLORS = {
    "claude": {
        "primary": (217, 119, 87),
        "dark": (164, 80, 54),
        "bg": (217, 119, 87),
        "accent": (255, 245, 240),
    },
    "chatgpt": {
        "primary": (16, 163, 127),
        "dark": (10, 120, 95),
        "bg": (16, 163, 127),
        "accent": (255, 255, 255),
    },
    "gemini": {
        "primary": (66, 133, 244),
        "dark": (103, 58, 183),
        "bg": (30, 30, 40),
        "accent": (66, 133, 244),
    },
    "mc": {
        "primary": (219, 112, 147),
        "dark": (160, 70, 100),
        "bg": (219, 112, 147),
        "accent": (255, 255, 255),
    },
}


def generate_avatar(provider: str, size: int = 120) -> Image.Image:
    """AI 캐릭터 아바타를 Pillow로 생성 (브랜드 로고)."""
    colors = CHAR_COLORS.get(provider, CHAR_COLORS["mc"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    s = size
    cx, cy = s // 2, s // 2

    if provider == "claude":
        _draw_claude(d, s, cx, cy, colors)
    elif provider == "chatgpt":
        _draw_chatgpt(d, s, cx, cy, colors)
    elif provider == "gemini":
        _draw_gemini(d, s, cx, cy, colors)
    else:
        _draw_mc(d, s, cx, cy, colors)

    return img


def _draw_claude(d, s, cx, cy, c):
    """Claude: 코랄색 원 + 중앙 스타버스트/스파클 마크."""
    r = s // 2 - 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c["bg"])

    num_rays = 6
    inner_r = s * 0.06
    outer_r = s * 0.22
    line_w = max(2, int(s * 0.055))

    for i in range(num_rays):
        angle = math.radians(60 * i - 90)
        x1 = cx + int(inner_r * math.cos(angle))
        y1 = cy + int(inner_r * math.sin(angle))
        x2 = cx + int(outer_r * math.cos(angle))
        y2 = cy + int(outer_r * math.sin(angle))
        d.line([x1, y1, x2, y2], fill=c["accent"], width=line_w)

    dot_r = max(2, int(s * 0.045))
    for i in range(num_rays):
        angle = math.radians(60 * i - 90)
        tx = cx + int(outer_r * math.cos(angle))
        ty = cy + int(outer_r * math.sin(angle))
        d.ellipse([tx - dot_r, ty - dot_r, tx + dot_r, ty + dot_r], fill=c["accent"])

    center_r = max(2, int(s * 0.06))
    d.ellipse([cx - center_r, cy - center_r, cx + center_r, cy + center_r], fill=c["accent"])


def _draw_chatgpt(d, s, cx, cy, c):
    """ChatGPT: 틸 그린 원 + 헥사곤 플라워 패턴."""
    r = s // 2 - 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c["bg"])

    hex_r = s * 0.22
    petal_r = s * 0.09
    line_w = max(2, int(s * 0.035))
    white = c["accent"]

    petal_centers = []
    for i in range(6):
        angle = math.radians(60 * i - 90)
        px = cx + int(hex_r * math.cos(angle))
        py = cy + int(hex_r * math.sin(angle))
        petal_centers.append((px, py))

    for i in range(6):
        x1, y1 = petal_centers[i]
        x2, y2 = petal_centers[(i + 1) % 6]
        _draw_arc_between(d, x1, y1, x2, y2, cx, cy, white, line_w, s)

    pr = int(petal_r * 0.45)
    for px, py in petal_centers:
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=white)


def _draw_arc_between(d, x1, y1, x2, y2, cx, cy, color, width, s):
    """두 점 사이에 바깥으로 볼록한 호를 선분으로 근사하여 그리기."""
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2
    dx = mx - cx
    dy = my - cy
    dist = math.sqrt(dx * dx + dy * dy) or 1
    bulge = s * 0.06
    ctrl_x = mx + dx / dist * bulge
    ctrl_y = my + dy / dist * bulge

    steps = 12
    points = []
    for t_i in range(steps + 1):
        t = t_i / steps
        bx = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * ctrl_x + t ** 2 * x2
        by = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * ctrl_y + t ** 2 * y2
        points.append((int(bx), int(by)))
    if len(points) > 1:
        d.line(points, fill=color, width=width, joint="curve")


def _draw_gemini(d, s, cx, cy, c):
    """Gemini: 다크 원 배경 + 4-pointed 스타 (블루-퍼플 그라데이션 느낌)."""
    r = s // 2 - 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c["bg"])

    _draw_four_pointed_star(d, cx, cy, s, c)


def _draw_four_pointed_star(d, cx, cy, s, c):
    """Gemini의 4-pointed star: 세로로 길고 가로가 좁은 형태."""
    blue = c["primary"]
    purple = c["dark"]

    vert_len = s * 0.36
    horiz_len = s * 0.18
    waist = s * 0.06

    right_half = []
    steps = 20
    for i in range(steps + 1):
        t = i / steps
        y = cy - vert_len + t * 2 * vert_len
        progress = t
        if progress <= 0.5:
            frac = progress / 0.5
            x = cx + waist * math.sin(frac * math.pi)
            if frac < 0.1:
                x = cx + horiz_len * frac / 0.1
            elif frac > 0.9:
                x = cx + horiz_len * (1 - frac) / 0.1
        else:
            frac = (progress - 0.5) / 0.5
            x = cx + waist * math.sin((1 - frac) * math.pi)
            if frac < 0.1:
                x = cx + horiz_len * (1 - frac * 10) * 0
            elif frac > 0.9:
                pass

        right_half.append((x, y))

    top = (cx, cy - vert_len)
    mid_right = (cx + horiz_len, cy)
    bottom = (cx, cy + vert_len)
    mid_left = (cx - horiz_len, cy)

    curve_points = []
    for i in range(steps + 1):
        t = i / steps
        bx = (1 - t) ** 2 * top[0] + 2 * (1 - t) * t * (cx + waist) + t ** 2 * mid_right[0]
        by = (1 - t) ** 2 * top[1] + 2 * (1 - t) * t * (cy - vert_len * 0.3) + t ** 2 * mid_right[1]
        curve_points.append((int(bx), int(by)))
    for i in range(1, steps + 1):
        t = i / steps
        bx = (1 - t) ** 2 * mid_right[0] + 2 * (1 - t) * t * (cx + waist) + t ** 2 * bottom[0]
        by = (1 - t) ** 2 * mid_right[1] + 2 * (1 - t) * t * (cy + vert_len * 0.3) + t ** 2 * bottom[1]
        curve_points.append((int(bx), int(by)))
    for i in range(1, steps + 1):
        t = i / steps
        bx = (1 - t) ** 2 * bottom[0] + 2 * (1 - t) * t * (cx - waist) + t ** 2 * mid_left[0]
        by = (1 - t) ** 2 * bottom[1] + 2 * (1 - t) * t * (cy + vert_len * 0.3) + t ** 2 * mid_left[1]
        curve_points.append((int(bx), int(by)))
    for i in range(1, steps + 1):
        t = i / steps
        bx = (1 - t) ** 2 * mid_left[0] + 2 * (1 - t) * t * (cx - waist) + t ** 2 * top[0]
        by = (1 - t) ** 2 * mid_left[1] + 2 * (1 - t) * t * (cy - vert_len * 0.3) + t ** 2 * top[1]
        curve_points.append((int(bx), int(by)))

    # 상단은 blue, 하단은 purple로 그라데이션 효과
    star_img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    star_d = ImageDraw.Draw(star_img)

    # 먼저 blue로 전체 채우기
    star_d.polygon(curve_points, fill=blue)

    # purple 오버레이를 하단에서 블렌딩 (간단 방식: 하반부만 purple)
    lower_img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    lower_d = ImageDraw.Draw(lower_img)
    lower_d.polygon(curve_points, fill=purple)

    # 그라데이션 마스크: 상단 0 → 하단 180
    try:
        import numpy as np
        grad = np.tile(
            np.linspace(0, 180, s, dtype=np.uint8).reshape(s, 1), (1, s)
        )
        grad_mask = Image.fromarray(grad, "L")
    except ImportError:
        grad_mask = Image.new("L", (s, s), 0)
        gd = ImageDraw.Draw(grad_mask)
        for yy in range(s):
            v = min(180, int((yy / s) * 180))
            gd.line([(0, yy), (s - 1, yy)], fill=v)

    star_img.paste(lower_img, mask=grad_mask)

    base = d._image
    base.alpha_composite(star_img, (0, 0))


def _draw_mc(d, s, cx, cy, c):
    """MC(사회자): 핑크 원 + 마이크 아이콘."""
    r = s // 2 - 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c["bg"])

    white = c["accent"]
    mic_w = int(s * 0.14)
    mic_h = int(s * 0.22)
    mic_top = cy - int(s * 0.18)

    d.rounded_rectangle(
        [cx - mic_w, mic_top, cx + mic_w, mic_top + mic_h],
        radius=mic_w,
        fill=white,
    )

    grid_lines = 3
    for i in range(1, grid_lines + 1):
        gy = mic_top + int(mic_h * i / (grid_lines + 1))
        d.line([cx - mic_w + 3, gy, cx + mic_w - 3, gy], fill=c["dark"], width=max(1, s // 60))

    arc_r_x = int(s * 0.20)
    arc_r_y = int(s * 0.16)
    arc_top = mic_top + mic_h // 3
    arc_w = max(2, int(s * 0.035))
    d.arc(
        [cx - arc_r_x, arc_top, cx + arc_r_x, arc_top + arc_r_y * 2],
        start=0, end=180,
        fill=white, width=arc_w,
    )

    stem_top = arc_top + arc_r_y * 2 - arc_w // 2
    stem_bottom = stem_top + int(s * 0.12)
    stem_w = max(2, int(s * 0.035))
    d.line([cx, stem_top, cx, stem_bottom], fill=white, width=stem_w)

    base_w = int(s * 0.12)
    d.line([cx - base_w, stem_bottom, cx + base_w, stem_bottom], fill=white, width=stem_w)


def generate_speech_bubble(width: int, height: int, color: tuple,
                           tail_side: str = "left") -> Image.Image:
    """말풍선 배경 이미지 생성."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    bubble_margin = 12
    tail_h = 15
    bx1, by1 = bubble_margin, 0
    bx2, by2 = width - bubble_margin, height - tail_h

    bg_color = color + (40,)
    border_color = color + (120,)

    d.rounded_rectangle([bx1, by1, bx2, by2], radius=12, fill=bg_color, outline=border_color, width=2)

    if tail_side == "left":
        tx = bx1 + 20
        d.polygon([(tx, by2), (tx + 10, by2), (tx - 5, by2 + tail_h)], fill=bg_color, outline=border_color)
    else:
        tx = bx2 - 20
        d.polygon([(tx, by2), (tx - 10, by2), (tx + 5, by2 + tail_h)], fill=bg_color, outline=border_color)

    return img


def get_avatar_tk(provider: str, size: int = 48):
    """tkinter PhotoImage로 변환된 아바타 반환."""
    import tkinter as tk
    avatar = generate_avatar(provider, size)
    buf = io.BytesIO()
    avatar.save(buf, format="PNG")
    buf.seek(0)
    photo = tk.PhotoImage(data=buf.getvalue())
    return photo


def save_avatars(output_dir: str, size: int = 120):
    """모든 아바타를 PNG로 저장 (디버그/미리보기용)."""
    os.makedirs(output_dir, exist_ok=True)
    for provider in ["claude", "chatgpt", "gemini", "mc"]:
        img = generate_avatar(provider, size)
        path = os.path.join(output_dir, f"avatar_{provider}.png")
        img.save(path, "PNG")
    print(f"Avatars saved to {output_dir}")
