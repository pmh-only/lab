"""Initialize native Immich APIs once; keep subsequent account/config edits intact."""

import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


BASE = "http://immich-service:2283/api"
DESIRED = json.loads(Path("/bootstrap/bootstrap.json").read_text())


def request(path, payload=None, token=None, method=None):
    headers = {"Content-Type": "application/json", "Host": "photos.pmh.codes", "X-Forwarded-Proto": "https"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Native Immich {path}: HTTP {error.code}; response and credentials suppressed") from None


def main():
    read = lambda name: (Path("/run/secrets/owner") / name).read_text().strip()
    email, name, password = read("ADMIN_EMAIL").lower(), read("ADMIN_NAME"), read("ADMIN_PASSWORD")
    client_secret = Path("/run/secrets/oidc/client-secret").read_text().strip()
    if "@" not in email or not name or len(password) < 48 or len(client_secret) < 48:
        raise RuntimeError("Invalid managed Immich bootstrap credentials")
    state = request("/server/config")
    created = not state["isInitialized"]
    if created:
        request("/auth/admin-sign-up", {"email": email, "name": name, "password": password})
        print("First native administrator initialized without importing previous accounts or secrets")
    else:
        print("Existing native administrator/account state preserved")
    token = None
    try:
        login = request("/auth/login", {"email": email, "password": password})
        if not login.get("isAdmin") or login.get("userEmail", "").lower() != email:
            raise RuntimeError("Native recovery owner could not be verified; refusing account changes")
        token = login["accessToken"]
        features = request("/server/features")
        if features["configFile"]:
            raise RuntimeError("Unexpected external config file; native UI configuration must stay editable")
        config = request("/system-config", token=token)
        if created:
            if config["oauth"]["enabled"] or config["oauth"]["clientId"]:
                raise RuntimeError("Existing OAuth settings differ; refusing a configuration takeover")
            config["oauth"].update({"enabled": True, "autoLaunch": False, "autoRegister": True,
                "clientId": DESIRED["oauth"]["clientId"], "clientSecret": client_secret,
                "issuerUrl": DESIRED["oauth"]["issuerUrl"], "buttonText": DESIRED["oauth"]["buttonText"],
                "scope": "openid email profile", "signingAlgorithm": "RS256", "allowInsecureRequests": False})
            config["machineLearning"]["urls"] = [DESIRED["machineLearningUrl"]]
            config["server"]["externalDomain"] = DESIRED["externalDomain"]
            request("/system-config", config, token=token, method="PUT")
        # Do not overwrite later UI changes, reset a password, or promote users.
        config = request("/system-config", token=token)
        if not config["oauth"]["enabled"] or config["oauth"]["clientId"] != DESIRED["oauth"]["clientId"] or config["oauth"]["issuerUrl"] != DESIRED["oauth"]["issuerUrl"] or config["oauth"]["clientSecret"] != client_secret:
            raise RuntimeError("Native OAuth/Vault configuration differs; coordinated review required")
        for uri in DESIRED["oauth"]["redirectURIs"]:
            response = request("/oauth/authorize", {"redirectUri": uri})
            url = urllib.parse.urlsplit(response["url"])
            params = urllib.parse.parse_qs(url.query)
            if url.hostname != "auth.pmh.codes" or params.get("client_id") != [DESIRED["oauth"]["clientId"]] or params.get("redirect_uri") != [uri]:
                raise RuntimeError("Native web/mobile OAuth redirect differs from the declared client")
        print("Native administrator login, editable UI settings and strict web/mobile OAuth authorization URLs verified")
    finally:
        if token:
            request("/auth/logout", {}, token=token)
            print("Only the bootstrap test session logged out; credential/token values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, urllib.error.URLError) as error:
        print(f"Immich owner bootstrap failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
