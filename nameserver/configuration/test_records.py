import base64
import copy
import json
from pathlib import Path
import unittest

from records import canonical, reconcile_ech


DESIRED = json.loads(Path(__file__).with_name("ech.json").read_text())
OWNER = "example.com"
ADDRESSES = DESIRED["gatewayIPv4"]


class Client:
    def __init__(self, records=()):
        self.records = copy.deepcopy(list(records))
        self.writes = []
        self.change_before_update = False
        self.reads = 0

    def post(self, path, parameters):
        if path == "zones/records/get":
            self.reads += 1
            if self.change_before_update and self.reads == 2:
                self.records[0]["disabled"] = True
            return {"response": {"records": copy.deepcopy(self.records)}}
        self.writes.append((path, parameters))
        params = parameters.get("newSvcParams", parameters["svcParams"]).split("|")
        data = {
            "svcPriority": parameters["svcPriority"],
            "svcTargetName": parameters["svcTargetName"],
            "svcParams": dict(zip(params[::2], params[1::2])),
        }
        # Match Technitium's colon-hex ECH response representation.
        data["svcParams"]["ech"] = bytes.fromhex(data["svcParams"]["ech"]).hex(":")
        record = {"name": parameters["domain"], "type": "HTTPS", "rData": data}
        if path == "zones/records/update":
            self.records = [record]
        elif path == "zones/records/add":
            self.records.append(record)
        else:
            raise AssertionError(path)
        return {"response": {}}


def https_record(**params):
    return {"name": OWNER, "type": "HTTPS", "rData": {
        "svcPriority": 1, "svcTargetName": ".",
        "svcParams": {"alpn": "h2,h3", "ech": DESIRED["echConfigList"], **params},
    }}


def imported(addresses=ADDRESSES, owner=OWNER):
    return {"zones": [{"zone": OWNER, "records": [
        {"name": owner, "type": "A", "ttl": 300, "data": {"ipAddress": address}}
        for address in addresses
    ]}]}


class HintsTest(unittest.TestCase):
    def test_add_and_idempotence(self):
        client = Client()
        reconcile_ech(client, DESIRED, imported(), [OWNER])
        data = json.loads(canonical("HTTPS", client.records[0]["rData"]))
        self.assertEqual(set(data["svcParams"]["ipv4hint"].split(",")), set(ADDRESSES))
        self.assertEqual(client.writes[0][1]["autoIpv4Hint"], "false")
        reconcile_ech(client, DESIRED, imported(), [OWNER])
        self.assertEqual(len(client.writes), 1)

    def test_upgrade_legacy_in_place(self):
        client = Client([https_record()])
        reconcile_ech(client, DESIRED, imported(), [OWNER])
        self.assertEqual([path for path, _ in client.writes], ["zones/records/update"])
        self.assertIn("ipv4hint", client.records[0]["rData"]["svcParams"])
        self.assertEqual(base64.b64decode(DESIRED["echConfigList"]).hex(),
                         client.writes[0][1]["svcParams"].split("ech|")[1])

    def test_hints_use_only_owner_addresses_including_wildcards(self):
        client = Client()
        reconcile_ech(client, DESIRED, imported(ADDRESSES[:1], "*." + OWNER), [OWNER])
        self.assertEqual(client.records[0]["name"], "*." + OWNER)
        self.assertEqual(client.records[0]["rData"]["svcParams"]["ipv4hint"], ADDRESSES[0])

    def test_expand_hints_without_changing_ech(self):
        client = Client([https_record(ipv4hint=",".join(ADDRESSES[:2]))])
        reconcile_ech(client, DESIRED, imported(), [OWNER])
        self.assertEqual([path for path, _ in client.writes], ["zones/records/update"])
        self.assertEqual(set(client.records[0]["rData"]["svcParams"]["ipv4hint"].split(",")), set(ADDRESSES))
        reconcile_ech(client, DESIRED, imported(), [OWNER])
        self.assertEqual(len(client.writes), 1)

    def test_refuse_hint_removal(self):
        client = Client([https_record(ipv4hint=",".join(ADDRESSES))])
        with self.assertRaises(RuntimeError):
            reconcile_ech(client, DESIRED, imported(ADDRESSES[:2]), [OWNER])
        self.assertEqual(client.writes, [])

    def test_reject_unexpected_or_disabled_records(self):
        disabled = https_record()
        disabled["disabled"] = True
        changed_ech = https_record(ech=base64.b64encode(b"\x00\x04\xfe\x0d\x00\x01").decode())
        for record in [https_record(ipv4hint="192.0.2.1"), https_record(port="443"), disabled, changed_ech]:
            with self.subTest(record=record):
                client = Client([record])
                with self.assertRaises(RuntimeError):
                    reconcile_ech(client, DESIRED, imported(), [OWNER])
                self.assertEqual(client.writes, [])

    def test_reject_concurrent_change(self):
        client = Client([https_record()])
        client.change_before_update = True
        with self.assertRaises(RuntimeError):
            reconcile_ech(client, DESIRED, imported(), [OWNER])
        self.assertEqual(client.writes, [])

    def test_reject_mixed_gateway_and_foreign_addresses(self):
        client = Client()
        with self.assertRaises(RuntimeError):
            reconcile_ech(client, DESIRED, imported([ADDRESSES[0], "192.0.2.1"]), [OWNER])
        self.assertEqual(client.writes, [])


if __name__ == "__main__":
    unittest.main()
