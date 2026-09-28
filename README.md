# Forge HQ

AI agents that run a print-on-demand t-shirt shop. They find niches, design typography tees, and write Etsy listings. You approve each one, and approved designs go to Etsy through Printify.

```
 every morning (or when you press Run)
 ┌────────┐   ┌─────────┐   ┌──────────┐   ┌────────────┐   ┌────────────┐
 │ SCOUT  │ → │ ANALYST │ → │ DESIGNER │ → │ COPYWRITER │ → │ COMPLIANCE │ → GitHub Issue (draft)
 └────────┘   └─────────┘   └──────────┘   └────────────┘   └────────────┘
   live Etsy data when ETSY_API_KEY is set                         │
                                                                   ▼
                          you add the `approved` label (phone or web)
                                                                   ▼
                  Printify: upload print file → Bella+Canvas 3001 product → publish to Etsy
```

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
| `ETSY_API_KEY` | etsy.com/developers/your-apps: your app's keystring and shared secret joined by a colon, like `abc123:xyz789` | Optional, turns on live data |

Keys never go in code, in `config.yaml`, or in chat.

## What it costs to run

- **GitHub Actions:** free for this volume.
- **Claude API:** a few cents to about $1 per daily run.
- **Etsy:** $0.20 per published listing, plus fees when you sell.
- **Printify:** free. You pay the base cost only when an order comes in.

Fonts in `forge/fonts` come from Google Fonts under the SIL Open Font License / Apache 2.0.
