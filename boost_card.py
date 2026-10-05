"""
boost_card.py  -  draws the ELT server-boost card (PNG).

    render_boost_card(name, server_name, avatar_bytes, level, total_boosts,
                      boosts=1, level_up=None) -> PNG bytes

Needs only Pillow. Font: put any .ttf/.otf in a "fonts" folder next to this file (the same
fonts folder as your punishment bot works), or set FONT_PATH. Falls back to DejaVu / Pillow's built-in font.
"""

import io
import os
import random
import unicodedata
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1000, 360
MAGENTA = (255, 90, 210)
PURPLE = (170, 70, 255)

_HERE = os.path.dirname(os.path.abspath(__file__))


def safe_text(text: str, fallback: str = "") -> str:
    """Keeps only characters a normal font can draw (fancy letters become plain ones)."""
    text = unicodedata.normalize("NFKC", text or "")
    out = "".join(c for c in text if ord(c) < 0x250 and (c.isalnum() or c in " ._-'&!|#@+()"))
    out = " ".join(out.split())
    return out or fallback


@lru_cache(maxsize=None)
def _font_paths():
    paths = [os.environ.get("FONT_PATH")]
    fonts_dir = os.path.join(_HERE, "fonts")
    if os.path.isdir(fonts_dir):
        files = sorted(f for f in os.listdir(fonts_dir) if f.lower().endswith((".ttf", ".otf")))
        files.sort(key=lambda f: 0 if "bold" in f.lower() else 1)
        paths += [os.path.join(fonts_dir, f) for f in files]
    paths += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    return [p for p in paths if p and os.path.exists(p)]


@lru_cache(maxsize=None)
def font(size: int):
    for p in _font_paths():
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)      # Pillow 10.1+
    except TypeError:
        return ImageFont.load_default()


def text_w(draw, text, fnt, spacing=0):
    return draw.textlength(text, font=fnt) + spacing * max(len(text) - 1, 0)


def draw_spaced(draw, xy, text, fnt, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + spacing


def fit_text(draw, text, max_w, start, minimum):
    """Largest font size (start -> minimum) that fits; ellipsis if even the smallest is too wide."""
    for size in range(start, minimum - 1, -2):
        f = font(size)
        if text_w(draw, text, f) <= max_w:
            return text, f
    f = font(minimum)
    while len(text) > 1 and text_w(draw, text + "…", f) > max_w:
        text = text[:-1]
    return text.rstrip() + "…", f


def star(draw, cx, cy, r, fill):
    k = r * 0.28
    draw.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
                  (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=fill)


def gem(draw, cx, cy, r, fill, outline=None):
    pts = [(cx, cy - r), (cx + r * 0.85, cy - r * 0.15), (cx, cy + r), (cx - r * 0.85, cy - r * 0.15)]
    draw.polygon(pts, fill=fill, outline=outline)


def render_boost_card(name, server_name, avatar_bytes, level, total_boosts, boosts=1, level_up=None) -> bytes:
    name = safe_text(name, "Booster")
    server_name = safe_text(server_name, "the server")

    # ---- background gradient ----
    base = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(base)
    for x in range(W):
        t = x / (W - 1)
        d.line([(x, 0), (x, H)], fill=(int(34 - 22 * t), int(10 - 5 * t), int(66 - 40 * t), 255))

    # ---- glows ----
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([175 - 190, 180 - 190, 175 + 190, 180 + 190], fill=(190, 60, 255, 120))
    g.ellipse([W - 220, -100, W + 80, 200], fill=(255, 70, 170, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(55))
    base = Image.alpha_composite(base, glow)

    # ---- sparkles (same member = same pattern) ----
    rnd = random.Random(sum(map(ord, name)) + level)
    sp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sp)
    for _ in range(26):
        x, y = rnd.randint(300, W - 20), rnd.randint(14, H - 14)
        star(sd, x, y, rnd.choice([3, 4, 5, 7, 9]), (255, 200, 245, rnd.randint(60, 170)))
    base = Image.alpha_composite(base, sp)

    # ---- avatar with ring ----
    cx, cy = 175, 180
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse([cx - 122, cy - 122, cx + 122, cy + 122], fill=MAGENTA + (255,))
    rd.ellipse([cx - 115, cy - 115, cx + 115, cy + 115], fill=(20, 8, 38, 255))
    base = Image.alpha_composite(base, ring)

    try:
        av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((222, 222), Image.LANCZOS)
    except Exception:
        av = Image.new("RGBA", (222, 222), (60, 30, 100, 255))
        gem(ImageDraw.Draw(av), 111, 111, 60, MAGENTA + (255,))
    mask = Image.new("L", (222, 222), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 221, 221], fill=255)
    base.paste(av, (cx - 111, cy - 111), mask)

    d = ImageDraw.Draw(base)
    # boost badge on the avatar
    bx, by = cx + 84, cy + 88
    d.ellipse([bx - 34, by - 34, bx + 34, by + 34], fill=(20, 8, 38, 255))
    d.ellipse([bx - 29, by - 29, bx + 29, by + 29], fill=MAGENTA + (255,))
    gem(d, bx, by, 17, (255, 255, 255, 255))

    # ---- text ----
    x0 = 340
    max_w = W - x0 - 50

    if level_up:
        tag = f"LEVEL {level_up} UNLOCKED"
    elif boosts > 1:
        tag = f"{boosts}X SERVER BOOST"
    else:
        tag = "NEW SERVER BOOST"
    draw_spaced(d, (x0, 52), tag, font(24), MAGENTA + (255,), 5)
    d.line([(x0, 90), (x0 + 70, 90)], fill=PURPLE + (255,), width=4)

    shown, f = fit_text(d, name, max_w, 68, 34)
    d.text((x0, 104), shown, font=f, fill=(255, 255, 255, 255))

    if level_up:
        line = f"unlocked Level {level_up} for {server_name}!"
    elif boosts > 1:
        line = f"boosted {server_name} {boosts} times!"
    else:
        line = f"just boosted {server_name}!"
    shown, f = fit_text(d, line, max_w, 30, 18)
    d.text((x0, 190), shown, font=f, fill=(226, 205, 245, 255))

    # ---- pills ----
    f2 = font(22)
    pills = [(f"LEVEL {level}", True), (f"{total_boosts} BOOST{'S' if total_boosts != 1 else ''}", False)]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    spots, px = [], x0
    for text, filled in pills:
        w = int(text_w(d, text, f2, 2)) + 44
        ld.rounded_rectangle([px, 248, px + w, 296], radius=24,
                             fill=(MAGENTA + (70,)) if filled else (255, 255, 255, 22),
                             outline=MAGENTA + (255,), width=2)
        spots.append((px + 22, text))
        px += w + 16
    base = Image.alpha_composite(base, layer)
    d = ImageDraw.Draw(base)
    for tx, text in spots:
        draw_spaced(d, (tx, 258), text, f2, (255, 255, 255, 255), 2)

    shown, f = fit_text(d, server_name.upper(), max_w, 18, 12)
    d.text((x0, 316), shown, font=f, fill=(150, 120, 185, 255))

    # ---- border + rounded corners ----
    d.rounded_rectangle([1, 1, W - 2, H - 2], radius=30, outline=PURPLE + (255,), width=3)
    corner = Image.new("L", (W, H), 0)
    ImageDraw.Draw(corner).rounded_rectangle([0, 0, W - 1, H - 1], radius=30, fill=255)
    base.putalpha(corner)

    out = io.BytesIO()
    base.save(out, "PNG", optimize=True)
    return out.getvalue()
