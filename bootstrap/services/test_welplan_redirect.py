import json
import subprocess
import unittest

import yaml

from provision import ROOT


class WelplanRedirectTests(unittest.TestCase):
    def test_only_the_redirect_is_rendered(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "welplan")], text=True)))
        self.assertEqual(len(docs), 1)
        route = docs[0]
        self.assertEqual(route["kind"], "HTTPRoute")
        self.assertEqual(route["metadata"]["namespace"], "welplan")
        self.assertEqual(route["spec"]["hostnames"], ["welplan.pmh.codes"])
        self.assertEqual(route["spec"]["parentRefs"][0]["name"], "main")
        self.assertEqual(route["spec"]["parentRefs"][0]["namespace"], "gateway")
        rules = route["spec"]["rules"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["matches"], [{"path": {"type": "PathPrefix", "value": "/"}}])
        self.assertNotIn("backendRefs", rules[0])
        self.assertEqual(rules[0]["filters"], [{
            "type": "RequestRedirect",
            "requestRedirect": {
                "scheme": "https", "hostname": "welplus.welstory.com",
                "path": {"type": "ReplaceFullPath", "replaceFullPath": "/"},
                "statusCode": 302,
            },
        }])

    def test_retired_workload_and_identity_cannot_be_recreated_by_bootstrap(self):
        self.assertEqual({p.name for p in (ROOT / "welplan").iterdir()}, {"kustomization.yml", "ingress.yml"})
        app = yaml.safe_load((ROOT / "apps/welplan.yml").read_text())
        self.assertEqual(app["kind"], "Application")
        self.assertEqual(app["spec"]["source"]["path"], "welplan")
        declarations = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())
        self.assertNotIn("welplan", declarations)
        for path in ["bootstrap/services/welplan.py", "bootstrap/services/welplan_dns.py"]:
            self.assertFalse((ROOT / path).exists())


if __name__ == "__main__":
    unittest.main()
