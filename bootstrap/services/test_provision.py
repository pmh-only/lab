import copy
import unittest
from unittest.mock import Mock

from provision import fresh_ech, generated, mysql_identity, provision, repair_unused_bootstrap_driver, valid_field, validate_ech
from unittest.mock import patch


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

    def test_database_urls_are_fresh_and_scope_checked(self):
        url = generated("postgres:keysboard")
        self.assertTrue(valid_field(url, "postgres:keysboard"))
        self.assertFalse(valid_field(url, "postgres:heartbeat"))
        self.assertFalse(valid_field(url.replace("pgsql-service", "unknown-host"), "postgres:keysboard"))
        self.assertNotEqual(url, generated("postgres:keysboard"))

    def test_verified_mysql_drivers_use_their_native_connection_formats(self):
        for kind in ["mysql-url:keysboard", "mysql-dsn:heartbeat"]:
            value = generated(kind)
            self.assertTrue(valid_field(value, kind))
            role, password = mysql_identity(value, kind)
            self.assertGreaterEqual(len(password), 48)
            self.assertIn(role, value)
        self.assertFalse(valid_field(generated("postgres:keysboard"), "mysql-url:keysboard"))

    def test_driver_repair_refuses_nonempty_databases(self):
        vault = Mock()
        fields = {"DATABASE_URL": "mysql-dsn:heartbeat"}
        with patch("provision.sql", side_effect=['{"marker":"lab-service-bootstrap-v1:heartbeat"}', "1"]):
            with self.assertRaises(RuntimeError):
                repair_unused_bootstrap_driver(vault, "heartbeat", "heartbeat/heartbeat-secret", {"DATABASE_URL": generated("postgres:heartbeat")}, fields)
        vault.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
