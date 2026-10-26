#!/usr/bin/env python3
"""Audit committed updater declarations for deployed applications.

The image-updater Application owns these resources; root apps stays manual.
Explicitly enabled infrastructure retains its existing version tag. Helm image
updates go to Git-backed values files; chart versions and Vault manual sync stay.
"""

import argparse
import json
import subprocess

import yaml


REVIEWED = {
    "books", "chatsolution", "codexlb", "connect", "go", "heartbeat",
    "here", "indexgen", "keysboard", "meta", "speed", "stmt",
}
DEPLOYED = {
    "as218822", "authentik", "database", "gateway", "guessaiword", "image-updater", "immich",
    "kopia", "minio", "monitoring", "nameserver", "notaikr", "office", "remote", "seafile",
    "solver", "spotify", "thepool", "trace", "track", "traffic", "visualized",
}
HELM = {
    "cert-manager", "cert-manager-technitium-webhook", "descheduler", "envoy-gateway",
    "otp", "pdf", "reloader", "tailscale", "vault-secrets-operator", "velero", "velero-ui",
}
ENABLED = REVIEWED | DEPLOYED | HELM | {"mail"}
DECLARATIONS = ("reviewed.yml", "deployed.yml", "helm.yml", "mail.yml")


def declaration(name):
    docs = []
    for filename in DECLARATIONS:
        source = subprocess.check_output(["git", "show", "HEAD:image-updater/" + filename], text=True)
        for doc in yaml.safe_load_all(source):
            for d in (doc.get("items", []) if doc and doc.get("kind") == "List" else [doc]):
                if d and d.get("kind") == "ImageUpdater" and d["metadata"]["name"] == name:
                    docs.append(d)
    if len(docs) != 1:
        raise RuntimeError(f"Expected one committed updater declaration for {name}")
    updater = docs[0]
    if updater["spec"]["writeBackConfig"]["method"] != "git:secret:argocd/git":
        raise RuntimeError("Unexpected credentials/write-back configuration")
    refs = updater["spec"]["applicationRefs"]
    if len(refs) != 1 or refs[0]["namePattern"] != name:
        raise RuntimeError("Refusing wildcard/multi-app bootstrap registration")
    if any(i.get("commonUpdateSettings", {}).get("updateStrategy") != "digest" for i in refs[0]["images"]):
        raise RuntimeError("Only existing-tag digest tracking is enabled")
    return updater


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("services", nargs="+", choices=sorted(ENABLED))
    parser.add_argument("--apply", action="store_true", help="Register the exact committed resources after checking live health")
    args = parser.parse_args()
    live = json.loads(subprocess.check_output(["kubectl", "get", "applications", "-n", "argocd", "-o", "json"], text=True))
    apps = {a["metadata"]["name"]: a for a in live["items"]}
    if apps["apps"]["spec"].get("syncPolicy", {}).get("automated"):
        raise RuntimeError("Root apps Application must remain manual")
    prepared = []
    for name in args.services:
        app = apps[name]
        status = app.get("status", {})
        if status.get("health", {}).get("status") != "Healthy" or status.get("sync", {}).get("status") != "Synced":
            raise RuntimeError(f"{name} is not Synced/Healthy; review it before enabling updates")
        obj = declaration(name)
        sources = app["spec"].get("sources", [app["spec"].get("source", {})])
        if not any(s.get("repoURL") == "https://github.com/pmh-only/lab.git" for s in sources):
            raise RuntimeError("A Git-backed manifest or values source is required")
        images = status.get("summary", {}).get("images", [])
        for image in obj["spec"]["applicationRefs"][0]["images"]:
            repository = image["imageName"].rsplit(":", 1)[0]
            operator_proxy = name == "tailscale" and image["alias"] == "proxy" and image.get("commonUpdateSettings", {}).get("forceUpdate")
            if not operator_proxy and not any(actual.startswith(repository + ":") or actual.startswith(repository + "@") for actual in images):
                raise RuntimeError(f"{name}: updater image is not deployed; review the stale declaration")
        prepared.append((name, obj))
    # Preflight the entire selection before creating any resources.
    for name, obj in prepared:
        if args.apply:
            subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(obj), text=True, check=True)
        print(f"{name}: committed digest updater {'registered' if args.apply else 'reviewed (dry run)'}")


if __name__ == "__main__":
    main()
