"""Local compliance checks. Catches obvious problems; it is NOT a substitute for a USPTO search."""
from __future__ import annotations

import re

from .spec import phrase

TRADEMARK_WORDS = [
    "nike", "adidas", "under armour", "disney", "marvel", "pixar", "star wars", "harry potter", "hogwarts",
    "nfl", "nba", "mlb", "nhl", "ncaa", "mls", "super bowl", "march madness", "olympic", "olympics",
    "coca-cola", "pepsi", "starbucks", "dunkin", "taylor swift", "swiftie", "eras tour", "barbie",
    "pokemon", "pokémon", "nintendo", "zelda", "hello kitty", "harley", "harley-davidson",
    "lego", "peanuts", "snoopy", "grinch", "dr seuss", "seuss", "sesame street",
    "yellowstone", "buccaneers", "bucs", "tampa bay lightning", "gators", "seminoles",
    "salt life", "life is good", "guy harvey", "costa del mar", "columbia pfg", "patagonia",
    "margaritaville", "jimmy buffett", "parrothead", "stranger things", "bluey", "minecraft", "fortnite",
    "roblox", "nascar", "pga", "ufc", "wwe", "budweiser", "bud light", "jack daniels", "jägermeister",
    "hooters", "waffle house", "publix", "chick-fil-a", "mcdonalds", "mcdonald's", "walmart",
    "tiktok", "instagram", "iphone", "tesla", "chevy", "chevrolet",
    "john deere", "carhartt", "red bull", "monster energy", "jurassic park", "ghostbusters",
    "dunder mifflin", "schitt", "golden girls", "bob ross", "beatles", "grateful dead",
    "just do it", "keep calm and", "i'm lovin' it",
]
# Common words that are also brands: flagged as warnings, not blockers.
WARN_WORDS = ["target", "apple", "google", "friends", "rays", "dodge", "ford", "canes", "the office",
              "stanley", "yeti", "jeep", "mario", "coke", "elvis"]
AI_DISCLOSURE = re.compile(r"ai tools|help of ai|using ai|ai-assisted", re.I)


def check(listing: dict) -> list[dict]:
    flags: list[dict] = []
    spec = listing.get("spec") or {"lines": []}
    blob = " ".join(
        [listing.get("title", ""), phrase(spec) if spec.get("lines") else "", " ".join(listing.get("tags", [])), listing.get("description", "")]
    ).lower()
    for w in TRADEMARK_WORDS:
        if re.search(r"(^|[^a-z])" + re.escape(w) + r"([^a-z]|$)", blob):
            flags.append({"bad": True, "kind": "trademark", "msg": f'Possible trademark or brand: "{w}". Remove it before listing.'})
    for w in WARN_WORDS:
        if re.search(r"(^|[^a-z])" + re.escape(w) + r"([^a-z]|$)", blob):
            flags.append({"bad": False, "kind": "trademark", "msg": f'Contains "{w}", which is also a brand name. Fine as a normal word; not fine as the brand.'})
    title = listing.get("title", "")
    if not title:
        flags.append({"bad": True, "kind": "title", "msg": "Missing title."})
    elif len(title) > 140:
        flags.append({"bad": True, "kind": "title", "msg": f"Title is {len(title)} characters (Etsy max 140)."})
    tags = listing.get("tags", [])
    if len(tags) > 13:
        flags.append({"bad": True, "kind": "tags", "msg": f"{len(tags)} tags (Etsy max 13)."})
    elif len(tags) < 13:
        flags.append({"bad": False, "kind": "tags", "msg": f"Only {len(tags)} tags. Use all 13."})
    long_tags = [t for t in tags if len(t) > 20]
    if long_tags:
        flags.append({"bad": True, "kind": "tags", "msg": f"Tags over 20 characters: {', '.join(long_tags)}"})
    seen, dups = set(), []
    for t in tags:
        if t.lower() in seen:
            dups.append(t)
        seen.add(t.lower())
    if dups:
        flags.append({"bad": False, "kind": "tags", "msg": f"Duplicate tags: {', '.join(dups)}"})
    if not AI_DISCLOSURE.search(listing.get("description", "")):
        flags.append({"bad": False, "kind": "disclosure", "msg": "Description is missing the AI-assisted design disclosure."})
    return flags


def blocking(flags: list[dict]) -> list[dict]:
    return [f for f in flags if f["bad"]]


def fix_tags(tags: list[str]) -> list[str]:
    """Trim, dedupe, drop over-length tags, cap at 13."""
    out, seen = [], set()
    for t in tags:
        t = " ".join(str(t).lower().split())
        if not t or len(t) > 20 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:13]


DISCLOSURE_LINE = "Design created by our shop with the help of AI tools and printed on demand by our production partner."


def ensure_disclosure(description: str) -> str:
    return description if AI_DISCLOSURE.search(description or "") else (description.rstrip() + "\n\n" + DISCLOSURE_LINE).strip()
