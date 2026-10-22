# Changelog

## 0.2.0 (2026-10-22)
- First public release, MIT licence.
- Fixed: the `site-audit` skill header did not parse (a colon inside the description), so Claude loaded the skill
  with no description. A check in `tools/manifests.py --check` now fails any suite on such a header.
- Listing details for Anthropic's plugin directory (icon, documentation, support and privacy links) and
  install lines in the README.

## 0.1.1 (2026-10-09)
- Data (ledger, cache, sign-in, history) moves to `~/.untapped-plugins/`: Windows Store builds of Claude and Codex
  redirected `%LOCALAPPDATA%` writes into per-app folders, so each host kept its own spend ledger and cap.

## 0.1.0 (2026-10-09)
- First version: `site-audit` skill (SOP-MEASURE-SITEAUDIT-001), `page_facts`, `audit_pages`.
- First live run: finduntappedgrowth.com, 18/18 pages, 0 errors.
