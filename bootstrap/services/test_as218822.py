import base64
import unittest
from unittest.mock import Mock, patch

import yaml

from as218822 import MARKER, PRIVATE_FIELDS, complete_identity, ensure_identity, fresh_private_key, public_key
from provision import ROOT


class AS218822Tests(unittest.TestCase):
    def test_fresh_local_key_is_valid_and_stable(self):
        private = fresh_private_key()
        self.assertEqual(len(base64.b64decode(private)), 32)
        self.assertEqual(len(base64.b64decode(public_key(private))), 32)
        self.assertNotEqual(private, public_key(private))
        identity = complete_identity(None, PRIVATE_FIELDS)
        self.assertEqual(complete_identity(identity, PRIVATE_FIELDS), identity)
        self.assertEqual(identity["MANAGED_BY"], MARKER)
        self.assertNotIn("WG_LUNALIGHT_PRESHARED_KEY", identity)

    def test_existing_unowned_or_old_private_key_is_not_imported(self):
        with self.assertRaises(RuntimeError):
            complete_identity({"WG_CORE_PRIVATE_KEY": fresh_private_key()}, PRIVATE_FIELDS)

    def test_existing_managed_keys_are_not_rewritten(self):
        vault = Mock()
        vault.get.return_value = complete_identity(None, PRIVATE_FIELDS)
        original = dict(vault.get.return_value)
        self.assertEqual(ensure_identity(vault, "as218822/as218822-router-wireguard", PRIVATE_FIELDS), original)
        vault.create.assert_not_called()
        vault.run.assert_not_called()

    def test_namespace_network_probe_has_no_host_routing_or_old_key_access(self):
        job = yaml.safe_load((ROOT / "bootstrap/as218822/network-smoke.yml").read_text())
        pod = job["spec"]["template"]["spec"]
        self.assertFalse(pod["hostUsers"])
        self.assertFalse(pod.get("hostNetwork", False))
        self.assertFalse(pod["automountServiceAccountToken"])
        container = pod["containers"][0]
        self.assertFalse(container["securityContext"]["privileged"])
        self.assertEqual(container["securityContext"]["capabilities"]["add"], ["NET_ADMIN", "NET_RAW"])
        self.assertNotIn("env", container)
        self.assertEqual(pod["volumes"], [{"name": "tun", "hostPath": {"path": "/dev/net/tun", "type": "CharDevice"}}])

    def test_existing_dotenv_validation_rejects_missing_fields_before_native_fallback(self):
        script = (ROOT / "bootstrap/as218822/validate-existing.sh").read_text()
        self.assertIn("export BIRD_VALIDATE=1", script)
        self.assertIn('printenv "$variable" >/dev/null', script)
        self.assertLess(script.index('[ "$missing" = 0 ] || exit 2'), script.index("    render-bird-config"))
        self.assertNotIn("set -x", script)
        self.assertNotIn("cat /run/bird/validation.log", script)
        self.assertIn("^MISSING_VARIABLE [A-Z0-9_]+$", script)

    def test_reader_keeps_the_user_supplied_existing_dotenv_key_path(self):
        source = (ROOT / "bootstrap/services/as218822.py").read_text()
        reader_call = next(line for line in source.splitlines() if 'reader(vault, "as218822"' in line)
        self.assertIn('"as218822/bird-dotenvx"', reader_call)
