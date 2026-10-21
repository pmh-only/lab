import base64
import unittest
from unittest.mock import Mock

from provision import ensure_credentials


class PublicDNSCredentialsTests(unittest.TestCase):
    def test_existing_secrets_are_not_rotated(self):
        vault = Mock()
        vault.get.side_effect = [{"password": "a" * 64}, {"password": "b" * 64}, {"key": base64.b64encode(b"c" * 32).decode()}]
        ensure_credentials(vault)
        vault.create.assert_not_called()

    def test_fresh_secrets_are_separate_and_strong(self):
        vault = Mock()
        vault.get.return_value = None
        ensure_credentials(vault)
        self.assertEqual(vault.create.call_count, 3)
        first, second, key = [call.args[1] for call in vault.create.call_args_list]
        self.assertNotEqual(first["password"], second["password"])
        self.assertGreaterEqual(len(first["password"]), 32)
        self.assertEqual(len(base64.b64decode(key["key"])), 32)

    def test_existing_unexpected_data_is_not_overwritten(self):
        vault = Mock()
        vault.get.return_value = {"unexpected": "value"}
        with self.assertRaises(RuntimeError):
            ensure_credentials(vault)
        vault.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
