import copy
import unittest
from unittest.mock import Mock

from configure import configure, reconcile


DESIRED = {
    "enableDnsOverHttp": True,
    "dnsReverseProxyNetworkACL": ["172.16.0.0/24", "172.16.1.0/24"],
    "dnsOverHttpRealIpHeader": "X-Real-IP",
    "recursion": "AllowOnlyForPrivateNetworks",
}


class ReconcileTests(unittest.TestCase):
    def test_matching_settings_are_not_written(self):
        client = Mock()
        client.post.return_value = {"response": copy.deepcopy(DESIRED)}
        reconcile(client, DESIRED)
        client.post.assert_called_once_with("settings/get")

    def test_only_declared_non_secret_settings_are_updated(self):
        client = Mock()
        current = dict(DESIRED, dnsReverseProxyNetworkACL=[])
        client.post.side_effect = [{"response": current}, {"status": "ok"}, {"response": DESIRED}]
        reconcile(client, DESIRED)
        parameters = client.post.call_args_list[1].args[1]
        self.assertEqual(set(parameters), set(DESIRED))
        self.assertEqual(parameters["dnsReverseProxyNetworkACL"], "172.16.0.0/24,172.16.1.0/24")
        self.assertEqual(parameters["enableDnsOverHttp"], "true")

    def test_legacy_acl_field_is_supported(self):
        client = Mock()
        current = dict(DESIRED)
        current["reverseProxyNetworkACL"] = current.pop("dnsReverseProxyNetworkACL")
        client.post.return_value = {"response": current}
        reconcile(client, DESIRED)
        client.post.assert_called_once_with("settings/get")

    def test_unsupported_acl_is_rejected_without_writing(self):
        client = Mock()
        client.post.return_value = {"response": {}}
        with self.assertRaises(RuntimeError):
            reconcile(client, DESIRED)
        client.post.assert_called_once_with("settings/get")

    def test_verification_failure_is_reported(self):
        client = Mock()
        current = dict(DESIRED, dnsReverseProxyNetworkACL=[])
        client.post.side_effect = [{"response": current}, {"status": "ok"}, {"response": current}]
        with self.assertRaises(RuntimeError):
            reconcile(client, DESIRED)

    def test_session_is_revoked_when_configuration_fails(self):
        client = Mock(token=None)
        client.post.side_effect = [{"token": "temporary-session"}, {"response": {}}, {"status": "ok"}]
        with self.assertRaises(RuntimeError):
            configure(client, DESIRED, "test-password")
        self.assertEqual(client.post.call_args_list[-1].args, ("user/logout",))
        self.assertIsNone(client.token)


if __name__ == "__main__":
    unittest.main()
