# Changelog

## 0.2.0 (2026-10-22)
- First public release, MIT licence.
- Claude Code: the DataForSEO login, password and daily cap are entered in the plugin's settings (secure store) instead of system environment
  variables; Codex keeps the environment variables. An unset setting falls back to the variable.
- Listing details for Anthropic's plugin directory (icon, documentation, support and privacy links) and
  install lines in the README.

## 0.1.1 (2026-10-09)
- Data (ledger, cache, sign-in, history) moves to `~/.untapped-plugins/`: Windows Store builds of Claude and Codex
  redirected `%LOCALAPPDATA%` writes into per-app folders, so each host kept its own spend ledger and cap.

## 0.1.0 (2026-10-09)
- First version: `google_serp`, `google_search_volume`, `serp_estimate`, `serp_spend`.
- SQLite cache + spend ledger with a daily cap; no automatic retry of uncertain paid calls.
- Codex and Claude Code manifests from one source; stdlib-only stdio MCP server.
- Fixed before release: Windows console codec crashed the server on non-Latin result text (found by a live
  sandbox call); stdio is now forced to UTF-8.
