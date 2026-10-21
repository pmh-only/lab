import json
import re
import subprocess
import unittest

import yaml

from clickhouse import allowed_writer_grant, query_user_statements
from provision import ROOT, PROFILES


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "trace")], text=True)))

    def test_main_and_readonly_native_clients_use_distinct_credentials(self):
        code = (ROOT / "trace/prepare-clickhouse-client.mjs").read_text()
        self.assertIn("3c2b3d2cf7ae90715d8783498c940eff75a7a81bbaac6fa5b5a0b4c6c84c507d", code)
        self.assertIn("username: process.env.CLICKHOUSE_USER", code)
        self.assertIn("source.split(original).length !== 2", code)
        for doc in self.docs:
            if doc["kind"] not in {"Job", "Deployment"}:
                continue
            pod = doc["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            for container in pod.get("initContainers", []) + pod["containers"]:
                self.assertIn("@sha256:", container["image"])
                env = {e["name"]: e for e in container.get("env", [])}
                if "CLICKHOUSE_HOST" in env:
                    self.assertNotIn("@", env["CLICKHOUSE_HOST"]["value"])
                    self.assertEqual(env["CLICKHOUSE_USER"]["value"], "traffic")
                    self.assertEqual(env["CLICKHOUSE_QUERY_USER"]["value"], "traffic_query")
                    self.assertNotEqual(env["CLICKHOUSE_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"], env["CLICKHOUSE_QUERY_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"])

    def test_public_backend_signup_stays_disabled_while_private_job_can_initialize(self):
        backend = next(d for d in self.docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "trace")
        env = {e["name"]: e for e in backend["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["DISABLE_SIGNUP"]["value"], "true")
        self.assertNotIn("ADMIN_PASSWORD", env)
        self.assertEqual(backend["spec"]["strategy"]["type"], "Recreate")
        job = next(d for d in self.docs if d["kind"] == "Job")
        env = {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["DISABLE_SIGNUP"]["value"], "false")
        self.assertGreater(int(job["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]), int(backend["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]))
        script = (ROOT / "trace/initialize-owner.mjs").read_text()
        self.assertIn('login("signUpEmail"', script)
        self.assertIn('login("signInEmail"', script)
        self.assertIn("auth.api.signOut", script)
        self.assertNotIn("setval", script)
        self.assertNotIn("hashPassword", script)

    def test_original_public_tracking_bindings_are_preserved(self):
        desired = json.loads((ROOT / "trace/bootstrap.json").read_text())
        docs = list(yaml.safe_load_all((ROOT / "gateway/nginx.yml").read_text()))
        nginx = next(d["data"]["nginx.conf"] for d in docs if d and "nginx.conf" in d.get("data", {}))
        binding = re.search(r"map \$host \$tracking_site_id \{(.*?)\}", nginx, re.S).group(1)
        self.assertRegex(binding, r'default\s+"1"')
        self.assertRegex(binding, r'welplan\.pmh\.codes\s+"' + desired["sites"][1]["publicId"] + '"')
        self.assertEqual([s["siteId"] for s in desired["sites"]], [1, 2])
        self.assertEqual(desired["sites"][1]["domain"], "welplan.pmh.codes")
        self.assertEqual(PROFILES["trace"][1]["MAPBOX_TOKEN"], "optional-empty")

    def test_query_profile_keeps_upstream_readonly_limits_and_event_only_grant(self):
        statements = query_user_statements("fresh-placeholder-" * 4)
        self.assertIn("readonly = 2 READONLY", statements[1])
        self.assertIn("max_execution_time = 10 READONLY", statements[1])
        self.assertIn("max_result_rows = 1000 READONLY", statements[1])
        self.assertEqual(statements[-1], "GRANT SELECT ON traffic.events TO traffic_query")
        self.assertFalse(any("GRANT ALL" in statement for statement in statements))

    def test_admin_metadata_grants_are_column_scoped_not_global_administration(self):
        grant = {"database": "system", "access_type": "SELECT", "table": "parts", "column": "bytes_on_disk", "grant_option": 0}
        self.assertTrue(allowed_writer_grant(grant))
        for change in [{"table": "users"}, {"column": None}, {"access_type": "ALTER"}, {"grant_option": 1}, {"database": None}]:
            self.assertFalse(allowed_writer_grant({**grant, **change}))
        code = (ROOT / "trace/initialize-owner.mjs").read_text()
        self.assertIn("await initializeCloudTables()", code)
        self.assertNotIn('IS_CLOUD = "true"', code)


if __name__ == "__main__":
    unittest.main()
