# Privacy: Untapped Index Watch

- **Find Untapped Growth receives nothing.** The plugin runs on your computer and talks only to Google
  (sign-in and the Search Console API) and to your own site (to read its sitemap). No telemetry.
- **Access requested:** `webmasters.readonly` (read-only Search Console). It cannot change anything in Search Console.
- **Stored on your computer:** the Google sign-in (refresh token) in `UNTAPPED_GOOGLE_HOME`, and the inspection
  history in `UNTAPPED_INDEX_HOME`. `google_logout` revokes the sign-in at Google and deletes it; delete the
  folders to erase everything.
- Your OAuth client secret and tokens are never included in any tool output or error message.
