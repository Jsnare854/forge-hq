import io
import json
import time
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from forge import cli, compliance, trends
from forge.config import load_config
from forge.illustrator import build_prompt, to_print_canvas
from forge.printify import PrintifyError, build_variants, mockup_urls, pick_blueprint, pick_colors, pick_provider, pick_shop
from forge.render import PRINT_H, PRINT_W, render_mockup, render_print
from forge.spec import STYLES, format_issue, normalize_spec, parse_issue

SPEC = {"lines": [{"text": "Powered By", "size": "sm"}, {"text": "Coffee &", "size": "lg"}, {"text": "Charting", "size": "lg"}],
        "style": "stamp", "font": "Archivo Black", "ink": "#f2f2f2", "accent": "#58d6ff", "shirt": "black"}
TAGS = ["night shift nurse", "nurse shirt", "nurse gift", "nursing student", "funny nurse tee", "coffee nurse",
        "nurse week gift", "rn shirt", "icu nurse", "er nurse", "charting", "nurse life", "gift for nurse"]
NOW = time.time()


def etsy_listing(i, favs, age_days, title):
    return {"listing_id": 1000 + i, "title": title, "num_favorers": favs, "original_creation_timestamp": NOW - age_days * 86400,
            "price": {"amount": 2499 + i * 100, "divisor": 100}, "tags": ["fishing shirt", "boat dad"], "url": f"https://etsy.com/listing/{1000+i}"}


class FakeEtsy:
    def __init__(self):
        self.queries = []

    def search(self, q, limit=100, offset=0, sort_on="score"):
        self.queries.append(q)
        return {"count": 18000, "results": [
            etsy_listing(1, 400, 20, "Reel Cool Dad Funny Fishing T-Shirt"),
            etsy_listing(2, 900, 700, "Vintage Bass Fishing Shirt Gift"),
            etsy_listing(3, 5, 10, "Fishing Hat Embroidered"),  # not apparel -> dropped
            etsy_listing(4, 60, 30, "Snook Slam Sunset Tee"),
        ]}


def fake_ask(prompt, model, max_tokens=0):
    if "Trend Scout" in prompt:
        return [{"niche": f"Niche {i}", "audience": "a", "angle": "b", "searchPhrases": [f"phrase {i}", f"alt {i}"]} for i in range(8)]
    if "Market Analyst" in prompt:
        assert ("LIVE Etsy data" in prompt) == ("QUERY" in prompt)
        return [{"niche": f"Niche {i}", "demand": 8, "competition": 6, "passion": 9, "why": "x", "what_wins": "dad humor",
                 "visual_style": "retro", "price_band": "$24-28", "evidence_ids": [1001, 1004], "avoid_phrases": ["reel cool dad"]} for i in range(4)]
    if "Designer" in prompt:
        out = []
        for i in range(4):
            for j in range(2):
                out.append({"niche": f"Niche {i}", **SPEC, "lines": [{"text": f"Line {i}{j}", "size": "xl"}, {"text": "sub", "size": "sm"}],
                            "mode": "illustrated", "artPrompt": "a leaping snook over a retro sunset",
                            "title": "Night Shift Nurse Shirt, Coffee And Charting Tee, Funny Nurse Gift", "tags": TAGS + ["extra one"],
                            "description": "For nurses.", "price": 99, "risk": "low", "riskNotes": "ok"})
        return out
    raise AssertionError(prompt[:80])


def art_png():
    img = Image.new("RGBA", (1024, 1365), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([200, 200, 800, 900], fill=(255, 120, 60, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class FakeIdeogram:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, n=2, speed="DEFAULT", upscale="X2"):
        self.prompts.append(prompt)
        return [art_png() for _ in range(n)]


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
        self.created, self.published, self.updated, self.deleted, self.uploads = [], None, None, [], []

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
        self.uploads.append(data)
        return f"img{len(self.uploads)}"

    def create_product(self, shop, payload):
        pid = f"prod{len(self.created) + 1}"
        self.created.append((shop, payload, pid))
        return {"id": pid, "images": [{"src": f"https://mock/{pid}/back.jpg", "position": "back"},
                                       {"src": f"https://mock/{pid}/front.jpg", "position": "front", "is_default": True}]}

    def update_product(self, shop, pid, payload):
        self.updated = (shop, pid, payload)

    def delete_product(self, shop, pid):
        self.deleted.append(pid)

    def publish(self, shop, pid):
        self.published = (shop, pid)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DRAFTS", tmp_path / "drafts")
    monkeypatch.setattr(cli, "PENDING", tmp_path / "drafts" / "pending.json")
    return load_config()


def approve_review(prev, text, niche):
    return {"best": 1, "scores": [4, 9], "notes": "clean"}


def reject_review(prev, text, niche):
    return {"best": None, "scores": [2, 3], "notes": "misspelled"}


# ---------- renderer / illustrator ----------

@pytest.mark.parametrize("style", list(STYLES))
def test_every_style_renders_print_file(style):
    png = render_print({**SPEC, "style": style, "lines": SPEC["lines"] + [{"text": "Est 2026", "size": "sm"}]})
    img = Image.open(io.BytesIO(png))
    assert img.size == (PRINT_W, PRINT_H) and img.mode == "RGBA"
    assert img.getchannel("A").getextrema()[0] == 0
    assert img.getbbox() is not None


def test_mockup_renders():
    assert Image.open(io.BytesIO(render_mockup(SPEC))).size == (600, 680)


def test_art_placed_on_print_canvas():
    img = Image.open(io.BytesIO(to_print_canvas(art_png())))
    assert img.size == (PRINT_W, PRINT_H)
    x0, y0, x1, y1 = img.getbbox()
    assert x1 - x0 > PRINT_W * 0.8 and y0 < PRINT_H * 0.1  # scaled up, chest-weighted


def test_prompt_contains_exact_text():
    p = build_prompt("a snook", [{"text": "Tides Wait", "size": "md"}, {"text": "For No One", "size": "xl"}], "navy")
    assert '"Tides Wait / For No One"' in p and "dark navy shirt" in p


# ---------- trend radar ----------

def test_radar_ranks_momentum_and_drops_non_apparel():
    rep = trends.scan(FakeEtsy(), ["fishing shirt"], top=5, log=lambda *a: None)
    r = rep[0]
    assert r["active_listings"] == 18000 and r["sampled"] == 3
    assert r["hot"][0]["title"].startswith("Reel Cool Dad")  # 400 favs in 20 days beats 900 in 700 days
    assert r["new_listings_with_traction"] == 2
    assert [e["id"] for e in trends.evidence_for(rep, [1004, 9999])] == [1004]


# ---------- issue round trip ----------

def test_issue_round_trip_and_user_edits():
    L = {"niche": "Night shift nurses", "spec": normalize_spec(SPEC), "title": "T", "tags": TAGS, "price": 27.5, "mode": "type",
         "description": "Desc line.\n\nSecond para.", "risk": "low", "risk_notes": "fine", "art_prompt": "cup", "seed": "nurses", "flags": [],
         "evidence": [{"title": "Nurse | Tee", "favorites": 50, "age_days": 20, "price": 26, "url": "https://e/1"}], "brief": {"why": "hot"}}
    title, body = format_issue(L, ["http://m1", "http://m2"], "http://p.png", "D1", "P1")
    assert "Why this niche" in body and "https://e/1" in body and 'src="http://m2"' in body
    back = parse_issue(body)
    assert back["spec"] == L["spec"] and back["tags"] == TAGS and back["price"] == 27.5
    assert back["description"] == L["description"] and back["niche"] == "Night shift nurses" and back["risk"] == "low"
    assert (back["draft_id"], back["product_id"], back["mode"]) == ("D1", "P1", "type")
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


def test_compliance_blocks_copying_a_competitor():
    ev = [{"title": "Reel Cool Dad Funny Fishing T-Shirt"}]
    copy = {"spec": normalize_spec({"lines": ["Reel Cool Dad", "Club"]}), "title": "x", "tags": TAGS, "description": compliance.DISCLOSURE_LINE, "evidence": ev}
    orig = {**copy, "spec": normalize_spec({"lines": ["Tides Wait", "For No One"]})}
    assert any(f["kind"] == "too_close" and f["bad"] for f in compliance.check(copy))
    assert not any(f["kind"] == "too_close" for f in compliance.check(orig))


def test_fix_tags_limits():
    tags = compliance.fix_tags(["A", "a", "this tag is way too long for etsy"] + [f"t{i}" for i in range(20)])
    assert len(tags) == 13 and all(len(t) <= 20 for t in tags) and tags[0] == "a"


# ---------- printify selection ----------

def test_printify_selection():
    pf = FakePF()
    assert pick_shop(pf.shops())["id"] == 111
    with pytest.raises(PrintifyError):
        pick_shop([{"id": 1, "sales_channel": "disconnected"}])
    assert pick_blueprint(pf.blueprints(), "Bella+Canvas", "3001")["id"] == 12
    assert pick_provider(pf.providers(12), ["Monster Digital"])["id"] == 29
    assert pick_provider(pf.providers(12), [])["id"] == 29
    c = load_config()["printify"]
    colors = pick_colors(pf.variants(12, 29), normalize_spec(SPEC), c)
    assert colors[0] == "Black" and "White" not in colors and len(colors) == 4
    rows = build_variants(pf.variants(12, 29), colors, c["sizes"], 27.99, c["upcharge_cents"])
    assert len(rows) == 4 * 6 and {r["price"] for r in rows} == {2799, 2999, 3199}
    assert mockup_urls({"images": [{"src": "b", "position": "back"}, {"src": "f", "position": "front", "is_default": True}]})[0] == "f"


# ---------- end to end ----------

def run_draft(cfg, review=approve_review, ideogram=None):
    pf = FakePF()
    etsy = FakeEtsy()
    listings = cli.cmd_draft(SimpleNamespace(seed="fishing"), cfg, ask=fake_ask, etsy=etsy, ideogram=ideogram or FakeIdeogram(), review_fn=review, pf=pf)
    return listings, pf, etsy


def test_full_loop_trend_radar_illustrator_mockups_publish(cfg):
    listings, pf, etsy = run_draft(cfg)
    assert len(listings) == 8 and len(etsy.queries) == 12  # radar capped at 12 searches
    assert all(l["mode"] == "illustrated" for l in listings)
    assert all(l["price"] == 32.99 and len(l["tags"]) == 13 for l in listings)
    assert all(l["evidence"] and l["evidence"][0]["id"] == 1001 for l in listings)
    assert len(pf.created) == 8 and all(l["product_id"] for l in listings)  # real Printify drafts
    assert pf.published is None  # nothing went to Etsy
    assert listings[0]["mockups"][0].endswith("front.jpg")
    assert list(cli.DRAFTS.glob("radar-*.json"))

    gh = FakeGH()
    assert cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh) == 8
    body = gh.issues[1]["body"]
    assert "front.jpg" in body and "Why this niche" in body and "product=prod1" in body

    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "not-approved"
    gh.add_labels(1, ["approved"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="randomuser", force=False), cfg, gh=gh, pf=pf) == "not-owner"

    # Owner edits the title, then approves -> existing draft is updated and published (no new product)
    gh.issues[1]["body"] = body.replace("Night Shift Nurse Shirt, Coffee", "Snook Fishing Shirt, Coffee")
    gh.add_labels(1, ["approved"])
    n_before = len(pf.created)
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "published"
    assert len(pf.created) == n_before and pf.updated[1] == "prod1" and pf.updated[2]["title"].startswith("Snook Fishing Shirt")
    assert pf.published == (111, "prod1") and gh.issues[1]["state"] == "closed"
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "already-published"

    # Rejecting (closing) another issue deletes its Printify draft
    gh.close(2)
    assert cli.cmd_cleanup(SimpleNamespace(issue=2), cfg, gh=gh, pf=pf) == "deleted" and "prod2" in pf.deleted
    assert cli.cmd_cleanup(SimpleNamespace(issue=1), cfg, gh=gh, pf=pf) == "skip"  # published ones are never deleted


def test_art_director_rejection_falls_back_to_typography(cfg):
    ideo = FakeIdeogram()
    listings, pf, _ = run_draft(cfg, review=reject_review, ideogram=ideo)
    assert all(l["mode"] == "type" for l in listings)
    assert len(ideo.prompts) == 16  # 2 attempts per design
    assert all(any(f["kind"] == "art" for f in l["flags"]) for l in listings)


def test_type_design_edit_recreates_product(cfg):
    listings, pf, _ = run_draft(cfg, review=reject_review)
    gh = FakeGH()
    cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh)
    gh.issues[1]["body"] = gh.issues[1]["body"].replace("style: stamp", "style: badge")
    gh.add_labels(1, ["approved"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "published"
    assert "prod1" in pf.deleted and pf.published[1] == f"prod{len(pf.created)}"


def test_high_risk_is_blocked_until_override(cfg):
    gh, pf = FakeGH(), FakePF()
    L = {"niche": "Sports", "spec": normalize_spec({"lines": ["Bucs Til I Die"]}), "title": "Football Shirt", "tags": TAGS, "price": 27.99,
         "description": compliance.DISCLOSURE_LINE, "risk": "high", "risk_notes": "team name", "seed": "s", "flags": []}
    gh.create_issue(*format_issue(L), ["draft", "risk-high", "approved"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "blocked"
    assert not pf.created and "Not published" in gh.comments[-1][1]
    gh.add_labels(1, ["approved", "override-risk"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "published"


def test_publish_failure_is_reported(cfg):
    gh, pf = FakeGH(), FakePF()
    L = {"niche": "N", "spec": normalize_spec(SPEC), "title": "Nurse Shirt", "tags": TAGS, "price": 27.99,
         "description": compliance.DISCLOSURE_LINE, "risk": "low", "risk_notes": "", "seed": "s", "flags": []}
    gh.create_issue(*format_issue(L), ["draft", "approved"])

    def boom(*a):
        raise PrintifyError("Printify POST failed (400): bad variant")
    pf.create_product = boom
    with pytest.raises(PrintifyError):
        cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf)
    labels = {l["name"] for l in gh.issues[1]["labels"]}
    assert "publish-failed" in labels and "approved" not in labels and "Publishing failed" in gh.comments[-1][1]
