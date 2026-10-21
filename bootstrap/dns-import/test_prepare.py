import base64
import unittest

from prepare import prepare


HEADER = """example.test 3600 IN SOA ns.old.test. host.old.test. 1 3600 300 604800 300
example.test. 3600 IN NS ns.old.test.
"""


class PrepareTests(unittest.TestCase):
    def test_flattened_apex_cname_is_excluded_but_mail_remains(self):
        text = HEADER + """example.test. 1 IN CNAME public.example.
example.test. 1 IN MX 1 mail.example.
example.test. 1 IN TXT "v=spf1 -all"
*.example.test. 1 IN A 192.0.2.10
"""
        result, report = prepare(text, "example.test", set())
        records = result["zones"][0]["records"]
        self.assertEqual({r["type"] for r in records}, {"A", "MX", "TXT"})
        self.assertTrue(all(r["ttl"] == 300 for r in records))
        self.assertEqual(report["preservedRecords"], 3)
        self.assertEqual(len(report["excluded"]), 3)
        self.assertTrue(result["zones"][0]["emptyApexWeb"])

    def test_reserved_nameserver_address_is_not_imported(self):
        result, report = prepare(HEADER + "ns1.example.test. 300 IN A 192.0.2.10\n", "example.test", {"ns1.example.test"})
        self.assertEqual(result["zones"][0]["records"], [])
        self.assertEqual(report["excluded"][-1]["reason"], "nameserver-address-managed-separately")

    def test_txt_character_string_boundaries_are_preserved(self):
        result, _ = prepare(HEADER + 'example.test. 300 IN TXT "first" "second"\n', "example.test", set())
        strings = result["zones"][0]["records"][0]["data"]["characterStringsBase64"]
        self.assertEqual([base64.b64decode(s) for s in strings], [b"first", b"second"])

    def test_include_directives_are_rejected_without_file_access(self):
        with self.assertRaises(RuntimeError):
            prepare(HEADER + "$INCLUDE /must-not-be-read\n", "example.test", set())

    def test_foreign_record_is_not_silently_discarded(self):
        with self.assertRaises(RuntimeError):
            prepare(HEADER + "foreign.example. 300 IN A 192.0.2.10\n", "example.test", set())

    def test_apex_address_and_ipv6_are_not_imported(self):
        result, _ = prepare(HEADER + "example.test. 300 IN A 192.0.2.10\nexample.test. 300 IN AAAA 2001:db8::1\n", "example.test", set())
        self.assertEqual(result["zones"][0]["records"], [])


if __name__ == "__main__":
    unittest.main()
