import json
import unittest
from html.parser import HTMLParser

import yaml

from provision import ROOT


class TextContent(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())


class WelplanStaticTests(unittest.TestCase):
    def test_notice_has_the_exact_requested_text_without_scripts_or_redirects(self):
        html = (ROOT / "welplan/index.html").read_text()
        parsed = TextContent()
        parsed.feed(html)
        self.assertEqual(parsed.text[-3:], [
            "서비스 이용이 일시 중단되었습니다.",
            "본 서비스는 관련 권리자와의 협의가 완료되지 않아 제공을 중단했습니다.",
            "이용에 불편을 드려 죄송합니다.",
        ])
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("iframe", parsed.tags)
        self.assertNotIn("http-equiv", html)
        self.assertNotIn("welstory", html)

    def test_standard_bucket_route_is_used_without_a_dedicated_application(self):
        self.assertEqual({p.name for p in (ROOT / "welplan").iterdir()}, {"index.html", "README.md"})
        self.assertFalse((ROOT / "apps/welplan.yml").exists())
        docs = list(yaml.safe_load_all((ROOT / "minio/ingress.yml").read_text()))
        route = next(d for d in docs if d["metadata"]["name"] == "minio-bucket-route")
        self.assertIn("*.pmh.codes", route["spec"]["hostnames"])
        declarations = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())
        self.assertNotIn("welplan", declarations)
        for path in ["bootstrap/services/welplan.py", "bootstrap/services/welplan_dns.py"]:
            self.assertFalse((ROOT / path).exists())
        gateway = (ROOT / "gateway/nginx.yml").read_text()
        self.assertRegex(gateway, r'welplan\.pmh\.codes\s+""')
