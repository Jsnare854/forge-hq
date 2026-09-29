"""Learning loop: reads YOUR shop's public Etsy numbers so the agents steer toward what works for you.

Uses public listing data (views, favorites, age). Per-listing sales need Etsy seller login (OAuth),
which this doesn't use yet, so views and favorites are the signal.
"""
from __future__ import annotations

import time

from .trends import slim


def shop_performance(etsy, shop_name: str, log=print) -> dict | None:
    if not etsy or not shop_name:
        return None
    try:
        shop = etsy.find_shop(shop_name)
        if not shop:
            log(f"  LEARNING  couldn't find Etsy shop '{shop_name}'. Set etsy_shop_name in config.yaml.")
            return None
        raw = etsy.shop_listings(shop["shop_id"])
    except Exception as e:
        log(f"  LEARNING  shop stats failed: {e}")
        return None
    now = time.time()
    rows = []
    for it in raw:
        r = slim(it, now)
        views = int(it.get("views") or 0)
        r["views"] = views
        r["views_per_day"] = round(views / max(1, r["age_days"]), 2)
        rows.append(r)
    rows.sort(key=lambda r: (r["favorites"], r["views_per_day"]), reverse=True)
    mature = [r for r in rows if r["age_days"] >= 21]
    return {
        "shop": shop.get("shop_name"),
        "sales_total": shop.get("transaction_sold_count"),
        "active": len(rows),
        "winners": [r for r in rows if r["favorites"] >= 3 or r["views_per_day"] >= 5][:10],
        "duds": [r for r in mature if r["favorites"] == 0 and r["views_per_day"] < 1][:10],
        "all": rows,
    }


def compact(perf: dict | None) -> str:
    if not perf or not perf["active"]:
        return ""
    lines = [f"YOUR SHOP ({perf['shop']}): {perf['active']} active listings, {perf.get('sales_total') or 0} total sales."]
    if perf["winners"]:
        lines.append("Working (lean into these niches/angles/styles):")
        lines += [f"  + {r['title'][:90]} | {r['views']} views, {r['favorites']} favs, {r['age_days']}d" for r in perf["winners"]]
    if perf["duds"]:
        lines.append("Not working after 3+ weeks (avoid repeating these angles):")
        lines += [f"  - {r['title'][:90]} | {r['views']} views, 0 favs, {r['age_days']}d" for r in perf["duds"]]
    return "\n".join(lines)


def report_markdown(perf: dict) -> str:
    out = [f"## Weekly shop report: {perf['shop']}", "",
           f"**Active listings:** {perf['active']}  ·  **Total sales (all time):** {perf.get('sales_total') or 0}", ""]
    if perf["all"]:
        out.append("| Listing | Age | Views | Views/day | Favorites |\n|---|---|---|---|---|")
        for r in perf["all"][:25]:
            out.append(f"| [{r['title'][:60]}]({r['url']}) | {r['age_days']}d | {r['views']} | {r['views_per_day']} | {r['favorites']} |")
    out.append("")
    if perf["winners"]:
        out.append("**🔥 Working:** the agents will make more in these directions.")
    if perf["duds"]:
        out.append(f"**🧊 {len(perf['duds'])} listings have zero favorites after 3+ weeks.** Consider new photos or a better title, or deactivate them to keep the shop focused.")
    if not perf["winners"] and perf["active"] < 20:
        out.append("It's early. Most new shops need 20–30 listings and 3–6 weeks before Etsy traffic picks up. Keep approving steadily.")
    return "\n".join(out)
