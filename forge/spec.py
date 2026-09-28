"""Design spec + listing model, and the editable GitHub-issue format they round-trip through."""
from __future__ import annotations

import re

SIZES = {"xl": 1.0, "lg": 0.72, "md": 0.48, "sm": 0.3}
STYLES = {
    "stack": "Stacked bold",
    "split": "Split with rules",
    "badge": "Round badge",
    "sunset": "Retro sunset",
    "stamp": "Distressed stamp",
    "script": "Script + block",
}
FONTS = ["Anton", "Archivo Black", "Alfa Slab One", "Bebas Neue", "Pacifico", "Permanent Marker"]
SHIRTS = {
    "black": "#141414",
    "white": "#f4f4f1",
    "heather": "#9a9ea3",
    "navy": "#1d2a44",
    "sand": "#d9c7a3",
    "forest": "#27432f",
    "maroon": "#5c1f27",
}
# Designer shirt key -> Printify color name on the Bella+Canvas 3001.
SHIRT_TO_PRINTIFY = {
    "black": "Black",
    "white": "White",
    "heather": "Athletic Heather",
    "navy": "Navy",
    "sand": "Soft Cream",
    "forest": "Forest",
    "maroon": "Maroon",
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_spec(d: dict) -> dict:
    raw = d.get("lines") or []
    lines = []
    for ln in raw:
        if isinstance(ln, str):
            ln = {"text": ln, "size": "lg"}
        text = str(ln.get("text", "")).strip()
        size = str(ln.get("size", "lg")).lower()
        if text:
            lines.append({"text": text, "size": size if size in SIZES else "lg"})
    lines = lines[:5] or [{"text": "YOUR", "size": "md"}, {"text": "TEXT", "size": "xl"}]
    style = d.get("style") if d.get("style") in STYLES else "stack"
    font = d.get("font") if d.get("font") in FONTS else "Anton"
    ink = d.get("ink") if _HEX.match(str(d.get("ink", ""))) else "#ffffff"
    accent = d.get("accent") if _HEX.match(str(d.get("accent", ""))) else "#ffb84d"
    shirt = str(d.get("shirt", "")).lower()
    shirt = shirt if shirt in SHIRTS else "black"
    return {"lines": lines, "style": style, "font": font, "ink": ink.lower(), "accent": accent.lower(), "shirt": shirt}


def lines_to_text(lines: list[dict]) -> str:
    return " | ".join(f"{l['size']}: {l['text']}" for l in lines)


def text_to_lines(s: str) -> list[dict]:
    out = []
    for part in s.split("|"):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(xl|lg|md|sm)\s*:\s*(.+)$", part, re.I)
        out.append({"size": m.group(1).lower(), "text": m.group(2).strip()} if m else {"size": "lg", "text": part})
    return out


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def phrase(spec: dict) -> str:
    return " ".join(l["text"] for l in spec["lines"])


# ---------------- issue body ----------------

MARKER = "<!-- forge:v1 -->"


def format_issue(listing: dict, mockup_url: str | None = None, print_url: str | None = None) -> tuple[str, str]:
    spec = listing["spec"]
    risk = str(listing.get("risk", "low")).upper()
    title = f"{listing.get('niche') or 'Design'}: {phrase(spec)}"[:120]
    flags = listing.get("flags") or []
    flag_md = "\n".join(f"- {'⛔' if f['bad'] else '⚠️'} {f['msg']}" for f in flags) or "- No automatic flags."
    parts = [
        MARKER,
        f"![Shirt mockup]({mockup_url})" if mockup_url else "",
        "",
        f"**Niche:** {listing.get('niche', '')}  ·  **Trademark risk:** {risk}  ·  **Seed:** {listing.get('seed', '')}",
        "",
        "> **Approve:** add the `approved` label. **Reject:** close this issue.",
        "> You can edit the Title, Tags, Price, Design or Description below before approving. The publisher uses your edits.",
        "",
        "### Title",
        listing.get("title", ""),
        "",
        "### Tags",
        ", ".join(listing.get("tags", [])),
        "",
        "### Price",
        f"{float(listing.get('price', 27.99)):.2f}",
        "",
        "### Design",
        "```text",
        f"lines: {lines_to_text(spec['lines'])}",
        f"style: {spec['style']}",
        f"font: {spec['font']}",
        f"ink: {spec['ink']}",
        f"accent: {spec['accent']}",
        f"shirt: {spec['shirt']}",
        "```",
        "",
        "### Description",
        listing.get("description", ""),
        "",
        "### Compliance",
        flag_md,
        f"\n{listing.get('risk_notes', '')}".rstrip(),
        "",
        "### AI illustration prompt",
        listing.get("image_prompt", "") or "_none_",
        "",
        f"[Full-size print file]({print_url})" if print_url else "",
    ]
    return title, "\n".join(parts).strip() + "\n"


def _sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cur = None
    buf: list[str] = []
    for line in body.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip().lower(), []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def parse_issue(body: str) -> dict:
    if MARKER not in (body or ""):
        raise ValueError("This issue wasn't created by Forge HQ (marker missing).")
    s = _sections(body)
    design_raw = re.sub(r"^```\w*\s*|```\s*$", "", s.get("design", ""), flags=re.M).strip()
    d: dict = {}
    for line in design_raw.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            d[k.strip().lower()] = v.strip()
    spec = normalize_spec({**d, "lines": text_to_lines(d.get("lines", ""))})
    tags = [t.strip().lower() for t in re.split(r"[,\n]", s.get("tags", "")) if t.strip()]
    try:
        price = float(re.sub(r"[^0-9.]", "", s.get("price", "")) or 27.99)
    except ValueError:
        price = 27.99
    m = re.search(r"\*\*Trademark risk:\*\*\s*(\w+)", body)
    niche = re.search(r"\*\*Niche:\*\*\s*(.*?)\s*·", body)
    return {
        "title": " ".join(s.get("title", "").split()),
        "tags": tags,
        "price": round(price, 2),
        "spec": spec,
        "description": s.get("description", "").strip(),
        "risk": (m.group(1).lower() if m else "medium"),
        "niche": niche.group(1).strip() if niche else "",
        "image_prompt": s.get("ai illustration prompt", ""),
    }
