import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest

from records import reconcile
from zonefiles import load_declaration, read_records


CONFIGURATION = Path(__file__).parent
ZONES = CONFIGURATION.parent / "zones"


class ZoneFilesTest(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.com.zone"
            path.write_text(text)
            return read_records(path, "example.com")

    def test_bind_syntax_and_binary_txt_strings(self):
        records = self.parse(r'''
$ORIGIN example.com.
$TTL 5m
@ IN A 192.0.2.1 ; comment
  IN AAAA 2001:db8::1
*.web IN CNAME @
@ IN MX 10 mail
_minecraft._tcp 60 IN SRV 0 5 25565 play.example.net.
txt IN TXT ( "one;two" "quote\034slash\092\000\255" )
''')
        by_type = {record["type"]: record for record in records}
        self.assertEqual(by_type["A"]["name"], "example.com")
        self.assertEqual(by_type["AAAA"]["ttl"], 300)
        self.assertEqual(by_type["CNAME"]["name"], "*.web.example.com")
        self.assertEqual(by_type["CNAME"]["data"]["cname"], "example.com")
        self.assertEqual(by_type["MX"]["data"]["exchange"], "mail.example.com")
        self.assertEqual(by_type["SRV"]["ttl"], 60)
        self.assertEqual(by_type["SRV"]["data"]["target"], "play.example.net")
        self.assertEqual([base64.b64decode(s) for s in by_type["TXT"]["data"]["characterStringsBase64"]],
                         [b"one;two", b'quote"slash\\\x00\xff'])

    def test_reject_out_of_zone_records_instead_of_silently_ignoring(self):
        for text in ["outside.net. IN A 192.0.2.1", "$ORIGIN outside.net.\n@ IN A 192.0.2.1"]:
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, "outside"):
                self.parse("$TTL 300\n" + text)

    def test_reject_unmanaged_types_and_unsafe_directives(self):
        for text in ["@ IN NS ns.example.com.", "@ IN HTTPS 1 . alpn=h2,h3",
                     "$INCLUDE /etc/passwd", "$GENERATE 1-5 host$ A 192.0.2.$",
                     "@ IN A not-an-ip", "@ 0 IN A 192.0.2.1", "@ CH TXT hello"]:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                self.parse("$ORIGIN example.com.\n$TTL 300\n" + text)

    def test_repository_records(self):
        declaration = load_declaration(CONFIGURATION, ZONES)
        records = [record for zone in declaration["zones"] for record in zone["records"]]
        hawal = next(r for r in records if r["name"] == "_minecraft._tcp.hawal.pmh.so")
        self.assertEqual(hawal["data"], {"priority": 0, "weight": 5, "port": 25565, "target": "play.pmh.codes"})
        self.assertEqual(hawal["ttl"], 300)
        self.assertTrue(any(r["name"] == "*.pmh.so" and r["type"] == "A" for r in records))
        self.assertTrue(any(r["type"] == "TXT" for r in records))
        self.assertTrue(any(r["type"] == "AAAA" for r in records))

    def test_matching_zonefiles_do_not_write_or_delete_dynamic_data(self):
        declaration = load_declaration(CONFIGURATION, ZONES)
        snapshot = [
            {"name": r["name"], "type": r["type"], "rData": r["data"]}
            for zone in declaration["zones"] for r in zone["records"]
        ] + [
            {"name": "_acme-challenge.pmh.codes", "type": "TXT", "rData": {"characterStringsBase64": ["YWNtZQ=="]}},
            {"name": "pmh.codes", "type": "RRSIG", "rData": {}},
            {"name": "pmh.codes", "type": "SOA", "rData": {}},
            {"name": "pmh.codes", "type": "DNSKEY", "rData": {}},
        ]
        before = copy.deepcopy(snapshot)

        class Client:
            def post(self, path, parameters):
                if path != "zones/records/get":
                    raise AssertionError("Matching records must not trigger a write: " + path)
                return {"response": {"records": copy.deepcopy([r for r in snapshot if r["name"] == parameters["domain"]])}}

        reconcile(Client(), declaration, [zone["zone"] for zone in declaration["zones"]])
        self.assertEqual(snapshot, before)

    def test_metadata_requires_unique_allowed_zones_and_no_inline_records(self):
        for policies in [[{"zone": "outside.net"}], [{"zone": "example.com"}] * 2,
                         [{"zone": "example.com", "records": []}], []]:
            with self.subTest(policies=policies), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                (path / "zones.json").write_text(json.dumps({"zones": policies}))
                (path / "example.com.zone").write_text("$ORIGIN example.com.\n$TTL 300\n@ IN A 192.0.2.1\n")
                with self.assertRaises(RuntimeError):
                    load_declaration(path, allowed_zones=["example.com"])


if __name__ == "__main__":
    unittest.main()
