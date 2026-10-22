---
name: search-console
description: Answer "what do people search to find my site, what's close to page one, what changed" from the user's own Google Search Console, using the untapped-search-console tools. Use for search traffic questions, keyword opportunities on an existing site, before rewriting titles or writing new pages, and to judge whether a search change worked. Not for sites the user doesn't own (use untapped-serp for those).
---

# Search Console (untapped-search-console)

Free and read-only. Sign-in is shared with untapped-index-watch: if `google_login_status` says not configured,
follow the setup in that plugin's skill (a Desktop-app OAuth client + `UNTAPPED_GOOGLE_CLIENT_SECRET`), then
`google_login`.

## Which tool
| Question | Tool |
|---|---|
| "How is the site doing?" | `gsc_totals` (true totals), then `gsc_whats_working` |
| "What should I work on?" | `gsc_whats_working`: start with **close**, then **top3_no_clicks** |
| "Which searches reach this page?" | `gsc_performance` with `dimensions: ["query"]`, `page_contains` |
| "Which page ranks for this search?" | `gsc_performance` with `dimensions: ["query","page"]`, `query_contains` |
| "Did my change work? What moved?" | `gsc_compare` (same-length windows; add `page_contains` for one page) |

## Reading it honestly
- Windows end **3 days back** by default because recent data isn't final. Never call a drop in the last 2–3 days
  real unless `end_lag_days` was 3+.
- `gsc_performance` sums cover the returned rows only; quote `gsc_totals` for the site's real totals.
- Position is an average of averages: say "around 8", not "8.3".
- Under ~100 impressions a month, week-to-week changes are noise; say so rather than reading trends into them.
- **Indexed with zero impressions** is a demand/authority problem, not an indexing one. Check the page's target
  phrase has searches (untapped-serp `google_search_volume`) before rewriting it.
- Improve the page that already ranks before creating a new page for the same query (that splits the signal).
