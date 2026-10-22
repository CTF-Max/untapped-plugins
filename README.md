# Untapped Plugins

Four free plugins that let an AI agent (Claude Code or Codex) answer the questions a business owner asks about
Google: *Are my pages on Google? What do people search to find me? Where do I show up for this phrase? What is
holding my website back?* Built by [Find Untapped Growth](https://finduntappedgrowth.com/), a local visibility
company in Palm Coast, Florida.

| Plugin | What your agent can do with it | Cost |
|---|---|---|
| [Untapped Index Watch](untapped-index-watch/) | Check every page in your sitemap against Google's index, say what each problem usually means, and show which pages dropped out or got picked up since last time | Free (your own Search Console) |
| [Untapped Search Console](untapped-search-console/) | Read your own Search Console: the searches that bring clicks, the ones close to page one, the ones near the top that nobody clicks, and what changed since last month | Free (your own Search Console) |
| [Untapped Site Audit](untapped-site-audit/) | Audit a website in the order that finds the real bottleneck, plus page checks across a whole sitemap: titles, headings, descriptions, canonicals, noindex, schema, thin pages, duplicates | Free |
| [Untapped SERP](untapped-serp/) | See what Google actually shows for a phrase in a place (positions, People Also Ask, the map pack, which sites an AI Overview cites) and monthly search volume | Your own DataForSEO account: about $0.002 per Google lookup, $0.09 per search-volume request (list prices read 2026-10-09); a daily cap you set stops spending |

## Install

**Claude Code** (one plugin at a time):

```
/plugin install untapped-site-audit --marketplace CTF-Max/untapped-plugins
```

or from a terminal: `claude plugin marketplace add CTF-Max/untapped-plugins`, then
`claude plugin install <plugin-name>@untapped-plugins`.

**Codex:**

```
codex plugin marketplace add CTF-Max/untapped-plugins
codex plugin add untapped-site-audit@untapped-plugins
```

Every plugin needs Python 3.10 or newer on PATH as `python`, and nothing else: no packages to install. Each
plugin's README has its setup (the Google plugins need a one-time, read-only Google sign-in).

## What they do with your data

- They run on your computer. Find Untapped Growth receives nothing: no accounts, no telemetry, no analytics.
- The Google plugins sign in read-only and talk only to Google. Untapped SERP talks only to DataForSEO, with your
  own account. Untapped Site Audit reads only the website you ask it to audit.
- Passwords and sign-in tokens are never written to logs or shown in answers. Each plugin's `PRIVACY.md` lists
  exactly what goes where.

## Also available as MCP servers

Each plugin's tools are also published as an MCP Bundle (`.mcpb`) on the
[Releases](https://github.com/CTF-Max/untapped-plugins/releases) page, for apps that install MCP servers directly.

## For developers

```
python -m unittest discover -s untapped-serp/tests            # each plugin: offline tests, no network
python tools/manifests.py --check                             # manifests + marketplaces match tools/manifests.py
python tools/sync_shared.py --check                           # shared modules copied into each plugin are current
python tools/build_mcpb.py                                    # MCP Bundles into dist/, registry entries into registry/
```

One source writes every manifest (`tools/manifests.py`); shared code lives in `shared/` and is copied into each
plugin, because an installed plugin is copied on its own.

## Licence

MIT. See [LICENSE](LICENSE). Questions or problems: [open an issue](https://github.com/CTF-Max/untapped-plugins/issues).
