"""Apply a Discord account's native per-user quota after verified OAuth login."""

from contextvars import ContextVar
import logging


DISCORD_QUOTA_BYTES = 10_000_000_000
_discord_login = ContextVar("pmh_discord_login", default=False)
logger = logging.getLogger(__name__)


def mark_discord_login():
    # Called only by the native OAuth role hook, using the IdP's userinfo claim.
    _discord_login.set(True)


def apply_discord_quota(username, api=None):
    if api is None:
        from seaserv import seafile_api
        api = seafile_api
    current = int(api.get_user_quota(username))
    quota = min(current, DISCORD_QUOTA_BYTES) if current > 0 else DISCORD_QUOTA_BYTES
    # Always materialize a per-user quota, even if a former Pro role currently
    # reports the same effective limit. Community does not enforce role quotas.
    api.set_user_quota(username, quota)
    applied = int(api.get_user_quota(username))
    if applied <= 0 or applied > quota:
        raise RuntimeError("The Discord user quota was not applied")
    return applied


def quota_failure(request):
    from django.http import HttpResponse
    from seahub import auth
    auth.logout(request)
    return HttpResponse(
        "Storage quota could not be applied. Please try signing in again.",
        status=503, content_type="text/plain; charset=utf-8",
    )


class DiscordQuotaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _discord_login.set(False)
        try:
            response = self.get_response(request)
            if _discord_login.get():
                try:
                    user = getattr(request, "user", None)
                    authenticated = getattr(user, "is_authenticated", False)
                    if callable(authenticated):
                        authenticated = authenticated()
                    if not authenticated:
                        raise RuntimeError("OAuth did not authenticate a user")
                    apply_discord_quota(user.username)
                except Exception as error:
                    logger.error("Discord quota assignment failed (%s)", type(error).__name__)
                    return quota_failure(request)
            return response
        finally:
            _discord_login.reset(token)
