"""Product families: one design becomes a tee, a sweatshirt, a hoodie and a mug (each its own Etsy listing)."""
from __future__ import annotations

import copy
import re

from . import compliance

APPAREL_WORDS = re.compile(r"\b(t-?shirts?|tees?|shirts?)\b", re.I)


def profiles(cfg: dict) -> list[dict]:
    """Enabled product profiles, in config order. Falls back to a single tee from the printify section."""
    prods = [p for p in (cfg.get("products") or []) if p.get("enabled", True)]
    if prods:
        return prods
    pc = cfg.get("printify", {})
    return [{
        "key": "tee", "name": "T-Shirt", "noun": "Shirt", "brand": pc.get("blueprint_brand", "Bella+Canvas"),
        "model": pc.get("blueprint_model", "3001"), "blueprint_id": pc.get("blueprint_id"), "print_provider_id": pc.get("print_provider_id"),
        "sizes": pc.get("sizes"), "upcharge_cents": pc.get("upcharge_cents", {}), "colors_per_product": pc.get("colors_per_product", 4),
        "dark_shirts": pc.get("dark_shirts"), "light_shirts": pc.get("light_shirts"), "placement": pc.get("placement", {}),
        "price": None,
    }]


def _swap(text: str, noun: str) -> str:
    return APPAREL_WORDS.sub(lambda m: noun if m.group(0)[0].isupper() else noun.lower(), text)


def _trim_title(t: str) -> str:
    t = " ".join(t.split())
    if len(t) <= 140:
        return t
    cut = t[:140].rsplit(",", 1)[0]
    return cut if len(cut) > 60 else t[:140]


def adapt(listing: dict, prof: dict) -> dict:
    """Copy of the listing rewritten for this product (title, tags, description, price)."""
    L = copy.deepcopy(listing)
    noun = prof.get("noun") or prof.get("name", "")
    if prof.get("price"):
        L["price"] = float(prof["price"])
    if prof.get("key") == "tee" or noun.lower() == "shirt":
        return L
    title = _swap(L["title"], noun)
    if title == L["title"]:
        title = f"{noun}, {title}"
    L["title"] = _trim_title(title)
    extra = [t.lower() for t in (prof.get("tags") or [])]
    swapped = [_swap(t, noun.lower()) for t in L.get("tags", [])]
    L["tags"] = compliance.fix_tags(extra + swapped)
    desc = _swap(L.get("description", ""), noun.lower())
    desc = desc.replace(compliance.DISCLOSURE_LINE, "").strip()
    if prof.get("blurb"):
        desc = f"{desc}\n\n{prof['blurb']}"
    L["description"] = compliance.ensure_disclosure(desc)
    return L
