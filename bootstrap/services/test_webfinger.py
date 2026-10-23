import io
import json
from types import SimpleNamespace
import unittest

from minio.error import S3Error

from provision import ROOT
from s3 import public_download_policy
from webfinger import BUCKET, KEY, publish


class Response(io.BytesIO):
    def release_conn(self):
        pass


class FakeS3:
    def __init__(self, exists=False, policy=None, objects=None):
        self.exists, self.policy = exists, policy
        self.objects, self.writes = dict(objects or {}), []

    def bucket_exists(self, bucket):
        assert bucket == BUCKET
        return self.exists

    def make_bucket(self, bucket):
        self.writes.append("make_bucket")
        self.exists = True

    def get_bucket_policy(self, bucket):
        if self.policy is None:
            raise S3Error(None, "NoSuchBucketPolicy", "missing", None, None, None)
        return json.dumps(self.policy)

    def set_bucket_policy(self, bucket, policy):
        self.writes.append("set_policy")
        self.policy = json.loads(policy)

    def list_objects(self, bucket, recursive):
        return [SimpleNamespace(object_name=k) for k in self.objects]

    def get_object(self, bucket, key):
        if key not in self.objects:
            raise S3Error(None, "NoSuchKey", "missing", None, None, None)
        return Response(self.objects[key])

    def put_object(self, bucket, key, data, length, content_type):
        assert bucket == BUCKET and key == KEY and content_type == "application/jrd+json"
        self.writes.append("put_object")
        self.objects[key] = data.read()


class WebFingerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (ROOT / "minio_static/www/.well-known/webfinger").read_bytes()

    def test_public_static_document_uses_same_tailscale_issuer_and_exact_subject(self):
        document = json.loads(self.body)
        self.assertEqual(document["subject"], "acct:pmh_only@pmh.codes")
        self.assertEqual(document["links"], [{"rel": "http://openid.net/specs/connect/1.0/issuer", "href": "https://auth.pmh.codes/application/o/tailscale/"}])

    def test_new_www_bucket_is_read_only_public_and_replay_does_not_overwrite(self):
        client = FakeS3()
        publish(client, self.body)
        self.assertEqual(client.writes, ["make_bucket", "set_policy", "put_object"])
        self.assertEqual(client.policy, public_download_policy("www"))
        client.writes.clear()
        publish(client, self.body)
        self.assertEqual(client.writes, [])

    def test_private_data_unknown_policy_or_existing_document_are_not_changed(self):
        for client in [FakeS3(True, objects={"private.txt": b"private"}),
                       FakeS3(True, policy={"unknown": True}),
                       FakeS3(True, objects={KEY: b'{"unexpected": true}'})]:
            with self.subTest(client=client), self.assertRaises(RuntimeError):
                publish(client, self.body)
            self.assertEqual(client.writes, [])

    def test_public_apex_and_explicit_legacy_redirect_dns_preserve_authority_only_asn_zone(self):
        zones = {z["zone"]: z for z in json.loads((ROOT / "nameserver/configuration/imported-records.json").read_text())["zones"]}
        self.assertFalse(zones["pmh.codes"]["emptyApexWeb"])
        addresses = {r["data"]["ipAddress"] for r in zones["pmh.codes"]["records"] if r["name"] == "pmh.codes" and r["type"] == "A"}
        self.assertEqual(addresses, {"168.110.121.95", "138.2.112.39"})
        self.assertFalse(zones["pmh.so"]["emptyApexWeb"])
        for owner in ["pmh.so", "*.pmh.so", "*.here.pmh.so", "*.s3.pmh.so", "*.mc.pmh.so"]:
            self.assertEqual({r["data"]["ipAddress"] for r in zones["pmh.so"]["records"] if r["name"] == owner and r["type"] == "A"}, addresses)
        self.assertTrue(zones["as218822.net"]["authorityOnly"])
        self.assertTrue(zones["as218822.net"]["emptyApexWeb"])


if __name__ == "__main__":
    unittest.main()
