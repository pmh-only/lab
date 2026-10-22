#!/usr/bin/env python3
"""Compose fresh native Spring/H2 configuration without using bundled secrets."""

import importlib.util
import json
import re
import secrets
import sys

from provision import ROOT, reader


MODEL = "gpt-3.5-turbo"
DATABASE_URL = "jdbc:h2:file:/var/lib/guessaiword/game;DB_CLOSE_ON_EXIT=FALSE"


def configuration(api_key, password):
    if not re.fullmatch(r"sk-[A-Za-z0-9_-]{20,}", api_key) or not re.fullmatch(r"[A-Za-z0-9_-]{48,}", password):
        raise RuntimeError("Unexpected supplied API key or managed database password format")
    # SPRING_CONFIG_LOCATION replaces the packaged configuration entirely.
    # These values come from the actual image's native Spring/H2 contract,
    # not from its old embedded application.properties or credentials.
    properties = {
        "server.port": "8080",
        "spring.datasource.url": DATABASE_URL,
        "spring.datasource.driverClassName": "org.h2.Driver",
        "spring.datasource.username": "guessaiword",
        "spring.datasource.password": password,
        "spring.jpa.hibernate.ddl-auto": "update",
        "spring.h2.console.enabled": "true",
        "spring.h2.console.settings.web-allow-others": "false",
        "spring.web.resources.static-locations": "classpath:/frontend/dist/",
        "guessaiword.ai.apikey": api_key,
        "guessaiword.ai.model": MODEL,
    }
    return "# lab-guessaiword-configuration-v1\n" + "".join(f"{k}={v}\n" for k, v in properties.items())


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    path = "guessaiword/guessaiword-secret"
    data = vault.get(path)
    allowed = {"OPENAI_API_KEY", "DB_PASSWORD", "application.properties"}
    if not data or not data.get("OPENAI_API_KEY") or set(data) - allowed:
        raise RuntimeError("The supplied native OpenAI key is missing or unknown fields need review")
    desired = dict(data)
    desired.setdefault("DB_PASSWORD", secrets.token_urlsafe(48))
    properties = configuration(desired["OPENAI_API_KEY"], desired["DB_PASSWORD"])
    if data.get("application.properties") not in {None, properties}:
        raise RuntimeError("Existing native configuration differs; refusing uncoordinated key/password changes")
    desired["application.properties"] = properties
    if desired != data:
        metadata = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", path))["data"]
        vault.run("kv", "put", "-cas=" + str(metadata["current_version"]), "-mount=secret", path, "-", payload=json.dumps(desired))
    reader(vault, "guessaiword", path)
    print("guessaiword: supplied API key preserved; fresh native H2 password and exclusive Spring configuration stored in Vault; values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"GuessAIWord provisioning failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
