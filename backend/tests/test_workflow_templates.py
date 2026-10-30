"""Phase 19: parameterised workflow templates and the deterministic variant generator."""

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.customers.models import Customer
from app.modules.ledger import service as ledger
from app.modules.workflows import authoring, engine, examples, templates, validation
from app.modules.workflows.models import DefinitionStatus, WorkflowStepRun, WorkflowVariant
from app.modules.workflows.templates import RenderError, TemplateDocument
from tests.factories import auth, funded_account, make_staff, make_user, principal

FIXED = {"fee": 5, "approval_permission": "accounts:manage", "screen_customers": True}


def template_document(template_id: str = "TPL-TEST-STATEMENT", version: int = 1) -> dict:
    found = examples.templates()[0]  # v1, without a catalogue
    doc = copy.deepcopy(found)
    doc.update(template_id=template_id, version=version, id_range=[7000, 7009])
    return doc


def steps_of(definition: dict) -> dict[str, dict]:
    return {s["id"]: s for s in definition["steps"]}


def codes(report) -> set[tuple[str, str]]:
    return {(e["location"], e["code"]) for e in report.errors}


@pytest.fixture
def admin(db: Session):
    return make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)


@pytest.fixture
def template(db: Session, admin):
    templates.import_template(db, template_document(), admin.id)
    return TemplateDocument.model_validate(template_document())


# --- Rendering --------------------------------------------------------------------------------


def test_rendering_types_text_country_data_and_minor_units(db: Session, template) -> None:
    params = {"country_code": "GB", "account_type": "savings", **FIXED}
    gb = templates.render(db, template, params, workflow_id="WF-7000", version=1)
    by_id = steps_of(gb)
    assert gb["name"] == "Paper Statements — United Kingdom, savings accounts"
    assert by_id["charge_fee"]["params"]["amount"] == 500  # 5 GBP, typed as a number
    assert by_id["charge_fee"]["name"] == "Charge the paper-statement fee (5 GBP)"
    assert by_id["fee_approval"]["approval"]["permissions"] == ["accounts:manage"]
    assert gb["origin"] == {
        "template_id": "TPL-TEST-STATEMENT",
        "template_version": 1,
        "variant_key": templates.variant_key(params),
    }
    jp = templates.render(
        db, template, {**params, "country_code": "JP"}, workflow_id="WF-7001", version=1
    )
    assert steps_of(jp)["charge_fee"]["params"]["amount"] == 5  # JPY has no minor units

    # Leaving the optional screening out routes around all three of its steps.
    plain = templates.render(
        db, template, {**params, "screen_customers": False}, workflow_id="WF-7002", version=1
    )
    plain_steps = steps_of(plain)
    assert not {"screen", "screen_route", "compliance_review"} & set(plain_steps)
    assert plain_steps["check_product"]["next"] == "route_delivery"
    assert validation.validate(db, plain, versions=False, generated=True).valid


def test_render_errors_are_located(db: Session, template) -> None:
    broken = template.model_copy(deep=True)
    steps_of(broken.body)["screen"]["$include"] = "yes"
    with pytest.raises(RenderError, match=r"\$include must be a boolean"):
        templates.render(
            db,
            broken,
            {"country_code": "GB", "account_type": "current", **FIXED},
            workflow_id="WF-7000",
            version=1,
        )
    with pytest.raises(RenderError, match="Unknown country 'ZZ'"):
        templates.render(
            db,
            template,
            {"country_code": "ZZ", "account_type": "current", **FIXED},
            workflow_id="WF-7000",
            version=1,
        )
    optional = template.model_copy(deep=True)
    del steps_of(optional.body)["screen"]["next"]
    with pytest.raises(RenderError, match="needs a `next`"):
        templates.render(
            db,
            optional,
            {"country_code": "GB", "account_type": "current", **FIXED, "screen_customers": False},
            workflow_id="WF-7000",
            version=1,
        )


# --- Template validation and import -------------------------------------------------------------


def test_the_example_template_is_valid_and_clean(db: Session) -> None:
    report = templates.validate_template(db, examples.templates()[0])
    assert report.valid and report.warnings == [], report.errors
    assert report.preview["workflow_id"] == "WF-2000"


def test_template_validation_reports_every_problem(db: Session) -> None:
    doc = template_document()
    doc["parameters"]["properties"]["unused"] = {"type": "string"}
    doc["body"]["description"] += " {{nope}} {{country.flag}}"
    doc["body"]["workflow_id"] = "WF-7000"
    doc["example"]["fee"] = "five"
    report = templates.validate_template(db, doc)
    assert codes(report) >= {
        ("body", "unknown_parameter"),
        ("body", "unknown_country_field"),
        ("body.workflow_id", "reserved"),
        ("example", "invalid_example"),
    }
    assert ("parameters", "unused_parameter") in {
        (w["location"], w["code"]) for w in report.warnings
    }

    # The example rendered must pass full definition validation, e.g. money behind approval.
    unsafe = template_document()
    steps_of(unsafe["body"])["route_delivery"]["next"] = "charge_fee"
    found = templates.validate_template(db, unsafe)
    assert ("example → steps.charge_fee", "approval_required") in codes(found)

    shape = template_document()
    shape["id_range"] = [10, 20]
    assert not templates.validate_template(db, shape).valid


def test_template_versions_are_immutable_and_increasing(db: Session, admin) -> None:
    record, created, _ = templates.import_template(db, template_document(), admin.id)
    assert created and record.status == "active"
    again, created, _ = templates.import_template(db, template_document(), admin.id)
    assert (again.id, created) == (record.id, False)
    changed = template_document()
    changed["description"] = "Edited"
    with pytest.raises(templates.TemplateInvalid) as refused:
        templates.import_template(db, changed, admin.id)
    assert refused.value.details["errors"][0]["code"] == "version_exists"
    templates.import_template(db, template_document(version=3), admin.id)
    with pytest.raises(templates.TemplateInvalid) as refused:
        templates.import_template(db, template_document(version=2), admin.id)
    assert refused.value.details["errors"][0]["code"] == "version_not_increasing"


# --- Generation -------------------------------------------------------------------------------


def _grid(countries=("GB", "US"), products=("current", "savings")) -> list[dict]:
    return templates.expand(
        {"country_code": list(countries), "account_type": list(products)}, None, FIXED
    )


def test_generation_is_deterministic_idempotent_and_versioned(db: Session, admin, template) -> None:
    first = templates.generate(db, "TPL-TEST-STATEMENT", _grid(), admin.id)
    assert [(r.workflow_id, r.status, r.version) for r in first.results] == [
        ("WF-7000", "created", 1),
        ("WF-7001", "created", 1),
        ("WF-7002", "created", 1),
        ("WF-7003", "created", 1),
    ]
    # Ids follow the variant keys' order, whatever order the sets were given in.
    assert [r.params["country_code"] + r.params["account_type"] for r in first.results] == [
        "GBcurrent",
        "UScurrent",
        "GBsavings",
        "USsavings",
    ]
    again = templates.generate(db, "TPL-TEST-STATEMENT", list(reversed(_grid())), admin.id)
    assert {r.status for r in again.results} == {"unchanged"}
    assert [r.workflow_id for r in again.results] == ["WF-7000", "WF-7001", "WF-7002", "WF-7003"]

    # A changed template publishes new versions of the same workflows.
    v2 = template_document(version=2)
    v2["body"]["business_owner"] = "Retail Operations ({{country.code}})"
    templates.import_template(db, v2, admin.id)
    updated = templates.generate(db, "TPL-TEST-STATEMENT", _grid(), admin.id)
    assert [(r.workflow_id, r.status, r.version) for r in updated.results] == [
        ("WF-7000", "updated", 2),
        ("WF-7001", "updated", 2),
        ("WF-7002", "updated", 2),
        ("WF-7003", "updated", 2),
    ]
    # A new parameter set takes the next free id; one held by another workflow is skipped.
    other = authoring.import_definition(
        db, {**examples.documents()[0], "workflow_id": "WF-7004"}, admin.id
    )[0]
    assert other.workflow_id == "WF-7004"
    more = templates.generate(db, "TPL-TEST-STATEMENT", _grid(("GB", "US", "DE")), admin.id)
    assert [(r.workflow_id, r.status) for r in more.results if r.status == "created"] == [
        ("WF-7005", "created"),
        ("WF-7006", "created"),
    ]
    rows = db.execute(
        select(
            WorkflowVariant.workflow_id,
            WorkflowVariant.template_version,
            WorkflowVariant.definition_version,
        )
        .where(WorkflowVariant.template_id == "TPL-TEST-STATEMENT")
        .order_by(WorkflowVariant.workflow_id)
    ).all()
    assert rows[0] == ("WF-7000", 2, 2) and len(rows) == 6


def test_generation_is_all_or_nothing_and_respects_limits(db: Session, admin, template) -> None:
    sets = _grid() + [{"country_code": "GB", "account_type": "loan", **FIXED}]
    report = templates.generate(db, "TPL-TEST-STATEMENT", sets, admin.id)
    assert not report.valid and report.count("invalid") == 1
    assert db.execute(select(WorkflowVariant)).scalars().first() is None  # nothing stored

    dry = templates.generate(db, "TPL-TEST-STATEMENT", _grid(), admin.id, dry_run=True)
    assert dry.count("created") == 4
    assert db.execute(select(WorkflowVariant)).scalars().first() is None

    eleven = templates.expand(
        {"fee": list(range(1, 12))},
        None,
        {**FIXED, "country_code": "GB", "account_type": "current"},
    )
    full = templates.generate(db, "TPL-TEST-STATEMENT", eleven, admin.id)  # range of 10 ids
    assert [r.errors[0]["code"] for r in full.results if r.status == "invalid"] == ["range_full"]
    with pytest.raises(BusinessRuleViolation, match="At most 3"):
        templates.generate(db, "TPL-TEST-STATEMENT", _grid(), admin.id, limit=3)
    templates.set_status(db, "TPL-TEST-STATEMENT", 1, DefinitionStatus.RETIRED, admin.id)
    with pytest.raises(ConflictError, match="retired"):
        templates.generate(db, "TPL-TEST-STATEMENT", _grid(), admin.id, version=1)


def test_variants_are_changed_only_by_regenerating(db: Session, admin, template) -> None:
    templates.generate(db, "TPL-TEST-STATEMENT", _grid(), admin.id)
    exported = authoring.export(db, "WF-7000")
    by_hand = {**exported, "version": 2}
    by_hand.pop("origin")
    with pytest.raises(authoring.DefinitionInvalid) as refused:
        authoring.import_definition(db, by_hand, admin.id)
    assert refused.value.details["errors"][0]["code"] == "owned_by_template"
    forged = {**examples.documents()[0], "workflow_id": "WF-7900", "origin": exported["origin"]}
    with pytest.raises(authoring.DefinitionInvalid) as refused:
        authoring.import_definition(db, forged, admin.id)
    assert refused.value.details["errors"][0]["code"] == "origin_reserved"


def test_a_generated_variant_charges_its_country_s_fee(db: Session, admin, template) -> None:
    staff = make_staff(db)
    templates.generate(db, "TPL-TEST-STATEMENT", _grid(("GB",), ("current",)), admin.id)
    account = funded_account(db, staff, balance=10_000, country_code="GB")
    customer = db.get(Customer, account.customer_id)
    request = {
        "customer_number": customer.customer_number,
        "account_number": account.account_number,
        "months": 2,
        "delivery": "post",
    }
    execution, _ = engine.start(
        db, workflow_id="WF-7000", payload=request, initiator=principal(staff.employee)
    )
    assert execution.current_steps == ["fee_approval"]
    db.flush()
    task = db.execute(
        select(WorkflowStepRun).where(
            WorkflowStepRun.execution_id == execution.id, WorkflowStepRun.status == "waiting"
        )
    ).scalar_one()
    engine.complete_task(db, task.id, principal(staff.manager), decision="approve")
    assert execution.outcome == "sent"
    assert execution.context["charge_fee"]["amount"] == 500
    balance = ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))
    assert balance == 9_500

    # The same request against the US variant's product check is refused: wrong country.
    templates.generate(db, "TPL-TEST-STATEMENT", _grid(("US",), ("current",)), admin.id)
    refused, _ = engine.start(
        db, workflow_id="WF-7001", payload=request, initiator=principal(staff.employee)
    )
    assert (refused.outcome, refused.context["_failure"]["code"]) == ("refused", "wrong_product")


def test_the_templates_api(client: TestClient, db: Session) -> None:
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    employee = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    body = {"template": template_document()}
    assert client.post("/api/v1/workflow-templates", json=body, headers=employee).status_code == 403
    report = client.post("/api/v1/workflow-templates/validate", json=body, headers=admin).json()
    assert (report["valid"], report["existing"]) == (True, "new")
    assert report["preview"]["workflow_id"] == "WF-7000"
    assert client.post("/api/v1/workflow-templates", json=body, headers=admin).status_code == 201
    assert client.post("/api/v1/workflow-templates", json=body, headers=admin).status_code == 200

    params = {"country_code": "SG", "account_type": "current", **FIXED}
    rendered = client.post(
        "/api/v1/workflow-templates/TPL-TEST-STATEMENT/render",
        json={"params": params},
        headers=employee,
    ).json()
    assert rendered["report"]["valid"] and rendered["definition"]["name"].endswith(
        "Singapore, current accounts"
    )
    bad = client.post(
        "/api/v1/workflow-templates/TPL-TEST-STATEMENT/render",
        json={"params": {**params, "fee": 0}},
        headers=employee,
    ).json()
    assert bad["definition"] is None and bad["report"]["errors"][0]["code"] == "invalid_params"

    spec = {"grid": {"country_code": ["SG", "GB"]}, "fixed": {**FIXED, "account_type": "current"}}
    dry = client.post(
        "/api/v1/workflow-templates/TPL-TEST-STATEMENT/generate",
        json={**spec, "dry_run": True},
        headers=admin,
    ).json()
    assert (dry["stored"], dry["created"]) == (False, 2)
    done = client.post(
        "/api/v1/workflow-templates/TPL-TEST-STATEMENT/generate", json=spec, headers=admin
    ).json()
    assert (done["stored"], done["created"]) == (True, 2)
    variants = client.get(
        "/api/v1/workflow-templates/TPL-TEST-STATEMENT/variants", headers=employee
    ).json()
    assert [v["workflow_id"] for v in variants] == ["WF-7000", "WF-7001"]
    listed = client.get("/api/v1/workflows?template_id=TPL-TEST-STATEMENT", headers=employee).json()
    assert [w["workflow_id"] for w in listed] == ["WF-7000", "WF-7001"]
    assert (
        client.get("/api/v1/workflows?source=stored&limit=1", headers=employee).json()[0]["source"]
        == "stored"
    )
    detail = client.get("/api/v1/workflows/WF-7000", headers=employee).json()
    assert detail["origin"]["template_id"] == "TPL-TEST-STATEMENT"
    assert detail["template_id"] == "TPL-TEST-STATEMENT"
    listed_templates = client.get("/api/v1/workflow-templates", headers=employee).json()
    mine = [t for t in listed_templates if t["template_id"] == "TPL-TEST-STATEMENT"]
    assert mine[0]["variants"] == 2 and mine[0]["id_range"] == [7000, 7009]
    retired = client.post(
        "/api/v1/workflow-templates/TPL-TEST-STATEMENT/versions/1/retire", headers=admin
    ).json()
    assert retired["status"] == "retired"
    assert (
        client.post(
            "/api/v1/workflow-templates/TPL-TEST-STATEMENT/generate", json=spec, headers=admin
        ).status_code
        == 404
    )
