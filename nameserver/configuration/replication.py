"""Reconcile authenticated zone replication. Never log TSIG or login secrets."""

import time


def encoded(value):
    if isinstance(value, list):
        return ",".join(value)
    if isinstance(value, bool):
        return str(value).lower()
    return value


def equal(left, right):
    return left == right


def update(client, get_path, set_path, desired, scope=None):
    scope = scope or {}
    actual = client.post(get_path, scope)["response"]
    if any(key not in actual for key in desired):
        raise RuntimeError(f"DNS API {get_path} does not expose required replication settings")
    if not all(equal(actual[key], value) for key, value in desired.items()):
        client.post(set_path, {**scope, **{key: encoded(value) for key, value in desired.items()}})
        actual = client.post(get_path, scope)["response"]
        if not all(equal(actual.get(key), value) for key, value in desired.items()):
            raise RuntimeError("Replication settings verification failed")


def tsig(client, key_name, shared_secret):
    settings = client.post("settings/get")["response"]
    if settings.get("zoneTransferAllowedNetworks"):
        raise RuntimeError("An unauthenticated global zone-transfer bypass exists; refusing to enable replication")
    keys = settings.get("tsigKeys", [])
    expected = {"keyName": key_name, "sharedSecret": shared_secret, "algorithmName": "hmac-sha256"}
    current = next((key for key in keys if key["keyName"] == key_name), None)
    if current:
        if any(current.get(field) != value for field, value in expected.items()):
            raise RuntimeError("An existing TSIG key differs; use an explicit coordinated rotation")
        return
    keys = keys + [expected]
    fields = [str(key[field]) for key in keys for field in ("keyName", "sharedSecret", "algorithmName")]
    if any("|" in field for field in fields):
        raise RuntimeError("Existing TSIG data cannot be safely preserved in the API table")
    client.post("settings/set", {"tsigKeys": "|".join(fields)})
    actual = client.post("settings/get")["response"].get("tsigKeys", [])
    if not any(all(key.get(field) == value for field, value in expected.items()) for key in actual):
        raise RuntimeError("TSIG setup verification failed")


def serial(client, zone):
    records = client.post("zones/records/get", {"zone": zone, "domain": zone})["response"]["records"]
    return next(record["rData"]["serial"] for record in records if record["type"] == "SOA")


def reconcile(primary, secondary, password, shared_secret, desired, zones):
    secondary.token = secondary.post("user/login", {"user": "admin", "pass": password})["token"]
    try:
        tsig(primary, desired["tsigKeyName"], shared_secret)
        tsig(secondary, desired["tsigKeyName"], shared_secret)
        update(secondary, "settings/get", "settings/set", {
            "recursion": "Deny", "notifyAllowedNetworks": desired["primaryNetworks"],
        })
        existing = {zone["name"]: zone for zone in secondary.post("zones/list")["response"]["zones"]}
        for zone in zones:
            update(primary, "zones/options/get", "zones/options/set", {
                "zoneTransfer": "UseSpecifiedNetworkACL",
                "zoneTransferNetworkACL": desired["podNetworks"],
                "zoneTransferTsigKeyNames": [desired["tsigKeyName"]],
                "notify": "SpecifiedNameServers", "notifyNameServers": desired["secondaryAddresses"],
                "queryAccess": "Allow", "update": "Deny",
            }, {"zone": zone})
            current = existing.get(zone)
            if current and (current["type"] != "Secondary" or current.get("disabled")):
                raise RuntimeError(f"Refusing to replace or enable the existing secondary zone {zone}")
            if not current:
                secondary.post("zones/create", {
                    "zone": zone, "type": "Secondary",
                    "primaryNameServerAddresses": ",".join(desired["primaryAddresses"]),
                    "zoneTransferProtocol": "Tcp", "tsigKeyName": desired["tsigKeyName"],
                })
            update(secondary, "zones/options/get", "zones/options/set", {
                "primaryNameServerAddresses": desired["primaryAddresses"],
                "primaryZoneTransferProtocol": "Tcp",
                "primaryZoneTransferTsigKeyName": desired["tsigKeyName"],
                "zoneTransfer": "Deny", "notify": "None",
                "queryAccess": "Allow", "update": "Deny",
            }, {"zone": zone})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if all(serial(primary, zone) == serial(secondary, zone) for zone in zones):
                    print(f"TSIG-authenticated replication verified: {len(zones)} matching primary/secondary SOA serials")
                    return
            except (RuntimeError, StopIteration):
                pass
            time.sleep(1)
        raise RuntimeError("Secondary transfer did not reach matching SOA serials")
    finally:
        try:
            secondary.post("user/logout")
        finally:
            secondary.token = None
