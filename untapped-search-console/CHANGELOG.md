# Changelog

## 0.2.0 (2026-10-22)
- First public release, MIT licence.
- Claude Code: the Google OAuth client file is chosen in the plugin's settings (secure store) instead of system environment
  variables; Codex keeps the environment variables. An unset setting falls back to the variable.
- Listing details for Anthropic's plugin directory (icon, documentation, support and privacy links) and
  install lines in the README.

## 0.1.1 (2026-10-09)
- Data (ledger, cache, sign-in, history) moves to `~/.untapped-plugins/`: Windows Store builds of Claude and Codex
  redirected `%LOCALAPPDATA%` writes into per-app folders, so each host kept its own spend ledger and cap.

## 0.1.0 (2026-10-09)
- First version: shared Google sign-in, `gsc_sites`, `gsc_totals`, `gsc_performance`, `gsc_whats_working`, `gsc_compare`.
