from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import yaml


BLUEPRINT = Path(__file__).resolve().parents[1] / "blueprints" / "discord.yaml"
ENTRIES = yaml.load(BLUEPRINT.read_text(), Loader=yaml.BaseLoader)["entries"]
ACCESS_ENTRIES = yaml.load(
    BLUEPRINT.with_name("discord-application-access.yaml").read_text(), Loader=yaml.BaseLoader
)["entries"]


def expression(name, context, entries=ENTRIES):
    entry = next(entry for entry in entries if entry.get("identifiers", {}).get("name") == name)
    body = entry["attrs"]["expression"]
    namespace = dict(context)
    exec("def evaluate():\n" + "\n".join("    " + line for line in body.splitlines()), namespace)
    return namespace["evaluate"]()


class DiscordTests(unittest.TestCase):
    def test_as218822_operator_claim_excludes_discord_even_if_admin(self):
        entries = yaml.load(BLUEPRINT.with_name("as218822-user-access.yaml").read_text(),
                            Loader=yaml.BaseLoader)["entries"]
        for discord, admin, role in ((True, False, "user"), (True, True, "user"),
                                     (False, True, "operator"), (False, False, "user")):
            with self.subTest(discord=discord, admin=admin):
                user = Mock(is_active=True, is_superuser=admin, type="internal")
                user.sources.filter.return_value.exists.return_value = discord
                user.all_groups.return_value.filter.return_value.exists.return_value = discord
                self.assertEqual(expression("lab bootstrap: as218822 console roles",
                                            {"user": user}, entries), {"as218822_roles": [role]})

    def test_discord_application_access_is_denied_outside_allowlist(self):
        for source, group, allowed in ((True, False, False), (False, True, False),
                                        (True, True, False), (False, False, True)):
            with self.subTest(source=source, group=group):
                user = Mock()
                user.sources.filter.return_value.exists.return_value = source
                user.all_groups.return_value.filter.return_value.exists.return_value = group
                self.assertEqual(expression("discord-deny-application-access", {
                    "request": SimpleNamespace(user=user, obj=SimpleNamespace(slug="argocd")),
                }, ACCESS_ENTRIES), allowed)

    def test_discord_allowlist_contains_only_requested_applications(self):
        user = Mock()
        user.sources.filter.return_value.exists.return_value = True
        allowed = {"as218822", "books", "go", "immich", "meta", "pdf", "seafile"}
        for slug in allowed | {"argocd", "velero-ui", "kopia", "unknown"}:
            with self.subTest(slug=slug):
                self.assertEqual(expression("discord-deny-application-access", {
                    "request": SimpleNamespace(user=user, obj=SimpleNamespace(slug=slug)),
                }, ACCESS_ENTRIES), slug in allowed)

    def test_as218822_allows_discord_without_granting_administrator_status(self):
        for discord, admin, active, allowed in (
            (True, False, True, True), (False, True, True, True),
            (False, False, True, False), (True, False, False, False),
        ):
            with self.subTest(discord=discord, admin=admin, active=active):
                user = Mock(is_authenticated=True, is_active=active,
                            is_superuser=admin, type="internal")
                user.sources.filter.return_value.exists.return_value = discord
                user.all_groups.return_value.filter.return_value.exists.return_value = discord
                self.assertEqual(expression(
                    "lab bootstrap: as218822 console administrators only",
                    {"request": SimpleNamespace(user=user)}, ACCESS_ENTRIES,
                ), allowed)

    def test_all_current_applications_have_fail_closed_guard(self):
        bindings = [entry for entry in ACCESS_ENTRIES
                    if entry["model"] == "authentik_policies.policybinding"]
        self.assertEqual(len(bindings), 19)
        for binding in bindings:
            self.assertEqual(binding["attrs"]["failure_result"], "false")
            self.assertEqual(binding["attrs"]["enabled"], "true")

    def test_enrollment_allows_user_library_without_admin_access(self):
        stage = next(entry for entry in ENTRIES if entry.get("id") == "discord-enrollment-write")
        self.assertEqual(stage["attrs"]["user_type"], "internal")
        group = next(entry for entry in ENTRIES if entry["model"] == "authentik_core.group")
        self.assertEqual(group["attrs"]["is_superuser"], "false")

    def test_discord_ui_text_is_english(self):
        self.assertFalse(any("\uac00" <= char <= "\ud7a3" for char in BLUEPRINT.read_text()))

    def mapping(self, status, existing_user=None):
        response = Mock(status_code=status)
        if status not in (200, 404):
            response.raise_for_status.side_effect = RuntimeError("Discord API failure")
        client = Mock()
        client.do_request.return_value = response
        result = expression("discord-guild-membership", {
            "client": client,
            "token": {"access_token": "test-only"},
            "info": {"id": "123", "username": "member"},
            "ak_user_by": Mock(return_value=existing_user),
        })
        client.do_request.assert_called_once_with(
            "GET", "https://discord.com/api/v10/users/@me/guilds/541782241131495434/member",
            token={"access_token": "test-only"},
        )
        return result

    def policy(self, data, source="discord", sso=True):
        return expression("discord-required-guild", {
            "request": SimpleNamespace(context={
                "source": SimpleNamespace(slug=source), "prompt_data": data,
            }),
            "ak_is_sso_flow": sso,
            "ak_message": Mock(),
        })

    def test_member_allowed_and_group_assigned(self):
        data = self.mapping(200)
        self.assertEqual(data["groups"], ["discord"])
        self.assertEqual(data["username"], "member")
        self.assertTrue(self.policy(data))

    def test_username_collision_does_not_link_another_account(self):
        existing_user = Mock()
        existing_user.usersourceconnection_set.filter.return_value.exists.return_value = False
        self.assertEqual(self.mapping(200, existing_user)["username"], "member_discord_123")

    def test_existing_discord_user_keeps_readable_username(self):
        existing_user = Mock()
        existing_user.usersourceconnection_set.filter.return_value.exists.return_value = True
        self.assertEqual(self.mapping(200, existing_user)["username"], "member")

    def test_nonmember_denied(self):
        data = self.mapping(404)
        self.assertEqual(data["groups"], [])
        self.assertFalse(self.policy(data))

    def test_api_errors_fail_closed(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                self.mapping(status)

    def test_missing_mapping_denied(self):
        self.assertFalse(self.policy({}))

    def test_wrong_guild_denied(self):
        data = {"attributes": {"discord": {"guild_id": "other", "is_member": True}}}
        self.assertFalse(self.policy(data))

    def test_direct_and_other_source_flows_denied(self):
        data = self.mapping(200)
        self.assertFalse(self.policy(data, source="other"))
        self.assertFalse(self.policy(data, sso=False))


if __name__ == "__main__":
    unittest.main()
