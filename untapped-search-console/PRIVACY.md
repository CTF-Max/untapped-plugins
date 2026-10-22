# Privacy: Untapped Search Console

- **Find Untapped Growth receives nothing.** The plugin runs on your computer and talks only to Google
  (sign-in and the Search Console API). No telemetry.
- **Access requested:** `webmasters.readonly` (read-only Search Console). It cannot change anything in Search Console.
- **Stored on your computer:** only the Google sign-in (refresh token) in `UNTAPPED_GOOGLE_HOME`. `google_logout`
  revokes it at Google and deletes it.
- Your OAuth client secret and tokens are never included in any tool output or error message.
