"""Trend Radar: finds what is actually selling on Etsy right now.

Etsy does not publish sales per listing, so we use the same public signals paid tools use:
favorites, how recently the listing went up, and views when Etsy provides them.
  momentum = favorites / days since first listed      (new + loved = catching fire)
Listings are research only. The agents study the demand (niche, angle, style, price) and make
ORIGINAL designs. They never copy a phrase or a design.
"""
from __future__ import annotations

import re
import statistics
import time

APPAREL = re.compile(r"\b(t-?shirts?|tees?|shirts?|sweatshirts?|hoodies?|crewnecks?)\b", re.I)


def _age_days(it: dict, now: float) -> float:
    ts = it.get("original_creation_timestamp") or it.get("created_timestamp") or it.get("creation_timestamp")
    if not ts:
        return 365.0
    return max(3.0, (now - float(ts)) / 86400)


def _price(it: dict):
    p = it.get("price") or {}
    if p.get("amount") is not None and p.get("divisor"):
        return round(p["amount"] / p["divisor"], 2)
    return None


def slim(it: dict, now: float) -> dict:
    favs = int(it.get("num_favorers") or 0)
    age = _age_days(it, now)
    return {
        "id": it.get("listing_id"),
        "title": " ".join(str(it.get("title", "")).split())[:140],
        "tags": [str(t).lower() for t in (it.get("tags") or [])][:13],
        "price": _price(it),
        "favorites": favs,
        "views": it.get("views"),
        "age_days": round(age),
        "momentum": round(favs / age, 2),
        "url": it.get("url") or (f"https://www.etsy.com/listing/{it.get('listing_id')}" if it.get("listing_id") else ""),
    }


def scan(etsy, queries: list[str], per_query: int = 100, pages: int = 1, top: int = 12, log=print) -> list[dict]:
    """For each query: pull live listings, keep apparel, rank by momentum and by raw favorites."""
    now = time.time()
    out = []
    for q in queries:
        raw, count = [], 0
        for page in range(pages):
            try:
                data = etsy.search(q, limit=per_query, offset=page * per_query, sort_on="score")
            except Exception as e:
                log(f"  Etsy search failed for '{q}': {e}")
                break
            count = int(data.get("count") or count)
            raw += data.get("results") or []
            time.sleep(0.2)
        items = [slim(it, now) for it in raw if APPAREL.search(str(it.get("title", "")))]
        seen, uniq = set(), []
        for it in items:
            if it["id"] not in seen:
                seen.add(it["id"])
                uniq.append(it)
        hot = sorted(uniq, key=lambda x: x["momentum"], reverse=True)[:top]
        proven = [x for x in sorted(uniq, key=lambda x: x["favorites"], reverse=True) if x not in hot][: max(3, top // 3)]
        prices = [x["price"] for x in uniq if x["price"]]
        new_hits = [x for x in uniq if x["age_days"] <= 90 and x["favorites"] >= 20]
        out.append({
            "query": q,
            "active_listings": count,
            "sampled": len(uniq),
            "median_price": round(statistics.median(prices), 2) if prices else None,
            "new_listings_with_traction": len(new_hits),
            "hot": hot,
            "proven": proven,
        })
        log(f"  RADAR  {q!r}: {count:,} listings, {len(new_hits)} new ones with traction")
    return out


def compact(report: list[dict], max_chars: int = 45000) -> str:
    """Trim the report for the Analyst prompt."""
    import json

    lines = []
    for r in report:
        head = {k: r[k] for k in ("query", "active_listings", "sampled", "median_price", "new_listings_with_traction")}
        lines.append("QUERY " + json.dumps(head))
        for tag, group in (("HOT", r["hot"]), ("PROVEN", r["proven"])):
            for it in group:
                lines.append(f"  {tag} id={it['id']} fav={it['favorites']} age={it['age_days']}d mom={it['momentum']} ${it['price']} | {it['title']} | tags: {', '.join(it['tags'][:8])}")
    text = "\n".join(lines)
    return text[:max_chars]


def evidence_for(report: list[dict], ids: list) -> list[dict]:
    by_id = {}
    for r in report:
        for it in r["hot"] + r["proven"]:
            by_id[str(it["id"])] = it
    return [by_id[str(i)] for i in ids if str(i) in by_id]
