#!/usr/bin/env python3
"""
LinkedIn OAuth 2.0 setup helper.

Run once to obtain LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_ID, then
paste both values into your .env file.

Usage:
  python linkedin_auth.py

Two-phase capture:
  Phase 1 - tries to auto-capture the redirect via a local HTTP server.
  Phase 2 - if that fails, asks you to paste the redirect URL from the
             browser address bar (always works, no port requirements).
"""

import http.server
import os
import sys
import threading
import urllib.parse

# Force UTF-8 on Windows to avoid CP1252 UnicodeEncodeError
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import webbrowser

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()
REDIRECT_URI  = "http://localhost:8000/callback"
SCOPES        = "openid profile w_member_social w_organization_social r_organization_social"

AUTH_URL    = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL   = "https://www.linkedin.com/oauth/v2/accessToken"
PROFILE_URL = "https://api.linkedin.com/v2/userinfo"


# -- Local callback server (Phase 1) ------------------------------------------

_auth_code: str | None = None
_code_event = threading.Event()


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        global _auth_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if "code" in params:
            _auth_code = params["code"][0]
            msg = b"<h2 style='font-family:sans-serif;color:green'>Done! Return to the terminal.</h2>"
            status = 200
        elif "error" in params:
            desc = params.get("error_description", ["Unknown LinkedIn error"])[0]
            msg = f"<h2 style='font-family:sans-serif;color:red'>LinkedIn error: {desc}</h2>".encode()
            status = 400
        else:
            msg = b"<h2 style='font-family:sans-serif'>Waiting...</h2>"
            status = 200

        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(msg)

        # signal main thread whether success or failure
        _code_event.set()
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def _try_local_server(timeout: int = 90) -> str | None:
    """Start local HTTP server and wait up to *timeout* seconds for callback."""
    try:
        server = http.server.HTTPServer(("127.0.0.1", 8000), _CallbackHandler)
    except OSError:
        print("  [warn] Port 8000 already in use — skipping auto-capture.\n")
        return None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    got_it = _code_event.wait(timeout=timeout)
    if not got_it:
        server.shutdown()

    return _auth_code if got_it else None


# -- Manual fallback (Phase 2) -------------------------------------------------

def _extract_code_from_url(raw: str) -> str | None:
    raw = raw.strip()
    # Handle case where user pastes just the code value
    if raw.startswith("http"):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
        return params.get("code", [None])[0]
    # Assume they pasted the code directly
    return raw or None


# -- Token + profile helpers ---------------------------------------------------

def _exchange_code(code: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": REDIRECT_URI,
            "client_id":    CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if not resp.ok:
        print(f"\n[ERROR] Token exchange failed ({resp.status_code}):\n{resp.text}\n")
        raise SystemExit(1)
    return resp.json()


def _get_profile(access_token: str) -> dict:
    resp = requests.get(
        PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if not resp.ok:
        print(f"\n[ERROR] Profile fetch failed ({resp.status_code}):\n{resp.text}\n")
        raise SystemExit(1)
    return resp.json()


# -- Main ----------------------------------------------------------------------

def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print(
            "\n[ERROR] LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be in .env\n"
            "  Copy .env.example → .env and fill in those two values first.\n"
        )
        raise SystemExit(1)

    # Build authorization URL
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
    })

    print("\n--- LinkedIn OAuth Setup -------------------------------------------")
    print("\nPRE-REQUISITE (do this once in the LinkedIn Developer Portal):")
    print("  App → Auth tab → OAuth 2.0 settings → Authorized redirect URLs")
    print(f"  Add exactly:  {REDIRECT_URI}\n")

    print("Step 1 – Opening your browser…")
    print(f"  (If nothing opens, copy this URL and paste it in your browser)")
    print(f"\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # Phase 1: try local server
    print("Waiting up to 90 s for the automatic redirect capture…")
    code = _try_local_server(timeout=90)

    # Phase 2: manual fallback
    if not code:
        print("\nAuto-capture didn't work. Do this instead:")
        print("  1. Complete the authorization in your browser.")
        print("  2. You will land on a page that may show an error or blank page —")
        print("     that is fine. Just look at the browser ADDRESS BAR.")
        print("  3. Copy the FULL URL from the address bar (starts with http://localhost…)")
        print("  4. Paste it below (or paste just the 'code=…' value).\n")
        raw = input("Paste the redirect URL (or code value): ").strip()
        code = _extract_code_from_url(raw)
        if not code:
            print("[ERROR] Could not extract an authorization code. Aborting.")
            raise SystemExit(1)

    print("\nAuthorization code received. Exchanging for access token…")

    token_data  = _exchange_code(code)
    access_token = token_data["access_token"]
    expires_in   = token_data.get("expires_in", "unknown")
    refresh_token = token_data.get("refresh_token", "")

    print("Fetching your LinkedIn profile…")
    profile    = _get_profile(access_token)
    # /v2/userinfo (OIDC) returns "sub" as the person ID
    person_id  = profile.get("sub") or profile.get("id", "")
    author_id  = f"urn:li:person:{person_id}"
    first_name = profile.get("given_name") or profile.get("localizedFirstName", "")
    last_name  = profile.get("family_name") or profile.get("localizedLastName", "")

    # -- Print results ---------------------------------------------------------
    print("\n--- Add these lines to your .env file ------------------------------")
    print(f"\nLINKEDIN_ACCESS_TOKEN={access_token}")
    print(f"LINKEDIN_AUTHOR_ID={author_id}")
    if refresh_token:
        print(f"LINKEDIN_REFRESH_TOKEN={refresh_token}   # keep safe; valid ~1 year")

    print(f"\n--- Profile confirmed ----------------------------------------------")
    print(f"  Name      : {first_name} {last_name}")
    print(f"  Person ID : {person_id}")
    print(f"  Token TTL : {int(expires_in):,} seconds (~{int(expires_in)//86400} days)")
    print("--------------------------------------------------------------------\n")


if __name__ == "__main__":
    main()
