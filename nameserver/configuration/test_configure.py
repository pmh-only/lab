import copy
import unittest
from unittest.mock import Mock, patch

from configure import configure, grant_user, reconcile, reconcile_dns01


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


class DNS01PermissionsTests(unittest.TestCase):
    def setUp(self):
        self.desired = {"username": "cert-manager-dns01", "displayName": "cert-manager DNS01 (GitOps)", "zones": ["pmh.codes"]}
        self.user = {"displayName": self.desired["displayName"], "memberOfGroups": ["Everyone"]}

    def test_other_users_and_groups_are_preserved(self):
        old_user = {"username": "operator", "canView": True, "canModify": False, "canDelete": False}
        group = {"name": "Administrators", "canView": True, "canModify": True, "canDelete": True}
        new_user = {"username": "cert-manager-dns01", "canView": True, "canModify": False, "canDelete": False}
        client = Mock()
        client.post.side_effect = [
            {"response": {"userPermissions": [old_user], "groupPermissions": [group]}},
            {"status": "ok"},
            {"response": {"userPermissions": [old_user, new_user], "groupPermissions": [group]}},
        ]
        grant_user(client, "admin/permissions/get", "admin/permissions/set", {"section": "Zones"}, "cert-manager-dns01", False, False)
        parameters = client.post.call_args_list[1].args[1]
        self.assertEqual(parameters["userPermissions"], "operator|true|false|false|cert-manager-dns01|true|false|false")
        self.assertEqual(parameters["groupPermissions"], "Administrators|true|true|true")

    def test_matching_permissions_are_not_written(self):
        client = Mock()
        client.post.return_value = {"response": {"userPermissions": [{"username": "svc", "canView": True, "canModify": False, "canDelete": False}]}}
        grant_user(client, "get", "set", {}, "svc", False, False)
        client.post.assert_called_once_with("get", {})

    def test_privileged_service_group_is_rejected(self):
        client = Mock()
        client.post.return_value = {"response": dict(self.user, memberOfGroups=["Administrators"])}
        with self.assertRaises(RuntimeError):
            reconcile_dns01(client, self.desired)
        client.post.assert_called_once_with("admin/users/get", {"user": "cert-manager-dns01"})

    def test_existing_non_primary_zone_is_not_replaced(self):
        client = Mock()
        client.post.side_effect = [{"response": self.user}, {"response": {"zones": [{"name": "pmh.codes", "type": "Forwarder"}]}}]
        with patch("configure.grant_user"), self.assertRaises(RuntimeError):
            reconcile_dns01(client, self.desired)
        self.assertFalse(any(call.args[0] == "zones/create" for call in client.post.call_args_list))

    def test_new_zone_is_created_but_global_modification_is_not_granted(self):
        client = Mock()
        client.post.side_effect = [{"response": self.user}, {"response": {"zones": []}}, {"status": "ok"}]
        with patch("configure.grant_user") as grant:
            reconcile_dns01(client, self.desired)
        client.post.assert_any_call("zones/create", {"zone": "pmh.codes", "type": "Primary"})
        self.assertEqual(grant.call_args_list[0].args[-2:], (False, False))
        self.assertEqual(grant.call_args_list[1].args[-2:], (True, True))


if __name__ == "__main__":
    unittest.main()
