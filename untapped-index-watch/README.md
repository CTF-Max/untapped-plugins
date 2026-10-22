# Untapped Index Watch

Is every page of your site in Google's index, and what changed since last time? Free and read-only, using your own
Search Console. Built by [Find Untapped Growth](https://finduntappedgrowth.com/).

## Tools

| Tool | What it does |
|---|---|
| `google_login` / `google_login_status` / `google_logout` | Sign in to Google once (read-only Search Console); shared by every Untapped Google plugin |
| `gsc_sites` | Your Search Console properties |
| `index_check` | Inspects each sitemap URL (or a list): indexed / not indexed / **unknown**, plain-language flags, what each problem usually means and what to do, and pages that dropped out or got picked up since the last check |
| `index_history` | Past checks per site (counts per run) or one URL's history, stored locally |

Flags: dropped out of the index · not indexed (with Google's reason) · blocked by the page's own noindex · robots.txt ·
Google couldn't fetch it · Google chose a different canonical · canonical changed · not crawled for 45+ days.
An inspection that fails is reported as UNKNOWN, never as "not indexed".

## Install

- **Claude Code:** `/plugin install untapped-index-watch --marketplace CTF-Max/untapped-plugins`
  (or, from a terminal: `claude plugin marketplace add CTF-Max/untapped-plugins`, then
  `claude plugin install untapped-index-watch@untapped-plugins`).
- **Codex:** `codex plugin marketplace add CTF-Max/untapped-plugins`, then `codex plugin add untapped-index-watch@untapped-plugins`.
- Needs Python 3.10+ on PATH as `python`. Standard library only: nothing to `pip install`.

## Setup (once, about 5 minutes)

1. Google Cloud console → create a project → enable **Google Search Console API**.
2. OAuth consent screen → External → add yourself as a test user.
3. Credentials → Create OAuth client ID → **Desktop app** → Download JSON.
4. Point the plugin at it:
   - **Claude Code:** choose the file in the plugin's settings ("Google OAuth client file") when you enable it
     (later: `/plugin` → untapped-index-watch → configure).
   - **Codex:** set the variable, then restart Codex:
     ```powershell
     setx UNTAPPED_GOOGLE_CLIENT_SECRET "C:\path\to\client_secret.json"
     ```
5. Ask your agent to run `google_login`; approve read-only access in the browser.

| Setting / variable | Default |
|---|---|
| Google OAuth client file / `UNTAPPED_GOOGLE_CLIENT_SECRET` | (required) path to your Desktop-app OAuth client JSON |
| `UNTAPPED_GOOGLE_HOME` | `~/.untapped-plugins/google` — the saved sign-in (shared) |
| `UNTAPPED_INDEX_HOME` | `~/.untapped-plugins/index-watch` — check history |

## What it connects to

Only Google: `accounts.google.com` and `oauth2.googleapis.com` to sign in, `searchconsole.googleapis.com` and
`www.googleapis.com` for Search Console, and your own site's sitemap. No telemetry. Details: [PRIVACY.md](PRIVACY.md).

## Limits

- Google allows 2,000 URL inspections per property per day (600 a minute); the default checks 50 URLs.
- *Request indexing* has no API: it's a manual click in Search Console.
- Inspection reports Google's last known state, which can lag a recent change by days.

## Development

```
python -m unittest discover -s untapped-index-watch/tests   # offline, 13 tests
```
