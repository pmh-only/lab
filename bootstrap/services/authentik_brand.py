#!/usr/bin/env python3
"""Apply the repository's visual-only Authentik brand through its native API.

Defaults to a dry run. Reuses the existing non-root Vault operator login and
bootstrap API identity. Does not touch users, providers, stages, MFA or policies.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

from oidc import Authentik
from provision import ROOT


ASSETS = ROOT / "authentik/branding"
CSS_MARKER = "/* PMH Identity"
VISUAL_FIELDS = {
    "branding_title", "branding_logo", "branding_favicon",
    "branding_default_flow_background", "branding_custom_css", "attributes",
}


class BrandAPI(Authentik):
    def send(self, path, body=None, method="GET", content_type="application/json"):
        request = urllib.request.Request(
            "https://auth.pmh.codes/api/v3/" + path, data=body, method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": content_type},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
                return json.loads(data) if data else None
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Authentik branding API returned HTTP {error.code}; response suppressed") from None

    def patch(self, path, data):
        return self.send(path, json.dumps(data).encode(), "PATCH")

    def upload(self, name, content):
        boundary = "pmh-brand-" + secrets.token_hex(16)
        parts = []
        for field, value in [("usage", "media"), ("name", name)]:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name.rsplit("/", 1)[-1]}"\r\nContent-Type: image/svg+xml\r\n\r\n'.encode())
        parts.extend([content, f"\r\n--{boundary}--\r\n".encode()])
        self.send("admin/file/", b"".join(parts), "POST", "multipart/form-data; boundary=" + boundary)


def asset_name(filename, content):
    return "branding/pmh-" + filename.removesuffix(".svg") + "-" + hashlib.sha256(content).hexdigest()[:16] + ".svg"


def visual_patch(brand, settings, css, assets):
    attributes = copy.deepcopy(brand.get("attributes", {}))
    attributes.setdefault("settings", {}).setdefault("theme", {}).update(settings["theme"])
    return {
        "branding_title": settings["title"],
        "branding_custom_css": css,
        "attributes": attributes,
        **{key: asset_name(filename, assets[filename]) for key, filename in settings["assets"].items()},
    }


def provision_brand(api, settings, css, assets, apply=False):
    if not css.startswith(CSS_MARKER):
        raise RuntimeError("Expected the managed CSS marker")
    brands = [b for b in api.list("core/brands/") if b["domain"] == settings["domain"]]
    if len(brands) != 1:
        raise RuntimeError("Expected exactly one existing target brand")
    brand = brands[0]
    if brand.get("branding_custom_css") and not brand["branding_custom_css"].startswith(CSS_MARKER):
        raise RuntimeError("Unmanaged custom CSS exists; refusing to replace it")
    if brand["branding_title"] not in {"authentik", settings["title"]}:
        raise RuntimeError("Unexpected existing brand title; review it before replacing it")
    flows = api.request("flows/instances/?" + urllib.parse.urlencode({"slug": settings["flowSlug"]}))["results"]
    if len(flows) != 1 or flows[0]["designation"] != "authentication":
        raise RuntimeError("Expected the existing authentication flow")
    flow = flows[0]
    if flow["title"] not in {"Welcome to authentik!", settings["flowTitle"]}:
        raise RuntimeError("Unmanaged flow title exists; refusing to replace it")
    desired = visual_patch(brand, settings, css, assets)
    if set(desired) != VISUAL_FIELDS:
        raise RuntimeError("Only the declared visual brand fields may be changed")
    if not apply:
        print("Authentik brand: visual-only dry run; 3 immutable SVG assets, dark login + portal; no writes")
        return desired
    files = api.request("admin/file/?usage=media&search=branding/")
    for filename, content in assets.items():
        name = asset_name(filename, content)
        matches = [f for f in files if f["name"] == name]
        if len(matches) > 1:
            raise RuntimeError("Ambiguous managed asset name")
        if not matches:
            api.upload(name, content)
    # The PATCH never includes flow bindings, certificates, default/domain,
    # application routing, identity mappings or user preferences.
    path = "core/brands/" + brand["brand_uuid"] + "/"
    if any(brand.get(k) != v for k, v in desired.items()):
        updated = api.patch(path, desired)
        if any(updated.get(k) != v for k, v in desired.items()):
            raise RuntimeError("Visual brand update verification failed")
        if any(updated.get(k) != v for k, v in brand.items() if k not in VISUAL_FIELDS):
            raise RuntimeError("Nonvisual brand fields changed; stop and review")
    if flow["title"] != settings["flowTitle"]:
        updated = api.patch("flows/instances/" + flow["pk"] + "/", {"title": settings["flowTitle"]})
        if updated["title"] != settings["flowTitle"] or any(updated.get(k) != v for k, v in flow.items() if k != "title"):
            raise RuntimeError("Flow title-only verification failed")
    print("Authentik brand: dark login + portal applied; existing flows, users, MFA and provider permissions preserved")
    return desired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    api = BrandAPI(vault.get("authentik/bootstrap-worker")["AUTHENTIK_BOOTSTRAP_TOKEN"])
    settings = json.loads((ASSETS / "brand.json").read_text())
    assets = {f: (ASSETS / f).read_bytes() for f in settings["assets"].values()}
    provision_brand(api, settings, (ASSETS / "theme.css").read_text(), assets, args.apply)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"Authentik branding failed: {type(error).__name__}; details suppressed", file=sys.stderr)
        sys.exit(1)
