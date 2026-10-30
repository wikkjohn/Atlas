import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.dependencies import DbSession
from app.core.permissions import Permission
from app.modules.compliance.screening import SANCTIONS_LISTS
from app.modules.countries import service as countries
from app.modules.identity.dependencies import Authorized
from app.modules.rules import service
from app.modules.rules.schemas import (
    CountryRulesOut,
    RuleVersionIn,
    RuleVersionOut,
    SanctionsListOut,
)

router = APIRouter(tags=["country rules"])


@router.get(
    "/countries/{country_id}/rules",
    response_model=CountryRulesOut,
    summary="A country's rules in force on a day, and every version",
)
def country_rules(
    country_id: uuid.UUID,
    db: DbSession,
    _: Authorized(Permission.COUNTRIES_READ),
    on: Annotated[date | None, Query(description="Default today")] = None,
) -> CountryRulesOut:
    country = countries.get_country(db, country_id)
    day = on or datetime.now(UTC).date()
    current = service.version_on(db, country, day)
    return CountryRulesOut(
        iso_country_code=country.iso_country_code,
        on=day,
        current=service.version_out(db, [current])[0] if current else None,
        effective=service.rules_on(db, country, day),
        versions=service.version_out(db, service.versions(db, country)),
    )


@router.post(
    "/countries/{country_id}/rules",
    response_model=RuleVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a version of a country's rules (versions are never edited)",
)
def add_rule_version(
    country_id: uuid.UUID,
    body: RuleVersionIn,
    db: DbSession,
    actor: Authorized(Permission.COUNTRIES_MANAGE),
) -> RuleVersionOut:
    country = countries.get_country(db, country_id)
    record = service.add_version(db, country, body.rules, body.effective_from, body.note, actor.id)
    return service.version_out(db, [record])[0]


@router.get(
    "/sanctions-lists",
    response_model=list[SanctionsListOut],
    summary="The synthetic sanctions lists countries may screen against",
)
def sanctions_lists(_: Authorized(Permission.COUNTRIES_READ)) -> list[SanctionsListOut]:
    return [
        SanctionsListOut(list_id=list_id, description=description, entries=len(names))
        for list_id, (description, names) in SANCTIONS_LISTS.items()
    ]
