#!/usr/bin/env python3
"""Create the originally configured OIDC clients with fresh Vault-held secrets."""

import argparse
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

from provision import ROOT, reader


class Authentik:
    def __init__(self, token):
        self.token = token

    def request(self, path, data=None, missing_ok=False):
        request = urllib.request.Request("https://auth.pmh.codes/api/v3/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise RuntimeError(f"Authentik {path}: HTTP {error.code}; response suppressed") from None

    def list(self, path):
        result = self.request(path + ("&" if "?" in path else "?") + "page_size=200")
        if result.get("pagination", {}).get("next"):
            raise RuntimeError("Refusing a truncated Authentik lookup")
        return result["results"]


def provision_client(vault, api, slug, desired):
    provider_name = "lab bootstrap: " + slug
    secret_field = desired.get("secretField", "client-secret")
    companion_fields = desired.get("companionSecretFields", [])
    public_client = desired.get("publicClient", False)
    providers = api.list("providers/oauth2/")
    existing = next((p for p in providers if p["client_id"] == desired["clientID"]), None)
    stored = None if public_client else vault.get(desired["vaultPath"])
    if existing and (existing["name"] != provider_name or (stored is None and not public_client)):
        raise RuntimeError("An existing OIDC provider is not managed by this bootstrap; refusing takeover")
    if stored is None and not public_client:
        stored = {secret_field: secrets.token_urlsafe(48)}
        stored.update({field: secrets.token_urlsafe(48) for field in companion_fields})
        vault.create(desired["vaultPath"], stored)
    minimum_lengths = desired.get("companionMinimumLengths", {})
    if not public_client and (set(stored) != {secret_field, *companion_fields} or any(not isinstance(v, str) or len(v) < (48 if field == secret_field else minimum_lengths.get(field, 48)) for field, v in stored.items())):
        raise RuntimeError("Existing OIDC credentials need manual review")
    uris = [desired["redirectURI"], *desired.get("additionalRedirectURIs", [])]
    if len(uris) != len(set(uris)):
        raise RuntimeError("Duplicate declared OAuth redirects")
    redirects = [{"matching_mode": "strict", "url": uri, "redirect_uri_type": "authorization"} for uri in uris]
    extra_mappings = []
    if desired.get("extraScopeMappings"):
        scopes = api.list("propertymappings/provider/scope/")
        for mapping in desired["extraScopeMappings"]:
            matches = [m for m in scopes if m["name"] == mapping["name"]]
            if len(matches) > 1:
                raise RuntimeError("Custom scope mapping is not uniquely identifiable")
            if matches:
                current = matches[0]
                if any(current.get(key) != value for key, value in mapping.items()):
                    raise RuntimeError("Existing custom scope mapping differs; refusing privilege changes")
            else:
                if existing:
                    raise RuntimeError("Existing provider lacks its declared custom scope mapping")
                current = api.request("propertymappings/provider/scope/", mapping)
            extra_mappings.append(current["pk"])
    if existing:
        if not set(extra_mappings) <= set(existing.get("property_mappings", [])):
            raise RuntimeError("Existing provider lacks declared policy mapping")
        if existing["redirect_uris"] != redirects or existing["issuer_mode"] != "per_provider":
            raise RuntimeError("Existing managed provider has unexpected redirect/issuer settings")
        if existing.get("client_type", "confidential") != ("public" if public_client else "confidential"):
            raise RuntimeError("Existing provider has an unexpected client type")
        if public_client and (existing.get("grant_types") != desired["grantTypes"] or existing.get("sub_mode") != desired["subMode"]):
            raise RuntimeError("Existing public provider has unexpected grant/subject settings")
        if not public_client and existing.get("client_secret") and not secrets.compare_digest(existing["client_secret"], stored[secret_field]):
            raise RuntimeError("Provider/Vault client secret mismatch; refusing uncoordinated rotation")
        provider = existing
    else:
        flows = {f["slug"]: f["pk"] for f in api.list("flows/instances/")}
        certificates = api.list("crypto/certificatekeypairs/")
        signing_candidates = [c["pk"] for c in certificates if c["name"] == "authentik Self-signed Certificate"]
        if len(signing_candidates) != 1:
            raise RuntimeError("The fresh default signing certificate is not uniquely identifiable")
        signing = signing_candidates[0]
        scopes = api.list("propertymappings/provider/scope/")
        mappings = [s["pk"] for s in scopes if s.get("managed") in {
            "goauthentik.io/providers/oauth2/scope-openid", "goauthentik.io/providers/oauth2/scope-email",
            "goauthentik.io/providers/oauth2/scope-profile", "goauthentik.io/providers/oauth2/scope-profile-oidc-standard",
        }]
        if len(mappings) < 3:
            raise RuntimeError("Default OpenID/email/profile mappings are unavailable")
        mappings.extend(extra_mappings)
        payload = {
            "name": provider_name, "authorization_flow": flows["default-provider-authorization-implicit-consent"],
            "invalidation_flow": flows["default-provider-invalidation-flow"], "client_type": "public" if public_client else "confidential",
            "client_id": desired["clientID"], "redirect_uris": redirects,
            "issuer_mode": "per_provider", "signing_key": signing, "property_mappings": mappings,
            "grant_types": desired.get("grantTypes", ["authorization_code", "refresh_token"]),
            "sub_mode": desired.get("subMode", "hashed_user_id"),
            "include_claims_in_id_token": True,
        }
        if not public_client:
            payload["client_secret"] = stored[secret_field]
        provider = api.request("providers/oauth2/", payload)
    application = api.request("core/applications/" + urllib.parse.quote(slug, safe="") + "/", missing_ok=True)
    if application:
        if application.get("provider") != provider["pk"]:
            raise RuntimeError("Existing application slug belongs to an unrelated provider")
    else:
        api.request("core/applications/", {"name": slug, "slug": slug, "provider": provider["pk"],
                    "meta_launch_url": desired["launchURL"], "meta_description": "Managed by lab bootstrap", "policy_engine_mode": "all"})
    if not public_client:
        reader(vault, desired["namespace"], desired.get("readerPaths", desired["vaultPath"]))
    with urllib.request.urlopen("https://auth.pmh.codes/application/o/" + slug + "/.well-known/openid-configuration", timeout=20) as response:
        discovery = json.load(response)
    if discovery["issuer"] != "https://auth.pmh.codes/application/o/" + slug + "/":
        raise RuntimeError("OIDC issuer differs from the repository configuration")
    print(f"{slug}: declared client ID, strict redirect and signed OIDC discovery verified; {'public client (no client secret required)' if public_client else 'fresh managed secret'}")


def main():
    declarations = json.loads(Path(__file__).with_name("oidc.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("services", nargs="+", choices=sorted(declarations))
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    bootstrap = vault.get("authentik/bootstrap-worker")
    api = Authentik(bootstrap["AUTHENTIK_BOOTSTRAP_TOKEN"])
    for slug in args.services:
        provision_client(vault, api, slug, declarations[slug])


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, StopIteration) as error:
        print(f"OIDC provisioning failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
