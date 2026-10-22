# Untapped Site Audit

A website audit your agent runs in the order that finds the real bottleneck (indexed → seen → buyer phrases →
on-page targeting → visitors → engaged → buyers), plus free on-page checks across a whole sitemap.
Built by [Find Untapped Growth](https://finduntappedgrowth.com/).

## What's inside

- **Skill `site-audit`:** the 8-step audit. It uses Untapped Index Watch (step 1), Untapped Search Console (step 2)
  and Untapped SERP (step 3) when they're installed, and labels anything it can't measure UNKNOWN instead of guessing.
- **`page_facts`:** one page as a search engine reads it: status, redirect chain, title, meta description, meta
  robots + X-Robots-Tag + robots.txt (Googlebot), canonical, H1/H2s, schema types, hreflang, word count, links,
  images without alt, and the problems found.
- **`audit_pages`:** `page_facts` for every sitemap URL (or a list), plus site-wide problems: duplicate titles,
  H1s and descriptions; noindex, redirected or non-200 pages listed in the sitemap.

Both tools are free and read-only; they fetch pages one at a time like a polite crawler.

## Install

- **Claude Code:** `/plugin install untapped-site-audit --marketplace CTF-Max/untapped-plugins`
  (or, from a terminal: `claude plugin marketplace add CTF-Max/untapped-plugins`, then
  `claude plugin install untapped-site-audit@untapped-plugins`).
- **Codex:** `codex plugin marketplace add CTF-Max/untapped-plugins`, then `codex plugin add untapped-site-audit@untapped-plugins`.
- Needs Python 3.10+ on PATH as `python`. Standard library only: nothing to `pip install`.

## Setup

Nothing else to set up. To audit a local preview (localhost, 192.168.x.x), set `UNTAPPED_AUDIT_ALLOW_PRIVATE=1`; private addresses are
refused otherwise.

## What it connects to

Only the website you ask it to audit: its pages, its sitemap and its robots.txt, fetched one at a time. Nothing is
sent anywhere else; no telemetry. Details: [PRIVACY.md](PRIVACY.md).

## Limits

- Reads the HTML as served. A page built by JavaScript after loading can look empty here.
- Title 30–60 and description 70–160 characters are guidelines, not rules: Google rewrites snippets anyway.
- Default 25 pages per audit (up to 200).

## Development

```
python -m unittest discover -s untapped-site-audit/tests   # offline, 7 tests
```
