import json
from unittest.mock import Mock, patch
import unittest

import yaml

from provision import ROOT
from thepool import CORS, complete_credentials, cors_identity, initialize_database


class ThepoolTests(unittest.TestCase):
    def test_preserves_external_secret_and_generates_only_real_internal_credentials(self):
        original = {"DISCORD_CLIENT_SECRET": "provided-by-user"}
        result = complete_credentials(original)
        self.assertEqual(original, {"DISCORD_CLIENT_SECRET": "provided-by-user"})
        self.assertEqual(result["DISCORD_CLIENT_SECRET"], original["DISCORD_CLIENT_SECRET"])
        self.assertGreaterEqual(len(result["DISCORD_AUTH_TOKEN"]), 48)
        self.assertTrue(result["MINIO_ACCESS_KEY_ID"].startswith("lab-thepool-"))
        self.assertEqual(complete_credentials(result), result)
        with self.assertRaises(RuntimeError):
            complete_credentials({})

    def test_existing_partial_schema_data_cannot_be_reset(self):
        with patch("thepool.mysql_database"), patch("thepool.schema", return_value="DELIMITER $$"), patch("thepool.mysql_sql") as sql:
            sql.side_effect = [json.dumps({"tables": 3, "triggers": 0, "routines": 0}), json.dumps({"chunks": 1, "collections": 0, "totalsRows": 1, "total": 1})]
            with self.assertRaises(RuntimeError):
                initialize_database("x"*64)
            self.assertFalse(any("DROP " in c.args[0] or "CREATE " in c.args[0] for c in sql.call_args_list))

    def test_download_cors_is_readonly_and_only_allows_original_ui(self):
        rules = cors_identity(CORS)
        self.assertEqual(len(rules), 1)
        self.assertIn(("AllowedOrigin", "https://pool.pmh.codes"), rules[0])
        self.assertEqual({v for k,v in rules[0] if k == "AllowedMethod"}, {"GET", "HEAD"})

    def test_native_runtime_preserves_original_interfaces_and_never_uses_bundled_key(self):
        pod = yaml.safe_load((ROOT / "thepool/deployment.yml").read_text())["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        app = pod["containers"][0]
        self.assertNotIn("command", app)
        env = {e["name"]: e for e in app["env"]}
        self.assertEqual(env["DISCORD_CLIENT_ID"]["value"], "1563036864989106176")
        self.assertEqual(env["DISCORD_TARGET_GUILD_ID"]["value"], "541782241131495434")
        self.assertEqual(env["WEBSERVER_STATIC_ENDPOINT_PREFIX"]["value"], "https://s.pmh.codes")
        self.assertEqual(env["CRONJOB_POOL_SIZE_LIMIT_MB"]["value"], "51200")
        self.assertEqual(env["WEBSERVER_TLS_KEY_PATH"]["value"], "/tls/tls.key")
        self.assertIn("/tmp", [v["mountPath"] for v in app["volumeMounts"]])
        self.assertIn("GOPATH", [e["name"] for e in pod["initContainers"][0]["env"]])
        self.assertFalse(any("secretKeyRef" in str(e) for e in pod["initContainers"][0].get("env", [])))
        docs = list(yaml.safe_load_all((ROOT / "thepool/ingress.yml").read_text()))
        tls = next(d for d in docs if d["kind"] == "BackendTLSPolicy")
        self.assertEqual(tls["spec"]["validation"], {"hostname": "pool.pmh.codes", "wellKnownCACertificates": "System"})
        self.assertFalse(any(d["kind"] == "Backend" for d in docs))
