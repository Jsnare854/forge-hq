"""Art Director: Claude looks at each generated artwork and rejects anything a buyer would call cheap:
misspelled text, garbled letters, muddy colors, weak contrast on the shirt, or anything resembling a brand."""
from __future__ import annotations

import base64

from .config import secret
from .llm import parse_json

MIN_SCORE = 7


def review(previews: list[bytes], expected_text: str, niche: str, model: str, client=None) -> dict:
    """Returns {"best": index or None, "scores": [...], "notes": str}."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic(api_key=secret("ANTHROPIC_API_KEY"))
    content = []
    for i, p in enumerate(previews):
        content.append({"type": "text", "text": f"Option {i}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(p).decode()}})
    content.append({"type": "text", "text": f"""You are the Art Director for an Etsy t-shirt shop. Each option is a shirt graphic shown on the shirt color.
Niche: {niche}
The text MUST read exactly: "{expected_text}" (case and punctuation may differ; words and spelling may not).

Score each option 1-10 as a sellable shirt design. Automatic score 1 if: any word is misspelled, missing, doubled or garbled; there is stray gibberish text; it shows a real brand, logo, team or character; part of it is cut off; the artwork contains a drawn t-shirt, garment or clothing shape; or it sits on a solid background panel or block of color.
Score 3 or lower if a slash '/' appears between words, if the illustration covers part of the lettering, or if any lettering or key part is hard to see against this shirt color (e.g. navy or dark text on a black shirt).
Otherwise judge: readable from 6 feet away, strong contrast on this shirt color, clean screen-print look, looks like a design people would pay $28 for.
Reply with only JSON: {{"scores":[8,3],"text_ok":[true,false],"best":0,"notes":"one sentence"}}"""})
    msg = client.messages.create(model=model, max_tokens=600, messages=[{"role": "user", "content": content}])
    out = parse_json("".join(getattr(b, "text", "") for b in msg.content))
    scores = [int(s) if str(s).lstrip("-").isdigit() else 0 for s in (out.get("scores") or [])]
    text_ok = list(out.get("text_ok") or [])
    ok = [i for i, s in enumerate(scores) if s >= MIN_SCORE and (i >= len(text_ok) or text_ok[i] is not False)]
    best = max(ok, key=lambda i: scores[i]) if ok else None
    return {"best": best, "scores": scores, "notes": str(out.get("notes", ""))}
