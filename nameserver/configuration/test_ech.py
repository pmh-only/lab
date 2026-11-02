import base64
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from records import canonical, reconcile_ech


class ECHTests(unittest.TestCase):
    def setUp(self):
        self.desired = json.loads(Path(__file__).with_name("ech.json").read_text())
        self.imported = json.loads(Path(__file__).with_name("imported-records.json").read_text())
        self.state = []
        self.client = Mock()

        def post(path, payload):
            if path == "zones/records/get":
                return {"response": {"records": copy.deepcopy([r for r in self.state if r["name"] == payload["domain"]])}}
            self.assertEqual(path, "zones/records/add")
            self.assertEqual(payload["overwrite"], "false")
            parts = payload["svcParams"].split("|")
            self.state.append({"name": payload["domain"], "type": "HTTPS", "rData": {
                "svcPriority": payload["svcPriority"], "svcTargetName": "",
                "svcParams": dict(zip(parts[::2], parts[1::2])),
            }})
            return {"status": "ok"}
        self.client.post.side_effect = post

    def apply(self):
        reconcile_ech(self.client, self.desired, self.imported, [z["zone"] for z in self.imported["zones"]])

    def test_existing_address_owners_only_and_idempotent(self):
        self.apply()
        owners = {r["name"] for r in self.state}
        self.assertTrue({"pmh.codes", "*.pmh.codes", "auth.pmh.codes", "map.mc.pmh.codes", "*.here.pmh.codes", "pmh.so", "not.ai.kr", "as218822.net"} <= owners)
        self.assertTrue(owners.isdisjoint({"play.pmh.codes", "ns1.pmh.codes", "s3.pmh.codes", "*.mc.pmh.codes"}))
        self.client.post.reset_mock()
        self.apply()
        self.assertTrue(all(c.args[0] == "zones/records/get" for c in self.client.post.call_args_list))

    def test_unexpected_https_record_prevents_all_writes(self):
        self.state = [{"name": "pmh.codes", "type": "HTTPS", "rData": {"svcPriority": 0, "svcTargetName": "other.example", "svcParams": {}}}]
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertTrue(all(c.args[0] == "zones/records/get" for c in self.client.post.call_args_list))

    def test_mixed_external_gateway_address_is_rejected(self):
        zone = self.imported["zones"][0]
        zone["records"].append({"name": "pmh.codes", "type": "A", "ttl": 300, "data": {"ipAddress": "192.0.2.1"}})
        with self.assertRaises(RuntimeError):
            self.apply()
        self.client.post.assert_not_called()

    def test_malformed_public_config_and_unreviewed_parameters_are_rejected(self):
        for ech in ["not-base64", base64.b64encode(b"invalid").decode()]:
            with self.subTest(ech=ech), self.assertRaises((ValueError, RuntimeError)):
                canonical("HTTPS", {"svcPriority": 1, "svcTargetName": ".", "svcParams": {"alpn": "h2,h3", "ech": ech}})
