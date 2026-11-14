"""Discard only obsolete, unauthenticated default-login plans.

Preview:
  kubectl exec -i -n authentik deployment/authentik-worker -c authentik \
    -- ak shell -c 'exec(__import__("sys").stdin.read())' \
    < authentik/migrate-pending-login-plans.py

Apply: add `env APPLY_PENDING_LOGIN_MIGRATION=1` before `ak` in that command.
Authenticated sessions, cookies, OAuth state, and original return queries are
preserved. This is a one-time data migration, not a session logout operation.
"""

import os
from collections import Counter
from uuid import UUID

from django.db import transaction
from django.utils.timezone import now

from authentik.core.models import Session
from authentik.core.sessions import SessionStore
from authentik.flows.models import Flow
from authentik.flows.views.executor import SESSION_KEY_PLAN

LEGACY_STAGES = {
    "default-authentication-identification",
    "default-authentication-password",
    "cap-captcha",
    "default-authentication-mfa-validation",
    "default-authentication-login",
    "lab-login-choice",
    "lab-login-discord-redirect",
}
apply = os.environ.get("APPLY_PENDING_LOGIN_MIGRATION") == "1"
flow_pk = Flow.objects.get(slug="default-authentication-flow").pk
store = SessionStore()
counts = Counter()
with transaction.atomic():
    sessions = Session.objects.filter(
        expires__gt=now(), authenticatedsession__isnull=True
    ).select_for_update(of=("self",))
    for session in sessions.iterator():
        data = store.decode(session.session_data)
        plan = data.get(SESSION_KEY_PLAN)
        # FlowPlan serializes UUIDs as hex without hyphens.
        if plan is None or UUID(str(plan.flow_pk)) != flow_pk:
            continue
        stages = {binding.stage.name for binding in plan.bindings}
        if not stages.intersection(LEGACY_STAGES):
            continue
        counts["obsolete_pending_plans"] += 1
        if apply:
            del data[SESSION_KEY_PLAN]
            session.session_data = store.encode(data)
            session.save(update_fields=["session_data"])
            counts["migrated"] += 1

print("LOGIN_PLAN_MIGRATION", {"apply": apply, **counts})
