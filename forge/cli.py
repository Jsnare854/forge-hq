"""Command line entry points used by the GitHub Actions workflows.

  python -m forge draft [--seed "..."] [--niches N] [--designs N]   agents draft listings into drafts/
  python -m forge file-issues                                        turn new drafts into approval issues
  python -m forge publish --issue N --actor USER                     publish one approved issue
  python -m forge check                                              verify Printify + Etsy setup
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from . import compliance
from .config import ROOT, load_config, secret
from .spec import format_issue, parse_issue, phrase

DRAFTS = ROOT / "drafts"
PENDING = DRAFTS / "pending.json"


def summary(text: str):
    """Write to the GitHub Actions run summary page (and stdout)."""
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "design"


def next_seed(cfg: dict) -> str:
    path = ROOT / cfg["drafting"].get("seeds_file", "seeds.txt")
    seeds = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    if not seeds:
        raise SystemExit("seeds.txt is empty. Add at least one seed idea.")
    return seeds[dt.date.today().toordinal() % len(seeds)]


# ---------------- draft ----------------

def cmd_draft(args, cfg, ask=None, etsy=None) -> list[dict]:
    from .agents import run_pipeline
    from .etsy import Etsy
    from .render import render_mockup, render_print

    if args.niches:
        cfg["drafting"]["niches_per_run"] = int(args.niches)
    if args.designs:
        cfg["drafting"]["designs_per_niche"] = int(args.designs)
    seed = (args.seed or "").strip() or next_seed(cfg)
    if etsy is None:
        key = secret("ETSY_API_KEY", required=False)
        etsy = Etsy(key) if key else None
    kw = {"ask": ask} if ask else {}
    niches, listings = run_pipeline(seed, cfg, etsy=etsy, **kw)

    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M")
    pending = json.loads(PENDING.read_text()) if PENDING.exists() else []
    for i, L in enumerate(listings, 1):
        did = f"{stamp}-{i:02d}-{_slug(phrase(L['spec']))}"
        folder = DRAFTS / did
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "mockup.png").write_bytes(render_mockup(L["spec"]))
        (folder / "print.png").write_bytes(render_print(L["spec"]))
        (folder / "listing.json").write_text(json.dumps(L, indent=2))
        pending.append(did)
    PENDING.write_text(json.dumps(pending, indent=2))

    summary(f"## Forge HQ draft run\n**Seed:** {seed}  ·  **Live Etsy data:** {'yes' if etsy else 'no (add ETSY_API_KEY to enable)'}\n")
    summary("| Niche | Demand | Low comp | Passion | Why |\n|---|---|---|---|---|")
    for n in niches:
        summary(f"| {n['niche']} | {n.get('demand','')} | {n.get('competition','')} | {n.get('passion','')} | {n.get('why','')} |")
    summary(f"\n**{len(listings)} drafts** rendered.")
    return listings


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
        title, body = format_issue(L, gh.raw_url(f"drafts/{did}/mockup.png"), gh.raw_url(f"drafts/{did}/print.png"))
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
    from .printify import Printify, build_product, build_variants, pick_blueprint, pick_colors, pick_provider, pick_shop
    from .render import render_print

    gh = gh or GitHub()
    n = int(args.issue)
    issue = gh.issue(n)
    labels = {l["name"] if isinstance(l, dict) else l for l in issue.get("labels", [])}

    if "published" in labels:
        return "already-published"
    if "approved" not in labels:
        return "not-approved"
    if args.actor and args.actor.lower() != gh.owner.lower() and not args.force:
        gh.comment(n, f"Only @{gh.owner} can approve publishing. @{args.actor}'s label was ignored.")
        gh.remove_label(n, "approved")
        return "not-owner"
    if issue.get("state") == "closed":
        return "closed"

    listing = parse_issue(issue.get("body", ""))
    listing["description"] = compliance.ensure_disclosure(listing["description"])
    listing["tags"] = compliance.fix_tags(listing["tags"])
    flags = compliance.check(listing)
    blockers = compliance.blocking(flags)
    risky = "risk-high" in labels or listing.get("risk") == "high"
    if (blockers or risky) and "override-risk" not in labels:
        reasons = "\n".join(f"- {f['msg']}" for f in blockers) or "- Marked high trademark risk by the Compliance agent."
        gh.comment(
            n,
            "⛔ **Not published.**\n" + reasons + "\n\nEdit the issue to fix it and re-add `approved`, "
            "or add the `override-risk` label if you've checked it yourself (USPTO search) and want to publish anyway.",
        )
        gh.remove_label(n, "approved")
        return "blocked"

    pcfg = cfg["printify"]
    try:
        pf = pf or Printify(secret("PRINTIFY_API_TOKEN"))
        shop = pick_shop(pf.shops(), pcfg.get("shop_id"))
        bp = pick_blueprint(pf.blueprints(), pcfg.get("blueprint_brand", "Bella+Canvas"), pcfg.get("blueprint_model", "3001"), pcfg.get("blueprint_id"))
        prov = pick_provider(pf.providers(bp["id"]), pcfg.get("preferred_providers", []), pcfg.get("print_provider_id"))
        variants = pf.variants(bp["id"], prov["id"])
        colors = pick_colors(variants, listing["spec"], pcfg)
        rows = build_variants(variants, colors, pcfg.get("sizes", ["S", "M", "L", "XL", "2XL"]), listing["price"], pcfg.get("upcharge_cents", {}))
        png = render_print(listing["spec"])
        image_id = pf.upload_png(f"forge-{n}-{_slug(phrase(listing['spec']))}.png", png)
        product = pf.create_product(shop["id"], build_product(listing, image_id, bp["id"], prov["id"], rows, pcfg.get("placement", {})))
        pid = product["id"]
        published = False
        if pcfg.get("publish_to_etsy", True):
            pf.publish(shop["id"], pid)
            published = True
    except Exception as e:
        gh.comment(n, f"❌ **Publishing failed.** Nothing was listed on Etsy.\n\n```\n{str(e)[:1500]}\n```\nFix the problem and re-add the `approved` label to retry.")
        gh.remove_label(n, "approved")
        gh.add_labels(n, ["publish-failed"])
        raise

    gh.comment(
        n,
        f"✅ **{'Sent to Etsy' if published else 'Created in Printify (not published)'}**\n\n"
        f"- Printify product: `{pid}` in shop **{shop.get('title', shop['id'])}**\n"
        f"- Blank: {bp.get('title', 'Bella+Canvas 3001')} by **{prov.get('title')}**\n"
        f"- Colors: {', '.join(colors)}  ·  Sizes: {', '.join(pcfg.get('sizes', []))}  ·  Price ${listing['price']:.2f}\n\n"
        + ("Printify takes a minute or two to push it to Etsy. Check **Etsy → Shop Manager → Listings**." if published else "Open Printify → My products to review and publish it."),
    )
    gh.remove_label(n, "publish-failed")
    gh.add_labels(n, ["published"])
    gh.close(n)
    return "published" if published else "created"


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
        summary(f"\n**Using shop:** {shop.get('title')} (`{shop['id']}`)")
        summary(f"**Blank:** {bp.get('title')} (blueprint `{bp['id']}`)")
        summary(f"**Print provider:** {prov.get('title')} (`{prov['id']}`)\n")
        summary("Other providers for this blank:\n")
        for p in provs[:15]:
            summary(f"- `{p.get('id')}` {p.get('title')} ({(p.get('location') or {}).get('country', '?')})")
        colors = sorted({(v.get('options') or {}).get('color') or str(v.get('title', '')).split('/')[0].strip() for v in pf.variants(bp['id'], prov['id'])})
        summary(f"\nColors this provider offers: {', '.join(c for c in colors if c)}")
        summary(f"\n✅ Printify is connected. To lock these in, set in config.yaml:\n```yaml\nshop_id: {shop['id']}\nblueprint_id: {bp['id']}\nprint_provider_id: {prov['id']}\n```")
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
        summary("\n⚠️ No ETSY_API_KEY yet. Drafts will use Claude's judgment instead of live Etsy data until you add it.")
    anth = secret("ANTHROPIC_API_KEY", required=False)
    summary("\n✅ Claude API key is set." if anth else "\n❌ ANTHROPIC_API_KEY is missing. The agents can't run without it.")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="forge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--seed", default="")
    d.add_argument("--niches", default="")
    d.add_argument("--designs", default="")
    sub.add_parser("file-issues")
    p = sub.add_parser("publish")
    p.add_argument("--issue", required=True)
    p.add_argument("--actor", default="")
    p.add_argument("--force", action="store_true")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.cmd == "draft":
        cmd_draft(args, cfg)
        return 0
    if args.cmd == "file-issues":
        cmd_file_issues(args, cfg)
        return 0
    if args.cmd == "publish":
        result = cmd_publish(args, cfg)
        print("result:", result)
        return 0
    if args.cmd == "check":
        return cmd_check(args, cfg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
