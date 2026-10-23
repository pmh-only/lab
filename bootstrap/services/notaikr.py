#!/usr/bin/env python3
"""Grant only the native notaikr namespace reader access to its supplied API key."""

import importlib.util

from provision import ROOT, reader


def provision(vault):
    data = vault.get("notaikr/notaikr-secret")
    if not data or not isinstance(data.get("OPENAI_TOKEN"), str) or not data["OPENAI_TOKEN"].strip():
        raise RuntimeError("A genuine supplied OPENAI_TOKEN is required")
    reader(vault, "notaikr", "notaikr/notaikr-secret")
    print("notaikr: supplied OpenAI token preserved; namespace reader restricted to its existing Vault path")


def main():
    spec = importlib.util.spec_from_file_location("dns_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    provision(vault)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        raise SystemExit(f"notaikr provisioning failed: {type(error).__name__}; credential-bearing details suppressed")
