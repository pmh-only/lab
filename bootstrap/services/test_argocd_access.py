import subprocess
import json
from types import SimpleNamespace
import unittest

import yaml

from provision import ROOT


class ArgoAccessTests(unittest.TestCase):
    def test_fresh_native_server_certificate_and_verified_tls_route(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "argocd-access")], text=True)))
        certificate = next(d for d in docs if d["kind"] == "Certificate")
        self.assertEqual(certificate["spec"]["secretName"], "argocd-server-tls")
        self.assertEqual(certificate["spec"]["dnsNames"], ["argo.pmh.codes"])
        route = next(d for d in docs if d["kind"] == "HTTPRoute")
        self.assertEqual(route["spec"]["hostnames"], ["argo.pmh.codes"])
        self.assertEqual(route["spec"]["rules"][0]["backendRefs"][0]["port"], 443)
        tls = next(d for d in docs if d["kind"] == "BackendTLSPolicy")
        self.assertEqual(tls["spec"]["validation"], {"hostname": "argo.pmh.codes", "wellKnownCACertificates": "System"})
        self.assertEqual(route["metadata"]["annotations"], tls["metadata"]["annotations"])
        self.assertFalse(any(d["kind"] in {"Deployment", "Secret", "SecurityPolicy"} for d in docs))

    def test_native_auth_is_not_disabled_and_admin_ui_is_not_tracked(self):
        bootstrap = (ROOT / "bootstrap/argocd/kustomization.yml").read_text()
        self.assertIn("url: https://argo.pmh.codes", bootstrap)
        self.assertNotIn("server.insecure: true", bootstrap)
        self.assertNotIn("users.anonymous.enabled: true", bootstrap)
        nginx = next(yaml.safe_load_all((ROOT / "gateway/nginx.yml").read_text()))["data"]["nginx.conf"]
        self.assertIn('argo.pmh.codes       "";', nginx)

    def test_native_oidc_uses_vault_secret_pkce_and_admin_only_claim(self):
        docs = list(yaml.safe_load_all((ROOT / "argocd-access/configuration.yml").read_text()))
        config = next(d["data"] for d in docs if d["metadata"]["name"] == "argocd-cm")
        oidc = yaml.safe_load(config["oidc.config"])
        self.assertEqual(oidc["clientSecret"], "$argocd-oidc:client-secret")
        self.assertTrue(oidc["enablePKCEAuthentication"])
        self.assertEqual(config["users.anonymous.enabled"], "true")
        self.assertEqual(config["statusbadge.enabled"], "true")
        self.assertEqual(config["admin.enabled"], "true")
        rbac = next(d["data"] for d in docs if d["metadata"]["name"] == "argocd-rbac-cm")
        self.assertEqual(rbac["policy.default"], "role:public")
        self.assertEqual(rbac["scopes"], "[argocd_roles]")
        self.assertNotIn("role:readonly", rbac["policy.default"])
        secrets = list(yaml.safe_load_all((ROOT / "argocd-access/oidc-secret.yml").read_text()))
        vss = next(d for d in secrets if d["kind"] == "VaultStaticSecret")
        self.assertEqual(vss["spec"]["path"], "argocd/oidc")
        self.assertEqual(vss["spec"]["destination"]["labels"]["app.kubernetes.io/part-of"], "argocd")

    def test_public_access_only_grants_application_and_project_viewing(self):
        docs = list(yaml.safe_load_all((ROOT / "argocd-access/configuration.yml").read_text()))
        rbac = next(d["data"] for d in docs if d["metadata"]["name"] == "argocd-rbac-cm")
        rules = [line.strip() for line in rbac["policy.csv"].splitlines() if line.strip()]
        self.assertEqual({line for line in rules if line.startswith("p,")}, {
            "p, role:public, applications, get, */*, allow",
            "p, role:public, projects, get, *, allow",
        })
        self.assertEqual({line for line in rules if line.startswith("g,")}, {
            "g, lab-argocd-admins, role:admin",
            "g, admin, role:admin",
        })

    def test_only_active_human_authentik_administrators_receive_admin_role(self):
        declaration = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["argocd"]
        expression = declaration["extraScopeMappings"][0]["expression"].removeprefix("return ")
        for active, superuser, kind in [(True, True, "internal"), (True, False, "internal"), (True, True, "service_account"), (False, True, "internal")]:
            user = SimpleNamespace(is_active=active, is_superuser=superuser, type=kind)
            expected = ["lab-argocd-admins"] if active and superuser and kind == "internal" else []
            self.assertEqual(eval(expression, {"user": user}), {"argocd_roles": expected})
