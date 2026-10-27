import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import argocd_notifications as notifications


ROOT = Path(__file__).resolve().parents[2]


class NotificationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()).decode()

    def test_configuration_matches_app_and_selects_lab_sha_for_multi_source_apps(self):
        data = yaml.safe_load((ROOT / "argocd-access/notifications.yml").read_text())["data"]
        service = yaml.safe_load(data["service.github"])
        self.assertEqual(service["appID"], notifications.APP_ID)
        self.assertEqual(service["installationID"], notifications.INSTALLATION_ID)
        self.assertEqual(service["privateKey"], "$github-privateKey")
        self.assertEqual(yaml.safe_load(data["subscriptions"])[0]["recipients"], ["github:"])
        for name, state in [("pending", "pending"), ("succeeded", "success"), ("failed", "failure")]:
            github = yaml.safe_load(data[f"template.lab-{name}"])["github"]
            self.assertEqual(github["status"]["state"], state)
            self.assertIn("syncResult.revisions $i", github["revisionPath"])
            self.assertIn('eq $source.repoURL "https://github.com/pmh-only/lab.git"', github["revisionPath"])
            if name == "pending":
                self.assertNotIn("deployment", github)
            else:
                self.assertFalse(github["deployment"]["autoMerge"])
                self.assertEqual(github["deployment"]["requiredContexts"], [])
                self.assertEqual(github["deployment"]["environment"], "production/{{.app.metadata.name}}")
        triggers = yaml.safe_load(data["trigger.lab-deployment"])
        self.assertIn("'Healthy'", triggers[1]["when"])
        self.assertIn("'Synced'", triggers[1]["when"])
        for trigger in triggers:
            self.assertEqual(trigger["oncePer"], "app.status.operationState.startedAt")

    def test_vault_destination_uses_dedicated_namespace_scoped_reader(self):
        docs = list(yaml.safe_load_all((ROOT / "argocd-access/notifications-secret.yml").read_text()))
        auth = next(d["spec"] for d in docs if d["kind"] == "VaultAuth")
        secret = next(d["spec"] for d in docs if d["kind"] == "VaultStaticSecret")
        self.assertEqual(auth["kubernetes"]["role"], "argocd-notifications")
        self.assertEqual(auth["kubernetes"]["serviceAccount"], "notifications-vault-auth")
        self.assertEqual(secret["path"], notifications.VAULT_PATH)
        self.assertEqual(secret["destination"]["name"], "argocd-notifications-secret")
        self.assertTrue(secret["destination"]["overwrite"])

    def test_github_validation_checks_identity_permissions_and_repository_scope(self):
        with patch.object(notifications, "github", side_effect=[
            {"id": notifications.APP_ID},
            {"account": {"login": "pmh-only"}, "permissions": {"statuses": "write", "deployments": "write"}},
            {"repositories": [{"full_name": "pmh-only/lab"}]},
        ]) as github:
            notifications.validate_key(self.key)
        self.assertEqual(github.call_args.args[2], {
            "repositories": ["lab"], "permissions": {"statuses": "write", "deployments": "write"}})

    def test_wrong_installation_account_is_rejected_before_token_creation(self):
        with patch.object(notifications, "github", side_effect=[
            {"id": notifications.APP_ID}, {"account": {"login": "another-account"}},
        ]) as github:
            with self.assertRaisesRegex(RuntimeError, "not pmh-only"):
                notifications.validate_key(self.key)
            self.assertEqual(github.call_count, 2)

    def test_provision_is_idempotent_and_does_not_rotate_an_existing_key(self):
        vault = Mock()
        vault.get.return_value = {"github-privateKey": self.key}
        notifications.provision(vault, self.key)
        vault.create.assert_not_called()
        role = json.loads(vault.run.call_args.kwargs["payload"])
        self.assertEqual(role["bound_service_account_namespaces"], ["argocd"])
        self.assertEqual(role["bound_service_account_names"], ["notifications-vault-auth"])
        vault.reset_mock()
        vault.get.return_value = {"github-privateKey": "different-key"}
        with self.assertRaisesRegex(RuntimeError, "refusing"):
            notifications.provision(vault, self.key)
        vault.run.assert_not_called()

    def test_new_key_is_stored_only_in_vault(self):
        vault = Mock()
        vault.get.return_value = None
        notifications.provision(vault, self.key)
        vault.create.assert_called_once_with(notifications.VAULT_PATH, {"github-privateKey": self.key})

    def test_github_import_preserves_discord_webhook(self):
        vault = Mock()
        vault.get.return_value = {"github-privateKey": self.key, "discord-webhook-url": "existing-webhook"}
        notifications.provision(vault, self.key)
        vault.create.assert_not_called()
        self.assertFalse(any(call.args[:2] == ("kv", "put") for call in vault.run.call_args_list))
