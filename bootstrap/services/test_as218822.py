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
