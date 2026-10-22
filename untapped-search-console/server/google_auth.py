"""Google sign-in for the Search Console plugins: installed-app OAuth (loopback + PKCE), read-only scope.

Standard library only. The user brings their own Google Cloud "Desktop app" OAuth client (the JSON file Google
lets you download) and points UNTAPPED_GOOGLE_CLIENT_SECRET at it. The refresh token is stored in
UNTAPPED_GOOGLE_HOME (default ~/.untapped-plugins/google), shared by every Untapped Google plugin, so
one sign-in serves them all. Nothing is sent anywhere except Google.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from mcp_stdio import ToolError

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_HOSTS = {"searchconsole.googleapis.com", "www.googleapis.com"}
LOGIN_WINDOW_S = 600


def env_value(name, default=""):
    value = os.environ.get(name, "")
    # Claude hosts may pass unresolved optional substitutions (${NAME}, ${user_config.key}) literally.
    return default if not value or (value.startswith("${") and value.endswith("}")) else value


def google_home():
    override = env_value("UNTAPPED_GOOGLE_HOME")
    if override:
        return Path(override)
    # Not %LOCALAPPDATA%: Windows Store (MSIX) apps such as Claude desktop and Codex silently redirect new
    # AppData files into a per-app container, so each host would keep its own ledger, cap and sign-in.
    # The home folder is not virtualized, so every host and terminal shares one copy (found 2026-10-09).
    home = Path.home() / ".untapped-plugins" / "google"
    legacy = Path(os.environ.get("LOCALAPPDATA", "")) / "UntappedPlugins" / "google" / "token.json"
    if os.environ.get("LOCALAPPDATA") and not (home / "token.json").exists() and legacy.is_file():
        home.mkdir(parents=True, exist_ok=True)  # one-time move of a v0.1.0 sign-in
        (home / "token.json").write_bytes(legacy.read_bytes())
    return home


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_http(method, url, data, headers, timeout=60):
    """Returns (status, body bytes). No proxies, no redirects: a bearer token never leaves Google's hosts."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def google_error(status, body):
    try:
        err = json.loads(body).get("error")
        if isinstance(err, dict):
            return "Google API %s: %s" % (status, str(err.get("message") or err.get("status"))[:300])
        if isinstance(err, str):
            return "Google %s: %s" % (status, err[:100])
    except Exception:
        pass
    return "Google API returned HTTP %s." % status


class GoogleAuth:
    def __init__(self, home=None, http=None, browser=None, clock=time.time):
        self.home = Path(home) if home else google_home()
        self.http = http or urllib_http
        self.browser = browser if browser is not None else webbrowser.open
        self.clock = clock
        self.lock = threading.Lock()
        self.login = None  # {"state", "verifier", "redirect_uri", "server", "started", "result"}

    @property
    def token_path(self):
        return self.home / "token.json"

    # --- client + token files ------------------------------------------------------------------------
    def client(self):
        # Claude Code plugin settings arrive as UNTAPPED_GOOGLE_CLIENT_JSON; Codex and terminals use the variable.
        path = env_value("UNTAPPED_GOOGLE_CLIENT_JSON") or env_value("UNTAPPED_GOOGLE_CLIENT_SECRET")
        if not path:
            raise ToolError("Point the plugin at your Google OAuth client JSON (Claude Code: the plugin's settings; "
                            "Codex: the UNTAPPED_GOOGLE_CLIENT_SECRET environment variable). Get the file from "
                            "Google Cloud console → APIs & Services → Credentials → OAuth client ID → Desktop app "
                            "→ Download JSON, and enable the Google Search Console API for that project.")
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            raise ToolError("Could not read the OAuth client JSON at the configured path.") from None
        if "installed" not in data:
            raise ToolError("That OAuth client is not a Desktop app client. Create one of type 'Desktop app'.")
        installed = data["installed"]
        if not installed.get("client_id") or not installed.get("client_secret"):
            raise ToolError("The OAuth client JSON has no client_id/client_secret.")
        return installed["client_id"], installed["client_secret"]

    def token(self):
        try:
            return json.loads(self.token_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception:
            raise ToolError("The saved Google token is unreadable; run google_logout then google_login.") from None

    def save_token(self, token):
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(token), encoding="utf-8")
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.token_path)

    def secrets(self):
        """Every value that must never appear in tool output (for the redactor)."""
        values = []
        try:
            values += list(self.client())
        except ToolError:
            pass
        try:
            token = self.token() or {}
        except ToolError:
            token = {}
        values += [token.get("refresh_token"), token.get("access_token")]
        return [v for v in values if isinstance(v, str) and len(v) >= 6]

    # --- sign-in -------------------------------------------------------------------------------------
    def status(self):
        try:
            self.client()
            configured, why = True, None
        except ToolError as exc:
            configured, why = False, str(exc)
        token = self.token()
        out = {"client_configured": configured, "signed_in": bool(token and token.get("refresh_token")),
               "scope": SCOPE, "token_file": str(self.token_path)}
        if why:
            out["client_problem"] = why
        if self.login:
            out["login"] = self.login_state()
        return out

    def start_login(self):
        client_id, _ = self.client()
        with self.lock:
            self.stop_listener()
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            state = secrets.token_urlsafe(24)
            auth = self

            class Callback(http.server.BaseHTTPRequestHandler):
                def do_GET(self):  # noqa: N802
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    message = auth.finish_login(query)
                    body = ("<html><body style='font-family:sans-serif'><h2>%s</h2>"
                            "<p>You can close this tab and go back to your agent.</p></body></html>" % message).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            server = http.server.HTTPServer(("127.0.0.1", 0), Callback)
            redirect_uri = "http://127.0.0.1:%d/" % server.server_address[1]
            self.login = {"state": state, "verifier": verifier, "redirect_uri": redirect_uri, "server": server,
                          "started": self.clock(), "result": "pending"}
            threading.Thread(target=self.serve_until_done, args=(server,), daemon=True).start()
        url = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            "access_type": "offline", "prompt": "consent"})
        opened = False
        try:
            opened = bool(self.browser(url))
        except Exception:
            pass
        return {"auth_url": url, "browser_opened": opened, "expires_in_s": LOGIN_WINDOW_S,
                "next": "Open auth_url, approve read-only Search Console access, then call google_login_status."}

    def serve_until_done(self, server):
        server.timeout = 1
        while self.login and self.login.get("server") is server and self.login["result"] == "pending":
            if self.clock() - self.login["started"] > LOGIN_WINDOW_S:
                self.login["result"] = "expired"
                break
            server.handle_request()
        server.server_close()

    def stop_listener(self):
        if self.login and self.login["result"] == "pending":
            self.login["result"] = "cancelled"

    def finish_login(self, query):
        login = self.login
        if not login or login["result"] != "pending":
            return "This sign-in link is no longer active."
        if (query.get("state") or [""])[0] != login["state"]:
            return "Sign-in refused: state mismatch."
        if "error" in query:
            login["result"] = "error: " + query["error"][0][:80]
            return "Google sign-in was not completed (" + query["error"][0][:80] + ")."
        code = (query.get("code") or [""])[0]
        try:
            client_id, client_secret = self.client()
            status, body = self.http("POST", TOKEN_URL, urllib.parse.urlencode({
                "code": code, "client_id": client_id, "client_secret": client_secret,
                "redirect_uri": login["redirect_uri"], "grant_type": "authorization_code",
                "code_verifier": login["verifier"]}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded"})
            data = json.loads(body)
            if status != 200 or "refresh_token" not in data:
                login["result"] = "error: " + google_error(status, body)
                return "Google sign-in failed."
            if SCOPE not in data.get("scope", "").split():
                login["result"] = "error: read-only Search Console access was not granted"
                return "Sign-in finished without Search Console access. Please try again and allow it."
            self.save_token({"refresh_token": data["refresh_token"], "access_token": data.get("access_token"),
                             "expires_at": self.clock() + int(data.get("expires_in", 0)), "scope": data["scope"]})
            login["result"] = "signed_in"
            return "Signed in to Search Console (read-only)."
        except Exception:
            login["result"] = "error: token exchange failed"
            return "Google sign-in failed."

    def login_state(self):
        login = self.login or {}
        result = login.get("result", "not started")
        if result == "pending" and self.clock() - login.get("started", 0) > LOGIN_WINDOW_S:
            result = "expired"
        return result

    def logout(self):
        token = self.token()
        revoked = None
        if token and token.get("refresh_token"):
            try:
                status, _ = self.http("POST", REVOKE_URL, urllib.parse.urlencode(
                    {"token": token["refresh_token"]}).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
                revoked = status == 200
            except Exception:
                revoked = False
        try:
            self.token_path.unlink()
        except FileNotFoundError:
            pass
        return {"signed_out": True, "revoked_at_google": revoked}

    # --- API calls -----------------------------------------------------------------------------------
    def access_token(self):
        token = self.token()
        if not token or not token.get("refresh_token"):
            raise ToolError("Not signed in to Google. Call google_login first.")
        if token.get("access_token") and token.get("expires_at", 0) - self.clock() > 60:
            return token["access_token"]
        client_id, client_secret = self.client()
        try:
            status, body = self.http("POST", TOKEN_URL, urllib.parse.urlencode({
                "client_id": client_id, "client_secret": client_secret, "refresh_token": token["refresh_token"],
                "grant_type": "refresh_token"}).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
        except Exception:
            raise ToolError("Could not reach Google to refresh the sign-in.") from None
        if status != 200:
            if b"invalid_grant" in body:
                self.token_path.unlink(missing_ok=True)
                raise ToolError("The Google sign-in expired or was revoked. Call google_login again.")
            raise ToolError(google_error(status, body))
        data = json.loads(body)
        token.update(access_token=data["access_token"], expires_at=self.clock() + int(data.get("expires_in", 3600)))
        self.save_token(token)
        return token["access_token"]

    def api(self, method, url, body=None):
        host = urllib.parse.urlsplit(url).hostname
        if not url.startswith("https://") or host not in API_HOSTS:
            raise ToolError("Refused: only Google's Search Console API hosts are called with your sign-in.")
        headers = {"Authorization": "Bearer " + self.access_token(), "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            status, raw = self.http(method, url, data, headers)
        except Exception:
            raise ToolError("Could not reach the Search Console API (network error).") from None
        if status != 200:
            raise ApiError(status, google_error(status, raw))
        return json.loads(raw) if raw else {}


class ApiError(ToolError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


AUTH_TOOLS = [
    {"name": "google_login",
     "description": "Start Google sign-in (read-only Search Console). Opens the browser; returns the link too. "
                    "Then call google_login_status. One sign-in serves every Untapped Google plugin.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
    {"name": "google_login_status",
     "description": "Free. Whether a Google OAuth client is configured, whether you are signed in, and how a "
                    "pending sign-in went.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
    {"name": "google_logout",
     "description": "Revoke the saved Google sign-in at Google and delete it from this computer.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
]


def handle_auth_tool(auth, name, args):
    if args:
        raise ToolError(name + " takes no arguments.")
    if name == "google_login":
        return auth.start_login()
    if name == "google_login_status":
        return auth.status()
    if name == "google_logout":
        return auth.logout()
    return None


class Redactor:
    """Replaces every current secret (client secret, tokens) with [REDACTED]; re-reads them on each call."""

    def __init__(self, auth):
        self.auth = auth
        self.cached, self.read_at = [], -1.0

    def __call__(self, value):
        now = time.monotonic()
        if now - self.read_at > 1.0:  # a big result has thousands of strings; re-read the files once a second
            self.cached = sorted(set(self.auth.secrets()), key=len, reverse=True)
            self.read_at = now
        for secret in self.cached:
            value = value.replace(secret, "[REDACTED]")
        return value


def resolve_property(auth, site):
    """'sc-domain:x.com' / 'https://x.com/' pass through; a bare domain is matched against the user's properties."""
    site = (site or "").strip()
    if not site or len(site) > 300:
        raise ToolError("site must be a Search Console property or a domain like example.com.")
    if site.startswith("sc-domain:") or site.startswith("http://") or site.startswith("https://"):
        return site
    domain = site.lower().strip("/").removeprefix("www.")
    entries = auth.api("GET", "https://www.googleapis.com/webmasters/v3/sites").get("siteEntry", [])
    owned = [e.get("siteUrl") for e in entries if e.get("permissionLevel") != "siteUnverifiedUser"]
    for candidate in ("sc-domain:" + domain, "https://" + domain + "/", "https://www." + domain + "/",
                      "http://" + domain + "/", "http://www." + domain + "/"):
        if candidate in owned:
            return candidate
    raise ToolError("No verified Search Console property for %s. Your properties: %s"
                    % (domain, ", ".join(owned[:20]) or "none"))


def list_sites(auth):
    entries = auth.api("GET", "https://www.googleapis.com/webmasters/v3/sites").get("siteEntry", [])
    return {"properties": [{"site": e.get("siteUrl"), "permission": e.get("permissionLevel")} for e in entries]}
