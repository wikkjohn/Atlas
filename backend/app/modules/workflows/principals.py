"""Who acted on a case, as a principal the banking services can re-check."""

import uuid

from sqlalchemy import select

from app.core.permissions import permissions_for
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.workflows.engine import StepContext, StepError

POLICY_ENGINE_USERNAME = "atlas-policy-engine"


def principal(ctx: StepContext, user_id: str) -> AuthenticatedUser:
    user = ctx.db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise StepError("approver_inactive", "The approving user is no longer active.")
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        role=user.role.code,
        permissions=permissions_for(user.role.code),
    )


def policy_engine(ctx: StepContext) -> User | None:
    """The policy engine's service account, if it exists and is switched on."""
    user = ctx.db.execute(
        select(User).where(User.username == POLICY_ENGINE_USERNAME)
    ).scalar_one_or_none()
    return user if user is not None and user.is_active else None
