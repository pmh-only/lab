import json
from pathlib import Path
import unittest
from unittest.mock import Mock

import yaml

import argocd_discord as discord


ROOT = Path(__file__).resolve().parents[2]
WEBHOOK = "https://discord.com/api/webhooks/123456789/test-webhook-token"


class DiscordTests(unittest.TestCase):
    def test_only_discord_incoming_webhook_urls_are_accepted(self):
        self.assertEqual(discord.validate_url(WEBHOOK), "123456789")
        self.assertEqual(discord.validate_url(WEBHOOK + "?wait=true&thread_id=123"), "123456789")
        for value in ["http://discord.com/api/webhooks/123/token", "https://evil.example/api/webhooks/123/token",
                      "https://discord.com.evil.example/api/webhooks/123/token", WEBHOOK + "#fragment",
                      WEBHOOK + "?unsupported=true", "https://discord.com/channels/123/456"]:
            with self.assertRaises(RuntimeError):
                discord.validate_url(value)

    def test_import_merges_using_cas_and_preserves_github_key(self):
        vault = Mock()
        vault.get.return_value = {"github-privateKey": "existing-key"}
        vault.run.return_value = json.dumps({"data": {"current_version": 3}})
        discord.provision(vault, WEBHOOK)
        self.assertIn("-cas=3", vault.run.call_args.args)
        self.assertEqual(json.loads(vault.run.call_args.kwargs["payload"]), {
            "github-privateKey": "existing-key", "discord-webhook-url": WEBHOOK})
        self.assertNotIn(WEBHOOK, str(vault.run.call_args.args))

    def test_reimport_does_not_rotate_or_rewrite_credentials(self):
        vault = Mock()
        vault.get.return_value = {"github-privateKey": "existing-key", "discord-webhook-url": WEBHOOK}
        discord.provision(vault, WEBHOOK)
        vault.run.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "refusing"):
            discord.provision(vault, WEBHOOK + "-other")
        vault.run.assert_not_called()

    def test_import_requires_existing_github_credentials(self):
        vault = Mock()
        vault.get.return_value = None
        with self.assertRaises(RuntimeError):
            discord.provision(vault, WEBHOOK)
        vault.run.assert_not_called()

    def test_all_sync_phases_are_subscribed_separately_from_github(self):
        data = yaml.safe_load((ROOT / "argocd-access/notifications.yml").read_text())["data"]
        self.assertEqual(yaml.safe_load(data["service.webhook.discord"])["url"], "$discord-webhook-url")
        self.assertEqual(yaml.safe_load(data["subscriptions"]), [
            {"recipients": ["github:"], "triggers": ["lab-deployment"]},
            {"recipients": ["discord"], "triggers": ["discord-sync"]},
        ])
        triggers = yaml.safe_load(data["trigger.discord-sync"])
        self.assertEqual(len(triggers), 3)
        for trigger in triggers:
            self.assertEqual(trigger["oncePer"], "app.status.operationState.startedAt")
            self.assertEqual(trigger["send"], ["discord-sync"])
            self.assertIn(".After(time.Parse(", trigger["when"])
            self.assertNotIn("repoURL", trigger["when"])
        self.assertIn("'Running'", triggers[0]["when"])
        self.assertIn("'Succeeded'", triggers[1]["when"])
        self.assertIn("'Failed', 'Error'", triggers[2]["when"])
        body = yaml.safe_load(data["template.discord-sync"])["webhook"]["discord"]["body"]
        self.assertIn('"allowed_mentions": {"parse": []}', body)
        self.assertIn("| toJson", body)
        self.assertNotIn("operationState.message", body)
        self.assertNotIn(".secrets", body)
