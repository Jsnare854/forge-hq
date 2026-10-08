"""Printify API client: upload the print file, build a Bella+Canvas 3001 product, publish it to Etsy."""
from __future__ import annotations

import base64
import io
import time

import requests

from .spec import SHIRT_TO_PRINTIFY, luminance

BASE = "https://api.printify.com/v1"


class PrintifyError(RuntimeError):
    pass


class Printify:
    def __init__(self, token: str, session: requests.Session | None = None):
        self.token = token
        self.http = session or requests.Session()

    def _req(self, method: str, path: str, **kw):
        headers = {"Authorization": f"Bearer {self.token}", "User-Agent": "forge-hq", "Content-Type": "application/json"}
        for attempt in range(4):
            r = self.http.request(method, BASE + path, headers=headers, timeout=60, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise PrintifyError(f"Printify {method} {path} failed ({r.status_code}): {r.text[:500]}")
            return r.json() if r.content else {}
        raise PrintifyError(f"Printify {method} {path} kept failing ({r.status_code}): {r.text[:300]}")

    # ---- reads
    def shops(self):
        return self._req("GET", "/shops.json")

    def blueprints(self):
        return self._req("GET", "/catalog/blueprints.json")

    def providers(self, blueprint_id: int):
        return self._req("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json")

    def variants(self, blueprint_id: int, provider_id: int):
        out = self._req("GET", f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")
        return out.get("variants", out) if isinstance(out, dict) else out

    # ---- writes
    def upload_png(self, file_name: str, data: bytes) -> str:
        data, w, h = trim_png(data)
        out = self._req("POST", "/uploads/images.json", json={"file_name": file_name, "contents": base64.b64encode(data).decode()})
        IMAGE_DIMS[out["id"]] = (int(out.get("width") or w), int(out.get("height") or h))
        return out["id"]

    def image_dims(self, image_id: str) -> tuple[int, int] | None:
        if image_id not in IMAGE_DIMS:
            try:
                out = self._req("GET", f"/uploads/{image_id}.json")
                IMAGE_DIMS[image_id] = (int(out["width"]), int(out["height"]))
            except Exception:
                return None
        return IMAGE_DIMS[image_id]

    def create_product(self, shop_id, payload: dict) -> dict:
        return self._req("POST", f"/shops/{shop_id}/products.json", json=payload)

    def product(self, shop_id, product_id: str) -> dict:
        return self._req("GET", f"/shops/{shop_id}/products/{product_id}.json")

    def update_product(self, shop_id, product_id: str, payload: dict) -> dict:
        return self._req("PUT", f"/shops/{shop_id}/products/{product_id}.json", json=payload)

    def delete_product(self, shop_id, product_id: str) -> dict:
        return self._req("DELETE", f"/shops/{shop_id}/products/{product_id}.json")

    def publish(self, shop_id, product_id: str) -> dict:
        return self._req(
            "POST",
            f"/shops/{shop_id}/products/{product_id}/publish.json",
            json={"title": True, "description": True, "images": True, "variants": True, "tags": True, "keyFeatures": True, "shipping_template": True},
        )


# ---------- selection helpers (pure, tested) ----------

def pick_shop(shops: list[dict], shop_id=None) -> dict:
    if shop_id:
        for s in shops:
            if str(s.get("id")) == str(shop_id):
                return s
        raise PrintifyError(f"Shop {shop_id} not found in your Printify account.")
    etsy = [s for s in shops if str(s.get("sales_channel", "")).lower() == "etsy"]
    if len(etsy) == 1:
        return etsy[0]
    if not etsy:
        raise PrintifyError("No Etsy shop is connected to Printify. In Printify: Manage my stores → Connect → Etsy.")
    raise PrintifyError("More than one Etsy shop is connected. Set printify.shop_id in config.yaml (run Check Printify to see IDs).")


def pick_blueprint(blueprints: list[dict], brand: str | None, model: str | None, blueprint_id=None, title_has=None) -> dict:
    if blueprint_id:
        for b in blueprints:
            if str(b.get("id")) == str(blueprint_id):
                return b
    if model:
        brand_l, model_l = (brand or "").lower().replace(" ", ""), str(model).lower()
        for b in blueprints:
            if str(b.get("model", "")).lower() == model_l and brand_l in str(b.get("brand", "")).lower().replace(" ", ""):
                return b
        for b in blueprints:
            if model_l in str(b.get("title", "")).lower() or model_l in str(b.get("model", "")).lower():
                return b
    if title_has:
        options = title_has if isinstance(title_has[0], (list, tuple)) else [title_has]
        for words in options:
            words = [w.lower() for w in words]
            for b in blueprints:
                if all(w in str(b.get("title", "")).lower() for w in words):
                    return b
    raise PrintifyError(f"Couldn't find the {brand or ''} {model or title_has} blank in Printify's catalog.")


def pick_provider(providers: list[dict], preferred: list[str], provider_id=None) -> dict:
    if provider_id:
        for p in providers:
            if str(p.get("id")) == str(provider_id):
                return p
    for name in preferred:
        for p in providers:
            if p.get("title", "").lower() == name.lower():
                return p
    us = [p for p in providers if str((p.get("location") or {}).get("country", "")).upper() == "US"]
    if us:
        return us[0]
    if providers:
        return providers[0]
    raise PrintifyError("No print providers offer this blueprint.")


def _color_of(v: dict) -> str:
    opts = v.get("options") or {}
    if opts.get("color"):
        return str(opts["color"])
    return str(v.get("title", "")).split("/")[0].strip()


def _size_of(v: dict) -> str:
    opts = v.get("options") or {}
    if opts.get("size"):
        return str(opts["size"])
    parts = str(v.get("title", "")).split("/")
    return parts[-1].strip() if len(parts) > 1 else ""


def _has_color(variants: list[dict]) -> bool:
    return any((v.get("options") or {}).get("color") for v in variants)


def pick_colors(variants: list[dict], spec: dict, prof: dict) -> list[str]:
    """Pick product colors that suit the design. [] means the product has no color choice (e.g. a white mug)."""
    if not _has_color(variants):
        return []
    available = []
    for v in variants:
        c = _color_of(v)
        if c and c not in available:
            available.append(c)
    if prof.get("colors") == "all":
        return available[: int(prof.get("colors_per_product", 4))]
    lower = {c.lower(): c for c in available}
    cmap = prof.get("color_map") or SHIRT_TO_PRINTIFY
    primary = cmap.get(spec["shirt"], "Black")
    light_ink = luminance(spec["ink"]) > 0.5
    pool = prof.get("dark_shirts" if light_ink else "light_shirts") or []
    want = [primary] + [c for c in pool if c.lower() != primary.lower()]
    chosen = []
    for w in want:
        if w.lower() in lower and lower[w.lower()] not in chosen:
            chosen.append(lower[w.lower()])
        if len(chosen) >= int(prof.get("colors_per_product", 4)):
            break
    if not chosen:
        fallback = "Black" if light_ink else "White"
        if fallback.lower() in lower:
            chosen = [lower[fallback.lower()]]
    if not chosen:
        raise PrintifyError(f"None of the configured colors exist for this provider. Available: {', '.join(available[:20])}")
    return chosen


def build_variants(variants: list[dict], colors: list[str], sizes, price: float, upcharge: dict) -> list[dict]:
    base = int(round(price * 100))
    out = []
    for v in variants:
        c, s = _color_of(v), _size_of(v)
        if (not colors or c in colors) and (not sizes or s in sizes):
            out.append({"id": v["id"], "price": base + int(upcharge.get(s, 0)), "is_enabled": True})
    if not out:
        raise PrintifyError("No variants matched the chosen colors and sizes.")
    return out[:100]


IMAGE_DIMS: dict[str, tuple[int, int]] = {}  # Printify image id -> (width, height) of what we uploaded


def trim_png(data: bytes, pad_frac: float = 0.02) -> tuple[bytes, int, int]:
    """Cut away empty transparent margins so placement math works on the artwork itself."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if img.mode != "RGBA":
            return data, img.width, img.height
        bbox = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if not bbox:
            return data, img.width, img.height
        pad = int(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * pad_frac)
        box = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad))
        if box == (0, 0, img.width, img.height):
            return data, img.width, img.height
        img = img.crop(box)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), img.width, img.height
    except Exception:
        return data, 0, 0


def print_area(variants: list[dict], variant_ids: list, position: str = "front") -> tuple[float, float] | None:
    ids = set(variant_ids)
    for v in variants:
        if v.get("id") in ids:
            for ph in v.get("placeholders") or []:
                if ph.get("position") == position and ph.get("width") and ph.get("height"):
                    return float(ph["width"]), float(ph["height"])
    return None


def fit_spot(spot: dict, img: tuple[int, int] | None, area: tuple[float, float] | None) -> dict:
    """Printify placement: scale = image width / print-area width; x, y = image center (0-1).
    A spot with max_w / max_h is a box the WHOLE artwork must fit inside, so nothing is ever cut off.
    top = where the art's top edge sits (chest placement); without it, y is the center."""
    if not ("max_w" in spot or "max_h" in spot) or not img or not img[0] or not area:
        return {"x": float(spot.get("x", 0.5)), "y": float(spot.get("y", 0.42)), "scale": float(spot.get("scale", 0.9))}
    iw, ih = img
    aw, ah = area
    max_w, max_h = float(spot.get("max_w", 0.9)), float(spot.get("max_h", 0.9))
    ratio = (ih / iw) * (aw / ah)  # art height as a fraction of area height, per 1.0 of scale
    scale = min(max_w, max_h / ratio)
    h = scale * ratio
    y = float(spot["top"]) + h / 2 if "top" in spot else float(spot.get("y", 0.5))
    y = min(max(y, h / 2), 1 - h / 2) if h <= 1 else 0.5
    x = float(spot.get("x", 0.5))
    x = min(max(x, scale / 2), 1 - scale / 2) if scale <= 1 else 0.5
    return {"x": round(x, 4), "y": round(y, 4), "scale": round(scale, 4)}


def build_product(listing: dict, image_id: str, blueprint_id: int, provider_id: int, variant_rows: list[dict], placement,
                  variants: list[dict] | None = None) -> dict:
    spots = placement if isinstance(placement, list) else [placement or {}]
    area = print_area(variants or [], [v["id"] for v in variant_rows])
    img = IMAGE_DIMS.get(image_id)
    images = [{"id": image_id, **fit_spot(p, img, area), "angle": 0} for p in spots]
    return {
        "title": listing["title"],
        "description": listing["description"],
        "tags": listing["tags"],
        "blueprint_id": blueprint_id,
        "print_provider_id": provider_id,
        "variants": variant_rows,
        "print_areas": [
            {
                "variant_ids": [v["id"] for v in variant_rows],
                "placeholders": [
                    {
                        "position": "front",
                        "images": images,
                    }
                ],
            }
        ],
    }


def mockup_urls(product: dict, limit: int = 3) -> list[str]:
    imgs = product.get("images") or []
    imgs = sorted(imgs, key=lambda i: (not i.get("is_default"), i.get("position") != "front"))
    out = []
    for i in imgs:
        u = i.get("src")
        if u and u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def resolve_catalog(pf: "Printify", pcfg: dict, prof: dict | None = None, blueprints: list | None = None, shops: list | None = None) -> dict:
    """Find the shop, blank, provider and variants for one product profile."""
    prof = prof or {"brand": pcfg.get("blueprint_brand", "Bella+Canvas"), "model": pcfg.get("blueprint_model", "3001"),
                    "blueprint_id": pcfg.get("blueprint_id"), "print_provider_id": pcfg.get("print_provider_id")}
    shop = pick_shop(shops if shops is not None else pf.shops(), pcfg.get("shop_id"))
    bps = blueprints if blueprints is not None else pf.blueprints()
    bp = pick_blueprint(bps, prof.get("brand"), prof.get("model"), prof.get("blueprint_id"), prof.get("title_has"))
    prefs = prof.get("preferred_providers") or pcfg.get("preferred_providers", [])
    prov = pick_provider(pf.providers(bp["id"]), prefs, prof.get("print_provider_id"))
    return {"shop": shop, "bp": bp, "prov": prov, "variants": pf.variants(bp["id"], prov["id"])}


def create_draft(pf: "Printify", cat: dict, listing: dict, png_or_image_id, prof: dict, file_name: str = "design.png") -> dict:
    """Create an UNPUBLISHED Printify product. Nothing goes to Etsy until publish() is called.
    png_or_image_id: PNG bytes (uploaded here) or an already-uploaded Printify image id."""
    colors = pick_colors(cat["variants"], listing["spec"], prof)
    rows = build_variants(cat["variants"], colors, prof.get("sizes"), listing["price"], prof.get("upcharge_cents") or {})
    image_id = pf.upload_png(file_name, png_or_image_id) if isinstance(png_or_image_id, (bytes, bytearray)) else png_or_image_id
    product = pf.create_product(cat["shop"]["id"], build_product(listing, image_id, cat["bp"]["id"], cat["prov"]["id"], rows, prof.get("placement", {}), cat["variants"]))
    return {"product": product, "colors": colors, "rows": rows, "image_id": image_id}


def refit_print_areas(pf: "Printify", shop_id, product_id: str, cat: dict, rows: list[dict], prof: dict) -> list[dict] | None:
    """Rebuild an existing draft's print areas with fit-to-area placement (fixes art cut off by older drafts)."""
    try:
        prod = pf.product(shop_id, product_id)
        image_id = prod["print_areas"][0]["placeholders"][0]["images"][0]["id"]
    except Exception:
        return None
    pf.image_dims(image_id)
    return build_product({"title": "", "description": "", "tags": []}, image_id, cat["bp"]["id"], cat["prov"]["id"], rows,
                         prof.get("placement", {}), cat["variants"])["print_areas"]
