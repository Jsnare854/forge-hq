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
    "t-shirt mockup, shirt, model, person wearing, photo background, frame border around image, watermark, signature, "
    "brand logos, trademarks, misspelled words, extra letters, gibberish text, blurry, low resolution"
)


class IllustratorError(RuntimeError):
    pass


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
                raise IllustratorError(f"Ideogram failed ({r.status_code}): {r.text[:400]}")
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
    text = " / ".join(l["text"] for l in lines)
    dark = shirt in ("black", "navy", "forest", "maroon", "heather")
    return (
        f"T-shirt graphic design, isolated artwork on a transparent background. {art_prompt.strip()} "
        f'The design includes the exact text "{text}" spelled exactly like that, in bold, highly legible lettering that is part of the composition. '
        f"Screen-print style with clean edges, limited color palette (4-6 colors), no gradients that fade into the background, "
        f"colors that pop on a {'dark' if dark else 'light'} {shirt} shirt. Centered composition, nothing cut off at the edges."
    )


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
