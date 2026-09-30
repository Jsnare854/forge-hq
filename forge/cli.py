"""Command line entry points used by the GitHub Actions workflow.

  python -m forge draft [--seed "..."]         agents research, design, illustrate and create Printify drafts
  python -m forge file-issues                   turn new drafts into approval issues
  python -m forge publish --issue N --actor U   publish one approved issue to Etsy
  python -m forge cleanup --issue N             remove the Printify draft of a rejected (closed) issue
  python -m forge check                         verify Printify, Etsy, Claude and Ideogram setup
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

from . import compliance
from .config import ROOT, load_config, secret
from .spec import SHIRTS, format_issue, parse_issue, phrase

DRAFTS = ROOT / "drafts"
PENDING = DRAFTS / "pending.json"


def summary(text: str):
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "design"


def next_seed(cfg: dict, hist=None) -> str:
    path = ROOT / cfg["drafting"].get("seeds_file", "seeds.txt")
    seeds = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    if not seeds:
        raise SystemExit("seeds.txt is empty. Add at least one seed idea.")
    if hist is not None:
        return hist.next_seed(seeds)
    return seeds[dt.date.today().toordinal() % len(seeds)]


# ---------------- draft ----------------

def make_artwork(L: dict, cfg: dict, ideogram, review_fn, log=print) -> tuple[bytes, bytes]:
    """Returns (print_png, preview_png). Illustrated designs go through Ideogram + Art Director,
    falling back to the typography renderer if no candidate passes."""
    from .illustrator import build_prompt, preview, to_print_canvas
    from .render import render_mockup, render_print

    icfg = cfg.get("illustrator", {})
    if L.get("mode") == "illustrated" and ideogram:
        expected = " ".join(l["text"] for l in L["spec"]["lines"])
        prompt = build_prompt(L.get("art_prompt", ""), L["spec"]["lines"], L["spec"]["shirt"])
        for attempt in range(int(icfg.get("attempts", 2))):
            try:
                imgs = ideogram.generate(prompt, n=int(icfg.get("candidates", 2)), speed=icfg.get("speed", "DEFAULT"), upscale=icfg.get("upscale", "X2"))
            except Exception as e:
                log(f"  ILLUSTRATOR failed: {e}")
                break
            if not imgs:
                continue
            previews = [preview(i, SHIRTS[L["spec"]["shirt"]]) for i in imgs]
            try:
                verdict = review_fn(previews, expected, L["niche"])
            except Exception as e:
                log(f"  ART DIRECTOR failed: {e}")
                verdict = {"best": None, "scores": [], "notes": str(e)}
            log(f"  ART DIRECTOR scores {verdict['scores']} → {'option ' + str(verdict['best']) if verdict['best'] is not None else 'rejected'} ({verdict['notes']})")
            if verdict["best"] is not None:
                L["art_notes"] = f"Art Director: {verdict['notes']} (scores {verdict['scores']})"
                return to_print_canvas(imgs[verdict["best"]]), previews[verdict["best"]]
        if icfg.get("require_art", True):
            return None, None
        L["mode"] = "type"
        L.setdefault("flags", []).append({"bad": False, "kind": "art", "msg": "Illustrations didn't pass the Art Director, so this uses a typography layout instead."})
    return render_print(L["spec"]), render_mockup(L["spec"])


def crew_log(text: str, gh=None):
    """Append a line to the pinned 'Crew log' issue so you can see every scheduled run at a glance."""
    try:
        from .github_queue import GitHub
        gh = gh or GitHub()
        gh.crew_log(text)
    except SystemExit:
        pass
    except Exception as e:
        print(f"(crew log not updated: {e})")


def _shop_name(cfg, pf) -> str:
    name = (cfg["drafting"].get("etsy_shop_name") or "").strip()
    if name or not pf:
        return name
    try:
        from .printify import pick_shop
        return str(pick_shop(pf.shops(), cfg["printify"].get("shop_id")).get("title", ""))
    except Exception:
        return ""


def cmd_draft(args, cfg, ask=None, etsy=None, ideogram=None, review_fn=None, pf=None, gh=None) -> list[dict]:
    from .agents import run_pipeline
    from .performance import compact as perf_compact, shop_performance
    from .artdirector import review
    from .etsy import Etsy
    from .illustrator import Ideogram
    from .printify import Printify, create_draft, mockup_urls, resolve_catalog
    from .products import adapt, profiles

    if getattr(args, "auto", False):
        limit = int(cfg["drafting"].get("max_pending_drafts", 15))
        try:
            from .github_queue import GitHub
            waiting = (gh or GitHub()).count_open("draft")
        except Exception as e:
            waiting = 0
            print(f"Couldn't count waiting drafts ({e}); running anyway.")
        if waiting >= limit:
            msg = f"⏸️ Paused: {waiting} drafts are already waiting for you (limit {limit}). Approve or close some and the crew picks back up next run."
            summary(msg)
            crew_log(msg, gh)
            return []
    from .history import History, similar
    hist = History(DRAFTS / "history.json")
    seed = (getattr(args, "seed", "") or "").strip() or next_seed(cfg, hist)
    if etsy is None:
        key = secret("ETSY_API_KEY", required=False)
        etsy = Etsy(key) if key else False
    if ideogram is None:
        key = secret("IDEOGRAM_API_KEY", required=False)
        ideogram = Ideogram(key) if key else False
    cfg["drafting"]["illustrated"] = bool(ideogram)
    if not ideogram and cfg.get("illustrator", {}).get("require_art", True):
        msg = ("🛑 Not drafting: the illustrator is off because IDEOGRAM_API_KEY isn't reaching the crew. "
               "Check the secret exists (Settings → Secrets → Actions) and that forge.yml passes it to the draft job. "
               "No plain-text designs get filed while require_art is on.")
        summary(msg)
        crew_log(msg, gh)
        return []
    if review_fn is None:
        review_fn = lambda prev, text, niche: review(prev, text, niche, cfg["model"])
    if pf is None:
        tok = secret("PRINTIFY_API_TOKEN", required=False)
        pf = Printify(tok) if tok else False
    perf = shop_performance(etsy or None, _shop_name(cfg, pf)) if etsy else None
    kw = {"ask": ask} if ask else {}
    briefs, listings, report = run_pipeline(seed, cfg, etsy=etsy or None, perf_text=perf_compact(perf), history=hist, **kw)

    profs = profiles(cfg)
    cats = {}
    if pf and cfg["printify"].get("draft_products", True):
        try:
            shops, bps = pf.shops(), pf.blueprints()
            for prof in profs:
                try:
                    cats[prof["key"]] = resolve_catalog(pf, cfg["printify"], prof, blueprints=bps, shops=shops)
                except Exception as e:
                    summary(f"⚠️ {prof.get('name', prof['key'])} skipped: {e}")
        except Exception as e:
            summary(f"⚠️ Printify drafts skipped: {e}")

    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M")
    DRAFTS.mkdir(parents=True, exist_ok=True)
    if report:
        (DRAFTS / f"radar-{stamp}.json").write_text(json.dumps({"seed": seed, "report": report}, indent=1))
    pending = json.loads(PENDING.read_text()) if PENDING.exists() else []
    dropped = []
    for i, L in enumerate(listings, 1):
        did = f"{stamp}-{i:02d}-{_slug(phrase(L['spec']))}"
        print(f"DESIGN {i}/{len(listings)}  {L['niche']}: {phrase(L['spec'])}  [{L['mode']}]")
        if hist.is_repeat(phrase(L["spec"])) or any(similar(phrase(L["spec"]), phrase(o["spec"])) for o in listings[: i - 1] if o.get("draft_id")):
            print("  DROPPED: too similar to a design the crew already made.")
            dropped.append(phrase(L["spec"]))
            continue
        png, prev = make_artwork(L, cfg, ideogram, review_fn)
        if png is None:
            print("  DROPPED: no artwork passed the Art Director, so this design isn't filed.")
            dropped.append(phrase(L["spec"]))
            continue
        folder = DRAFTS / did
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "print.png").write_bytes(png)
        (folder / "mockup.png").write_bytes(prev)
        L["draft_id"] = did
        L["products"] = {}
        image_id = None
        for prof in profs:
            key = prof["key"]
            PL = adapt(L, prof)
            entry = {"name": prof.get("name", key), "price": PL["price"], "on": True, "product_id": "", "mockups": [], "colors": []}
            if key in cats and L.get("risk") != "high":
                try:
                    res = create_draft(pf, cats[key], PL, image_id or png, prof, f"forge-{did}.png")
                    image_id = res["image_id"]
                    entry.update(product_id=res["product"]["id"], colors=res["colors"], mockups=mockup_urls(res["product"]))
                    print(f"  PRINTIFY {entry['name']}: draft {entry['product_id']} ({', '.join(res['colors']) or 'n/a'})")
                except Exception as e:
                    print(f"  PRINTIFY {entry['name']} failed: {e}")
            L["products"][key] = entry
        first = next((p for p in L["products"].values() if p["mockups"]), None)
        if first:
            L["mockups"] = first["mockups"]
        (folder / "listing.json").write_text(json.dumps(L, indent=2))
        pending.append(did)
        hist.add(seed, L["niche"], phrase(L["spec"]), L.get("art_style", ""))
    PENDING.write_text(json.dumps(pending, indent=2))
    hist.save()

    summary(f"## Forge HQ draft run\n**Seed:** {seed}  ·  **Live Etsy data:** {'yes' if etsy else 'no'}  ·  **Illustrator:** {'on' if ideogram else 'off (add IDEOGRAM_API_KEY)'}\n")
    if report:
        summary("### Trend Radar\n| Search | Active listings | New with traction | Median price |\n|---|---|---|---|")
        for r in report:
            summary(f"| {r['query']} | {r['active_listings']:,} | {r['new_listings_with_traction']} | ${r['median_price']} |")
    if perf:
        summary(f"\n**Learning loop:** {perf['active']} live listings read from {perf['shop']}; {len(perf['winners'])} working, {len(perf['duds'])} not.")
    summary("\n### Opportunities picked\n| Niche | Demand | Low comp | Passion | Why |\n|---|---|---|---|---|")
    for b in briefs:
        summary(f"| {b['niche']} | {b.get('demand','')} | {b.get('competition','')} | {b.get('passion','')} | {b.get('why','')} |")
    kept = [L for L in listings if L.get("draft_id")]
    summary(f"\n**{len(kept)} drafts** ready for review ({len(profs)} products each)." + (f" {len(dropped)} dropped by the Art Director." if dropped else ""))
    crew_log(f"✅ Drafted {len(kept)} designs × {len(profs)} products. Seed: {seed}." + (f" Dropped {len(dropped)} whose art didn't pass review." if dropped else ""), gh)
    return kept


# ---------------- file issues ----------------

def cmd_file_issues(args, cfg, gh=None):
    from .github_queue import GitHub

    gh = gh or GitHub()
    if not PENDING.exists():
        summary("No new drafts to file.")
        return 0
    pending = json.loads(PENDING.read_text())
    gh.ensure_labels()
    filed = 0
    for did in pending:
        folder = DRAFTS / did
        L = json.loads((folder / "listing.json").read_text())
        mocks = L.get("mockups") or [gh.raw_url(f"drafts/{did}/mockup.png")]
        title, body = format_issue(L, mocks, gh.raw_url(f"drafts/{did}/print.png"), did, L.get("product_id", ""))
        labels = ["draft"] + (["risk-high"] if L.get("risk") == "high" else [])
        issue = gh.create_issue(title, body, labels)
        filed += 1
        summary(f"- #{issue.get('number')} {title}")
    PENDING.unlink()
    summary(f"\n**{filed} drafts are waiting for your approval** in the Issues tab.")
    return filed


# ---------------- publish ----------------

def cmd_publish(args, cfg, gh=None, pf=None) -> str:
    from .github_queue import GitHub
    from .printify import Printify, build_variants, create_draft, resolve_catalog
    from .render import render_print

    gh = gh or GitHub()
    n = int(args.issue)
    issue = gh.issue(n)
    labels = {l["name"] if isinstance(l, dict) else l for l in issue.get("labels", [])}

    if "published" in labels:
        return "already-published"
    if "approved" not in labels:
        return "not-approved"
    if args.actor and args.actor.lower() != gh.owner.lower() and not getattr(args, "force", False):
        gh.comment(n, f"Only @{gh.owner} can approve publishing. @{args.actor}'s label was ignored.")
        gh.remove_label(n, "approved")
        return "not-owner"
    if issue.get("state") == "closed":
        return "closed"

    listing = parse_issue(issue.get("body", ""))
    listing["description"] = compliance.ensure_disclosure(listing["description"])
    listing["tags"] = compliance.fix_tags(listing["tags"])
    stored = {}
    folder = DRAFTS / listing["draft_id"] if listing.get("draft_id") else None
    if folder and (folder / "listing.json").exists():
        stored = json.loads((folder / "listing.json").read_text())
        listing["evidence"] = stored.get("evidence", [])
    flags = compliance.check(listing)
    blockers = compliance.blocking(flags)
    risky = "risk-high" in labels or listing.get("risk") == "high"
    if (blockers or risky) and "override-risk" not in labels:
        reasons = "\n".join(f"- {f['msg']}" for f in blockers) or "- Marked high trademark risk by the Compliance agent."
        gh.comment(n, "⛔ **Not published.**\n" + reasons + "\n\nEdit the issue to fix it and re-add `approved`, "
                      "or add the `override-risk` label if you've checked it yourself (USPTO search) and want to publish anyway.")
        gh.remove_label(n, "approved")
        return "blocked"

    from .products import adapt, profiles

    pcfg = cfg["printify"]
    profs = {p["key"]: p for p in profiles(cfg)}
    fam = listing.get("products") or {}
    if not fam:  # issue made before product families: treat as a single tee
        fam = {"tee": {"on": True, "price": listing["price"], "product_id": listing.get("product_id", ""), "name": "T-Shirt"}}
    stored_fam = stored.get("products") or {}
    design_changed = bool(listing.get("mode") != "illustrated" and stored and stored.get("spec") != listing["spec"])
    results, failures, removed = [], [], []
    try:
        pf = pf or Printify(secret("PRINTIFY_API_TOKEN"))
        shops, bps = pf.shops(), pf.blueprints()
        png = None
        image_id = None
        shop_title = ""
        for key, item in fam.items():
            prof = profs.get(key) or {"key": key, "name": item.get("name", key)}
            pid = item.get("product_id") or ""
            try:
                cat = resolve_catalog(pf, pcfg, prof if key in profs else None, blueprints=bps, shops=shops)
                shop_id = cat["shop"]["id"]
                shop_title = cat["shop"].get("title", shop_id)
                if not item.get("on", True):
                    if pid:
                        pf.delete_product(shop_id, pid)
                        removed.append(prof.get("name", key))
                    continue
                PL = adapt(listing, prof)
                PL["price"] = float(item.get("price") or PL["price"])
                colors = (stored_fam.get(key) or {}).get("colors") or stored.get("colors") if key == "tee" else (stored_fam.get(key) or {}).get("colors")
                if pid and not design_changed:
                    from .printify import pick_colors
                    colors = colors if colors is not None else pick_colors(cat["variants"], PL["spec"], prof)
                    rows = build_variants(cat["variants"], colors, prof.get("sizes"), PL["price"], prof.get("upcharge_cents") or {})
                    pf.update_product(shop_id, pid, {"title": PL["title"], "description": PL["description"], "tags": PL["tags"], "variants": rows})
                else:
                    if pid:
                        try:
                            pf.delete_product(shop_id, pid)
                        except Exception:
                            pass
                    if image_id is None and png is None:
                        if listing.get("mode") == "illustrated" and folder and (folder / "print.png").exists():
                            png = (folder / "print.png").read_bytes()
                        else:
                            png = render_print(listing["spec"])
                    res = create_draft(pf, cat, PL, image_id or png, prof, f"forge-{n}-{_slug(phrase(listing['spec']))}.png")
                    image_id, pid, colors = res["image_id"], res["product"]["id"], res["colors"]
                if pcfg.get("publish_to_etsy", True):
                    pf.publish(shop_id, pid)
                results.append((prof.get("name", key), pid, PL["price"], colors or [], cat["prov"].get("title")))
            except Exception as e:
                failures.append((prof.get("name", key), str(e)))
        if not results and failures:
            raise RuntimeError("; ".join(f"{name}: {err}" for name, err in failures))
    except Exception as e:
        gh.comment(n, f"❌ **Publishing failed.** Nothing was listed on Etsy.\n\n```\n{str(e)[:1500]}\n```\nFix the problem and re-add the `approved` label to retry.")
        gh.remove_label(n, "approved")
        gh.add_labels(n, ["publish-failed"])
        raise

    published = pcfg.get("publish_to_etsy", True)
    lines = [f"- **{name}**: ${price:.2f}, {', '.join(colors) or 'standard'} (Printify `{pid}`, {prov})" for name, pid, price, colors, prov in results]
    msg = [f"✅ **{'Sent to Etsy' if published else 'Created in Printify (not published)'}**: {len(results)} listing{'s' if len(results) != 1 else ''} in **{shop_title}**", "", *lines]
    if removed:
        msg.append(f"\nRemoved unticked drafts: {', '.join(removed)}")
    if failures:
        msg.append("\n⚠️ Some products failed and were NOT listed:\n" + "\n".join(f"- {name}: `{err[:300]}`" for name, err in failures))
        msg.append("Re-add `approved` to retry just those (listed ones won't duplicate).")
    msg.append("\n" + ("Printify takes a minute or two to push each one to Etsy. Check **Etsy → Shop Manager → Listings**." if published else "Open Printify → My products to review and publish."))
    gh.comment(n, "\n".join(msg))
    gh.remove_label(n, "publish-failed")
    if failures:
        gh.remove_label(n, "approved")
        gh.add_labels(n, ["publish-failed"])
        return "partial"
    gh.add_labels(n, ["published"])
    gh.close(n)
    return "published" if published else "created"


# ---------------- cleanup ----------------

def cmd_cleanup(args, cfg, gh=None, pf=None) -> str:
    from .github_queue import GitHub
    from .printify import Printify, pick_shop

    gh = gh or GitHub()
    n = int(args.issue)
    issue = gh.issue(n)
    labels = {l["name"] if isinstance(l, dict) else l for l in issue.get("labels", [])}
    if "published" in labels or issue.get("state") != "closed":
        return "skip"
    try:
        listing = parse_issue(issue.get("body", ""))
    except ValueError:
        return "skip"
    pids = [p.get("product_id") for p in (listing.get("products") or {}).values() if p.get("product_id")]
    if not pids and listing.get("product_id"):
        pids = [listing["product_id"]]
    if not pids:
        return "nothing"
    pf = pf or Printify(secret("PRINTIFY_API_TOKEN"))
    shop = pick_shop(pf.shops(), cfg["printify"].get("shop_id"))
    gone = 0
    for pid in pids:
        try:
            pf.delete_product(shop["id"], pid)
            gone += 1
        except Exception as e:
            print(f"Delete failed for {pid} (may already be gone): {e}")
    gh.comment(n, f"🗑️ Rejected. {gone} unpublished Printify draft{'s' if gone != 1 else ''} deleted.")
    return "deleted" if gone else "failed"


# ---------------- weekly report ----------------

def cmd_report(args, cfg, etsy=None, pf=None, gh=None) -> str:
    from .etsy import Etsy
    from .github_queue import GitHub
    from .performance import report_markdown, shop_performance
    from .printify import Printify

    if etsy is None:
        key = secret("ETSY_API_KEY", required=False)
        etsy = Etsy(key) if key else None
    if not etsy:
        summary("No ETSY_API_KEY, so there's no report.")
        return "no-key"
    if pf is None:
        tok = secret("PRINTIFY_API_TOKEN", required=False)
        pf = Printify(tok) if tok else None
    perf = shop_performance(etsy, _shop_name(cfg, pf))
    if not perf:
        summary("Couldn't read your shop. Set drafting.etsy_shop_name in config.yaml to your exact Etsy shop name.")
        return "no-shop"
    md = report_markdown(perf)
    gh = gh or GitHub()
    gh.ensure_labels()
    gh.create_issue(f"Weekly shop report: {dt.date.today():%b %d}", md, ["report"])
    summary(md)
    return "filed"


# ---------------- check ----------------

def cmd_check(args, cfg, pf=None, etsy=None):
    from .etsy import Etsy
    from .printify import Printify, pick_blueprint, pick_provider, pick_shop

    pcfg = cfg["printify"]
    summary("## Forge HQ setup check\n")
    ok = True
    try:
        pf = pf or Printify(secret("PRINTIFY_API_TOKEN"))
        shops = pf.shops()
        summary("**Printify shops**\n\n| ID | Name | Channel |\n|---|---|---|")
        for s in shops:
            summary(f"| {s.get('id')} | {s.get('title')} | {s.get('sales_channel')} |")
        shop = pick_shop(shops, pcfg.get("shop_id"))
        bp = pick_blueprint(pf.blueprints(), pcfg.get("blueprint_brand", "Bella+Canvas"), pcfg.get("blueprint_model", "3001"), pcfg.get("blueprint_id"))
        provs = pf.providers(bp["id"])
        prov = pick_provider(provs, pcfg.get("preferred_providers", []), pcfg.get("print_provider_id"))
        summary(f"\n✅ **Using shop:** {shop.get('title')} (`{shop['id']}`)")
        summary(f"**Blank:** {bp.get('title')} (blueprint `{bp['id']}`)")
        summary(f"**Print provider:** {prov.get('title')} (`{prov['id']}`)\n")
        colors = sorted({(v.get('options') or {}).get('color') or str(v.get('title', '')).split('/')[0].strip() for v in pf.variants(bp['id'], prov['id'])})
        summary(f"Colors this provider offers: {', '.join(c for c in colors if c)}")
        from .printify import resolve_catalog
        from .products import profiles
        summary("\n**Product family**\n\n| Product | Blank | Provider |\n|---|---|---|")
        bps = pf.blueprints()
        for prof in profiles(cfg):
            try:
                c = resolve_catalog(pf, pcfg, prof, blueprints=bps, shops=shops)
                summary(f"| ✅ {prof.get('name')} | {c['bp'].get('title')} (`{c['bp']['id']}`) | {c['prov'].get('title')} (`{c['prov']['id']}`) |")
            except Exception as e:
                ok = False
                summary(f"| ❌ {prof.get('name')} | {e} | |")
    except SystemExit as e:
        ok = False
        summary(f"❌ {e}")
    except Exception as e:
        ok = False
        summary(f"❌ Printify check failed: {e}")

    key = secret("ETSY_API_KEY", required=False)
    if key or etsy:
        try:
            st = (etsy or Etsy(key)).search_stats("fishing shirt", limit=5)
            summary(f"\n✅ Etsy live data works: 'fishing shirt' has {st['active_listings']:,} active listings.")
        except Exception as e:
            summary(f"\n⚠️ Etsy API key is set but the test search failed: {e}")
    else:
        summary("\n⚠️ No ETSY_API_KEY. The Trend Radar is off; drafts use Claude's judgment only.")
    summary("\n✅ Claude API key is set." if secret("ANTHROPIC_API_KEY", required=False) else "\n❌ ANTHROPIC_API_KEY is missing. The agents can't run without it.")
    summary("\n✅ Ideogram key is set: illustrated designs are on." if secret("IDEOGRAM_API_KEY", required=False) else "\n⚠️ No IDEOGRAM_API_KEY. Designs will be typography-only until you add it.")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="forge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--seed", default="")
    d.add_argument("--auto", action="store_true", help="scheduled run: skip if too many drafts are waiting")
    sub.add_parser("file-issues")
    sub.add_parser("report")
    p = sub.add_parser("publish")
    p.add_argument("--issue", required=True)
    p.add_argument("--actor", default="")
    p.add_argument("--force", action="store_true")
    c = sub.add_parser("cleanup")
    c.add_argument("--issue", required=True)
    sub.add_parser("check")
    lg = sub.add_parser("log")
    lg.add_argument("--text", required=True)
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.cmd == "draft":
        cmd_draft(args, cfg)
    elif args.cmd == "file-issues":
        cmd_file_issues(args, cfg)
    elif args.cmd == "publish":
        print("result:", cmd_publish(args, cfg))
    elif args.cmd == "cleanup":
        print("result:", cmd_cleanup(args, cfg))
    elif args.cmd == "report":
        print("result:", cmd_report(args, cfg))
    elif args.cmd == "log":
        crew_log(args.text)
    elif args.cmd == "check":
        return cmd_check(args, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
