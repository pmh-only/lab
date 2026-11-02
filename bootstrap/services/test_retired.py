import json
import unittest

from provision import ROOT, PROFILES
from register_image_updaters import ENABLED


class RetiredServiceTests(unittest.TestCase):
    def test_codexlb_and_remote_cannot_be_recreated_by_bootstrap(self):
        oidc = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())
        for name in ("codexlb", "remote"):
            self.assertFalse((ROOT / "apps" / (name + ".yml")).exists())
            self.assertFalse((ROOT / name / "kustomization.yml").exists())
            self.assertNotIn(name, ENABLED)
            self.assertNotIn(name, PROFILES)
            self.assertNotIn(name, oidc)
