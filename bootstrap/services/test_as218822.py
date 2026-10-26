import base64
import subprocess
import unittest
from unittest.mock import Mock, patch

import yaml

from as218822 import MARKER, PRIVATE_FIELDS, complete_identity, ensure_identity, fresh_private_key, public_key
from as218822_console import ensure_tunnel_state
from provision import ROOT


class AS218822Tests(unittest.TestCase):
    def test_console_never_overwrites_existing_tunnel_clients(self):
        with patch("as218822_console.subprocess.check_output", return_value="secret/wireguard-tunnels\n"), patch("as218822_console.subprocess.run") as create:
            ensure_tunnel_state()
        create.assert_not_called()

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

    def test_original_router_layout_has_no_privileged_containers(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "as218822")], text=True)))
        workloads = [d for d in docs if d["kind"] in ["StatefulSet", "Deployment"]]
        for workload in workloads:
            pod = workload["spec"]["template"]["spec"]
            for container in pod.get("initContainers", []) + pod["containers"]:
                self.assertFalse(container.get("securityContext", {}).get("privileged", False))
        core = next(d for d in workloads if d["metadata"]["name"] == "bird")["spec"]["template"]["spec"]
        self.assertEqual(core["runtimeClassName"], "sysbox-runc")
        self.assertFalse(core["hostUsers"])
        self.assertFalse(core.get("hostNetwork", False))
        tailscale = next(c for c in core["containers"] if c["name"] == "tailscale")
        self.assertIn({"name": "TS_DEBUG_FIREWALL_MODE", "value": "nftables"}, tailscale["env"])
        self.assertNotIn("lifecycle", tailscale)
        self.assertIn("as218822_exit_snat", " ".join(core["initContainers"][0]["command"]))
        self.assertIn("net.ipv4.ping_group_range=0 0", " ".join(core["initContainers"][0]["command"]))
        self.assertNotIn("ip6tables-legacy", str(core))
        gre = next(d for d in workloads if d["metadata"]["name"] == "bird-gre-gateway")["spec"]["template"]["spec"]
        self.assertTrue(gre["hostNetwork"])
        self.assertEqual(gre["nodeSelector"], {"kubernetes.io/hostname": "pmhoci"})
        guard = gre["initContainers"][0]
        self.assertEqual(guard["securityContext"]["capabilities"], {"drop": ["ALL"]})
        self.assertNotIn("sysctl -w", " ".join(guard["command"]))
        self.assertFalse(any(v.get("hostPath", {}).get("path", "").startswith("/proc") for v in gre["volumes"]))

    def test_internal_peer_and_portal_public_keys_use_managed_config(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "as218822")], text=True)))
        config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "router-public-config")["data"]
        self.assertIn("PublicKey = ${WG_CORE_PUBLIC_KEY}", config["core.conf"])
        self.assertIn("PublicKey = ${WG_GRE_GATEWAY_PUBLIC_KEY}", config["gre-gateway.conf"])
        console = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "console")
        env = {e["name"]: e for e in console["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["WIREGUARD_PUBLIC_KEY"]["valueFrom"]["configMapKeyRef"]["key"], "WG_PORTAL_PUBLIC_KEY")
        for key in ["WG_CORE_PUBLIC_KEY", "WG_GRE_GATEWAY_PUBLIC_KEY", "WG_PORTAL_PUBLIC_KEY"]:
            self.assertEqual(len(base64.b64decode(config[key], validate=True)), 32)

    def test_validator_rejects_a_wireguard_self_peer_without_printing_private_keys(self):
        source = (ROOT / "bootstrap/as218822/validate-existing.sh").read_text()
        self.assertIn("wg pubkey", source)
        self.assertIn('[ "$own_public" = "$peer_public" ]', source)
        self.assertIn("SELF_PEER", source)
        self.assertNotIn('echo "$own_public"', source)
