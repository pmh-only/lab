import subprocess
import unittest
from unittest.mock import Mock, patch

import yaml

from notaikr import provision
from provision import ROOT


class NotaikrTests(unittest.TestCase):
    def test_reader_preserves_existing_supplied_key(self):
        vault = Mock()
        vault.get.return_value = {"OPENAI_TOKEN": "user-provided-placeholder"}
        with patch("notaikr.reader") as reader:
            provision(vault)
        reader.assert_called_once_with(vault, "notaikr", "notaikr/notaikr-secret")
        vault.create.assert_not_called()

    def test_missing_real_key_is_not_invented(self):
        vault = Mock()
        for data in [None, {}, {"OPENAI_TOKEN": ""}]:
            vault.get.return_value = data
            with self.assertRaises(RuntimeError):
                provision(vault)
        vault.create.assert_not_called()

    def test_private_runtime_is_nonroot_readonly_and_has_no_cluster_token(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "notaikr")], text=True)))
        self.assertFalse(any(d["kind"] == "HTTPRoute" for d in docs))
        pod = next(d for d in docs if d["kind"] == "Deployment")["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["securityContext"]["runAsUser"], 1000)
        app = pod["containers"][0]
        self.assertNotIn("command", app)
        self.assertFalse(app["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(app["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(app["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertEqual(app["env"][0]["valueFrom"]["secretKeyRef"]["key"], "OPENAI_TOKEN")

    def test_native_dns_manages_new_zone_without_external_cloudflare_credentials(self):
        issuer = yaml.safe_load((ROOT / "cert-manager/technitium/production-issuer.yml").read_text())
        solvers = issuer["spec"]["acme"]["solvers"]
        native = next(s for s in solvers if "not.ai.kr" in s.get("selector", {}).get("dnsZones", []))
        self.assertNotIn("cnameStrategy", native["dns01"])
        self.assertEqual(native["dns01"]["webhook"]["solverName"], "technitium")
        self.assertTrue(any("pmh.codes" in s.get("selector", {}).get("dnsZones", []) for s in solvers))
