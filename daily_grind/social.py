"""Share cards: the picture LinkedIn, X and Facebook show when someone shares a page.

1200x630 (the size these sites prefer for a big preview). Some apps (Facebook on phones)
crop it to a square from the center, so all the text stays inside the center 630x630
"safe square". The cover fills the sides, so the wide version still looks full.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
W, H = 1200, 630
CX = W // 2
SAFE = 630          # center square that every crop keeps
TEXT_W = 540        # title width, inside the safe square with a margin
TITLE_TOP = 220
TITLE_BOTTOM = 515

BG = (7, 9, 12)
AMBER = (255, 180, 84)
AMBER_2 = (255, 138, 61)
CYAN = (94, 234, 212)
WHITE = (240, 244, 248)
MUTED = (150, 162, 175)


def font(name: str, size: int, weight: str) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / f"{name}.ttf"), size)
    f.set_variation_by_name(weight)
    return f


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=f) <= width or not line:
            line = test
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def fit_title(draw: ImageDraw.ImageDraw, text: str) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Biggest size where the title fits the safe square in 5 lines or less."""
    for size in range(60, 30, -2):
        f = font("SpaceGrotesk", size, "Bold")
        lines = wrap(draw, text, f, TEXT_W)
        if len(lines) <= 5 and len(lines) * int(size * 1.14) <= TITLE_BOTTOM - TITLE_TOP:
            return f, lines
    f = font("SpaceGrotesk", 32, "Bold")
    lines = wrap(draw, text, f, TEXT_W)[:5]
    lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return f, lines


def background(cover: Path | None) -> Image.Image:
    canvas = Image.new("RGB", (W, H), BG)
    if cover and cover.exists():
        img = Image.open(cover).convert("RGB")
        scale = max(W / img.width, H / img.height)
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        left, top = (img.width - W) // 2, (img.height - H) // 2
        canvas.paste(img.crop((left, top, left + W, top + H)))
    # dark in the middle (behind the text), lighter on the sides so the picture shows
    shade = Image.new("L", (W, 1))
    for x in range(W):
        dist = abs(x - CX) / (W / 2)            # 0 in the center, 1 at the edges
        shade.putpixel((x, 0), int(255 * (0.86 if dist < 0.45 else max(0.42, 0.86 - (dist - 0.45) * 0.9))))
    canvas.paste(Image.new("RGB", (W, H), BG), (0, 0), shade.resize((W, H)))
    return canvas


def centered(d: ImageDraw.ImageDraw, y: int, text: str, f: ImageFont.FreeTypeFont, fill) -> None:
    d.text((CX - d.textlength(text, font=f) / 2, y), text, font=f, fill=fill)


def make_card(cover: Path | None, out: Path, label: str, title: str, tag: str = "") -> None:
    img = background(cover)
    d = ImageDraw.Draw(img)

    # brand
    brand = font("JetBrainsMono", 24, "Bold")
    bw = d.textlength("AI DAILY GRIND", font=brand) + 26
    x0 = CX - bw / 2
    d.rounded_rectangle((x0, 62, x0 + 14, 76), radius=4, fill=AMBER)
    d.text((x0 + 26, 56), "AI DAILY GRIND", font=brand, fill=WHITE)

    # small label (date / token number), and the tag as a pill
    mono = font("JetBrainsMono", 21, "Regular")
    if tag:
        tw = d.textlength(tag.upper(), font=mono)
        lw = d.textlength(label.upper(), font=mono)
        total = lw + 18 + tw + 24
        x = CX - total / 2
        d.text((x, 140), label.upper(), font=mono, fill=CYAN)
        px = x + lw + 18
        d.rounded_rectangle((px, 136, px + tw + 24, 170), radius=15, outline=AMBER, width=2)
        d.text((px + 12, 140), tag.upper(), font=mono, fill=AMBER)
    else:
        centered(d, 140, label.upper(), mono, CYAN)

    # title, centered in its zone
    f, lines = fit_title(d, title)
    line_h = int(f.size * 1.14)
    y = TITLE_TOP + (TITLE_BOTTOM - TITLE_TOP - line_h * len(lines)) // 2
    for line in lines:
        centered(d, y, line, f, WHITE)
        y += line_h

    # footer: site + a coffee-to-tech light line
    centered(d, H - 78, "aidailygrind.com", font("JetBrainsMono", 22, "Medium"), MUTED)
    for x in range(W):
        t = x / W
        color = tuple(int(AMBER_2[i] + (CYAN[i] - AMBER_2[i]) * t) for i in range(3))
        d.line([(x, H - 6), (x, H)], fill=color)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=86, optimize=True, progressive=True)
