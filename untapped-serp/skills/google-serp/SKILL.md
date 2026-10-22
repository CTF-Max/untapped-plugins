---
name: google-serp
description: Look up real Google results and search volume through the untapped-serp tools. Use when the task needs where a site ranks on Google, who ranks for a phrase, what People Also Ask / the local pack / an AI Overview shows, which sites an AI Overview cites, or how many people search a phrase each month, and built-in web search is too thin to answer. Not for reading a page's content (use web fetch) or for anything Search Console already measures for a site you own.
---

# Google results and search volume (untapped-serp)

The tools call DataForSEO with **the user's own account**. Each fresh call costs real money, so check the cache and
the price before calling.

## Tools
| Tool | Cost | Use for |
|---|---|---|
| `google_serp` | ~$0.002 per 10 results (depth 10 = one charge); cached 24 h | Rankings for one phrase in one place; `target_domain` lists every position a site holds |
| `google_search_volume` | ~$0.09 per call, 1–100 keywords (batch them!); cached 30 days | Monthly searches, CPC, competition |
| `serp_estimate` | free | Cost reserve + whether today's cap allows a call |
| `serp_spend` | free | Spend today/this month, the cap, recent calls, whether credentials are set |

## How to work
1. **Batch volume lookups:** one `google_search_volume` call with all the keywords, never one call per keyword.
2. **Set the place:** local rankings change by city. Use `location_name` like `"Palm Coast,Florida,United States"`
   or `location_coordinate` `"29.58,-81.21"` for a street-level view. The default is the whole United States.
3. **Keep depth small:** depth 10 answers "is it on page one". Use 20–100 only when you need to find a site that
   isn't on page one. Each extra 10 results is another charge.
4. **If a call is refused by the cap,** tell the user the numbers in the error and ask before they raise
   `UNTAPPED_SERP_DAILY_CAP_USD`. Never work around the cap.
5. **If credentials are missing,** say: add the DataForSEO API login and password (dashboard → API Access). In
   Claude Code they go in the plugin's settings (`/plugin` → untapped-serp → configure); in Codex, set
   `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` as environment variables and restart the app.

## Reading the results honestly
- One SERP is **one location, one device, one moment**. Say which, and don't call it "the" ranking.
- `search_volume: null` means **no data**, not zero. Google Ads volumes are rounded buckets: treat 10 vs 20 as
  "very low", not a doubling.
- `target: "not in top N"` means not found in the results fetched, not "not indexed".
- `sandbox: true` means dummy data from DataForSEO's free test API: never report it as real Google results.
- Quote the `check_url` when you show a ranking, so the user can open the same search.
