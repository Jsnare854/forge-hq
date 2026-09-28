"""Typography t-shirt renderer: print-ready transparent PNGs and a quick tee mockup."""
from __future__ import annotations

import io
import math
import random
import zlib
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .spec import SHIRTS, SIZES, normalize_spec

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILES = {
    "Anton": "Anton-Regular.ttf",
    "Archivo Black": "ArchivoBlack-Regular.ttf",
    "Alfa Slab One": "AlfaSlabOne-Regular.ttf",
    "Bebas Neue": "BebasNeue-Regular.ttf",
    "Pacifico": "Pacifico-Regular.ttf",
    "Permanent Marker": "PermanentMarker-Regular.ttf",
}
PRINT_W, PRINT_H = 4500, 5400


@lru_cache(maxsize=256)
def font(family: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / FONT_FILES.get(family, FONT_FILES["Anton"])), max(8, int(size)))


def rgba(hex_color: str, a: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def fit_size(text: str, family: str, max_w: float, max_size: float) -> int:
    s = max(8, int(max_size))
    w = font(family, s).getlength(text)
    if w > max_w:
        s = int(s * max_w / w)
    return max(8, s)


def _stack(img, spec, lines, cx, top, max_w, max_h, *, rules=False, shadow=False, family=None, upper=True, accent=None):
    d = ImageDraw.Draw(img)
    fam = family or spec["font"]
    acc = accent or spec["accent"]
    base = max_w * 0.36
    texts = [l["text"].upper() if upper else l["text"] for l in lines]
    sizes = [fit_size(t, fam, max_w, base * SIZES[l["size"]]) for t, l in zip(texts, lines)]
    gap = 0.12
    total = sum(s * (1 + gap) for s in sizes)
    if total > max_h:
        k = max_h / total
        sizes = [max(8, int(s * k)) for s in sizes]
        total = sum(s * (1 + gap) for s in sizes)
    y = top + (max_h - total) / 2
    for t, l, sz in zip(texts, lines, sizes):
        f = font(fam, sz)
        col = acc if (l["size"] in ("sm", "md") and len(lines) > 1) else spec["ink"]
        if shadow:
            off = max(2, sz * 0.05)
            d.text((cx + off, y + off), t, font=f, fill=rgba(spec["accent"]), anchor="ma")
            col = spec["ink"]
        d.text((cx, y), t, font=f, fill=rgba(col), anchor="ma")
        if rules and l["size"] == "sm":
            w = f.getlength(t)
            pad = sz * 0.5
            ry = y + sz * 0.5
            th = max(2, int(sz * 0.08))
            ln = max(0, (max_w - w) / 2 - pad)
            if ln > 4:
                d.rectangle([cx - w / 2 - pad - ln, ry, cx - w / 2 - pad, ry + th], fill=rgba(acc))
                d.rectangle([cx + w / 2 + pad, ry, cx + w / 2 + pad + ln, ry + th], fill=rgba(acc))
        y += sz * (1 + gap)
    return y


def _arc_text(img, text, cx, cy, r, size, family, color, top=True):
    f = font(family, size)
    widths = [f.getlength(c) + size * 0.06 for c in text]
    total = sum(widths)
    ang = -total / (2 * r)
    for ch, w in zip(text, widths):
        a = ang + w / (2 * r)
        if ch.strip():
            box = int(size * 1.6)
            glyph = Image.new("RGBA", (box, box), (0, 0, 0, 0))
            ImageDraw.Draw(glyph).text((box / 2, box / 2), ch, font=f, fill=rgba(color), anchor="mm")
            if top:
                x, y, rot = cx + r * math.sin(a), cy - r * math.cos(a), -math.degrees(a)
            else:
                x, y, rot = cx + r * math.sin(a), cy + r * math.cos(a), math.degrees(a)
            g = glyph.rotate(rot, resample=Image.BICUBIC, expand=True)
            img.alpha_composite(g, (int(x - g.width / 2), int(y - g.height / 2)))
        ang += w / r


def draw_design(spec: dict, W: int = PRINT_W, H: int = PRINT_H) -> Image.Image:
    s = normalize_spec(spec)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    seed = zlib.crc32(("|".join(l["text"] for l in s["lines"]) + s["style"]).encode())
    R = random.Random(seed)
    cx, pad = W / 2, W * 0.06
    max_w = W - pad * 2
    style = s["style"]

    if style == "stack":
        _stack(img, s, s["lines"], cx, H * 0.08, max_w, H * 0.84)
    elif style == "split":
        _stack(img, s, s["lines"], cx, H * 0.08, max_w, H * 0.84, rules=True)
    elif style == "badge":
        r, cy = W * 0.44, H * 0.5
        lw = int(W * 0.028)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba(s["ink"]), width=lw)
        r2 = r * 0.8
        d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=rgba(s["accent"]), width=max(2, int(W * 0.01)))
        lines = list(s["lines"])
        first = lines.pop(0) if len(lines) > 2 else None
        last = lines.pop() if len(lines) > 2 else None
        ring_r = (r + r2) / 2
        if first:
            _arc_text(img, first["text"].upper(), cx, cy, ring_r, int(W * 0.075), s["font"], s["ink"], top=True)
        if last:
            _arc_text(img, last["text"].upper(), cx, cy, ring_r, int(W * 0.075), s["font"], s["ink"], top=False)
        k = W * 0.012
        for dx in (-ring_r, ring_r):
            d.polygon([(cx + dx, cy - k), (cx + dx + k, cy), (cx + dx, cy + k), (cx + dx - k, cy)], fill=rgba(s["accent"]))
        _stack(img, s, lines, cx, cy - r2 * 0.66, r2 * 1.6, r2 * 1.3)
    elif style == "sunset":
        sy, sr = H * 0.36, W * 0.3
        sun = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        top_c, bot_c = rgba(s["accent"]), rgba(s["ink"])
        grad = Image.new("RGBA", (1, 256))
        for i in range(256):
            t = i / 255
            grad.putpixel((0, i), tuple(int(top_c[j] + (bot_c[j] - top_c[j]) * t) for j in range(4)))
        grad = grad.resize((int(sr * 2), int(sr * 2)))
        mask = Image.new("L", grad.size, 0)
        md = ImageDraw.Draw(mask)
        md.ellipse([0, 0, grad.width - 1, grad.height - 1], fill=255)
        for i in range(6):
            yy = sr + sr * 0.05 + i * sr * 0.17
            md.rectangle([0, yy, grad.width, yy + sr * (0.03 + i * 0.018)], fill=0)
        sun.paste(grad, (int(cx - sr), int(sy - sr)), mask)
        img.alpha_composite(sun)
        _stack(img, s, s["lines"], cx, H * 0.56, max_w, H * 0.38, shadow=True)
    elif style == "stamp":
        bx, by, bw, bh = pad, H * 0.14, max_w, H * 0.72
        d.rectangle([bx, by, bx + bw, by + bh], outline=rgba(s["ink"]), width=int(W * 0.022))
        inset = W * 0.03
        d.rectangle([bx + inset, by + inset, bx + bw - inset, by + bh - inset], outline=rgba(s["ink"]), width=max(2, int(W * 0.007)))
        _stack(img, s, s["lines"], cx, by + bh * 0.1, bw * 0.84, bh * 0.8)
        erase = Image.new("L", (W, H), 0)
        ed = ImageDraw.Draw(erase)
        for _ in range(900):
            x, y = R.random() * W, R.random() * H
            rr = R.random() * R.random() * W * 0.012
            ed.ellipse([x - rr, y - rr, x + rr, y + rr], fill=255)
        for _ in range(30):
            x, y = R.random() * W, R.random() * H
            ed.rectangle([x, y, x + R.random() * W * 0.2, y + R.random() * W * 0.004 + 1], fill=255)
        alpha = img.getchannel("A")
        alpha = Image.composite(Image.new("L", (W, H), 0), alpha, erase)
        img.putalpha(alpha)
    elif style == "script":
        first, rest = s["lines"][0], s["lines"][1:]
        block_fam = "Anton" if s["font"] == "Pacifico" else s["font"]
        sz = fit_size(first["text"], "Pacifico", max_w * 0.9, W * 0.2)
        f = font("Pacifico", sz)
        layer = Image.new("RGBA", (W, int(sz * 2.2)), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((W / 2, layer.height / 2), first["text"], font=f, fill=rgba(s["accent"]), anchor="mm")
        layer = layer.rotate(5.7, resample=Image.BICUBIC, expand=True)
        img.alpha_composite(layer, (int(cx - layer.width / 2), int(H * 0.3 - layer.height / 2)))
        if rest:
            _stack(img, {**s, "accent": s["ink"]}, rest, cx, H * 0.46, max_w, H * 0.46, family=block_fam)
    return img


def render_print(spec: dict) -> bytes:
    img = draw_design(spec, PRINT_W, PRINT_H)
    bbox = img.getbbox()
    if not bbox:
        raise ValueError("Design rendered empty")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _tee(W, H):
    return [
        (W * .34, H * .04), (W * .42, H * .085), (W * .5, H * .1), (W * .58, H * .085), (W * .66, H * .04),
        (W * .94, H * .16), (W * .86, H * .33), (W * .76, H * .29), (W * .77, H * .97), (W * .23, H * .97),
        (W * .24, H * .29), (W * .14, H * .33), (W * .06, H * .16),
    ]


def render_mockup(spec: dict, W: int = 600, H: int = 680) -> bytes:
    s = normalize_spec(spec)
    img = Image.new("RGBA", (W, H), rgba("#0c1c13"))
    shirt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shirt)
    sd.polygon(_tee(W, H), fill=rgba(SHIRTS[s["shirt"]]), outline=(0, 0, 0, 90))
    shade = Image.new("L", (W, 1))
    for x in range(W):
        t = abs(x - W / 2) / (W / 2)
        shade.putpixel((x, 0), int(60 * t))
    shade = shade.resize((W, H))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    dark.putalpha(Image.composite(shade, Image.new("L", (W, H), 0), shirt.getchannel("A")))
    img.alpha_composite(shirt)
    img.alpha_composite(dark)
    dw = int(W * 0.4)
    dh = int(dw * PRINT_H / PRINT_W)
    design = draw_design(s, dw * 2, dh * 2).resize((dw, dh), Image.LANCZOS)
    img.alpha_composite(design, ((W - dw) // 2, int(H * 0.2)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
