import unittest

import yaml

from provision import ROOT


class ApplicationInventoryTests(unittest.TestCase):
    def test_retired_services_and_their_updaters_are_not_deployment_targets(self):
        retired = {"bitwarden", "bro", "workflows", "run", "openebs-zfs"}
        for path in (ROOT / "apps").glob("*.yml"):
            for doc in yaml.safe_load_all(path.read_text()):
                if doc and doc.get("kind") in {"Application", "ImageUpdater"}:
                    self.assertNotIn(doc["metadata"]["name"], retired)
        for name in retired:
            self.assertFalse((ROOT / "apps" / (name + ".yml")).exists())
        self.assertFalse((ROOT / "run/kustomization.yml").exists())

    def test_retired_bitwarden_does_not_disable_other_otp_authentication(self):
        docs = list(yaml.safe_load_all((ROOT / "apps/otp.yml").read_text()))
        app = next(d for d in docs if d and d.get("kind") == "Application")
        source = next(s for s in app["spec"]["sources"] if s.get("chart") == "otp-inbox")
        values = source["helm"]["valuesObject"]
        self.assertFalse(values["bitwarden"]["enabled"])
        self.assertTrue(values["passkey"]["enabled"])
        self.assertIn("connectDiscoveryUrl", values["config"])
        self.assertIn("mailDiscoveryUrl", values["config"])


if __name__ == "__main__":
    unittest.main()
