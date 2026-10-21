import copy
import unittest
from unittest.mock import Mock

from provision import fresh_ech, provision, validate_ech


class ProvisionTests(unittest.TestCase):
    def test_generated_ech_private_and_public_keys_match(self):
        data = fresh_ech()
        validate_ech(data)
        self.assertNotEqual(data, fresh_ech())

    def test_existing_keys_are_not_rotated(self):
        data = fresh_ech()
        vault = Mock()
        vault.get.return_value = copy.deepcopy(data)
        provision(vault, "gateway")
        vault.create.assert_not_called()
        self.assertEqual(vault.get.return_value, data)

    def test_optional_external_api_key_is_empty_not_fabricated(self):
        vault = Mock()
        vault.get.return_value = None
        provision(vault, "speed")
        fields = vault.create.call_args.args[1]
        self.assertGreaterEqual(len(fields["PASSWORD"]), 48)
        self.assertEqual(fields["IPINFO_APIKEY"], "")

    def test_invalid_existing_credentials_are_not_overwritten(self):
        vault = Mock()
        vault.get.return_value = {"SSH_PASSWORD": "old"}
        with self.assertRaises(RuntimeError):
            provision(vault, "here")
        vault.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
