import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    "seahub_discord_quota_test", Path(__file__).resolve().parents[1] / "seahub_discord_quota.py"
)
quota = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quota)


class DiscordQuotaTests(unittest.TestCase):
    def test_unlimited_or_oversized_quota_is_capped(self):
        for current in (-2, -1, 0, 20_000_000_000):
            with self.subTest(current=current):
                api = Mock()
                api.get_user_quota.side_effect = [current, quota.DISCORD_QUOTA_BYTES]
                self.assertEqual(quota.apply_discord_quota("test-user", api), 10_000_000_000)
                api.set_user_quota.assert_called_once_with("test-user", 10_000_000_000)

    def test_smaller_existing_limit_is_preserved(self):
        api = Mock()
        api.get_user_quota.return_value = 2_000_000_000
        self.assertEqual(quota.apply_discord_quota("test-user", api), 2_000_000_000)
        api.set_user_quota.assert_called_once_with("test-user", 2_000_000_000)

    def test_former_pro_role_limit_is_materialized_per_user(self):
        api = Mock()
        api.get_user_quota.return_value = quota.DISCORD_QUOTA_BYTES
        quota.apply_discord_quota("test-user", api)
        api.set_user_quota.assert_called_once_with("test-user", quota.DISCORD_QUOTA_BYTES)

    def test_failed_native_quota_write_is_not_accepted(self):
        api = Mock()
        api.get_user_quota.side_effect = [-2, -2]
        with self.assertRaises(RuntimeError):
            quota.apply_discord_quota("test-user", api)

    def test_verified_discord_login_is_limited_before_response(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, username="test-user"))
        response = object()

        def callback(request):
            quota.mark_discord_login()
            return response

        with patch.object(quota, "apply_discord_quota") as apply:
            self.assertIs(quota.DiscordQuotaMiddleware(callback)(request), response)
        apply.assert_called_once_with("test-user")

    def test_other_users_are_not_modified_and_context_does_not_leak(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, username="test-user"))

        def discord_callback(request):
            quota.mark_discord_login()
            return object()

        with patch.object(quota, "apply_discord_quota") as apply:
            quota.DiscordQuotaMiddleware(discord_callback)(request)
            quota.DiscordQuotaMiddleware(lambda request: object())(request)
        apply.assert_called_once_with("test-user")

    def test_quota_failure_blocks_the_login_response(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, username="test-user"))

        def callback(request):
            quota.mark_discord_login()
            return "authenticated-response"

        with patch.object(quota, "apply_discord_quota", side_effect=RuntimeError), \
                patch.object(quota, "quota_failure", return_value="blocked-response") as fail:
            self.assertEqual(quota.DiscordQuotaMiddleware(callback)(request), "blocked-response")
        fail.assert_called_once_with(request)

    def test_unverified_login_cannot_assign_another_users_quota(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=False, username="test-user"))

        def callback(request):
            quota.mark_discord_login()
            return "not-authenticated"

        with patch.object(quota, "apply_discord_quota") as apply, \
                patch.object(quota, "quota_failure", return_value="blocked-response"):
            self.assertEqual(quota.DiscordQuotaMiddleware(callback)(request), "blocked-response")
        apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
