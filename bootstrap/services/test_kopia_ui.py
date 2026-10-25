import base64
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import yaml

from kopia_ui import ADMIN_EXPRESSION, admin_policy, read_policy, ui_secrets
from provision import ROOT


class KopiaUITests(unittest.TestCase):
    def test_console_has_no_write_permissions_to_remote_backups(self):
        policy = read_policy()
        self.assertEqual({a for s in policy["Statement"] for a in s["Action"]}, {"s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"})
        self.assertTrue(all(r.startswith("arn:aws:s3:::kopia") for s in policy["Statement"] for r in s["Resource"]))

    def test_only_authenticated_active_internal_admins_are_allowed(self):
        for authenticated in [False, True]:
            for active in [False, True]:
                for admin in [False, True]:
                    for kind in ["internal", "external", "service_account"]:
                        user = SimpleNamespace(is_authenticated=authenticated, is_active=active, is_superuser=admin, type=kind)
                        request = SimpleNamespace(user=user)
                        result = eval(ADMIN_EXPRESSION.removeprefix("return "), {"request": request})
                        self.assertEqual(result, authenticated and active and admin and kind == "internal")

    def test_unmanaged_access_policy_is_not_overwritten(self):
        api = Mock()
        api.list.return_value = [{"pk": "policy", "name": "lab bootstrap: kopia console administrators only", "expression": "return True"}]
        with self.assertRaisesRegex(RuntimeError, "policy differs"):
            admin_policy(api)
        api.request.assert_not_called()

    def test_older_binding_without_dry_run_is_idempotent_but_explicit_dry_run_is_rejected(self):
        policy = {"pk": "policy", "name": "lab bootstrap: kopia console administrators only", "expression": ADMIN_EXPRESSION, "execution_logging": False}
        binding = {"policy": "policy", "target": "app", "order": 0, "enabled": True, "negate": False, "failure_result": False, "timeout": 30}
        users = [{"pk": 1, "is_active": True, "is_superuser": True, "type": "internal"},
                 {"pk": 2, "is_active": True, "is_superuser": False, "type": "internal"}]
        api = Mock()
        api.list.side_effect = [[policy], [binding], users]
        api.request.side_effect = [{"pk": "app", "policy_engine_mode": "all"}, {"passing": True}, {"passing": False}]
        admin_policy(api)
        self.assertTrue(all(not c.args[0].endswith("bindings/") for c in api.request.call_args_list))
        api = Mock()
        api.list.side_effect = [[policy], [{**binding, "dry_run": True}]]
        api.request.return_value = {"pk": "app", "policy_engine_mode": "all"}
        with self.assertRaisesRegex(RuntimeError, "binding differs"):
            admin_policy(api)

    def test_dedicated_reader_does_not_overwrite_worker_permissions_or_rotate_passwords(self):
        password, repository = "s" * 64, "r" * 64
        data = {"server-password": password, "repository-password": repository,
                "proxy-authorization": "Basic " + base64.b64encode(("lab-console:" + password).encode()).decode()}
        vault = Mock()
        vault.get.side_effect = [{"REPOSITORY_PASSWORD": repository}, data]
        ui_secrets(vault)
        vault.create.assert_not_called()
        self.assertEqual(vault.run.call_args_list[0].args[:3], ("policy", "write", "lab-kopia-ui"))
        self.assertEqual(vault.run.call_args_list[1].args[:2], ("write", "auth/kubernetes/role/kopia-ui"))
        policy = vault.run.call_args_list[0].kwargs["payload"]
        self.assertNotIn('"secret/data/kopia/s3"', policy)

    def test_ui_is_read_only_loopback_password_protected_and_has_no_host_mounts(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "kopia")], text=True)))
        self.assertFalse(any(d["kind"] == "PersistentVolumeClaim" for d in docs))
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertTrue(all("hostPath" not in v and "persistentVolumeClaim" not in v for v in pod["volumes"]))
        native = next(c for c in pod["containers"] if c["name"] == "kopia")
        command = native["command"][-1]
        self.assertIn("--readonly", command)
        self.assertIn("--address=127.0.0.1:51515", command)
        self.assertNotIn("--without-password", command)
        self.assertNotIn("allow-extremely-dangerous", command)
        self.assertNotIn("disable-csrf", command)
        self.assertNotIn("repository create", command)
        self.assertTrue(any(e["name"] == "KOPIA_SERVER_PASSWORD" and "valueFrom" in e for e in native["env"]))
        for c in pod["containers"]:
            self.assertIn("@sha256:", c["image"])
            self.assertFalse(c["securityContext"]["allowPrivilegeEscalation"])
            self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
        service = next(d for d in docs if d["kind"] == "Service")
        self.assertEqual(service["spec"]["ports"][0]["targetPort"], "http")
        policy = next(d for d in docs if d["kind"] == "NetworkPolicy")["spec"]
        self.assertEqual(policy["ingress"][0]["from"][0]["namespaceSelector"]["matchLabels"], {"kubernetes.io/metadata.name": "envoy-gateway-system"})
        self.assertEqual(policy["ingress"][0]["ports"], [{"protocol": "TCP", "port": 8080}])
        oidc = next(d for d in docs if d["kind"] == "SecurityPolicy")["spec"]["oidc"]
        self.assertEqual(oidc["redirectURL"], "https://backup.pmh.codes/oauth2/callback")
        self.assertFalse(oidc["passThroughAuthHeader"])
        self.assertFalse(oidc["forwardAccessToken"])
        self.assertTrue(oidc["provider"]["tokenEndpoint"].startswith("https://"))
        self.assertFalse(any(d["kind"] == "VaultAuth" and d["metadata"]["name"] == "vault" for d in docs))
        gateway = next(d["data"]["nginx.conf"] for d in yaml.safe_load_all((ROOT / "gateway/nginx.yml").read_text()) if d and "nginx.conf" in d.get("data", {}))
        self.assertRegex(gateway, r'backup\.pmh\.codes\s+""')
