"""Memory of what the crew already made, so it stops repeating itself."""
from __future__ import annotations

import datetime as dt
import json
import random
import re
from pathlib import Path

ART_STYLES = [
    "retro 1970s sunset stripes", "vintage national-park badge", "bold cartoon mascot", "hand-drawn ink line art",
    "distressed collegiate varsity", "groovy psychedelic lettering", "western rodeo poster", "old-school tattoo flash",
    "minimalist single-line drawing", "watercolor splash", "vintage travel poster", "comic book pop art",
    "woodcut / linocut print", "kawaii cute illustration", "80s neon synthwave", "botanical engraving",
]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", text.lower())) - {"the", "a", "an", "of", "and", "&", "my", "i", "in", "on", "to", "is"}


def similar(a: str, b: str, threshold: float = 0.6) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= threshold


class History:
    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            self.items = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.items = []

    def recent(self, key: str, n: int) -> list[str]:
        out = []
        for it in reversed(self.items):
            v = it.get(key)
            if v and v not in out:
                out.append(v)
            if len(out) >= n:
                break
        return out

    def is_repeat(self, phrase: str) -> bool:
        return any(similar(phrase, it.get("phrase", "")) for it in self.items[-400:])

    def add(self, seed: str, niche: str, phrase: str, style: str):
        self.items.append({"date": dt.date.today().isoformat(), "seed": seed, "niche": niche, "phrase": phrase, "style": style})
        self.items = self.items[-600:]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, indent=1))

    def next_seed(self, seeds: list[str]) -> str:
        """Least recently used seed; never-used seeds first, in random order."""
        last_used = {}
        for i, it in enumerate(self.items):
            last_used[it.get("seed")] = i
        unused = [s for s in seeds if s not in last_used]
        if unused:
            return random.choice(unused)
        return min(seeds, key=lambda s: last_used.get(s, -1))

    def styles_for_batch(self, n: int) -> list[str]:
        used = self.recent("style", 8)
        pool = [s for s in ART_STYLES if s not in used] or list(ART_STYLES)
        random.shuffle(pool)
        while len(pool) < n:
            pool += random.sample(ART_STYLES, len(ART_STYLES))
        return pool[:n]
