"""Live Etsy market data via the official Etsy Open API v3 (public listing search).

Etsy does not publish search volume to anyone, so this measures COMPETITION and PROOF OF DEMAND:
how many active listings match a phrase, what the top results charge, how many favorites they hold,
and how many of the top results are new (new listings with favorites = a rising niche).
"""
from __future__ import annotations

import statistics
import time

import requests

API = "https://openapi.etsy.com/v3/application/listings/active"


class Etsy:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.key = api_key
        self.http = session or requests.Session()

    def search_stats(self, phrase: str, limit: int = 25) -> dict:
        r = self.http.get(
            API,
            params={"keywords": phrase, "limit": limit, "sort_on": "score"},
            headers={"x-api-key": self.key},
            timeout=20,
        )
        if r.status_code == 429:
            time.sleep(2)
            r = self.http.get(API, params={"keywords": phrase, "limit": limit, "sort_on": "score"}, headers={"x-api-key": self.key}, timeout=20)
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        prices, favs, new = [], [], 0
        cutoff = time.time() - 90 * 86400
        for it in results:
            p = it.get("price") or {}
            if p.get("amount") is not None and p.get("divisor"):
                prices.append(p["amount"] / p["divisor"])
            favs.append(int(it.get("num_favorers") or 0))
            created = it.get("created_timestamp") or it.get("creation_timestamp") or it.get("original_creation_timestamp")
            if created and created >= cutoff:
                new += 1
        return {
            "phrase": phrase,
            "active_listings": int(data.get("count") or 0),
            "median_price": round(statistics.median(prices), 2) if prices else None,
            "avg_favorites_top": round(sum(favs) / len(favs), 1) if favs else 0,
            "new_in_top_90d": new,
            "sampled": len(results),
        }


def enrich(etsy: Etsy | None, candidates: list[dict], log=print) -> list[dict]:
    """Attach live stats for each candidate's search phrases. Safe no-op without a key."""
    if not etsy:
        return candidates
    for c in candidates:
        stats = []
        for ph in (c.get("searchPhrases") or [])[:3]:
            try:
                stats.append(etsy.search_stats(ph))
                time.sleep(0.25)
            except Exception as e:  # keep going; one bad phrase shouldn't kill the run
                log(f"  Etsy lookup failed for '{ph}': {e}")
        c["etsy"] = stats
    return candidates
