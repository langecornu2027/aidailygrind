"""Share cards: the picture LinkedIn, X and Facebook show when someone shares a page.

1200x630 (the size these sites prefer for a big preview): the cover with a dark fade,
the brand, a small label, and the title in big letters.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
W, H = 1200, 630
PAD = 64
TEXT_W = 700  # the title stays on the dark left side
LABEL_Y = 150
TITLE_Y = LABEL_Y + 54
TITLE_BOTTOM = H - PAD - 56  # keep clear of the footer

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
    """Biggest size where the title fits in 4 lines and above the footer."""
    for size in range(68, 34, -4):
        f = font("SpaceGrotesk", size, "Bold")
        lines = wrap(draw, text, f, TEXT_W)
        if len(lines) <= 4 and len(lines) * int(size * 1.12) <= TITLE_BOTTOM - TITLE_Y:
            return f, lines
    f = font("SpaceGrotesk", 36, "Bold")
    lines = wrap(draw, text, f, TEXT_W)[:4]
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
    # dark fade from the left, so the text is easy to read
    fade = Image.new("L", (W, 1))
    for x in range(W):
        t = x / W
        fade.putpixel((x, 0), int(255 * (0.96 if t < 0.45 else max(0.25, 0.96 - (t - 0.45) * 1.6))))
    shade = Image.new("RGB", (W, H), BG)
    canvas.paste(shade, (0, 0), fade.resize((W, H)))
    return canvas


def make_card(cover: Path | None, out: Path, label: str, title: str, tag: str = "") -> None:
    img = background(cover)
    d = ImageDraw.Draw(img)

    # brand
    d.rounded_rectangle((PAD, PAD, PAD + 14, PAD + 14), radius=4, fill=AMBER)
    d.text((PAD + 26, PAD - 6), "AI DAILY GRIND", font=font("JetBrainsMono", 24, "Bold"), fill=WHITE)

    # small label (date / token number) and tag
    mono = font("JetBrainsMono", 22, "Regular")
    y = LABEL_Y
    d.text((PAD, y), label.upper(), font=mono, fill=CYAN)
    if tag:
        x = PAD + d.textlength(label.upper(), font=mono) + 18
        tw = d.textlength(tag.upper(), font=mono)
        d.rounded_rectangle((x, y - 4, x + tw + 24, y + 30), radius=15, outline=AMBER, width=2)
        d.text((x + 12, y), tag.upper(), font=mono, fill=AMBER)

    # title
    f, lines = fit_title(d, title)
    y = TITLE_Y
    line_h = int(f.size * 1.12)
    for line in lines:
        d.text((PAD, y), line, font=f, fill=WHITE)
        y += line_h

    # footer: site + a coffee-to-tech light line
    d.text((PAD, H - PAD - 24), "aidailygrind.com", font=font("JetBrainsMono", 24, "Medium"), fill=MUTED)
    for x in range(W):
        t = x / W
        color = tuple(int(AMBER_2[i] + (CYAN[i] - AMBER_2[i]) * t) for i in range(3))
        d.line([(x, H - 6), (x, H)], fill=color)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=86, optimize=True, progressive=True)
