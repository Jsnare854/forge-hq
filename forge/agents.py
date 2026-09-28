"""The agent crew: Scout, Analyst, Designer + Copywriter, Compliance."""
from __future__ import annotations

import json

from . import compliance
from .etsy import Etsy, enrich
from .llm import ask_json
from .spec import FONTS, SHIRTS, STYLES, normalize_spec

RULES = (
    "Hard rules: nothing that depends on trademarks, brand names, pro or college teams, athletes, celebrities, "
    "TV/movie/game/music references, song lyrics, famous catchphrases, or political candidates."
)


def scout(seed: str, n_candidates: int, model: str, ask=ask_json) -> list[dict]:
    prompt = f"""You are the Trend Scout for a new print-on-demand Etsy shop selling graphic t-shirts.
Seed idea: {json.dumps(seed)}
Propose {n_candidates} specific micro-niches: a clear audience plus an identity or angle they wear proudly.
Go narrower than the seed (not "nurses" but "night shift ICU nurses"). {RULES}
For each, give 3 short phrases a shopper would type into Etsy search (e.g. "icu nurse shirt").
Reply with only a JSON array:
[{{"niche":"Night shift ICU nurses","audience":"RNs working overnight and people buying them gifts","angle":"coffee, chaos and pride","season":"evergreen, peaks in May","searchPhrases":["night shift nurse shirt","icu nurse gift","nurse coffee tee"]}}]"""
    out = ask(prompt, model)
    return [c for c in (out if isinstance(out, list) else []) if isinstance(c, dict) and c.get("niche")]


def analyst(candidates: list[dict], keep: int, model: str, ask=ask_json) -> list[dict]:
    has_data = any(c.get("etsy") for c in candidates)
    data_note = (
        "Each niche includes LIVE Etsy data for its search phrases: active_listings (competition), median_price, "
        "avg_favorites_top (proof buyers engage), new_in_top_90d (new listings ranking = room for new sellers). "
        "Base your scores on this data. Low competition means active_listings under ~20,000; very saturated is over ~100,000."
        if has_data
        else "No live Etsy data is available. Score from general knowledge and say so in 'why'."
    )
    prompt = f"""You are the Niche Analyst for a new print-on-demand Etsy t-shirt shop with zero reviews, so it must pick niches it can rank in.
{data_note}
Score each niche 1-10: demand (buyer interest), competition (10 = LOW competition), passion (how strongly buyers identify with it and buy it as a gift).
Keep the best {keep} for a brand-new shop and drop the rest.
Niches:
{json.dumps(candidates, indent=1)[:40000]}
Reply with only a JSON array of the kept niches, best first:
[{{"niche":"...","audience":"...","angle":"...","demand":8,"competition":6,"passion":9,"why":"one sentence citing the data","dataBacked":{str(has_data).lower()}}}]"""
    out = ask(prompt, model)
    kept = [c for c in (out if isinstance(out, list) else []) if isinstance(c, dict) and c.get("niche")]
    by_name = {c["niche"].lower(): c for c in candidates}
    for k in kept:
        src = by_name.get(k["niche"].lower(), {})
        k.setdefault("audience", src.get("audience", ""))
        k.setdefault("angle", src.get("angle", ""))
        k["etsy"] = src.get("etsy", [])
    return kept[:keep]


def designer(niches: list[dict], per_niche: int, model: str, pricing: dict, ask=ask_json) -> list[dict]:
    lo, hi = pricing.get("min_price", 24.99), pricing.get("max_price", 32.99)
    prompt = f"""You are the Designer, Copywriter and Compliance team for a new print-on-demand Etsy t-shirt shop.
For EACH niche below, create {per_niche} original typography t-shirt designs and write the Etsy listing for each.

Niches:
{chr(10).join(f"- {n['niche']} | audience: {n.get('audience','')} | angle: {n.get('angle','')}" for n in niches)}

Design rules:
- Original phrases only. {RULES} Prefer witty, specific insider language the audience actually uses.
- 2 to 4 lines, each at most 4 words. Size per line: "xl" (hero), "lg", "md", or "sm" (small connector like "powered by").
- style: one of {list(STYLES)}. "badge" needs 3-4 lines (first and last curve around the ring). "script" uses line 1 as a handwritten word.
- font: one of {FONTS}.
- shirt: one of {list(SHIRTS)}. ink and accent are hex colors with strong contrast against that shirt.
- imagePrompt: a prompt for an AI image generator for an illustrated version: flat vector or retro screen-print style, subject specific to the niche, transparent background, no text.

Listing rules:
- title: at most 140 characters, front-load what a buyer types ("Night Shift Nurse Shirt, ..."), comma-separated, include a gift angle.
- tags: exactly 13, each at most 20 characters, lowercase, no repeats, mix broad and long-tail.
- description: 3 short paragraphs (who it's for and the joke; soft unisex tee; gift line). End with exactly: "{compliance.DISCLOSURE_LINE}"
- price: USD between {lo} and {hi}.
- risk: "low", "medium" or "high" trademark/IP risk; riskNotes: one sentence why.

Reply with only a JSON array, one object per design:
[{{"niche":"...","lines":[{{"text":"Powered By","size":"sm"}},{{"text":"Coffee &","size":"lg"}},{{"text":"Charting","size":"lg"}}],"style":"stamp","font":"Archivo Black","shirt":"black","ink":"#f2f2f2","accent":"#58d6ff","imagePrompt":"...","title":"...","tags":["..."],"description":"...","price":27.99,"risk":"low","riskNotes":"..."}}]"""
    out = ask(prompt, model, max_tokens=16000)
    listings = []
    for x in out if isinstance(out, list) else []:
        if not isinstance(x, dict) or not x.get("lines"):
            continue
        try:
            price = float(x.get("price") or pricing.get("default_price", 27.99))
        except (TypeError, ValueError):
            price = pricing.get("default_price", 27.99)
        L = {
            "niche": str(x.get("niche", "")),
            "spec": normalize_spec(x),
            "title": " ".join(str(x.get("title", "")).split())[:140],
            "tags": compliance.fix_tags(x.get("tags") or []),
            "description": compliance.ensure_disclosure(str(x.get("description", "")).strip()),
            "price": round(min(max(price, lo), hi), 2),
            "risk": x.get("risk") if x.get("risk") in ("low", "medium", "high") else "medium",
            "risk_notes": str(x.get("riskNotes", "")),
            "image_prompt": str(x.get("imagePrompt", "")),
        }
        listings.append(L)
    return listings


def run_pipeline(seed: str, cfg: dict, etsy: Etsy | None = None, ask=ask_json, log=print) -> tuple[list[dict], list[dict]]:
    dr = cfg["drafting"]
    model = cfg["model"]
    n = int(dr.get("niches_per_run", 4))
    k = int(dr.get("designs_per_niche", 2))
    cap = int(dr.get("max_drafts_per_run", 10))
    mult = int(dr.get("candidate_multiplier", 2))

    log(f"SCOUT      seed: {seed}")
    cands = scout(seed, n * mult, model, ask)
    log(f"SCOUT      {len(cands)} candidate niches")
    if etsy:
        log("SCOUT      pulling live Etsy data…")
        enrich(etsy, cands, log)
    niches = analyst(cands, n, model, ask)
    for c in niches:
        log(f"ANALYST    D{c.get('demand')} C{c.get('competition')} P{c.get('passion')}  {c['niche']}  ({c.get('why','')})")
    k = max(1, min(k, cap // max(1, len(niches))))
    listings = designer(niches, k, model, cfg["pricing"], ask)[:cap]
    log(f"DESIGNER   {len(listings)} designs + listings")
    for L in listings:
        L["seed"] = seed
        L["flags"] = compliance.check(L)
        if compliance.blocking([f for f in L["flags"] if f["kind"] == "trademark"]):
            L["risk"] = "high"
        log(f"COMPLIANCE {L['risk'].upper():6} {L['niche']}: {' '.join(l['text'] for l in L['spec']['lines'])}")
    return niches, listings
