"""Run with: kubectl exec -i -n authentik deployment/authentik-worker -c authentik \
-- ak shell -c 'exec(__import__("sys").stdin.read())' < authentik/tests/cap-guard.py

Checks live configuration and server validation order without testing a real
user's password, writing database records, or changing reputation/MFA devices.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory
from rest_framework.exceptions import ValidationError

from authentik.blueprints.models import BlueprintInstance
from authentik.core.models import User
from authentik.flows.models import FlowStageBinding
from authentik.stages.identification.models import IdentificationStage
from authentik.stages.identification.stage import IdentificationChallengeResponse

identification = IdentificationStage.objects.get(
    name="lab-internal-identification"
)
assert identification.password_stage is not None
assert identification.captcha_stage is not None
assert identification.captcha_stage.error_on_invalid_score
assert not identification.sources.exists()
bindings = FlowStageBinding.objects.filter(
    target__slug="lab-internal-authentication"
)
assert not bindings.filter(stage__name="cap-captcha").exists()
assert not bindings.filter(stage=identification.password_stage).exists()
for name in (
    "lab-internal-identification",
    "default-authentication-mfa-validation",
):
    assert bindings.get(stage__name=name).invalid_response_action == "restart"
assert BlueprintInstance.objects.get(path="custom/cap.yaml").status == "successful"
assert BlueprintInstance.objects.get(path="custom/login-choice.yaml").status == "successful"
assert not bindings.filter(
    stage__name__in=["lab-login-choice", "lab-login-discord-redirect"]
).exists()
entry = FlowStageBinding.objects.filter(target__slug="default-authentication-flow")
assert set(entry.values_list("stage__name", flat=True)) == {
    "lab-auth-method-selection", "lab-auth-internal-flow", "lab-auth-discord-flow"
}
discord_identification = IdentificationStage.objects.get(name="lab-discord-identification")
assert discord_identification.user_fields == []
assert discord_identification.password_stage is None
assert discord_identification.captcha_stage is None
assert discord_identification.sources.filter(slug="discord", enabled=True).exists()

user = User(username="captcha-regression-test")
view = SimpleNamespace(
    executor=SimpleNamespace(
        current_stage=identification,
        plan=SimpleNamespace(context={}),
    ),
    request=RequestFactory().post("/"),
    get_user=Mock(return_value=user),
    logger=Mock(),
)
module = "authentik.stages.identification.stage"
for token in (None, "invalid", "expired-or-replayed"):
    with (
        patch(f"{module}.verify_captcha_token", side_effect=ValidationError("Invalid CAPTCHA")),
        patch(f"{module}.authenticate") as password_check,
    ):
        try:
            IdentificationChallengeResponse(stage=view).validate(
                {"uid_field": user.username, "password": "not-a-real-password", "captcha_token": token}
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("Invalid CAPTCHA accepted")
        password_check.assert_not_called()

events = []
with (
    patch(
        f"{module}.verify_captcha_token",
        side_effect=lambda *args, **kwargs: events.append("captcha") or {"success": True},
    ),
    patch(
        f"{module}.authenticate",
        side_effect=lambda *args, **kwargs: events.append("password") or None,
    ),
):
    try:
        IdentificationChallengeResponse(stage=view).validate(
            {"uid_field": user.username, "password": "wrong", "captcha_token": "test-solve"}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Invalid password accepted")
assert events == ["captcha", "password"], events
print("CAP_GUARD_PASS: CAPTCHA gates password validation; credentials and MFA restart without context.")
