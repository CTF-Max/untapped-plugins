# Privacy: Untapped SERP

- **Find Untapped Growth receives nothing.** The plugin runs on your computer and talks only to DataForSEO
  (`api.dataforseo.com`, or `sandbox.dataforseo.com` in sandbox mode). There is no telemetry and no analytics.
- **What goes to DataForSEO:** the keyword(s), location, language, device and depth you ask about, sent with your
  own API credentials. DataForSEO's own privacy policy and terms apply to that request.
- **What stays on your computer:** a SQLite file (see `UNTAPPED_SERP_HOME`) holding cached results and a ledger
  of calls (time, tool, keyword or keyword count, cost, status). Delete the folder to erase it.
- **Credentials** are read from your environment variables at call time. They are never written to disk, logged,
  or included in any tool output or error message.
