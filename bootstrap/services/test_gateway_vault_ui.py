import unittest

import yaml

from provision import ROOT


class GatewayVaultUITests(unittest.TestCase):
    def test_vault_preserves_compression_negotiation_without_analytics_injection(self):
        docs = list(yaml.safe_load_all((ROOT / "gateway/nginx.yml").read_text()))
        config = next(d for d in docs if d["kind"] == "ConfigMap")["data"]["nginx.conf"]
        self.assertIn('map $host $upstream_accept_encoding {\n    default "";\n    vault.pmh.codes $http_accept_encoding;\n  }', config)
        self.assertIn("proxy_set_header Accept-Encoding $upstream_accept_encoding;", config)
        self.assertRegex(config, r'vault\.pmh\.codes\s+"";')
        self.assertIn("sub_filter '<head>' '<head>$tracking_script';", config)
        daemonset = next(d for d in docs if d["kind"] == "DaemonSet")
        self.assertEqual(daemonset["spec"]["template"]["metadata"]["annotations"]["pmh.codes/config-revision"], "2026-10-26-vault-gzip")


if __name__ == "__main__":
    unittest.main()
