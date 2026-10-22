import json
import unittest
from unittest.mock import Mock, patch

import yaml

from provision import ROOT
from otp import FIELDS, mail_token


class OTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = yaml.safe_load((ROOT / "apps/otp.yml").read_text())
        cls.chart = next(s for s in cls.app["spec"]["sources"] if s.get("chart") == "otp-inbox")

    def test_native_chart_and_arm64_image_are_pinned_without_retired_bitwarden(self):
        self.assertEqual(self.chart["targetRevision"], "0.4.0")
        self.assertEqual(self.chart["helm"]["releaseName"], "otp-inbox")
        values = self.chart["helm"]["valuesObject"]
        self.assertIn("v0.4.0@sha256:", values["image"]["tag"])
        self.assertFalse(values["bitwarden"]["enabled"])
        self.assertTrue(values["passkey"]["enabled"])
        self.assertEqual(values["secrets"]["existingSecret"], "otp-inbox")
        self.assertTrue(values["config"]["connectDiscoveryUrl"].endswith("/.well-known/rostack"))
        self.assertTrue(values["config"]["mailDiscoveryUrl"].endswith("/.well-known/rostack"))
        header = values["gatewayApi"]["filters"][0]["responseHeaderModifier"]["set"][0]
        self.assertEqual(header, {"name": "X-Accel-Buffering", "value": "no"})

    def test_passkey_claim_is_retained_and_binds_alongside_its_first_consumer(self):
        pvc = yaml.safe_load((ROOT / "otp_configs/pvc.yml").read_text())
        self.assertEqual(pvc["metadata"]["name"], self.chart["helm"]["valuesObject"]["passkey"]["existingClaim"])
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "0")
        self.assertNotIn("volumeName", pvc["spec"])
        for doc in yaml.safe_load_all((ROOT / "otp_configs/secret.yml").read_text()):
            self.assertEqual(doc["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-2")

    def test_native_mail_credentials_are_passed_only_through_stdin_and_captured(self):
        secret = "private-test-token-value"
        with patch("otp.subprocess.run", return_value=Mock(returncode=0, stdout=json.dumps({"verified": True}))) as run:
            self.assertEqual(mail_token({"mode": "verify", "token": secret}), {"verified": True})
        args = run.call_args
        self.assertNotIn(secret, " ".join(args.args[0]))
        self.assertTrue(args.kwargs["capture_output"])
        self.assertEqual(json.loads(args.kwargs["input"])["token"], secret)
        self.assertEqual(FIELDS, {"CONNECT_ROSTACK_TOKEN", "MAIL_ROSTACK_TOKEN", "PASSKEY_SETUP_TOKEN"})

    def test_native_mail_bridge_does_not_create_or_reset_user_accounts(self):
        code = (ROOT / "bootstrap/services/otp-mail-token.mjs").read_text()
        self.assertIn('"getAuthUserId"', code)
        self.assertIn('"createApiKey"', code)
        self.assertIn('"verifyApiKey"', code)
        self.assertIn('"lab-otp-inbox"', code)
        self.assertIn("refusing duplicate issuance", code)
        self.assertNotIn("createSetupAuth", code)
        self.assertNotIn("signUpEmail", code)
        self.assertNotIn("changePassword", code)


if __name__ == "__main__":
    unittest.main()
