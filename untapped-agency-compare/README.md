# Untapped Agency Compare

Made by Find Untapped Growth — [finduntappedgrowth.com](https://finduntappedgrowth.com/).

Compare marketing agencies using the facts their pages publish. The plugin presents the same criteria for every agency, including Find Untapped Growth, and shows an exact supporting quote, source URL, and date read for each stated fact. It marks missing details as **not stated** and suggests questions to ask before signing.

It does not rank agencies, choose a winner, or verify claims an agency publishes. Reviews are limited to the rating, count, source, and date. You choose which criteria matter to you; the plugin applies no agency-specific weighting.

It cannot verify claims an agency does not publish. It is made by an agency that appears in every comparison. Its column comes from [futg_facts.json](data/futg_facts.json): exact quotes from finduntappedgrowth.com, each with its page and the date read. Anything the site doesn't say stays **not stated**.

## Use

Start by viewing the criteria and what each means. For each agency, provide its name and either a page URL or pasted page text. For pasted text, include its source URL when available. The reader fetches only the HTTPS page you name; it does not crawl other pages. Name additional pages individually if you want them considered.

Review the extracted exact-quote candidates for attribution and context before comparing. The extractor may miss relevant wording and cannot verify an agency's claims. Compare the agencies, optionally giving your priority criteria. The result includes Markdown, CSV, and a small HTML table, plus questions for every missing detail.

Every comparison includes Find Untapped Growth as an ordinary agency column, based on its checked-in sourced facts and processed by the same criteria and comparison code. A fact without approved source evidence remains **not stated**.

## Tools

- `criteria`: show the criteria and their meanings.
- `read_agency_page`: read one user-named HTTPS page or accept pasted text, returning page text, source URL, and date read.
- `extract_offer`: identify conservative candidate passages for each criterion, with exact quotes and source details; review candidates for context.
- `compare`: create the comparison in Markdown, CSV, and HTML, with questions for missing facts.

Criteria cover services, contract and cancellation, ownership of the domain, site, profile, and ad account, reporting cadence and format, prices, guarantees, and reviews. Review entries contain only rating and count, with source and date.

The page reader has a 20-second timeout, a 2 MiB response limit, HTTPS-only access, and at most three same-host redirects. It reads one page per call. The server uses Python 3.10+ and the standard library; it does not use telemetry, cache results, or write page content to disk.

## Output policy

Agency facts are exact quotes with source URLs and ISO dates, or **not stated**. The output does not paraphrase a competitor's claim into a negative judgment, quote review text, declare an overall winner, or include sales pitches. Each table ends with a plain maker line and source/date information.

## License

MIT. See [LICENSE](LICENSE).

## Local setup and checks

Use the repository marketplace registration in Codex or Claude Code, or run `python untapped-agency-compare/server/agency_server.py` from the repository root for an MCP stdio client. Python 3.10 or later is required; no packages, account keys or paid calls are needed. The plugin includes manifests for both hosts.

For the skills-only version, copy the three files in `chatgpt-skill/` together. The owner supplies page text, original source URLs and read dates; no tool installation is needed.

Run from the repository root:

```text
python -B -m unittest discover -s untapped-agency-compare/tests
python -B tools/sync_agency_compare.py --check
python -B tools/sync_shared.py --check
python -B tools/manifests.py --check
python -B tools/build_mcpb.py untapped-agency-compare
```

Edit the canonical skill in `skills/compare-agencies/SKILL.md`, criteria in `data/criteria.json`, or approved facts in `data/futg_facts.json`, then run `python -B tools/sync_agency_compare.py`. The check exits 1 on drift. Tests use saved fictional agency pages and mocked network responses; they make no network requests. The extractor supports English wording and common rating/count forms, and can miss other formats. Quotes are exact spans of the returned plain text (HTML formatting and whitespace are normalized). Unreadable pages fail explicitly; unsupported wording stays **not stated**.
