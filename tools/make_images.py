# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Maakt de afbeeldingen van de integratie opnieuw: playlist-covers en het merkicoon.

    uv run --script tools/make_images.py

Lettertype: Anton (SIL Open Font License), wordt bij het draaien gedownload.
Eigen ontwerp: geen Spotify-logo of -artwork (dat mag niet worden overgenomen).
"""
import os
import random
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMP = os.path.join(ROOT, "custom_components", "spotify_weekmix")
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"
FONT = os.path.join(ROOT, "tools", ".Anton-Regular.ttf")

# Van energiek (maandag) naar rustig (zondag).
DAYS = [("maandag", "#ff5a1f", "#ffb800"), ("dinsdag", "#ff3d7f", "#ff9a3d"),
        ("woensdag", "#7b2ff7", "#ff4fa3"), ("donderdag", "#2f5bf7", "#a24ff7"),
        ("vrijdag", "#ff2d55", "#7b2ff7"), ("zaterdag", "#00a6a6", "#2f80f7"),
        ("zondag", "#1d3b6e", "#3fa7a0")]
DARK = (17, 17, 17)


def hexc(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def font(size):
    return ImageFont.truetype(FONT, size)


def cover(i, day, c1, c2, n=640):
    a, b = hexc(c1), hexc(c2)
    img = Image.new("RGBA", (n, n), DARK + (255,))
    d = ImageDraw.Draw(img)
    rnd = random.Random(i)
    for _ in range(10):
        x, y = rnd.randint(-80, n), rnd.randint(-80, n)
        w, h = rnd.randint(70, 170), rnd.randint(110, 240)
        t = rnd.random()
        col = tuple(int(a[k] * (1 - t) + b[k] * t) for k in range(3))
        d.polygon([(x, y + 40), (x + w, y), (x + w, y + h - 40), (x, y + h)], fill=col)
    band = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(band).polygon([(0, 210), (n, 150), (n, 470), (0, 530)], fill=DARK + (235,))
    img = Image.alpha_composite(img, band)
    txt = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)
    name, size = day.upper(), 190
    while td.textlength(name, font=font(size)) > n - 70:
        size -= 4
    td.text(((n - td.textlength(name, font=font(size))) / 2, 205), name, font=font(size), fill="white")
    sub = "WEEKMIX"
    td.text(((n - td.textlength(sub, font=font(64))) / 2, 205 + size * 1.12), sub, font=font(64), fill=c2)
    img = Image.alpha_composite(img, txt.rotate(5, resample=Image.BICUBIC, center=(n / 2, n / 2)))
    img.convert("RGB").save(os.path.join(COMP, "covers", f"{day}.jpg"), quality=88)


def icon(size):
    """Zeven balkjes (één per dag) als equalizer in een donkere afgeronde tegel."""
    s = size * 4                                   # supersampling voor nette randen
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=DARK + (255,))
    heights = [0.62, 0.40, 0.78, 0.52, 0.86, 0.46, 0.32]
    pad, gap = s * 0.15, s * 0.03
    bw = (s - 2 * pad - 6 * gap) / 7
    base = s * 0.80
    for k, (h, (_, c1, _c2)) in enumerate(zip(heights, DAYS, strict=True)):
        x = pad + k * (bw + gap)
        top = base - h * s * 0.62
        d.rounded_rectangle([x, top, x + bw, base], radius=int(bw / 2), fill=hexc(c1))
    return img.resize((size, size), Image.LANCZOS)


def logo(height, text_color):
    ic = icon(height)
    f = font(int(height * 0.78))
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = int(tmp.textlength("WEEKMIX", font=f))
    img = Image.new("RGBA", (height + int(height * 0.25) + tw, height), (0, 0, 0, 0))
    img.paste(ic, (0, 0), ic)
    ImageDraw.Draw(img).text((height + int(height * 0.25), int(height * 0.02)), "WEEKMIX",
                             font=f, fill=text_color)
    return img.crop(img.getbbox())


def main():
    if not os.path.exists(FONT):
        urllib.request.urlretrieve(FONT_URL, FONT)
    os.makedirs(os.path.join(COMP, "covers"), exist_ok=True)
    os.makedirs(os.path.join(COMP, "brand"), exist_ok=True)
    for i, (day, c1, c2) in enumerate(DAYS):
        cover(i, day, c1, c2)
    b = os.path.join(COMP, "brand")
    icon(256).save(os.path.join(b, "icon.png"))
    icon(512).save(os.path.join(b, "icon@2x.png"))
    logo(128, DARK).save(os.path.join(b, "logo.png"))
    logo(256, DARK).save(os.path.join(b, "logo@2x.png"))
    logo(128, (255, 255, 255)).save(os.path.join(b, "dark_logo.png"))
    logo(256, (255, 255, 255)).save(os.path.join(b, "dark_logo@2x.png"))


if __name__ == "__main__":
    main()
