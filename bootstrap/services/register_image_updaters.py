#!/usr/bin/env python3
"""Register committed updater declarations for healthy, compatibility-reviewed apps.

The root apps Application stays manual. Database/DNS/storage/authentication and
version-adapted images need a separate compatibility audit before registration.
"""

import argparse
import json
import subprocess

import yaml


REVIEWED = {
    "books", "chatsolution", "codexlb", "connect", "ghost", "go", "heartbeat",
    "here", "indexgen", "keysboard", "meta", "pdf", "speed", "stmt",
}


def declaration(name):
    source = subprocess.check_output(["git", "show", f"HEAD:apps/{name}.yml"], text=True)
    docs = [d for d in yaml.safe_load_all(source) if d and d.get("kind") == "ImageUpdater"]
    if len(docs) != 1:
        raise RuntimeError(f"Expected one committed updater declaration for {name}")
    updater = docs[0]
    if updater["spec"]["writeBackConfig"]["method"] != "git:secret:argocd/git":
        raise RuntimeError("Unexpected credentials/write-back configuration")
    refs = updater["spec"]["applicationRefs"]
    if len(refs) != 1 or refs[0]["namePattern"] != name:
        raise RuntimeError("Refusing wildcard/multi-app bootstrap registration")
    if any(i.get("commonUpdateSettings", {}).get("updateStrategy") != "digest" for i in refs[0]["images"]):
        raise RuntimeError("Only the already-declared mutable-tag digest policy was reviewed")
    return updater


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("services", nargs="+", choices=sorted(REVIEWED))
    parser.add_argument("--apply", action="store_true", help="Register the exact committed resources after checking live health")
    args = parser.parse_args()
    live = json.loads(subprocess.check_output(["kubectl", "get", "applications", "-n", "argocd", "-o", "json"], text=True))
    apps = {a["metadata"]["name"]: a for a in live["items"]}
    if apps["apps"]["spec"].get("syncPolicy", {}).get("automated"):
        raise RuntimeError("Root apps Application must remain manual")
    for name in args.services:
        app = apps[name]
        status = app.get("status", {})
        if status.get("health", {}).get("status") != "Healthy" or status.get("sync", {}).get("status") != "Synced":
            raise RuntimeError(f"{name} is not Synced/Healthy; review it before enabling updates")
        obj = declaration(name)
        if args.apply:
            subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(obj), text=True, check=True)
        print(f"{name}: committed digest updater {'registered' if args.apply else 'reviewed (dry run)'}")


if __name__ == "__main__":
    main()
