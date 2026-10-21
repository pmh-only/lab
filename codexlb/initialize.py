"""Initialize native dashboard authentication once; never reset an existing password."""

import http.cookiejar
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request


BASE = "http://codexlb-service:2455"


def session():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def request(opener, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=30) as response:
        return json.load(response)


def main():
    password = Path("/run/secrets/bootstrap/ADMIN_PASSWORD").read_text().strip()
    if not 48 <= len(password.encode()) <= 72:
        raise RuntimeError("Invalid managed dashboard password length")
    opener = session()
    state = request(opener, "/api/dashboard-auth/session")
    if not state.get("passwordRequired"):
        bootstrap = Path("/run/secrets/bootstrap/BOOTSTRAP_TOKEN").read_text().strip()
        if len(bootstrap) < 48:
            raise RuntimeError("Invalid managed bootstrap token")
        request(opener, "/api/dashboard-auth/password/setup", {"password": password, "bootstrapToken": bootstrap})
        request(opener, "/api/dashboard-auth/logout", {})
        print("Fresh native dashboard password initialized")
    else:
        print("Existing native dashboard password preserved")
    try:
        request(session(), "/api/dashboard-auth/password/login", {"password": "invalid-bootstrap-check"})
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise RuntimeError("Unexpected native negative-login response") from None
    else:
        raise RuntimeError("Native authentication accepted an invalid password")
    try:
        state = request(opener, "/api/dashboard-auth/password/login", {"password": password})
        if not state.get("authenticated") or not state.get("passwordRequired"):
            raise RuntimeError("Native dashboard authentication was not enabled")
        request(opener, "/api/accounts")
        print("Native dashboard owner login and authenticated account API verified; invalid password rejected")
    finally:
        request(opener, "/api/dashboard-auth/logout", {})
        print("Bootstrap test session invalidated; credential values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, urllib.error.URLError) as error:
        print(f"Native dashboard initialization failed: {type(error).__name__}; response suppressed", file=sys.stderr)
        sys.exit(1)
