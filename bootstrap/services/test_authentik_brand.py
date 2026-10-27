import copy
import json
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from authentik_brand import ASSETS, VISUAL_FIELDS, asset_name, provision_brand


class AuthentikBrandTests(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads((ASSETS / "brand.json").read_text())
        self.css = (ASSETS / "theme.css").read_text()
        self.assets = {f: (ASSETS / f).read_bytes() for f in self.settings["assets"].values()}
        self.brand = {
            "brand_uuid": "existing-brand", "domain": "authentik-default", "default": True,
            "branding_title": "authentik", "branding_custom_css": "",
            "flow_authentication": "existing-flow", "flow_invalidation": "existing-logout",
            "web_certificate": None, "client_certificates": [], "default_application": None,
            "attributes": {"unrelated": True, "settings": {"locale": "ko", "theme": {"unrelated": "preserved"}}},
        }
        self.flow = {"pk": "existing-flow", "title": "Welcome to authentik!", "designation": "authentication", "stages": ["password", "mfa"], "authentication": "require_unauthenticated"}
        self.api = Mock()
        self.api.list.return_value = [self.brand]
        self.api.request.side_effect = lambda path: {"results": [self.flow]} if path.startswith("flows/") else []
        self.api.patch.side_effect = lambda path, values: {**(self.brand if path.startswith("core/") else self.flow), **values}

    def test_dry_run_performs_no_writes(self):
        before = copy.deepcopy(self.brand)
        desired = provision_brand(self.api, self.settings, self.css, self.assets)
        self.api.patch.assert_not_called()
        self.api.upload.assert_not_called()
        self.assertEqual(self.brand, before)
        self.assertEqual(set(desired), VISUAL_FIELDS)
        self.assertEqual(desired["branding_custom_css"], self.css.strip())
        self.assertEqual(desired["attributes"]["settings"]["theme"]["base"], "dark")
        self.assertTrue(desired["attributes"]["unrelated"])
        self.assertEqual(desired["attributes"]["settings"]["locale"], "ko")
        self.assertEqual(desired["attributes"]["settings"]["theme"]["unrelated"], "preserved")

    def test_apply_uploads_only_hash_named_assets_and_patches_only_visuals(self):
        provision_brand(self.api, self.settings, self.css, self.assets, True)
        self.assertEqual(self.api.upload.call_count, 3)
        self.assertEqual(self.api.patch.call_count, 2)
        self.assertEqual(set(self.api.patch.call_args_list[0].args[1]), VISUAL_FIELDS)
        self.assertEqual(self.api.patch.call_args_list[1].args[1], {"title": "Welcome back"})
        self.assertEqual(self.api.patch.call_args_list[1].args[0], "flows/instances/default-authentication-flow/")
        for filename, content in self.assets.items():
            self.api.upload.assert_any_call(asset_name(filename, content), content)

    def test_reapply_is_idempotent_and_never_deletes_assets(self):
        desired = provision_brand(self.api, self.settings, self.css, self.assets)
        self.brand.update(desired)
        self.flow["title"] = self.settings["flowTitle"]
        files = [{"name": asset_name(name, content)} for name, content in self.assets.items()]
        self.api.request.side_effect = lambda path: {"results": [self.flow]} if path.startswith("flows/") else files
        provision_brand(self.api, self.settings, self.css, self.assets, True)
        self.api.patch.assert_not_called()
        self.api.upload.assert_not_called()
        self.api.delete.assert_not_called()

    def test_native_flow_cache_invalidation_is_not_an_authentication_change(self):
        self.flow["cache_count"] = 5
        def patch(path, values):
            if path.startswith("core/"):
                return {**self.brand, **values}
            return {**self.flow, **values, "cache_count": 0}
        self.api.patch.side_effect = patch
        provision_brand(self.api, self.settings, self.css, self.assets, True)

    def test_changing_an_authentication_stage_fails_verification(self):
        def patch(path, values):
            if path.startswith("core/"):
                return {**self.brand, **values}
            return {**self.flow, **values, "stages": ["password"]}
        self.api.patch.side_effect = patch
        with self.assertRaisesRegex(RuntimeError, "Flow title-only"):
            provision_brand(self.api, self.settings, self.css, self.assets, True)

    def test_unmanaged_customizations_are_not_overwritten(self):
        self.brand["branding_custom_css"] = "/* someone else's theme */"
        with self.assertRaisesRegex(RuntimeError, "Unmanaged custom CSS"):
            provision_brand(self.api, self.settings, self.css, self.assets, True)
        self.api.upload.assert_not_called()
        self.api.patch.assert_not_called()

    def test_theme_is_self_contained_and_keeps_native_auth_controls_accessible(self):
        self.assertNotIn("@import", self.css)
        # Inline SVG namespaces are not network requests; remote CSS assets are.
        self.assertNotRegex(self.css, r'''url\(\s*["']?(?:https?:)?//''')
        self.assertNotIn("display: none", self.css)
        self.assertIn(":focus-visible", self.css)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("forced-colors", self.css)
        self.assertIn('part="card"', self.css)
        for content in self.assets.values():
            root = ET.fromstring(content)
            self.assertTrue(root.tag.endswith("svg"))
            self.assertFalse(any(e.tag.endswith("script") for e in root.iter()))

    def test_discord_source_has_dedicated_full_width_style(self):
        self.assertIn('button[name="source-discord"]', self.css)
        self.assertIn('[part="source-list"]', self.css)
        self.assertIn("#5865f2", self.css)
        self.assertIn("mask: url(\"data:image/svg+xml,", self.css)


if __name__ == "__main__":
    unittest.main()
