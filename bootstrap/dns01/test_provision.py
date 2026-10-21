import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from provision import ACCOUNT_PATH, TOKEN_PATH, VaultCLI, provision


DESIRED = {"username": "cert-manager-dns01", "displayName": "cert-manager DNS01 (GitOps)"}
USER = {"username": DESIRED["username"], "displayName": DESIRED["displayName"], "memberOfGroups": ["Everyone"]}
CREDENTIALS = {"username": DESIRED["username"], "password": "private-account-password"}


class ProvisionTests(unittest.TestCase):
    def test_root_operator_is_rejected(self):
        vault = VaultCLI()
        with patch.object(vault, "run", return_value='{"data":{"policies":["root"],"path":"auth/token/root"}}'):
            with self.assertRaises(RuntimeError):
                vault.verify()
        self.assertFalse(vault.verified)

    def test_unverified_operator_cannot_write(self):
        with self.assertRaises(RuntimeError):
            VaultCLI().create(TOKEN_PATH, {"api-token": "must-not-be-written"})

    def test_existing_unmanaged_account_is_preserved(self):
        vault = Mock()
        vault.get.return_value = None
        administrator = Mock()
        administrator.post.return_value = {"response": {"users": [USER]}}
        with self.assertRaises(RuntimeError):
            provision(vault, administrator, Mock(), DESIRED)
        vault.create.assert_not_called()
        administrator.post.assert_called_once_with("admin/users/list")

    def test_existing_managed_token_is_not_rotated(self):
        vault = Mock()
        vault.get.side_effect = [CREDENTIALS, {"api-token": "private-api-token"}]
        administrator = Mock()
        administrator.post.side_effect = [{"response": {"users": [USER]}}, {"response": USER}]
        factory = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            provision(vault, administrator, factory, DESIRED)
        vault.create.assert_not_called()
        factory.assert_not_called()

    def test_password_and_token_are_stored_separately_without_printing_values(self):
        vault = Mock()
        vault.get.return_value = None
        administrator = Mock()
        administrator.post.side_effect = [{"response": {"users": []}}, {"status": "ok"}, {"response": USER}]
        token_client = Mock(token=None)
        token_client.post.return_value = {"username": DESIRED["username"], "token": "private-api-token"}
        output = io.StringIO()
        with patch("provision.secrets.token_urlsafe", return_value="private-account-password"), contextlib.redirect_stdout(output):
            provision(vault, administrator, lambda: token_client, DESIRED)
        self.assertEqual(vault.create.call_args_list[0].args, (ACCOUNT_PATH, CREDENTIALS))
        self.assertEqual(vault.create.call_args_list[1].args, (TOKEN_PATH, {"api-token": "private-api-token"}))
        self.assertIsNone(token_client.token)
        self.assertNotIn("private-api-token", output.getvalue())
        self.assertNotIn("private-account-password", output.getvalue())

    def test_unpersisted_token_is_revoked(self):
        vault = Mock()
        vault.get.side_effect = [CREDENTIALS, None, None]
        vault.create.side_effect = RuntimeError("write failed")
        administrator = Mock()
        administrator.post.side_effect = [{"response": {"users": [USER]}}, {"response": USER}]
        client = Mock(token=None)
        client.post.side_effect = [{"username": DESIRED["username"], "token": "private-api-token"}, {"status": "ok"}]
        with self.assertRaises(RuntimeError):
            provision(vault, administrator, lambda: client, DESIRED)
        self.assertEqual(client.post.call_args_list[-1].args, ("user/logout",))
        self.assertIsNone(client.token)


if __name__ == "__main__":
    unittest.main()
