import unittest
from unittest.mock import Mock

from setup import authenticate_operator


class OperatorAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.vault = Mock(token=None)
        self.credentials = {"root_token": "bootstrap-root"}

    def test_missing_operator_token_does_not_call_vault(self):
        with self.assertRaises(RuntimeError):
            authenticate_operator(self.vault, self.credentials, None)
        self.vault.request.assert_not_called()

    def test_bootstrap_root_is_rejected_before_any_request(self):
        with self.assertRaises(RuntimeError):
            authenticate_operator(self.vault, self.credentials, "bootstrap-root")
        self.vault.request.assert_not_called()
        self.assertIsNone(self.vault.token)

    def test_other_root_policy_tokens_are_rejected_before_configuration(self):
        self.vault.request.return_value = {"data": {"policies": ["root"]}}
        with self.assertRaises(RuntimeError):
            authenticate_operator(self.vault, self.credentials, "other-root")
        self.vault.request.assert_called_once_with("auth/token/lookup-self")
        self.assertIsNone(self.vault.token)

    def test_non_root_operator_is_accepted(self):
        self.vault.request.return_value = {"data": {"policies": ["default", "lab-operator"]}}
        authenticate_operator(self.vault, self.credentials, "operator-token")
        self.assertEqual(self.vault.token, "operator-token")

    def test_lookup_failure_clears_token(self):
        self.vault.request.side_effect = RuntimeError("lookup denied")
        with self.assertRaises(RuntimeError):
            authenticate_operator(self.vault, self.credentials, "operator-token")
        self.assertIsNone(self.vault.token)


if __name__ == "__main__":
    unittest.main()
