import unittest
from unittest.mock import Mock, patch

from replication import reconcile, tsig, update


class ReplicationTests(unittest.TestCase):
    def test_existing_global_unauthenticated_transfer_bypass_is_rejected(self):
        client = Mock()
        client.post.return_value = {"response": {"zoneTransferAllowedNetworks": ["0.0.0.0/0"], "tsigKeys": []}}
        with self.assertRaises(RuntimeError):
            tsig(client, "xfr.example", "private-key")
        client.post.assert_called_once_with("settings/get")

    def test_existing_key_is_not_rotated(self):
        client = Mock()
        client.post.return_value = {"response": {"tsigKeys": [{"keyName": "xfr.example", "sharedSecret": "private-key", "algorithmName": "hmac-sha256"}]}}
        tsig(client, "xfr.example", "private-key")
        self.assertEqual(client.post.call_count, 1)

    def test_key_conflict_is_not_overwritten(self):
        client = Mock()
        client.post.return_value = {"response": {"tsigKeys": [{"keyName": "xfr.example", "sharedSecret": "other-key", "algorithmName": "hmac-sha256"}]}}
        with self.assertRaises(RuntimeError):
            tsig(client, "xfr.example", "private-key")
        self.assertEqual(client.post.call_count, 1)

    def test_other_tsig_keys_are_preserved(self):
        old = {"keyName": "old.example", "sharedSecret": "existing-key", "algorithmName": "hmac-sha256"}
        new = {"keyName": "xfr.example", "sharedSecret": "private-key", "algorithmName": "hmac-sha256"}
        client = Mock()
        client.post.side_effect = [{"response": {"tsigKeys": [old]}}, {"status": "ok"}, {"response": {"tsigKeys": [old, new]}}]
        tsig(client, "xfr.example", "private-key")
        self.assertEqual(client.post.call_args_list[1].args[1], {"tsigKeys": "old.example|existing-key|hmac-sha256|xfr.example|private-key|hmac-sha256"})

    def test_matching_options_are_not_written(self):
        client = Mock()
        client.post.return_value = {"response": {"zoneTransferTsigKeyNames": ["xfr.example"]}}
        update(client, "get", "set", {"zoneTransferTsigKeyNames": ["xfr.example"]}, {"zone": "example"})
        client.post.assert_called_once_with("get", {"zone": "example"})

    def test_unsupported_options_fail_closed(self):
        client = Mock()
        client.post.return_value = {"response": {}}
        with self.assertRaises(RuntimeError):
            update(client, "get", "set", {"zoneTransferTsigKeyNames": ["xfr.example"]})
        self.assertEqual(client.post.call_count, 1)

    def test_secondary_configuration_requires_tsig_and_restricts_recursion(self):
        desired = {"tsigKeyName": "xfr.example", "podNetworks": ["172.16.0.0/24"], "primaryNetworks": ["172.16.1.0/24"], "primaryAddresses": ["172.17.0.20"], "secondaryAddresses": ["172.17.0.21"]}
        primary, secondary = Mock(), Mock(token=None)
        secondary.post.side_effect = [{"token": "temporary-session"}, {"response": {"zones": []}}, {"status": "ok"}, {"status": "ok"}]
        with patch("replication.tsig"), patch("replication.update") as settings, patch("replication.serial", return_value=42):
            reconcile(primary, secondary, "private-password", "private-key", desired, ["example"])
        self.assertEqual(settings.call_args_list[0].args[3]["recursion"], "Deny")
        self.assertEqual(settings.call_args_list[1].args[3]["zoneTransferTsigKeyNames"], ["xfr.example"])
        self.assertEqual(secondary.post.call_args_list[2].args[1]["tsigKeyName"], "xfr.example")
        self.assertEqual(secondary.post.call_args_list[-1].args, ("user/logout",))
        self.assertIsNone(secondary.token)

    def test_existing_primary_on_secondary_is_not_replaced(self):
        desired = {"tsigKeyName": "xfr.example", "podNetworks": [], "primaryNetworks": [], "primaryAddresses": [], "secondaryAddresses": []}
        primary, secondary = Mock(), Mock(token=None)
        secondary.post.side_effect = [{"token": "temporary-session"}, {"response": {"zones": [{"name": "example", "type": "Primary"}]}}, {"status": "ok"}]
        with patch("replication.tsig"), patch("replication.update"), self.assertRaises(RuntimeError):
            reconcile(primary, secondary, "private-password", "private-key", desired, ["example"])
        self.assertFalse(any(call.args[0] == "zones/create" for call in secondary.post.call_args_list))
        self.assertIsNone(secondary.token)


if __name__ == "__main__":
    unittest.main()
