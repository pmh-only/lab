import json
import re
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

import yaml

from provision import ROOT
from solver import EXTERNAL, provision


class SolverTests(unittest.TestCase):
    def test_missing_external_credentials_cannot_start_provisioning(self):
        vault, api = Mock(), Mock()
        vault.get.return_value = None
        with self.assertRaises(RuntimeError):
            provision(vault, api)
        vault.create.assert_not_called()
        api.request.assert_not_called()

    def test_supplied_credentials_and_existing_web_configuration_are_not_replaced(self):
        vault, api = Mock(), Mock()
        external = {field: "provided-placeholder" for field in EXTERNAL}
        internal = {"WEB_SESSION_SECRET": "x" * 64, "WEB_ADMIN_SUBJECTS": "existing-owner"}
        vault.get.side_effect = lambda path: {"solver/solver-secret": external, "solver/internal": internal}[path]
        with patch("solver.provision_client") as client:
            provision(vault, api)
        vault.create.assert_not_called()
        api.list.assert_not_called()
        client.assert_called_once()

    def test_manifests_preserve_native_runtime_with_least_required_identity(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "solver")], text=True)))
        route = next(d for d in docs if d["kind"] == "HTTPRoute")
        self.assertEqual(route["spec"]["hostnames"], ["solver.pmh.codes"])
        self.assertFalse(any(d["kind"] == "SecurityPolicy" for d in docs))
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        self.assertNotIn("ServiceAccountName", pod)
        self.assertEqual(pod["serviceAccountName"], "solver")
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertFalse(pod["hostUsers"])
        app = next(c for c in pod["containers"] if c["name"] == "solver")
        env = {e["name"]: e for e in app["env"]}
        self.assertEqual(env["DISCORD_CLIENT_ID"]["value"], "1563036864989106176")
        self.assertNotIn("NODE_TLS_REJECT_UNAUTHORIZED", env)
        self.assertNotIn("command", app)
        self.assertEqual(env["KV_STORE_PATH"]["value"], "/data/kv.sqlite")
        for container in pod["initContainers"] + pod["containers"]:
            self.assertFalse(container.get("securityContext", {}).get("privileged", False))
            if container["name"] != "solver":
                self.assertNotIn("cluster-view", [v["name"] for v in container.get("volumeMounts", [])])
        binding = next(d for d in docs if d["kind"] == "ClusterRoleBinding")
        self.assertEqual(binding["roleRef"]["name"], "view")

    def test_oidc_is_initialized_before_listener_and_existing_native_settings_are_preserved(self):
        code = (ROOT / "solver/initialize.mjs").read_text()
        self.assertIn("if (!loadOidcSettings())", code)
        self.assertIn("if (!session.user.allowed)", code)
        self.assertIn("!session.user.admin", code)
        self.assertIn("763d32ab0571673f0b3c3c4ef0f254422044861904a420cfbb6abfc446125f9f", code)
        self.assertNotIn("from '/app/dist/index.js'", code)
        self.assertNotIn("allowedSubjects: '*'", code)
        declaration = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["solver"]
        self.assertEqual(declaration["readerPaths"], ["solver/solver-secret", "solver/solver-oidc", "solver/internal"])

    def test_native_session_guard_enforces_existing_flags(self):
        code = (ROOT / "solver/initialize.mjs").read_text()
        guard = re.search(r"const after = `(.*?)`;", code, re.S).group(1)
        test = """
let current = null, status = null;
const getWebSession = () => current;
const sendJson = (_response, value) => { status = value; };
""" + guard + """
for (const [session, path, expected] of [
  [null, '/api/admin/oidc', 401],
  [{user:{allowed:false,admin:false}}, '/api/admin/oidc', 403],
  [{user:{allowed:true,admin:false}}, '/api/admin/oidc', 403],
  [{user:{allowed:true,admin:true}}, '/api/admin/oidc', null],
  [{user:{allowed:true,admin:false}}, '/api/sessions', null],
]) {
  current = session; status = null;
  const result = authenticated({url:path}, {});
  if (status !== expected || (expected !== null && result !== null)) throw new Error('Native authorization guard failed');
}
"""
        subprocess.run(["node", "-e", test], check=True, capture_output=True, text=True)
