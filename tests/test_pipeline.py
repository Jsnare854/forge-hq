import base64
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from forge import cli, compliance
from forge.config import load_config
from forge.printify import build_variants, pick_blueprint, pick_colors, pick_provider, pick_shop, PrintifyError
from forge.render import PRINT_H, PRINT_W, render_mockup, render_print
from forge.spec import STYLES, format_issue, normalize_spec, parse_issue

SPEC = {"lines": [{"text": "Powered By", "size": "sm"}, {"text": "Coffee &", "size": "lg"}, {"text": "Charting", "size": "lg"}],
        "style": "stamp", "font": "Archivo Black", "ink": "#f2f2f2", "accent": "#58d6ff", "shirt": "black"}
TAGS = ["night shift nurse", "nurse shirt", "nurse gift", "nursing student", "funny nurse tee", "coffee nurse",
        "nurse week gift", "rn shirt", "icu nurse", "er nurse", "charting", "nurse life", "gift for nurse"]


def fake_ask(prompt, model, max_tokens=0):
    if "Trend Scout" in prompt:
        return [{"niche": f"Niche {i}", "audience": "a", "angle": "b", "searchPhrases": [f"phrase {i}"]} for i in range(8)]
    if "Niche Analyst" in prompt:
        return [{"niche": f"Niche {i}", "demand": 8, "competition": 6, "passion": 9, "why": "x"} for i in range(4)]
    if "Designer" in prompt:
        out = []
        for i in range(4):
            for j in range(2):
                out.append({"niche": f"Niche {i}", **SPEC, "lines": [{"text": f"Line {i}{j}", "size": "xl"}, {"text": "sub", "size": "sm"}],
                            "title": "Night Shift Nurse Shirt, Coffee And Charting Tee, Funny Nurse Gift", "tags": TAGS + ["extra one"],
                            "description": "For nurses.", "price": 99, "risk": "low", "riskNotes": "ok", "imagePrompt": "cup"})
        return out
    raise AssertionError(prompt[:80])


class FakeGH:
    owner = "Jsnare854"

    def __init__(self):
        self.issues, self.comments, self.labels_made = {}, [], False

    def ensure_labels(self):
        self.labels_made = True

    def raw_url(self, path):
        return "https://example/" + path

    def create_issue(self, title, body, labels):
        n = len(self.issues) + 1
        self.issues[n] = {"number": n, "title": title, "body": body, "labels": [{"name": l} for l in labels], "state": "open"}
        return self.issues[n]

    def issue(self, n):
        return self.issues[n]

    def comment(self, n, text):
        self.comments.append((n, text))

    def add_labels(self, n, labels):
        self.issues[n]["labels"] += [{"name": l} for l in labels]

    def remove_label(self, n, label):
        self.issues[n]["labels"] = [l for l in self.issues[n]["labels"] if l["name"] != label]

    def close(self, n):
        self.issues[n]["state"] = "closed"


class FakePF:
    def __init__(self):
        self.created, self.published, self.uploaded = None, None, None

    def shops(self):
        return [{"id": 111, "title": "Snare Supply", "sales_channel": "etsy"}]

    def blueprints(self):
        return [{"id": 5, "title": "Kids Tee", "brand": "Other", "model": "X"}, {"id": 12, "title": "Unisex Jersey Short Sleeve Tee", "brand": "Bella+Canvas", "model": "3001"}]

    def providers(self, bp):
        return [{"id": 1, "title": "Far Away Prints", "location": {"country": "CN"}}, {"id": 29, "title": "Monster Digital", "location": {"country": "US"}}]

    def variants(self, bp, pp):
        out, vid = [], 1000
        for c in ["Black", "White", "Navy", "Maroon", "Forest", "Athletic Heather"]:
            for s in ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"]:
                vid += 1
                out.append({"id": vid, "title": f"{c} / {s}", "options": {"color": c, "size": s}})
        return out

    def upload_png(self, name, data):
        self.uploaded = data
        return "img123"

    def create_product(self, shop, payload):
        self.created = (shop, payload)
        return {"id": "prod789"}

    def publish(self, shop, pid):
        self.published = (shop, pid)
        return {}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DRAFTS", tmp_path / "drafts")
    monkeypatch.setattr(cli, "PENDING", tmp_path / "drafts" / "pending.json")
    return load_config()


# ---------- renderer ----------

@pytest.mark.parametrize("style", list(STYLES))
def test_every_style_renders_print_file(style):
    png = render_print({**SPEC, "style": style, "lines": SPEC["lines"] + [{"text": "Est 2026", "size": "sm"}]})
    img = Image.open(io.BytesIO(png))
    assert img.size == (PRINT_W, PRINT_H) and img.mode == "RGBA"
    assert img.getchannel("A").getextrema()[0] == 0  # transparent background
    assert img.getbbox() is not None


def test_mockup_renders():
    assert Image.open(io.BytesIO(render_mockup(SPEC))).size == (600, 680)


# ---------- spec / issue round trip ----------

def test_issue_round_trip_and_user_edits():
    L = {"niche": "Night shift nurses", "spec": normalize_spec(SPEC), "title": "T", "tags": TAGS, "price": 27.5,
         "description": "Desc line.\n\nSecond para.", "risk": "low", "risk_notes": "fine", "image_prompt": "cup", "seed": "nurses", "flags": []}
    title, body = format_issue(L, "http://m.png", "http://p.png")
    back = parse_issue(body)
    assert back["spec"] == L["spec"] and back["tags"] == TAGS and back["price"] == 27.5
    assert back["description"] == L["description"] and back["niche"] == "Night shift nurses" and back["risk"] == "low"
    edited = body.replace("lg: Charting", "xl: Paperwork").replace("style: stamp", "style: badge").replace("\n27.50\n", "\n$29.99\n")
    e = parse_issue(edited)
    assert e["spec"]["lines"][-1] == {"size": "xl", "text": "Paperwork"} and e["spec"]["style"] == "badge" and e["price"] == 29.99


def test_parse_rejects_foreign_issue():
    with pytest.raises(ValueError):
        parse_issue("just a normal issue")


# ---------- compliance ----------

def test_compliance_blocks_trademarks_but_not_common_words():
    L = {"spec": normalize_spec({"lines": ["Bucs Fan Forever"]}), "title": "Fishing shirt", "tags": TAGS, "description": compliance.DISCLOSURE_LINE}
    assert any(f["bad"] and f["kind"] == "trademark" for f in compliance.check(L))
    L2 = {**L, "spec": normalize_spec({"lines": ["Friends Dont Let", "Friends Fish Alone"]})}
    flags = compliance.check(L2)
    assert not compliance.blocking(flags) and any(f["kind"] == "trademark" for f in flags)


def test_fix_tags_limits():
    tags = compliance.fix_tags(["A", "a", "this tag is way too long for etsy"] + [f"t{i}" for i in range(20)])
    assert len(tags) == 13 and all(len(t) <= 20 for t in tags) and tags[0] == "a"


# ---------- printify selection ----------

def test_printify_selection():
    pf = FakePF()
    assert pick_shop(pf.shops())["id"] == 111
    with pytest.raises(PrintifyError):
        pick_shop([{"id": 1, "sales_channel": "shopify"}])
    assert pick_blueprint(pf.blueprints(), "Bella+Canvas", "3001")["id"] == 12
    assert pick_provider(pf.providers(12), ["Monster Digital"])["id"] == 29
    assert pick_provider(pf.providers(12), [])["id"] == 29  # falls back to a US provider
    cfg = load_config()["printify"]
    colors = pick_colors(pf.variants(12, 29), normalize_spec(SPEC), cfg)
    assert colors[0] == "Black" and "White" not in colors and len(colors) == 4
    rows = build_variants(pf.variants(12, 29), colors, cfg["sizes"], 27.99, cfg["upcharge_cents"])
    assert len(rows) == 4 * 6 and {r["price"] for r in rows} == {2799, 2999, 3199}


# ---------- end to end ----------

def test_draft_file_approve_publish(cfg):
    listings = cli.cmd_draft(SimpleNamespace(seed="nurses", niches="", designs=""), cfg, ask=fake_ask, etsy=False)
    assert len(listings) == 8
    assert all(l["price"] == 32.99 for l in listings)  # clamped to max
    assert all(len(l["tags"]) == 13 for l in listings)
    assert all(compliance.AI_DISCLOSURE.search(l["description"]) for l in listings)

    gh = FakeGH()
    assert cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh) == 8
    assert gh.labels_made and not cli.PENDING.exists()

    # Not approved yet -> nothing happens
    pf = FakePF()
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "not-approved"

    # Someone else approves -> refused
    gh.add_labels(1, ["approved"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="randomuser", force=False), cfg, gh=gh, pf=pf) == "not-owner"
    assert pf.created is None

    # Owner approves -> product created + published
    gh.add_labels(1, ["approved"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "published"
    shop, payload = pf.created
    assert shop == 111 and payload["blueprint_id"] == 12 and payload["print_provider_id"] == 29
    assert payload["print_areas"][0]["placeholders"][0]["images"][0]["id"] == "img123"
    assert len(payload["tags"]) == 13 and payload["title"].startswith("Night Shift Nurse Shirt")
    assert pf.published == (111, "prod789")
    assert Image.open(io.BytesIO(pf.uploaded)).size == (PRINT_W, PRINT_H)
    assert gh.issues[1]["state"] == "closed" and any(l["name"] == "published" for l in gh.issues[1]["labels"])

    # Re-labeling a published issue does nothing
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "already-published"


def test_high_risk_is_blocked_until_override(cfg):
    gh, pf = FakeGH(), FakePF()
    L = {"niche": "Sports", "spec": normalize_spec({"lines": ["Bucs Til I Die"]}), "title": "Football Shirt", "tags": TAGS, "price": 27.99,
         "description": compliance.DISCLOSURE_LINE, "risk": "high", "risk_notes": "team name", "image_prompt": "", "seed": "s", "flags": []}
    title, body = format_issue(L)
    gh.create_issue(title, body, ["draft", "risk-high", "approved"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "blocked"
    assert pf.created is None and "Not published" in gh.comments[-1][1]
    gh.add_labels(1, ["approved", "override-risk"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "published"


def test_publish_failure_is_reported(cfg):
    gh, pf = FakeGH(), FakePF()
    L = {"niche": "N", "spec": normalize_spec(SPEC), "title": "Nurse Shirt", "tags": TAGS, "price": 27.99,
         "description": compliance.DISCLOSURE_LINE, "risk": "low", "risk_notes": "", "image_prompt": "", "seed": "s", "flags": []}
    gh.create_issue(*format_issue(L), ["draft", "approved"])

    def boom(*a):
        raise PrintifyError("Printify POST failed (400): bad variant")
    pf.create_product = boom
    with pytest.raises(PrintifyError):
        cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf)
    labels = {l["name"] for l in gh.issues[1]["labels"]}
    assert "publish-failed" in labels and "approved" not in labels and "Publishing failed" in gh.comments[-1][1]
