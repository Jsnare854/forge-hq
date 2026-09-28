# Forge HQ

AI agents that run a print-on-demand t-shirt shop. They find niches, design typography tees, and write Etsy listings. You approve each one, and approved designs go to Etsy through Printify.

```
 every morning (or when you press Run)
 SCOUT → TREND RADAR → ANALYST → DESIGNER + COPYWRITER → ILLUSTRATOR → ART DIRECTOR → COMPLIANCE
          live Etsy        why it       original phrase,    Ideogram art   Claude checks    trademarks,
          listings:        sells        title, 13 tags      (transparent)  spelling and     copying,
          momentum =                                                       quality          Etsy limits
          favorites/day
                                          ↓
         unpublished Printify draft (real mockups) + GitHub Issue with the evidence
                                          ↓
         you add `approved`  →  your edits are applied  →  published to Etsy
         you close the issue →  the Printify draft is deleted
```

**How ideas are found:** the Trend Radar scans live Etsy searches and ranks shirts by momentum (favorites per day since listed), so the agents see what's catching fire right now. Competitor listings are research only. Designs must be original, and Compliance blocks any phrase that overlaps a competitor's title.

## Your daily routine

1. Open the **Issues** tab (the GitHub phone app works well). Each draft shows the shirt mockup, title, 13 tags, price and a compliance check.
2. **Approve:** add the `approved` label. It usually shows up on Etsy within a few minutes.
3. **Reject:** close the issue.
4. **Tweak first:** edit the issue (title, tags, price, design text, layout, colors), then approve. The publisher re-renders the design from your edited text.

Anything flagged as a possible trademark is blocked. Once you've checked the phrase yourself at [tmsearch.uspto.gov](https://tmsearch.uspto.gov), add `override-risk` along with `approved` to publish it anyway.

## Running things by hand

Go to **Actions → Forge HQ → Run workflow** and pick a task:

- **draft:** type a seed idea (e.g. "Florida fishing families") or leave it blank to use the next line in `seeds.txt`.
- **check:** confirms your Printify shop, the shirt blank, the print provider, and your API keys.
- **publish:** retries one issue by number.
- **test:** runs the automated tests.

## Settings you can change without code

- `config.yaml`: niches per run, designs per niche, price range, shirt colors, sizes, provider, and whether to publish straight to Etsy.
- `seeds.txt`: the idea list the daily run cycles through.

## Secrets (Settings → Secrets and variables → Actions)

| Name | Where to get it | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys (set a monthly spend limit) | Yes |
| `PRINTIFY_API_TOKEN` | Printify → Account → Connections → Generate token | Yes |
| `IDEOGRAM_API_KEY` | ideogram.ai → API (add credit) | Optional, turns on illustrated designs |
| `ETSY_API_KEY` | etsy.com/developers/your-apps: your app's keystring and shared secret joined by a colon, like `abc123:xyz789` | Optional, turns on live data |

Keys never go in code, in `config.yaml`, or in chat.

## What it costs to run

- **GitHub Actions:** free for this volume.
- **Claude API:** about $0.50–1.50 per daily run (research, writing, and art review).
- **Ideogram:** a few cents per image, about 2–4 images per design. Roughly $1–3 per run of 10 designs.
- **Etsy:** $0.20 per published listing, plus fees when you sell.
- **Printify:** free. You pay the base cost only when an order comes in.

Fonts in `forge/fonts` come from Google Fonts under the SIL Open Font License / Apache 2.0.
