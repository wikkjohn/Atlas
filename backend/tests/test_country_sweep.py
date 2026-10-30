"""Phase 28: cases that follow each country's rules, and the 120-country sweep."""

from datetime import date

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.compliance.screening import SANCTIONS_LISTS, normalize
from app.modules.countries.models import Country
from app.modules.organizations import blueprint
from app.modules.organizations.models import Organization
from app.simulation.generators import ApplicationGenerator
from app.simulation.models import SimulationCaseResult, SimulationRun
from app.simulation.runner import SimulationSetupError, create_run
from app.simulation.scenarios import ScenarioConfig, get_scenario
from app.simulation.sweep import case_kinds, report, sweep
from tests.factories import make_org_tree, make_user

TODAY = date(2026, 3, 2)
STRICT = {
    "min_age": 21,
    "identity_documents": ["passport"],
    "proof_of_address": False,
    "lists": ["synthetic-un-v1"],
    "high_value_major": 1000,
    "max_payment_major": 100_000,
}


def _age(born: date) -> int:
    return TODAY.year - born.year - ((TODAY.month, TODAY.day) < (born.month, born.day))


def test_applications_follow_their_countrys_rules() -> None:
    mix = {"clean": 1, "underage": 1, "missing_documents": 1, "sanctions_hit": 1}
    generator = ApplicationGenerator(
        seed=7,
        mix=mix,
        countries=["XX"],
        arrival_window_seconds=3600,
        document_delay_seconds=(60, 120),
        today=TODAY,
        rules={"XX": STRICT},
    )
    apps = generator.generate(200)
    assert {a.kind for a in apps} == set(mix)
    un_names = SANCTIONS_LISTS["synthetic-un-v1"][1]
    for app in apps:
        payload = app.payload
        age = _age(date.fromisoformat(payload["date_of_birth"]))
        documents = payload["documents"] + [d for d in [payload["_late_document"]] if d]
        identity = [d for d in documents if d["document_type"] != "proof_of_address"]
        assert [d["document_type"] for d in identity] == ["passport"]
        if app.kind == "underage":
            assert 17 <= age < 21  # three years below at most, by year of birth
        else:
            assert age >= 21
        if app.kind == "missing_documents":
            # Without a proof-of-address rule, the identity document is the late one.
            assert payload["_late_document"]["document_type"] == "passport"
        if app.kind == "sanctions_hit":
            assert normalize(payload["applicant_name"]) in un_names


def test_scenarios_without_country_rules_keep_their_configuration() -> None:
    # Existing scenarios hash the same: the new field is left out when unset.
    assert "country_rules" not in ScenarioConfig().model_dump(exclude_none=True)
    for scenario_id in ("retail-onboarding", "domestic-payments"):
        assert get_scenario(scenario_id).config.country_rules is None
    assert get_scenario("global-onboarding").config.country_rules is True
    reviewers = get_scenario("global-payments").config.reviewers
    assert {r.accuracy for r in reviewers.values()} == {1.0}


@pytest.fixture
def factory(db_connection: Connection):
    def make() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return make


def _launch(db: Session, *codes: str) -> None:
    for code in codes:
        country = db.execute(select(Country).where(Country.iso_country_code == code)).scalar_one()
        blueprint.launch_country(db, country, None, staff=False)


def test_runs_limited_to_countries_snapshot_their_rules(db: Session) -> None:
    make_org_tree(db)
    _launch(db, "SA")
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    with pytest.raises(SimulationSetupError, match="Not active countries: KE"):
        create_run(
            db,
            get_scenario("global-onboarding"),
            profile="custom",
            applications=5,
            employees=6,
            seed=1,
            created_by=creator.id,
            countries=["KE"],
        )
    run = create_run(
        db,
        get_scenario("global-onboarding"),
        profile="custom",
        applications=5,
        employees=6,
        seed=1,
        created_by=creator.id,
        countries=["SA"],
    )
    dataset = run.config["dataset"]
    assert dataset["countries"] == ["SA"] and dataset["staff_country"] == "SA"
    assert dataset["rules"]["SA"]["min_age"] == 18
    assert dataset["rules"]["SA"]["lists"] == ["synthetic-un-v1", "synthetic-watchlist-v1"]


def test_the_sweep_passes_in_operating_and_launched_countries(db: Session, factory) -> None:
    make_org_tree(db)
    _launch(db, "KE", "SA")
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    db.commit()

    results = sweep(factory, created_by=creator.id, countries=["JP", "KE", "SA"], cases=16)
    summary = report(results)
    assert summary["runs"] == 6 and summary["failed"] == [], summary["failed"]
    assert summary["passed"] == 6 and summary["cases"] == 96

    db.expire_all()
    for result in results:
        # Every kind of the scenario's mix occurs, as `case_kinds` predicted from the seed.
        scenario = get_scenario(result.scenario)
        assert set(result.kinds) == set(scenario.config.mix)
        predicted = case_kinds(scenario, result.seed, result.cases)
        assert {k: predicted.count(k) for k in set(predicted)} == result.kinds
        run = db.execute(
            select(SimulationRun).where(SimulationRun.run_number == result.run_number)
        ).scalar_one()
        # Staff work in the country's own subsidiary.
        team = db.execute(
            select(Organization).where(Organization.name == f"Simulation run {run.run_number}")
        ).scalar_one()
        country = db.get(Country, team.country_id)
        assert country.iso_country_code == result.country
        if result.scenario == "global-payments":
            paths = db.execute(
                select(SimulationCaseResult.kind, SimulationCaseResult.path).where(
                    SimulationCaseResult.run_id == run.id
                )
            ).all()
            for kind, path in paths:
                # High-value payments, on the country's scale, need a manager's approval.
                if kind == "high_value":
                    assert "payment_approval" in path, (result.country, path)
                elif kind == "routine":
                    assert "payment_approval" not in path, (result.country, path)


def test_the_api_starts_a_run_in_one_country_and_reruns_it_there(app, db: Session, factory) -> None:
    from fastapi.testclient import TestClient

    from app.simulation.router import get_simulation_sessionmaker
    from tests.factories import auth

    make_org_tree(db)
    researcher = auth(make_user(db, RoleCode.AI_RESEARCHER))
    db.commit()
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        body = {
            "scenario_id": "global-payments",
            "profile": "custom",
            "applications": 6,
            "employees": 6,
            "seed": 3,
            "country": "JP",
        }
        started = client.post("/api/v1/simulations", json=body, headers=researcher)
        assert started.status_code == 202, started.text
        dataset = started.json()["config"]["dataset"]
        assert dataset["countries"] == ["JP"] and dataset["rules"]["JP"]["high_value_major"]
        again = client.post(f"/api/v1/simulations/{started.json()['id']}/rerun", headers=researcher)
        assert again.status_code == 202, again.text
        assert again.json()["config"]["dataset"] == dataset
        refused = client.post(
            "/api/v1/simulations", json={**body, "country": "KE"}, headers=researcher
        )
        assert refused.status_code == 422 and "Not active countries: KE" in refused.text
