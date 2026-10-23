# Privacy

The plugin processes agency page text and agency names supplied for a comparison. The page-reading tool makes a network request only when you provide a page URL. It accepts HTTPS URLs, uses a 20-second timeout, limits responses to 2 MiB, and follows no more than three same-host redirects. It does not crawl linked pages; provide each additional page yourself.

Pasted page text is processed directly. The server does not send telemetry, keep a cache, or write page content or comparison data to disk. The tools use the Python standard library and do not contact an external extraction or comparison service.

Results may include exact passages from agency pages, their source URLs, and the date read. Check that quotes are attributed correctly and have enough context before relying on them. Extraction identifies candidates; it does not verify agency claims.
