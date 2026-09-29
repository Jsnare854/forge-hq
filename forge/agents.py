"""The agent crew: Scout → Trend Radar → Analyst → Designer/Copywriter → Illustrator → Art Director → Compliance."""
from __future__ import annotations

import json

from . import compliance, trends
from .llm import ask_json
from .spec import FONTS, SHIRTS, STYLES, normalize_spec

RULES = (
    "Hard rules: nothing that depends on trademarks, brand names, pro or college teams, athletes, celebrities, "
    "TV/movie/game/music references, song lyrics, famous catchphrases, or political candidates."
)


def scout(seed: str, n_candidates: int, model: str, ask=ask_json) -> list[dict]:
    prompt = f"""You are the Trend Scout for a print-on-demand Etsy shop selling graphic t-shirts.
Seed idea: {json.dumps(seed)}
Propose {n_candidates} specific micro-niches: a clear audience plus an identity or angle they wear proudly.
Go narrower than the seed (not "nurses" but "night shift ICU nurses"). {RULES}
For each, give 3 phrases a shopper types into Etsy search when looking for a shirt (e.g. "icu nurse shirt", "funny nurse tee").
Reply with only a JSON array:
[{{"niche":"Night shift ICU nurses","audience":"RNs working overnight and people buying them gifts","angle":"coffee, chaos and pride","searchPhrases":["night shift nurse shirt","icu nurse gift","nurse coffee tee"]}}]"""
    out = ask(prompt, model)
    return [c for c in (out if isinstance(out, list) else []) if isinstance(c, dict) and c.get("niche")]


def analyst_from_radar(report: list[dict], keep: int, model: str, ask=ask_json, perf_text: str = "") -> list[dict]:
    prompt = f"""You are the Market Analyst for a new Etsy print-on-demand t-shirt shop (zero reviews, so it must pick demand it can actually rank for).
Below is LIVE Etsy data. For each search query: total active listings (competition) and the top listings by
momentum (favorites per day since listed; HOT = new and gaining fast) and by total favorites (PROVEN).
Etsy does not share sales, so favorites + recency are the demand signal.

{trends.compact(report)}

{perf_text or "The shop has no performance data yet."}

Find the {keep} best opportunities. If the shop has listings that are working, favor related niches/angles (but not duplicates); avoid angles that are not working. An opportunity is a specific audience + angle where buyers are clearly engaging
(new listings gaining favorites fast), and the space is not hopelessly saturated.
For each, study the winning listings and describe WHY they win (humor type, identity, gift angle, visual style, colors, price),
so a designer can make something ORIGINAL that serves the same demand. Never tell the designer to reuse a competitor's phrase.
{RULES}

Reply with only a JSON array, best first:
[{{"niche":"Inshore snook anglers","audience":"...","angle":"...","demand":8,"competition":6,"passion":9,
"why":"one sentence citing the numbers","what_wins":"humor/identity/style patterns in the top listings",
"visual_style":"e.g. retro sunset badge, distressed, navy and sand shirts","price_band":"$24-28",
"evidence_ids":[1234567890,2345678901],"avoid_phrases":["exact phrases competitors already use"]}}]"""
    out = ask(prompt, model)
    return [c for c in (out if isinstance(out, list) else []) if isinstance(c, dict) and c.get("niche")][:keep]


def analyst_no_data(candidates: list[dict], keep: int, model: str, ask=ask_json, perf_text: str = "") -> list[dict]:
    prompt = f"""You are the Market Analyst for a new Etsy print-on-demand t-shirt shop. No live Etsy data is available,
so score from general knowledge and say so in "why".
{perf_text}
Score 1-10: demand, competition (10 = LOW), passion. Keep the best {keep}.
Niches:
{json.dumps(candidates, indent=1)[:30000]}
Reply with only a JSON array: [{{"niche":"...","audience":"...","angle":"...","demand":7,"competition":5,"passion":8,"why":"...","what_wins":"...","visual_style":"...","price_band":"$24-28","evidence_ids":[],"avoid_phrases":[]}}]"""
    out = ask(prompt, model)
    return [c for c in (out if isinstance(out, list) else []) if isinstance(c, dict) and c.get("niche")][:keep]


def designer(briefs: list[dict], per_niche: int, model: str, pricing: dict, illustrated: bool, ask=ask_json) -> list[dict]:
    lo, hi = pricing.get("min_price", 24.99), pricing.get("max_price", 32.99)
    brief_txt = []
    for b in briefs:
        ev = b.get("evidence") or []
        comps = "; ".join(f'"{e["title"][:70]}" ({e["favorites"]} favs, ${e["price"]})' for e in ev[:5])
        brief_txt.append(
            f"- NICHE: {b['niche']}\n  audience: {b.get('audience','')}\n  angle: {b.get('angle','')}\n"
            f"  what wins: {b.get('what_wins','')}\n  visual style that sells: {b.get('visual_style','')}\n"
            f"  price band: {b.get('price_band','')}\n  competitor listings (for context ONLY, do not reuse their phrases): {comps or 'n/a'}\n"
            f"  phrases to avoid: {', '.join(b.get('avoid_phrases') or []) or 'n/a'}"
        )
    art_rules = (
        "- artPrompt: describe an ILLUSTRATED shirt graphic for an image generator: the subject (specific to the niche), "
        "the style (retro screen print, vintage badge, bold vector, distressed, etc. matching what sells), 4-6 named colors, "
        "and where the text sits (e.g. 'text arched above the illustration'). Do not include the text itself; it is added automatically. No brands.\n"
        "- mode: \"illustrated\" for most designs; \"type\" only when a pure typography layout is clearly the stronger choice."
        if illustrated
        else '- mode: always "type".\n- artPrompt: a short illustration idea anyway (saved for later).'
    )
    prompt = f"""You are the Designer and Copywriter for an Etsy print-on-demand t-shirt shop.
For EACH brief below, create {per_niche} ORIGINAL shirt designs that serve the proven demand, then write the listing.

{chr(10).join(brief_txt)}

Design rules:
- The phrase must be original: new wording, not a rearrangement of a competitor's. {RULES}
- Witty, specific insider language the audience actually uses. 2 to 4 short lines, at most 4 words each.
- Size per line: "xl" (hero), "lg", "md", "sm" (small connector).
- style: one of {list(STYLES)} (used for type-only layouts and previews). font: one of {FONTS}.
- shirt: one of {list(SHIRTS)}; ink and accent are hex colors with strong contrast on it.
{art_rules}

Listing rules:
- title: at most 140 characters, front-load what a buyer types, comma-separated, include a gift angle.
- tags: exactly 13, each at most 20 characters, lowercase, no repeats. Borrow the SEARCH TERMS buyers use (they're not anyone's property), not phrases.
- description: 3 short paragraphs. End with exactly: "{compliance.DISCLOSURE_LINE}"
- price: USD between {lo} and {hi}, inside the niche's price band when possible.
- risk: "low" | "medium" | "high" trademark/IP risk, riskNotes: one sentence.

Reply with only a JSON array, one object per design:
[{{"niche":"...","lines":[{{"text":"Tides Wait","size":"md"}},{{"text":"For No One","size":"xl"}}],"style":"sunset","font":"Anton","shirt":"navy","ink":"#fff4e0","accent":"#ff7a3d",
"mode":"illustrated","artPrompt":"...","title":"...","tags":["..."],"description":"...","price":27.99,"risk":"low","riskNotes":"..."}}]"""
    out = ask(prompt, model, max_tokens=16000)
    listings = []
    for x in out if isinstance(out, list) else []:
        if not isinstance(x, dict) or not x.get("lines"):
            continue
        try:
            price = float(x.get("price") or pricing.get("default_price", 27.99))
        except (TypeError, ValueError):
            price = pricing.get("default_price", 27.99)
        listings.append({
            "niche": str(x.get("niche", "")),
            "spec": normalize_spec(x),
            "mode": "illustrated" if (illustrated and x.get("mode") != "type") else "type",
            "art_prompt": str(x.get("artPrompt", "")),
            "title": " ".join(str(x.get("title", "")).split())[:140],
            "tags": compliance.fix_tags(x.get("tags") or []),
            "description": compliance.ensure_disclosure(str(x.get("description", "")).strip()),
            "price": round(min(max(price, lo), hi), 2),
            "risk": x.get("risk") if x.get("risk") in ("low", "medium", "high") else "medium",
            "risk_notes": str(x.get("riskNotes", "")),
        })
    return listings


def run_pipeline(seed: str, cfg: dict, etsy=None, ask=ask_json, log=print, perf_text: str = "") -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (briefs, listings, radar_report)."""
    dr = cfg["drafting"]
    model = cfg["model"]
    n = int(dr.get("niches_per_run", 4))
    k = int(dr.get("designs_per_niche", 2))
    cap = int(dr.get("max_drafts_per_run", 10))
    mult = int(dr.get("candidate_multiplier", 2))
    illustrated = bool(dr.get("illustrated"))

    log(f"SCOUT      seed: {seed}")
    cands = scout(seed, n * mult, model, ask)
    log(f"SCOUT      {len(cands)} candidate niches")
    report: list[dict] = []
    if etsy:
        queries = []
        for c in cands:
            for q in (c.get("searchPhrases") or [])[:2]:
                q = " ".join(str(q).lower().split())
                if q and q not in queries:
                    queries.append(q)
        queries = queries[: int(dr.get("radar_queries", 12))]
        log(f"RADAR      scanning {len(queries)} live Etsy searches…")
        report = trends.scan(etsy, queries, per_query=100, pages=int(dr.get("radar_pages", 1)), top=12, log=log)
        briefs = analyst_from_radar(report, n, model, ask, perf_text) if report else analyst_no_data(cands, n, model, ask, perf_text)
    else:
        briefs = analyst_no_data(cands, n, model, ask, perf_text)
    for b in briefs:
        b["evidence"] = trends.evidence_for(report, b.get("evidence_ids") or []) if report else []
        log(f"ANALYST    D{b.get('demand')} C{b.get('competition')} P{b.get('passion')}  {b['niche']}  ({b.get('why','')})")
    k = max(1, min(k, cap // max(1, len(briefs))))
    listings = designer(briefs, k, model, cfg["pricing"], illustrated, ask)[:cap]
    log(f"DESIGNER   {len(listings)} designs + listings")
    by_niche = {b["niche"].lower(): b for b in briefs}
    for L in listings:
        b = by_niche.get(L["niche"].lower()) or (briefs[0] if len(briefs) == 1 else {})
        L["seed"] = seed
        L["evidence"] = b.get("evidence", [])[:5]
        L["brief"] = {key: b.get(key) for key in ("why", "what_wins", "visual_style", "price_band", "demand", "competition", "passion")}
        L["flags"] = compliance.check(L)
        if compliance.blocking([f for f in L["flags"] if f["kind"] in ("trademark", "too_close")]):
            L["risk"] = "high"
    return briefs, listings, report
