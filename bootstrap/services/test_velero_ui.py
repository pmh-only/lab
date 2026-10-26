import unittest

import yaml

from provision import ROOT


class VeleroUIPolicyTests(unittest.TestCase):
    def test_native_oauth_admin_has_explicit_ui_permissions(self):
        apps = list(yaml.safe_load_all((ROOT / "apps/velero.yml").read_text()))
        ui = next(a for a in apps if a["metadata"]["name"] == "velero-ui")
        values = next(s["helm"]["valuesObject"] for s in ui["spec"]["sources"] if "helm" in s)
        policies = values["configuration"]["policies"]
        self.assertTrue(policies["enabled"])
        self.assertEqual(policies["value"].strip().splitlines(), ["u,pmh_only@pmh.codes,manage,all"])
        env = {e["name"]: e for e in values["env"]}
        self.assertEqual(env["OAUTH_AUTH_ENABLED"]["value"], "true")
        self.assertEqual(env["BASIC_AUTH_ENABLED"]["value"], "false")
        self.assertNotIn("POLICY_FILE_PATH", env)  # Supplied by the chart.
