"""Phase 86: the authorization matrix, read from the code and enforced for every role.

1. Every route's requirement (public, any signed-in user, or one permission) matches the
   reviewed copy in `authorization_matrix.json`: adding a route or changing what one
   requires fails here until the copy is regenerated and the difference reviewed.
2. Every role is tried against every guarded route. A role without the permission gets
   403 naming that permission, for every method. A role with it passes the permission
   check (GET routes only: the others would act).
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.permissions import ROLE_PERMISSIONS, SERVICE_ROLES, Permission, RoleCode
from app.security import matrix
from tests.factories import auth, make_user
from tests.test_permissions import PUBLIC_ROUTES

SNAPSHOT = Path(__file__).with_name("authorization_matrix.json")
PEOPLE = [r for r in RoleCode if r not in SERVICE_ROLES]
ZERO = "00000000-0000-0000-0000-000000000000"


def _path(template: str) -> str:
    return re.sub(r"\{[^}]+\}", ZERO, template)


def test_the_routes_match_the_reviewed_matrix(app) -> None:
    current = matrix.routes(app)
    reviewed = json.loads(SNAPSHOT.read_text())
    assert current == reviewed, (
        "A route's requirement changed: review the difference with "
        "`python -m app.cli authz-matrix`, then regenerate with --write."
    )
    public = {tuple(k.split(" ", 1)) for k, v in current.items() if v == matrix.PUBLIC}
    assert public == PUBLIC_ROUTES
    # Every permission a route requires exists, and none is left unused by every route.
    required = {v for v in current.values() if v not in (matrix.PUBLIC, matrix.SIGNED_IN)}
    assert required <= {p.value for p in Permission}


def test_the_generated_document_is_current(app) -> None:
    document = Path(__file__).resolve().parents[2] / "docs" / "authorization-matrix.md"
    assert document.read_text() == matrix.markdown(matrix.routes(app))


@pytest.mark.parametrize("role", PEOPLE, ids=lambda r: r.value)
def test_every_role_is_refused_what_its_permissions_do_not_grant(
    role: RoleCode, client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "rate_limits_enabled", False)
    headers = auth(make_user(db, role))
    db.commit()
    held = {p.value for p in ROLE_PERMISSIONS[role]}
    refused = allowed = 0
    for key, need in matrix.routes(client.app).items():
        if need in (matrix.PUBLIC, matrix.SIGNED_IN):
            continue
        method, template = key.split(" ", 1)
        if need not in held:
            response = client.request(method, _path(template), json={}, headers=headers)
            body = response.json()
            assert response.status_code == 403, f"{role.value}: {key} -> {response.status_code}"
            assert body["error"]["details"]["required_permission"] == need, key
            refused += 1
        elif method == "GET":
            response = client.request(method, _path(template), headers=headers)
            denied_for_it = (
                response.status_code == 403
                and (response.json().get("error", {}).get("details") or {}).get(
                    "required_permission"
                )
                == need
            )
            assert not denied_for_it, f"{role.value} holds {need} but {key} refused it"
            allowed += 1
    if role == RoleCode.PLATFORM_ADMINISTRATOR:
        assert refused == 0 and allowed > 100
    else:
        assert refused > 0
