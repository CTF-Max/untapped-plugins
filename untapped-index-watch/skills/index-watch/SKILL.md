---
name: index-watch
description: Check whether a website's pages are in Google's index and what to do about the ones that aren't, using the untapped-index-watch tools (Search Console URL Inspection). Use when the user asks "is my site indexed", "why isn't my page on Google", "which pages dropped out", after publishing new pages, or as the first step of any website audit. Needs the user's own Search Console access.
---

# Index watch (untapped-index-watch)

Read-only and free. Google allows 2,000 inspections per site per day; the default checks 50 URLs.

## First time
1. `google_login_status`. If `client_configured` is false, walk the user through it (once, ~5 minutes):
   Google Cloud console → new project → enable **Google Search Console API** → APIs & Services → OAuth consent
   screen (External, add themselves as a test user) → Credentials → Create OAuth client ID → **Desktop app** →
   Download JSON → set `UNTAPPED_GOOGLE_CLIENT_SECRET` to that file's path → restart the app.
2. `google_login` → the browser opens → they approve read-only access → `google_login_status` shows `signed_in`.
   One sign-in serves every Untapped Google plugin.

## Checking a site
1. `index_check` with `site` (`example.com` is enough; it finds the matching property). It reads `/sitemap.xml`
   unless you pass `sitemap_url` or `urls`.
2. Report in this order: indexed / not indexed / **unknown**, then `newly_dropped`, then each `needs_attention` item
   with its `usually_means` and `do`.
3. Run it again after fixes or new pages; `index_history` shows the trend.

## Reading it honestly
- **UNKNOWN is not "not indexed".** The inspection call failed; check again later.
- **"URL is unknown to Google"** on a new page is a discovery delay, not a penalty. The fix is a submitted sitemap,
  a link from a crawled page, and *Request indexing* (a manual click in Search Console; there is no API for it).
- **Indexed is not seen.** A page can be indexed with zero impressions: that's a demand or authority problem, which
  Search Console's performance data (untapped-search-console) answers, not this tool.
- "Page with redirect" for http/www/old URLs is usually the redirects working. Don't "fix" it.
