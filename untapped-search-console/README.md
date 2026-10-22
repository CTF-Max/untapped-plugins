# Untapped Search Console

What people search to find your site, which searches are close to page one, and what moved since last month,
read from your own Search Console. Free and read-only. Built by [Find Untapped Growth](https://finduntappedgrowth.com/).

## Tools

| Tool | Answers |
|---|---|
| `google_login` / `google_login_status` / `google_logout` | One read-only Google sign-in, shared with every Untapped Google plugin |
| `gsc_sites` | Your Search Console properties |
| `gsc_totals` | The site's true clicks and impressions for a window |
| `gsc_performance` | Rows by query / page / country / device / date (up to 3 at once), with filters |
| `gsc_whats_working` | **earning** (protect) · **close**, position 4–20 with no clicks (where work pays) · **top3_no_clicks** (fix the title/snippet) · **invisible** (past 20) |
| `gsc_compare` | This window vs the previous one: gainers, losers, new, lost, and both windows' true totals |

Windows end 3 days back by default, because Search Console's last ~2 days aren't final and a window ending today
shows a fake dip.

## Install

- **Claude Code:** `/plugin install untapped-search-console --marketplace CTF-Max/untapped-plugins`
  (or, from a terminal: `claude plugin marketplace add CTF-Max/untapped-plugins`, then
  `claude plugin install untapped-search-console@untapped-plugins`).
- **Codex:** `codex plugin marketplace add CTF-Max/untapped-plugins`, then `codex plugin add untapped-search-console@untapped-plugins`.
- Needs Python 3.10+ on PATH as `python`. Standard library only: nothing to `pip install`.

## Setup

Same Google sign-in as Untapped Index Watch: a Google Cloud **Desktop app** OAuth client with the Search Console
API enabled (steps in [Index Watch's README](../untapped-index-watch/README.md#setup-once-about-5-minutes)).
Claude Code: choose that file in the plugin's settings ("Google OAuth client file"). Codex:
`setx UNTAPPED_GOOGLE_CLIENT_SECRET "C:\path\to\client_secret.json"` and restart. Then ask your agent to run
`google_login`. Signed in already through Index Watch? Nothing more to do.

## What it connects to

Only Google: `accounts.google.com` and `oauth2.googleapis.com` to sign in, `searchconsole.googleapis.com` and
`www.googleapis.com` for your Search Console data. No telemetry. Details: [PRIVACY.md](PRIVACY.md).

## Limits

- Google hides rare queries for privacy, so query rows never add up to the site total; `gsc_totals` gives the real one.
- Position is an average of averages: directional only.
- `gsc_compare` compares each window's top 1,000 rows, so "lost" can mean "fell below the top 1,000".

## Development

```
python -m unittest discover -s untapped-search-console/tests   # offline, 7 tests
```
