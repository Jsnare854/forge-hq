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


def format_issue(listing: dict, mockup_urls=None, print_url: str | None = None, draft_id: str = "", product_id: str = "") -> tuple[str, str]:
    """Build the approval issue. mockup_urls may be a single URL or a list (real Printify mockups).
    listing["products"] (optional): {key: {"name", "price", "product_id", "mockups", "on"}} for product families."""
    import json as _json
    spec = listing["spec"]
    if isinstance(mockup_urls, str):
        mockup_urls = [mockup_urls]
    mockup_urls = [u for u in (mockup_urls or []) if u]
    risk = str(listing.get("risk", "low")).upper()
    mode = listing.get("mode", "type")
    title = f"{listing.get('niche') or 'Design'}: {phrase(spec)}"[:120]
    flags = listing.get("flags") or []
    flag_md = "\n".join(f"- {'⛔' if f['bad'] else '⚠️'} {f['msg']}" for f in flags) or "- No automatic flags."
    products = listing.get("products") or {}
    fam_mocks = [(p.get("mockups") or [None])[0] for p in products.values() if p.get("mockups")]
    shown = fam_mocks if len(fam_mocks) > 1 else mockup_urls[:3]
    imgs = " ".join(f'<img src="{u}" width="240">' for u in shown[:4])
    brief = listing.get("brief") or {}
    ev = listing.get("evidence") or []
    why = []
    if brief.get("why"):
        why.append(f"**Why this niche:** {brief['why']}")
    if brief.get("what_wins"):
        why.append(f"**What's selling:** {brief['what_wins']}")
    if brief.get("visual_style"):
        why.append(f"**Style buyers want:** {brief['visual_style']}  ·  **Price band:** {brief.get('price_band') or 'n/a'}")
    if ev:
        why.append("\n| Comparable listing (research only) | Favorites | Age | Price |\n|---|---|---|---|")
        for e in ev[:5]:
            t = str(e.get("title", ""))[:70].replace("|", "/")
            why.append(f"| [{t}]({e.get('url','')}) | {e.get('favorites','')} | {e.get('age_days','')}d | ${e.get('price','')} |")
    if not why:
        why.append("_No live Etsy evidence for this one (Claude's judgment only)._")
    design_note = (
        "Illustrated artwork was generated for this design. Editing the lines below does NOT redraw the art; reject and redraft instead."
        if mode == "illustrated"
        else "Edit lines/style/font/colors to change the design; the publisher re-renders it."
    )
    parts = [
        MARKER,
        f"<!-- forge:draft={draft_id} product={product_id} mode={mode} -->",
        f"<!-- forge:products={_json.dumps({k: v.get('product_id', '') for k, v in products.items()}, separators=(',', ':'))} -->" if products else "",
        imgs,
        "",
        f"**Niche:** {listing.get('niche', '')}  ·  **Trademark risk:** {risk}  ·  **Seed:** {listing.get('seed', '')}",
        "",
        "> **Approve:** add the `approved` label. **Reject:** close this issue.",
        "> Before approving you can untick products, change prices, or edit the Title, Tags and Description. The publisher uses your edits.",
        "",
        "### Why this design",
        "\n".join(why),
        "",
        "### Title",
        listing.get("title", ""),
        "",
        "### Tags",
        ", ".join(listing.get("tags", [])),
        "",
        *(
            ["### Products", "_Each ticked product becomes its own Etsy listing. Untick any you don't want; edit prices freely._",
             *[f"- [{'x' if p.get('on', True) else ' '}] {k}: {p.get('name', k)}: ${float(p.get('price') or listing.get('price', 27.99)):.2f}" for k, p in products.items()], ""]
            if products else ["### Price", f"{float(listing.get('price', 27.99)):.2f}", ""]
        ),
        "### Design",
        f"_{design_note}_",
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
        "### Art prompt",
        listing.get("art_prompt", "") or listing.get("image_prompt", "") or "_none_",
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
    dm = re.search(r"```\w*\n(.*?)```", s.get("design", ""), re.S)
    design_raw = dm.group(1).strip() if dm else s.get("design", "")
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
    meta = re.search(r"<!-- forge:draft=(\S*) product=(\S*) mode=(\S*) -->", body)
    ids = {}
    pm = re.search(r"<!-- forge:products=(\{.*?\}) -->", body)
    if pm:
        import json as _json
        try:
            ids = _json.loads(pm.group(1))
        except ValueError:
            ids = {}
    products = {}
    for line in s.get("products", "").split("\n"):
        pr = re.match(r"^\s*-\s*\[([ xX])\]\s*([a-z0-9_-]+)\s*:\s*(.*?)\s*:\s*\$?\s*([0-9]+(?:\.[0-9]+)?)\s*$", line)
        if pr:
            products[pr.group(2)] = {"on": pr.group(1).lower() == "x", "name": pr.group(3), "price": round(float(pr.group(4)), 2), "product_id": ids.get(pr.group(2), "")}
    if products and "tee" in products:
        price = products["tee"]["price"]
    elif products:
        price = next(iter(products.values()))["price"]
    return {
        "draft_id": meta.group(1) if meta else "",
        "product_id": meta.group(2) if meta else "",
        "products": products,
        "mode": meta.group(3) if meta else "type",
        "title": " ".join(s.get("title", "").split()),
        "tags": tags,
        "price": round(price, 2),
        "spec": spec,
        "description": s.get("description", "").strip(),
        "risk": (m.group(1).lower() if m else "medium"),
        "niche": niche.group(1).strip() if niche else "",
        "art_prompt": s.get("art prompt", "") or s.get("ai illustration prompt", ""),
    }
