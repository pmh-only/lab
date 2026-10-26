import json
import subprocess
import unittest

import yaml

from provision import ROOT


class HereDomainMigrationTests(unittest.TestCase):
    def test_tunnel_urls_route_and_tls_use_the_codes_domain(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "here")], text=True)))
        route = next(d for d in docs if d["kind"] == "HTTPRoute")
        self.assertEqual(route["spec"]["hostnames"], ["*.here.pmh.codes"])
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        env = {e["name"]: e for e in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["HTTP_HOST_SUFFIX"]["value"], ".here.pmh.codes")
        self.assertEqual(env["SSH_DOMAIN"]["value"], "here.pmh.codes")
        certificate = yaml.safe_load((ROOT / "gateway/public-certificate.yml").read_text())
        self.assertIn("*.here.pmh.codes", certificate["spec"]["dnsNames"])
        self.assertIn("*.here.pmh.so", certificate["spec"]["dnsNames"])

    def test_wildcard_parent_names_resolve_before_redirecting(self):
        desired = json.loads((ROOT / "nameserver/configuration/imported-records.json").read_text())
        records = {r["name"]: set() for z in desired["zones"] for r in z["records"] if r["type"] == "A"}
        for zone in desired["zones"]:
            for record in zone["records"]:
                if record["type"] == "A":
                    records[record["name"]].add(record["data"]["ipAddress"])
        for name in ["here.pmh.so", "s3.pmh.so", "mc.pmh.so", "here.pmh.codes", "*.here.pmh.codes"]:
            self.assertEqual(records[name], {"168.110.121.95", "138.2.112.39"})
        docs = list(yaml.safe_load_all((ROOT / "gateway/nginx.yml").read_text()))
        config = next(d for d in docs if d["kind"] == "ConfigMap")["data"]["nginx.conf"]
        self.assertIn(r"~^(?<pmhso_subdomain>.+)\.pmh\.so$ $pmhso_subdomain.pmh.codes;", config)
        self.assertIn("return 301 https://$pmhso_redirect_host$request_uri;", config)
