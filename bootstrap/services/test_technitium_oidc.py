import copy
import json
from types import SimpleNamespace
import unittest

import yaml

from provision import ROOT
from technitium_oidc import SETTINGS, reconcile


class DNSClient:
    def __init__(self, desired):
        self.calls = []
        self.config = {**copy.deepcopy(desired), "ssoEnabled": False, "ssoAuthority": None,
                       "ssoClientId": None, "ssoGroupMap": [], "ssoScopes": ["openid", "profile", "email"],
                       "localGroups": ["Administrators"], "ssoClientSecret": "************"}

    def post(self, path, parameters=None):
        self.calls.append((path, parameters))
        if path == "admin/sso/get":
            return {"response": copy.deepcopy(self.config)}
        if path == "zones/list":
            return {"response": {"zones": [{"name": "pmh.codes", "type": "Primary", "disabled": False, "dnssecStatus": "SignedWithNSEC3"}]}}
        if path == "admin/users/get":
            return {"response": {"username": "admin", "disabled": False, "memberOfGroups": ["Administrators"], "isSsoUser": False}}
        if path == "admin/sso/set":
            for k, v in parameters.items():
                if k == "ssoClientSecret":
                    continue
                if k in ["ssoEnabled", "ssoAllowSignup", "ssoAllowSignupOnlyForMappedUsers"]:
                    v = v == "true"
                elif k == "ssoScopes":
                    v = v.split("|")
                elif k == "ssoGroupMap":
                    parts = v.split("|")
                    v = [{"remoteGroup": parts[i], "localGroup": parts[i+1]} for i in range(0, len(parts), 2)]
                elif k == "ssoMetadataAddress":
                    v = v or None
                self.config[k] = v
            return {"response": copy.deepcopy(self.config)}
        raise AssertionError("Unexpected API endpoint " + path)


class TechnitiumOIDCTests(unittest.TestCase):
    def setUp(self):
        self.desired = json.loads(SETTINGS.read_text())

    def test_only_native_sso_configuration_is_written(self):
        client = DNSClient(self.desired)
        reconcile(client, self.desired, "x" * 64)
        writes = [(p, v) for p, v in client.calls if p.endswith("/set")]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], "admin/sso/set")
        parameters = writes[0][1]
        self.assertEqual(parameters["ssoScopes"], "openid|profile|email|technitium")
        self.assertEqual(parameters["ssoGroupMap"], "lab-technitium-admins|Administrators")
        self.assertEqual(parameters["ssoAllowSignupOnlyForMappedUsers"], "true")
        client.calls.clear()
        reconcile(client, self.desired, "x" * 64)
        self.assertEqual([p for p, _ in client.calls], ["admin/sso/get"])

    def test_unmanaged_provider_and_group_map_are_not_replaced(self):
        for field, value in [("ssoAuthority", "https://unrelated.example/"), ("ssoClientId", "unrelated"),
                             ("ssoGroupMap", [{"remoteGroup": "everyone", "localGroup": "Administrators"}])]:
            client = DNSClient(self.desired)
            client.config[field] = value
            with self.assertRaisesRegex(RuntimeError, "Unmanaged"):
                reconcile(client, self.desired, "x" * 64)
            self.assertFalse(any(p.endswith("/set") for p, _ in client.calls))

    def test_claim_only_grants_admin_to_active_internal_superusers(self):
        declaration = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["technitium"]
        expression = declaration["extraScopeMappings"][0]["expression"].removeprefix("return ")
        for active in [False, True]:
            for admin in [False, True]:
                for kind in ["internal", "external", "service_account"]:
                    user = SimpleNamespace(is_active=active, is_superuser=admin, type=kind)
                    claim = eval(expression, {"user": user})
                    self.assertEqual(claim, {"roles": ["lab-technitium-admins"] if active and admin and kind == "internal" else []})

    def test_proxy_pins_public_origin_only_for_the_console(self):
        routes = list(yaml.safe_load_all((ROOT / "nameserver/ingress.yml").read_text()))
        ui = next(d for d in routes if d["metadata"]["name"] == "nameserver-route")
        headers = ui["spec"]["rules"][0]["filters"][0]["requestHeaderModifier"]["set"]
        self.assertEqual({h["name"]: h["value"] for h in headers}, {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "names.pmh.codes"})
        self.assertEqual(ui["spec"]["rules"][0]["backendRefs"][0]["port"], 5380)
        code = (ROOT / "bootstrap/services/technitium_oidc.py").read_text()
        self.assertNotIn('post("settings/set"', code)
        self.assertNotIn('"rollout"', code)
        self.assertNotIn('"zones/create"', code)
        gateway = next(d["data"]["nginx.conf"] for d in yaml.safe_load_all((ROOT / "gateway/nginx.yml").read_text()) if d and "nginx.conf" in d.get("data", {}))
        self.assertRegex(gateway, r'names\.pmh\.codes\s+""')


if __name__ == "__main__":
    unittest.main()
