# Privacy

The plugin reads only the local folders and files supplied to its tools and writes to the chosen output
directory. It sends no resume, project evidence, LinkedIn data, contact details or analytics to a service.
There are no accounts, credentials, cookies, telemetry, payment calls or background requests.

`read_job(url=...)` is the only network operation: it fetches the user-provided HTTPS job page, including
HTTPS redirects. That server sees the ordinary request and IP address. Paste posting text to avoid this.
The plugin does not sign in, submit applications, post to LinkedIn or publish portfolios.

Tool results include excerpts, source paths, job text and generated-file locations. The AI host receives
those results and handles them under its own privacy settings. “Local” describes the plugin's processing,
not a guarantee that the host agent runs on the computer. Select only evidence intended for that host.

Resume and portfolio source maps contain private source paths and quotations. Keep them private and review
the visible documents before sharing. A public portfolio upload is a separate user action; upload only
the intended `index.html`, not the evidence folder or sidecars.

Delete the chosen output directory to remove generated files. There is no separate plugin history store,
usage counter, cache or cloud copy. Original evidence is not modified. Fixed output names are replaced
on rerender; keep versions in separate job folders if needed.
