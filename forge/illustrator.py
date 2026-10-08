"""Illustrator: turns the Designer's art prompt into print-ready artwork with Ideogram 3.0
(transparent background), then places it on the 4500x5400 Printify print canvas."""
from __future__ import annotations

import io
import time

import requests
from PIL import Image, ImageFilter

from .render import PRINT_H, PRINT_W

ENDPOINT = "https://api.ideogram.ai/v1/ideogram-v3/generate-transparent"
NEGATIVE = (
    "t-shirt, shirt shape, shirt silhouette, garment, clothing, hoodie, mockup, model, person wearing, "
    "solid background panel, colored rectangle behind the design, photo background, frame border around image, watermark, signature, "
    "brand logos, trademarks, misspelled words, extra letters, slashes between words, gibberish text, blurry, low resolution"
)


class IllustratorError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status

    @property
    def fatal(self) -> bool:
        """Errors that will fail for every design (bad key, no credits): stop the run instead of retrying."""
        return self.status in (401, 402, 403)


class Ideogram:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.key = api_key
        self.http = session or requests.Session()

    def generate(self, prompt: str, n: int = 2, speed: str = "DEFAULT", upscale: str = "X2", aspect: str = "3x4") -> list[bytes]:
        form = {
            "prompt": (None, prompt),
            "aspect_ratio": (None, aspect),
            "rendering_speed": (None, speed),
            "magic_prompt": (None, "OFF"),
            "negative_prompt": (None, NEGATIVE),
            "num_images": (None, str(n)),
            "upscale_factor": (None, upscale),
        }
        last = None
        for attempt in range(3):
            r = self.http.post(ENDPOINT, headers={"Api-Key": self.key}, files=form, timeout=180)
            if r.status_code == 429 or r.status_code >= 500:
                last = r
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise IllustratorError(f"Ideogram failed ({r.status_code}): {r.text[:400]}", r.status_code)
            images = []
            for d in r.json().get("data") or []:
                if d.get("is_image_safe") is False or not d.get("url"):
                    continue
                img = self.http.get(d["url"], timeout=120)  # URLs expire, download right away
                img.raise_for_status()
                images.append(img.content)
            return images
        raise IllustratorError(f"Ideogram kept failing ({getattr(last, 'status_code', '?')})")


def build_prompt(art_prompt: str, lines: list[dict], shirt: str) -> str:
    # Quote each line separately: joining with " / " made the model print literal slashes.
    parts = [f'"{l["text"]}"' for l in lines if l.get("text")]
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    dark = shirt in ("black", "navy", "forest", "maroon", "heather")
    palette = ("bright, light colors (cream, white, warm yellow, light orange) so every part stands out on a black fabric; "
               "no black, navy or dark lettering") if dark else \
              ("bold, dark, saturated colors (black, deep navy, rich red) so every part stands out on white fabric; "
               "no white, cream or pale lettering")
    # Never say "t-shirt design" here: the model then draws a t-shirt shape inside the artwork.
    return (
        f"Standalone screen-print graphic, a single isolated emblem on a transparent background, like a vinyl sticker with no border. "
        f"{art_prompt.strip()} "
        f"The design includes the text {text}{' stacked on separate lines' if len(parts) > 1 else ''}, spelled exactly like that, with no slashes or extra punctuation, "
        f"in bold, highly legible lettering that is part of the composition and never covered by the illustration. "
        f"Use {palette}. Clean edges, limited palette of 4-6 colors, no gradients that fade into the background, "
        f"no background shape, panel or garment behind the artwork. Centered composition, nothing cut off at the edges."
    )


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def weak_contrast(png: bytes, shirt_hex: str) -> float:
    """Share of the visible artwork that would blend into this fabric color (0 = all pops, 1 = invisible)."""
    art = Image.open(io.BytesIO(png)).convert("RGBA")
    art.thumbnail((256, 256))
    sr, sg, sb = _rgb(shirt_hex)
    s_lum = 0.2126 * sr + 0.7152 * sg + 0.0722 * sb
    total = weak = 0
    for r, g, b, a in art.getdata():
        if a < 128:
            continue
        total += 1
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        dist = ((r - sr) ** 2 + (g - sg) ** 2 + (b - sb) ** 2) ** 0.5
        if abs(lum - s_lum) < 55 and dist < 110:
            weak += 1
    return weak / total if total else 1.0


def best_shirt(png: bytes, preferred: str, shirts: dict) -> tuple[str, float]:
    """Pick the fabric the artwork actually works on: the designer's pick unless black or white is clearly better."""
    cands = [preferred] + [c for c in ("black", "white") if c != preferred and c in shirts]
    scores = {c: weak_contrast(png, shirts[c]) for c in cands if c in shirts}
    best = min(scores, key=scores.get)
    if preferred in scores and scores[preferred] <= scores[best] + 0.03:
        best = preferred
    return best, scores[best]


def to_print_canvas(png: bytes, width_frac: float = 0.92) -> bytes:
    """Trim transparent margins and fit the art onto the 4500x5400 print canvas (top-weighted for the chest)."""
    art = Image.open(io.BytesIO(png)).convert("RGBA")
    bbox = art.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if not bbox:
        raise IllustratorError("Generated artwork is empty (fully transparent).")
    art = art.crop(bbox)
    max_w, max_h = PRINT_W * width_frac, PRINT_H * 0.92
    k = min(max_w / art.width, max_h / art.height)
    new = (max(1, int(art.width * k)), max(1, int(art.height * k)))
    art = art.resize(new, Image.LANCZOS)
    if k > 1.5:
        art = art.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    canvas = Image.new("RGBA", (PRINT_W, PRINT_H), (0, 0, 0, 0))
    canvas.alpha_composite(art, ((PRINT_W - art.width) // 2, int(PRINT_H * 0.04)))
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def preview(png: bytes, shirt_hex: str, size: int = 900) -> bytes:
    """Artwork on a flat shirt-colored square: what the Art Director looks at."""
    art = Image.open(io.BytesIO(png)).convert("RGBA")
    art.thumbnail((size, size), Image.LANCZOS)
    h = shirt_hex.lstrip("#")
    bg = Image.new("RGBA", (size, size), (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255))
    bg.alpha_composite(art, ((size - art.width) // 2, (size - art.height) // 2))
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "JPEG", quality=88)
    return buf.getvalue()
