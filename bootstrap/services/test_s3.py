import unittest

import yaml

from provision import ROOT, PROFILES as SERVICE_PROFILES, generated, valid_field
from s3 import PROFILES, bucket_policy, public_download_policy


class S3Tests(unittest.TestCase):
    def test_console_root_redirect_does_not_rewrite_oidc_or_s3_routes(self):
        docs = list(yaml.safe_load_all((ROOT / "minio/ingress.yml").read_text()))
        route = next(d for d in docs if d and d["kind"] == "HTTPRoute" and d["metadata"]["name"] == "minio-console-route")
        redirect, backend = route["spec"]["rules"]
        self.assertEqual(redirect["matches"], [{
            "path": {"type": "Exact", "value": "/"},
            "headers": [{"name": "Accept", "type": "RegularExpression", "value": ".*text/html.*"}],
        }])
        self.assertEqual(redirect["filters"][0]["requestRedirect"]["path"], {"type": "ReplaceFullPath", "replaceFullPath": "/rustfs/console/"})
        self.assertEqual(backend["backendRefs"][0]["port"], 9001)
        self.assertNotIn("filters", backend)

    def test_app_keys_are_fresh_and_identifiable(self):
        for name in PROFILES:
            kind = "s3-access:" + name
            first, second = generated(kind), generated(kind)
            self.assertNotEqual(first, second)
            self.assertTrue(valid_field(first, kind))
            self.assertFalse(valid_field("old-static-access-key", kind))
            self.assertFalse(valid_field(first, "s3-access:unrelated"))

    def test_policies_cannot_administer_server_or_other_buckets(self):
        for name, profile in PROFILES.items():
            policy = bucket_policy(profile["bucket"], profile["delete"])
            statements = policy["Statement"]
            self.assertEqual(statements[0]["Resource"], ["arn:aws:s3:::" + profile["bucket"]])
            self.assertEqual(statements[1]["Resource"], ["arn:aws:s3:::" + profile["bucket"] + "/*"])
            actions = {a for s in statements for a in s["Action"]}
            self.assertTrue(all(a.startswith("s3:") and "*" not in a for a in actions))
            self.assertNotIn("s3:DeleteBucket", actions)
            self.assertNotIn("s3:PutBucketPolicy", actions)
            self.assertEqual("s3:DeleteObject" in actions, profile["delete"])

    def test_only_public_download_objects_are_anonymous(self):
        policy = public_download_policy("pub")
        self.assertEqual(policy["Statement"][0]["Action"], ["s3:GetObject"])
        self.assertEqual(policy["Statement"][0]["Resource"], ["arn:aws:s3:::pub/*"])

    def test_credentials_share_the_declared_service_vault_path(self):
        for name in ["indexgen", "books"]:
            profile = PROFILES[name]
            path, fields = SERVICE_PROFILES[name]
            self.assertEqual(path, profile["path"])
            self.assertEqual(fields[profile["access"]], "s3-access:" + name)
            self.assertEqual(fields[profile["secret"]], "random")


if __name__ == "__main__":
    unittest.main()
