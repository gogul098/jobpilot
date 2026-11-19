"""One-time Gmail connection: run on your own computer, sign in, copy the printed refresh token.

    cd backend
    GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m app.gmail_auth

Uses only the Python standard library. The OAuth client must be type "Desktop app".
"""
from __future__ import annotations

import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/gmail.send"
PORT = int(os.getenv("GMAIL_AUTH_PORT", "8765"))


def main() -> None:
    cid, secret = os.getenv("GOOGLE_CLIENT_ID"), os.getenv("GOOGLE_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first.")
    redirect = f"http://127.0.0.1:{PORT}/"
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state})
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state and "code" in q:
                got["code"] = q["code"][0]
                msg = "Gmail connected. You can close this tab and go back to the terminal."
            else:
                msg = "Sign-in failed or was cancelled. Run the script again."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *a):
            pass

    print("Opening Google sign-in. If no browser opens, visit:\n" + url + "\n")
    webbrowser.open(url)
    with http.server.HTTPServer(("127.0.0.1", PORT), Handler) as srv:
        while "code" not in got:
            srv.handle_request()

    data = urllib.parse.urlencode({"code": got["code"], "client_id": cid, "client_secret": secret,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data) as r:
        tok = json.load(r)
    if "refresh_token" not in tok:
        sys.exit("Google returned no refresh token. Remove JobPilot's access at "
                 "myaccount.google.com/permissions and run this again.")
    print("Add this to Render > jobpilot > Environment as GMAIL_REFRESH_TOKEN:\n")
    print(tok["refresh_token"])


if __name__ == "__main__":
    main()
