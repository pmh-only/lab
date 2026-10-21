import base64
import unittest
from unittest.mock import Mock

from records import canonical, reconcile


def declaration(records):
    return {"zones": [{"zone": "example.test", "emptyApexWeb": True, "records": records}]}


def record(owner, record_type, data):
    return {"name": owner, "type": record_type, "ttl": 300, "data": data}


class RecordImportTests(unittest.TestCase):
    def test_authority_only_zone_allows_dnssec_but_no_imports(self):
        client = Mock()
        metadata = [{"name": "example.test", "type": t} for t in ["SOA", "NS", "DNSKEY", "NSEC3PARAM", "RRSIG"]]
        metadata.append({"name": "hash.example.test", "type": "NSEC3"})
        client.post.return_value = {"response": {"records": metadata}}
        plan = declaration([])
        plan["zones"][0]["authorityOnly"] = True
        reconcile(client, plan, ["example.test"])
        self.assertTrue(all(call.args[0] == "zones/records/get" for call in client.post.call_args_list))

    def test_unexpected_mail_or_child_delegation_is_not_deleted(self):
        for kind, owner in [("MX", "example.test"), ("TXT", "example.test"), ("NS", "child.example.test")]:
            client = Mock()
            client.post.return_value = {"response": {"records": [{"name": owner, "type": kind}]}}
            plan = declaration([])
            plan["zones"][0]["authorityOnly"] = True
            with self.subTest(kind=kind, owner=owner), self.assertRaises(RuntimeError):
                reconcile(client, plan, ["example.test"])
            self.assertEqual(client.post.call_count, 1)

    def test_existing_apex_website_is_not_deleted(self):
        client = Mock()
        client.post.return_value = {"response": {"records": [{"name": "example.test", "type": "A", "rData": {"ipAddress": "192.0.2.10"}}]}}
        with self.assertRaises(RuntimeError):
            reconcile(client, declaration([]), ["example.test"])
        client.post.assert_called_once_with("zones/records/get", {"zone": "example.test", "domain": "example.test"})

    def test_unreviewed_address_cannot_populate_apex(self):
        client = Mock()
        client.post.return_value = {"response": {"records": []}}
        with self.assertRaises(RuntimeError):
            reconcile(client, declaration([record("example.test", "A", {"ipAddress": "192.0.2.10"})]), ["example.test"])
        self.assertFalse(any(call.args[0] == "zones/records/add" for call in client.post.call_args_list))

    def test_existing_unknown_value_is_not_overwritten(self):
        client = Mock()
        client.post.side_effect = [
            {"response": {"records": []}},
            {"response": {"records": [{"name": "www.example.test", "type": "A", "rData": {"ipAddress": "192.0.2.11"}}]}},
        ]
        with self.assertRaises(RuntimeError):
            reconcile(client, declaration([record("www.example.test", "A", {"ipAddress": "192.0.2.10"})]), ["example.test"])
        self.assertFalse(any(call.args[0] == "zones/records/add" for call in client.post.call_args_list))

    def test_all_rrsets_are_checked_before_any_write(self):
        client = Mock()
        client.post.side_effect = [
            {"response": {"records": []}},
            {"response": {"records": []}},
            {"response": {"records": [{"name": "other.example.test", "type": "A", "rData": {"ipAddress": "192.0.2.11"}}]}},
        ]
        data = declaration([record("www.example.test", "A", {"ipAddress": "192.0.2.10"}), record("other.example.test", "A", {"ipAddress": "192.0.2.10"})])
        with self.assertRaises(RuntimeError):
            reconcile(client, data, ["example.test"])
        self.assertTrue(all(call.args[0] == "zones/records/get" for call in client.post.call_args_list))

    def test_matching_record_is_not_readded(self):
        client = Mock()
        actual = {"name": "www.example.test", "type": "CNAME", "rData": {"cname": "TARGET.EXAMPLE."}}
        client.post.side_effect = [{"response": {"records": []}}, {"response": {"records": [actual]}}, {"response": {"records": [actual]}}]
        reconcile(client, declaration([record("www.example.test", "CNAME", {"cname": "target.example"})]), ["example.test"])
        self.assertTrue(all(call.args[0] == "zones/records/get" for call in client.post.call_args_list))

    def test_txt_chunks_are_added_without_merging_or_printing(self):
        data = {"characterStringsBase64": [base64.b64encode(b"first").decode(), base64.b64encode(b"second").decode()]}
        actual = {"name": "example.test", "type": "TXT", "rData": data}
        client = Mock()
        client.post.side_effect = [{"response": {"records": []}}, {"status": "ok"}, {"response": {"records": [actual]}}]
        reconcile(client, declaration([record("example.test", "TXT", data)]), ["example.test"])
        payload = client.post.call_args_list[1].args[1]
        self.assertEqual(payload["characterStringsBase64"], ",".join(data["characterStringsBase64"]))
        self.assertEqual(payload["overwrite"], "false")

    def test_wrong_address_family_and_authority_records_are_rejected(self):
        with self.assertRaises(RuntimeError):
            canonical("A", {"ipAddress": "2001:db8::1"})
        with self.assertRaises(RuntimeError):
            canonical("NS", {"nameServer": "old.example"})


if __name__ == "__main__":
    unittest.main()
