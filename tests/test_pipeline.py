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


WORDS = ["tides", "anchor", "reel", "marlin", "coffee", "chart", "shift", "scrubs", "bell", "chalk", "grill", "smoke",
         "trail", "summit", "garden", "compost", "bait", "tackle", "pixel", "quest"]


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
                w1, w2 = WORDS[(i * 2 + j) * 2], WORDS[(i * 2 + j) * 2 + 1]
                out.append({"niche": f"Niche {i}", **SPEC, "lines": [{"text": f"{w1} {w2}", "size": "xl"}, {"text": "sub", "size": "sm"}],
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

    def list_issues(self, state="open", label="draft"):
        return [i for i in self.issues.values() if state == "all" or i["state"] == state]


class FakePF:
    def __init__(self):
        self.created, self.published, self.updated, self.deleted, self.uploads = [], None, None, [], []

    def shops(self):
        return [{"id": 111, "title": "Snare Supply", "sales_channel": "etsy"}]

    def blueprints(self):
        return [{"id": 5, "title": "Kids Tee", "brand": "Other", "model": "X"},
                {"id": 12, "title": "Unisex Jersey Short Sleeve Tee", "brand": "Bella+Canvas", "model": "3001"},
                {"id": 49, "title": "Unisex Heavy Blend Crewneck Sweatshirt", "brand": "Gildan", "model": "18000"},
                {"id": 77, "title": "Unisex Heavy Blend Hooded Sweatshirt", "brand": "Gildan", "model": "18500"},
                {"id": 68, "title": "Ceramic Mug 11oz", "brand": "Generic brand", "model": "Mug"}]

    def providers(self, bp):
        return [{"id": 1, "title": "Far Away Prints", "location": {"country": "CN"}}, {"id": 29, "title": "Monster Digital", "location": {"country": "US"}}]

    def variants(self, bp, pp):
        if bp == 68:
            return [{"id": 9001, "title": "11oz", "options": {"size": "11oz"}}]
        out, vid = [], bp * 1000
        palette = ["Black", "White", "Navy", "Maroon", "Forest Green", "Sport Grey", "Dark Heather"] if bp in (49, 77) else ["Black", "White", "Navy", "Maroon", "Forest", "Athletic Heather"]
        for c in palette:
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
    assert '"Tides Wait" and "For No One"' in p and "/" not in p and "black fabric" in p


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
    # product family: 4 unpublished Printify drafts per design, art uploaded once per design
    assert len(pf.created) == 32 and len(pf.uploads) == 8
    fam = listings[0]["products"]
    assert list(fam) == ["tee", "sweatshirt", "hoodie", "mug"] and all(p["product_id"] for p in fam.values())
    assert fam["sweatshirt"]["price"] == 41.99 and fam["mug"]["price"] == 19.99 and fam["tee"]["price"] == 32.99
    sweat = next(c for c in pf.created if c[1]["blueprint_id"] == 49)[1]
    assert "Sweatshirt" in sweat["title"] and "Shirt, Coffee" not in sweat["title"] and "crewneck sweatshirt" in sweat["tags"]
    mug = next(c for c in pf.created if c[1]["blueprint_id"] == 68)[1]
    assert mug["title"].startswith("Night Shift Nurse Mug") and len(mug["print_areas"][0]["placeholders"][0]["images"]) == 2
    assert [v["id"] for v in mug["variants"]] == [9001]
    assert pf.published is None  # nothing went to Etsy
    assert list(cli.DRAFTS.glob("radar-*.json"))

    gh = FakeGH()
    assert cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh) == 8
    body = gh.issues[1]["body"]
    assert "front.jpg" in body and "Why this niche" in body and "- [x] hoodie: Hoodie: $46.99" in body

    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "not-approved"
    gh.add_labels(1, ["approved"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="randomuser", force=False), cfg, gh=gh, pf=pf) == "not-owner"

    # Owner edits the title, unticks the mug, raises the hoodie price, then approves
    body = body.replace("Night Shift Nurse Shirt, Coffee", "Snook Fishing Shirt, Coffee")
    body = body.replace("- [x] mug:", "- [ ] mug:").replace("Hoodie: $46.99", "Hoodie: $49.99")
    gh.issues[1]["body"] = body
    gh.add_labels(1, ["approved"])
    published = []
    pf.publish = lambda shop, pid: published.append(pid)
    updates = []
    pf.update_product = lambda shop, pid, payload: updates.append((pid, payload))
    n_before = len(pf.created)
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "published"
    assert len(pf.created) == n_before  # existing drafts updated, not recreated
    assert published == ["prod1", "prod2", "prod3"] and "prod4" in pf.deleted  # mug draft removed
    hoodie = dict(updates)["prod3"]
    assert hoodie["title"].startswith("Snook Fishing Hoodie") and {v["price"] for v in hoodie["variants"]} >= {4999}
    assert "3 listings" in gh.comments[-1][1] and "Removed unticked drafts: Coffee Mug 11oz" in gh.comments[-1][1]
    assert gh.issues[1]["state"] == "closed"
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "already-published"

    # Rejecting (closing) another issue deletes all of its Printify drafts
    gh.close(2)
    assert cli.cmd_cleanup(SimpleNamespace(issue=2), cfg, gh=gh, pf=pf) == "deleted"
    assert {"prod5", "prod6", "prod7", "prod8"} <= set(pf.deleted)
    assert cli.cmd_cleanup(SimpleNamespace(issue=1), cfg, gh=gh, pf=pf) == "skip"  # published ones are never deleted


def test_one_product_failing_does_not_block_the_others(cfg):
    listings, pf, _ = run_draft(cfg)
    gh = FakeGH()
    cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh)
    gh.add_labels(1, ["approved"])
    real = pf.publish

    def flaky(shop, pid):
        if pid == "prod4":
            raise RuntimeError("mug provider offline")
        real(shop, pid)
    pf.publish = flaky
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "partial"
    c = gh.comments[-1][1]
    assert "3 listings" in c and "mug provider offline" in c
    labels = {l["name"] for l in gh.issues[1]["labels"]}
    assert "publish-failed" in labels and "published" not in labels and gh.issues[1]["state"] == "open"


def test_art_director_rejection_drops_design_by_default(cfg):
    ideo = FakeIdeogram()
    listings, pf, _ = run_draft(cfg, review=reject_review, ideogram=ideo)
    assert listings == [] and not pf.created and len(ideo.prompts) == 16


def test_no_illustrator_means_no_bland_drafts(cfg):
    gh = FakeGH()
    gh.log = []
    gh.crew_log = lambda t: gh.log.append(t)
    out = cli.cmd_draft(SimpleNamespace(seed="x"), cfg, ask=fake_ask, etsy=FakeEtsy(), ideogram=False, review_fn=approve_review, pf=FakePF(), gh=gh)
    assert out == [] and "IDEOGRAM_API_KEY" in gh.log[-1]


def test_art_director_rejection_falls_back_to_typography(cfg):
    cfg["illustrator"]["require_art"] = False
    ideo = FakeIdeogram()
    listings, pf, _ = run_draft(cfg, review=reject_review, ideogram=ideo)
    assert all(l["mode"] == "type" for l in listings)
    assert len(ideo.prompts) == 16  # 2 attempts per design
    assert all(any(f["kind"] == "art" for f in l["flags"]) for l in listings)


def test_type_design_edit_recreates_product(cfg):
    cfg["illustrator"]["require_art"] = False
    listings, pf, _ = run_draft(cfg, review=reject_review)
    gh = FakeGH()
    cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh)
    gh.issues[1]["body"] = gh.issues[1]["body"].replace("style: stamp", "style: badge")
    gh.add_labels(1, ["approved"])
    assert cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf) == "published"
    assert {"prod1", "prod2", "prod3", "prod4"} <= set(pf.deleted)  # design edited -> whole family recreated
    assert len(pf.created) == 32 + 4 and pf.published[1] == f"prod{len(pf.created)}"


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
    with pytest.raises(Exception):
        cli.cmd_publish(SimpleNamespace(issue=1, actor="Jsnare854", force=False), cfg, gh=gh, pf=pf)
    labels = {l["name"] for l in gh.issues[1]["labels"]}
    assert "publish-failed" in labels and "approved" not in labels and "Publishing failed" in gh.comments[-1][1]


# ---------- schedule brake + learning loop ----------

class ShopEtsy(FakeEtsy):
    def find_shop(self, name):
        return {"shop_id": 77, "shop_name": "SnareSupply", "transaction_sold_count": 3}

    def shop_listings(self, shop_id):
        return [
            {**etsy_listing(10, 12, 30, "Tides Wait For No One Fishing Shirt"), "views": 300},
            {**etsy_listing(11, 0, 40, "Plain Nurse Tee"), "views": 10},
        ]


def test_brake_skips_scheduled_run_when_queue_full(cfg):
    gh = FakeGH()
    gh.log = []
    gh.crew_log = lambda text: gh.log.append(text)
    gh.count_open = lambda label: 15
    out = cli.cmd_draft(SimpleNamespace(seed="x", auto=True), cfg, ask=fake_ask, etsy=FakeEtsy(), ideogram=FakeIdeogram(),
                        review_fn=approve_review, pf=FakePF(), gh=gh)
    assert out == [] and gh.log[-1].startswith("⏸️ Paused: 15 drafts")
    gh.count_open = lambda label: 3
    out = cli.cmd_draft(SimpleNamespace(seed="x", auto=True), cfg, ask=fake_ask, etsy=FakeEtsy(), ideogram=FakeIdeogram(),
                        review_fn=approve_review, pf=FakePF(), gh=gh)
    assert len(out) == 8 and gh.log[-1].startswith("✅ Drafted 8 designs × 4 products")


def test_learning_loop_feeds_analyst_and_weekly_report(cfg):
    seen = {}

    def ask(prompt, model, max_tokens=0):
        if "Market Analyst" in prompt:
            seen["prompt"] = prompt
        return fake_ask(prompt, model, max_tokens)

    cli.cmd_draft(SimpleNamespace(seed="fishing"), cfg, ask=ask, etsy=ShopEtsy(), ideogram=FakeIdeogram(), review_fn=approve_review, pf=FakePF())
    p = seen["prompt"]
    assert "YOUR SHOP (SnareSupply)" in p and "+ Tides Wait For No One" in p and "- Plain Nurse Tee" in p

    gh = FakeGH()
    assert cli.cmd_report(SimpleNamespace(), cfg, etsy=ShopEtsy(), pf=FakePF(), gh=gh) == "filed"
    issue = gh.issues[1]
    assert issue["labels"] == [{"name": "report"}] and "Tides Wait For No One" in issue["body"] and "zero favorites" in issue["body"]


# ---------- variety ----------

def test_history_rotates_seeds_and_blocks_repeats(cfg, tmp_path):
    from forge.history import History, similar
    h = History(tmp_path / "h.json")
    seeds = ["a", "b", "c"]
    used = set()
    for _ in range(3):
        s = h.next_seed(seeds)
        used.add(s)
        h.add(s, "n", f"phrase {s}", "")
    assert used == {"a", "b", "c"}  # every seed used before any repeats
    assert h.next_seed(seeds) == next(iter(h.items))["seed"]  # then least recently used
    assert similar("Tides Wait For No One", "The Tides Wait For No One") and not similar("Tides Wait", "Coffee Charting")
    assert len(set(h.styles_for_batch(8))) == 8


def test_second_run_avoids_first_runs_niches_and_phrases(cfg):
    prompts = []

    def ask(prompt, model, max_tokens=0):
        prompts.append(prompt)
        return fake_ask(prompt, model, max_tokens)

    first = cli.cmd_draft(SimpleNamespace(seed="fishing"), cfg, ask=ask, etsy=FakeEtsy(), ideogram=FakeIdeogram(), review_fn=approve_review, pf=FakePF())
    assert len(first) == 8
    prompts.clear()
    second = cli.cmd_draft(SimpleNamespace(seed="fishing"), cfg, ask=ask, etsy=FakeEtsy(), ideogram=FakeIdeogram(), review_fn=approve_review, pf=FakePF())
    scout_p = next(p for p in prompts if "Trend Scout" in p)
    design_p = next(p for p in prompts if "Designer" in p)
    assert "already covered these niches" in scout_p and "Niche 0" in scout_p
    assert "ALREADY used" in design_p and "tides anchor sub" in design_p and "DIFFERENT style" in design_p
    assert second == []  # fake designer repeats itself -> every repeat dropped


# ---------- duplicate-filing bug ----------

def test_drafts_are_never_filed_twice_and_old_duplicates_get_closed(cfg):
    listings, pf, _ = run_draft(cfg)
    gh = FakeGH()
    assert cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh) == 8
    # Simulate the old bug: the queue file came back (deletion wasn't committed) -> nothing is filed again
    cli.PENDING.write_text(json.dumps([l["draft_id"] for l in listings]))
    assert cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh) == 0 and len(gh.issues) == 8
    # Duplicates the old bug already created get closed, oldest copy kept
    for n in (1, 2):
        gh.create_issue(gh.issues[n]["title"], gh.issues[n]["body"], ["draft"])
    cli.cmd_file_issues(SimpleNamespace(), cfg, gh=gh)
    assert gh.issues[9]["state"] == "closed" and gh.issues[10]["state"] == "closed" and gh.issues[1]["state"] == "open"
    # ...and closing a duplicate must NOT delete the Printify drafts the original still uses
    assert cli.cmd_cleanup(SimpleNamespace(issue=9), cfg, gh=gh, pf=pf) == "duplicate" and not pf.deleted


def test_every_run_resets_the_queue_even_when_paused(cfg):
    cli.DRAFTS.mkdir(parents=True, exist_ok=True)
    cli.PENDING.write_text(json.dumps(["old-draft-1", "old-draft-2"]))
    gh = FakeGH()
    gh.count_open = lambda label: 99
    gh.crew_log = lambda t: None
    cli.cmd_draft(SimpleNamespace(seed="x", auto=True), cfg, ask=fake_ask, etsy=FakeEtsy(), ideogram=FakeIdeogram(), review_fn=approve_review, pf=FakePF(), gh=gh)
    assert json.loads(cli.PENDING.read_text()) == []


def test_out_of_credits_stops_the_run_with_a_clear_message(cfg):
    from forge.illustrator import IllustratorError

    class Broke:
        calls = 0

        def generate(self, *a, **k):
            Broke.calls += 1
            raise IllustratorError('Ideogram failed (402): {"reject_reason": "insufficient_funds"}', 402)
    gh = FakeGH()
    gh.log = []
    gh.crew_log = lambda t: gh.log.append(t)
    out = cli.cmd_draft(SimpleNamespace(seed="x"), cfg, ask=fake_ask, etsy=FakeEtsy(), ideogram=Broke(), review_fn=approve_review, pf=FakePF(), gh=gh)
    assert out == [] and Broke.calls == 1  # stopped on the first design, didn't burn through all 8
    assert "out of API credits" in gh.log[-1] and "Art Director" not in gh.log[-1]


def test_wordy_slogans_are_rejected():
    from forge.agents import designer

    def ask(p, m, max_tokens=0):
        return [{"niche": "n", **SPEC, "lines": ["After years of routes final", "delivery made retired carrier"], "title": "t", "tags": TAGS, "description": "d"},
                {"niche": "n", **SPEC, "lines": ["Signed Sealed", "Retired"], "title": "t", "tags": TAGS, "description": "d"}]
    out = designer([{"niche": "n"}], 2, "m", {"min_price": 24.99, "max_price": 32.99}, True, ask)
    assert [l["spec"]["lines"][0]["text"] for l in out] == ["Signed Sealed"]
