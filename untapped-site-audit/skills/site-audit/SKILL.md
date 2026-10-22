---
name: site-audit
description: Run a live website audit in the order that finds the real bottleneck (indexed → seen → which buyer phrases → does each page target its phrase → visitors → engaged → buyers). Use when the user asks "audit my site", "why isn't my site getting customers/traffic", "is my site indexed / ranking / being seen", before a search plan, or monthly for a site they manage. Uses untapped-site-audit, plus untapped-index-watch, untapped-search-console and untapped-serp when installed.
---

# Live site audit (indexed → seen → visitors → buyers)

Each step answers one question. **Never jump to the next step's fix while an earlier step is failing**: rewriting
titles can't help pages Google hasn't indexed, and a button colour can't help a page nobody sees.

| # | Question | Tool | A fail means |
|---|---|---|---|
| 1 | **Indexed?** | `index_check` (untapped-index-watch) | Fix discovery first: sitemap submitted, links to new pages, *Request indexing*. UNKNOWN = re-check, not "missing" |
| 2 | **Seen?** | `gsc_totals`, `gsc_whats_working`, `gsc_performance` by page (untapped-search-console), last 90 days + `gsc_compare` | Indexed with ~0 impressions = a demand or authority problem, not indexing |
| 3 | **Which buyer phrases?** | Step 2 queries + `google_search_volume` and `google_serp` (untapped-serp, paid: ask first) | One primary + 2–4 secondary phrases per money page, each labelled with its evidence (impressions, volume, or "unverified"). Ready-to-hire ≠ research ("what is…") |
| 4 | **Does each page target its phrase?** | `audit_pages` / `page_facts` (this plugin) | A ranked fix list with exact new titles/H1s; one page owns each phrase (no two pages competing); improve an existing page before adding one |
| 5 | **Visitors?** | The site's analytics (ask the user; not available to these tools) | Report missing data as **not collected**, never as zero. Subtract the owner's own visits and preview domains |
| 6 | **Engaged? Clicked?** | Event tracking, if the site has it | No event tracking = **UNKNOWN**: say so and recommend installing it. Page views can't answer this |
| 7 | **Buyers?** | Leads, bookings and calls the owner reports | Real enquiries only; test submissions don't count |
| 8 | **Write it down** | A dated report | Every claim has its number and source; unknowns stay labelled UNKNOWN |

## Working rules
- **Traffic decides the order of fixes.** Below ~100 real visits a week, don't A/B test or tune button colours:
  give every page a route for a ready buyer (call, text, book) and get the measuring in place.
- Without Search Console access, steps 1–2 are UNKNOWN. Say so; `audit_pages` still covers step 4.
- `audit_pages` reads the HTML as served. A page built by JavaScript after loading may look empty here; check one
  such page in the browser before calling it thin.
- Fixes go in the page source and get redeployed; re-run steps 1 and 4 after the release, and step 2 again 28 days
  later (search data is slow).
- Keep the user's money in mind: untapped-serp calls cost cents each; batch volume lookups into one call.
