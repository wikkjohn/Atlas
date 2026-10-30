"""Phase 22: the workflow catalogue (classification, ownership, search with facets) and the
review lifecycle of stored versions (draft → in review → active → retired, four-eyes)."""

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, PermissionDeniedError
from app.core.permissions import ROLE_PERMISSIONS, Permission, RoleCode
from app.modules.workflows import authoring, examples, service, templates, testing
from app.modules.workflows.definition import Catalogue
from app.modules.workflows.models import DefinitionStatus, WorkflowCatalogueEntry
from tests.factories import auth, make_user
from tests.test_stored_definitions import document

FIXED = {"fee": 5, "approval_permission": "accounts:manage", "screen_customers": True}


@pytest.fixture
def author(db: Session):
    return make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)


@pytest.fixture
def reviewer(db: Session):
    return make_user(db, RoleCode.DEPARTMENT_MANAGER)


def classified(workflow_id: str = "WF-1911", version: int = 1, **catalogue) -> dict:
    doc = document(workflow_id, version)
    doc["catalogue"] = {
        "department": "Customer Onboarding",
        "countries": ["GB", "DE"],
        "products": ["current"],
        "tags": ["kyc"],
        **catalogue,
    }
    return doc


def entry(db: Session, workflow_id: str) -> WorkflowCatalogueEntry | None:
    return db.execute(
        select(WorkflowCatalogueEntry).where(WorkflowCatalogueEntry.workflow_id == workflow_id)
    ).scalar_one_or_none()


# --- Lifecycle --------------------------------------------------------------------------------


def test_review_takes_a_draft_to_active_under_four_eyes_and_passing_tests(
    db: Session, author, reviewer
) -> None:
    record, _, _ = authoring.import_definition(
        db, classified(), author.id, status=DefinitionStatus.DRAFT
    )
    assert record.status == "draft"
    # A draft cannot be approved before it is submitted, nor started.
    with pytest.raises(ConflictError):
        authoring.approve(db, "WF-1911", 1, reviewer.id)
    authoring.submit(db, "WF-1911", 1, author.id)
    assert record.status == "in_review" and record.submitted_by == author.id

    with pytest.raises(PermissionDeniedError) as four_eyes:
        authoring.approve(db, "WF-1911", 1, author.id)
    assert four_eyes.value.details == {"rule": "four_eyes"}
    with pytest.raises(ConflictError) as untested:
        authoring.approve(db, "WF-1911", 1, reviewer.id)
    assert untested.value.details == {"rule": "tests_must_pass"}

    # Generated tests run on a version in review (they may start inactive versions).
    _, run = testing.run_stored(db, "WF-1911", 1, author.id)
    assert run.failed == 0 and run.passed > 0
    authoring.approve(db, "WF-1911", 1, reviewer.id, "Looks right.")
    assert (record.status, record.reviewed_by, record.review_note) == (
        "active",
        reviewer.id,
        "Looks right.",
    )
    # Its classification applies; its first classifier owns the workflow.
    found = entry(db, "WF-1911")
    assert found is not None
    assert (found.department, found.countries, found.owner_id) == (
        "Customer Onboarding",
        ["DE", "GB"],
        author.id,
    )
    authoring.set_status(db, "WF-1911", 1, DefinitionStatus.RETIRED, reviewer.id)
    assert record.status == "retired"
    with pytest.raises(ConflictError):
        authoring.submit(db, "WF-1911", 1, author.id)


def test_a_returned_version_goes_back_to_draft_with_the_reviewers_note(
    db: Session, author, reviewer
) -> None:
    record, _, _ = authoring.import_definition(
        db, classified("WF-1912"), author.id, status=DefinitionStatus.DRAFT
    )
    authoring.submit(db, "WF-1912", 1, author.id)
    authoring.reject(db, "WF-1912", 1, reviewer.id, "Screen the customer first.")
    assert (record.status, record.review_note) == ("draft", "Screen the customer first.")
    # Resubmitting clears the previous review.
    authoring.submit(db, "WF-1912", 1, author.id)
    assert (record.status, record.review_note, record.reviewed_by) == ("in_review", None, None)
    # Only active and retired versions are retired or reactivated directly.
    with pytest.raises(ConflictError):
        authoring.set_status(db, "WF-1912", 1, DefinitionStatus.ACTIVE, author.id)


def test_a_draft_does_not_reclassify_an_active_workflow(db: Session, author, reviewer) -> None:
    authoring.import_definition(db, classified("WF-1913"), author.id)  # published
    authoring.import_definition(
        db,
        classified("WF-1913", 2, department="Branch Network"),
        author.id,
        status=DefinitionStatus.DRAFT,
    )
    assert entry(db, "WF-1913").department == "Customer Onboarding"
    authoring.submit(db, "WF-1913", 2, author.id)
    testing.run_stored(db, "WF-1913", 2, author.id)
    authoring.approve(db, "WF-1913", 2, reviewer.id)
    assert entry(db, "WF-1913").department == "Branch Network"


def test_department_managers_author_and_review_workflows() -> None:
    assert Permission.WORKFLOWS_DEFINE in ROLE_PERMISSIONS[RoleCode.DEPARTMENT_MANAGER]
    assert Permission.WORKFLOWS_DEFINE not in ROLE_PERMISSIONS[RoleCode.BANKING_EMPLOYEE]


# --- Validation -------------------------------------------------------------------------------


def test_catalogue_countries_must_exist_and_odd_departments_are_flagged(db: Session) -> None:
    report = authoring.validate(db, classified(countries=["GB", "ZZ"], department="Narnia"))
    assert [(e["location"], e["code"]) for e in report.errors] == [
        ("catalogue.countries[1]", "unknown_country")
    ]
    assert ("catalogue.department", "unknown_department") in {
        (w["location"], w["code"]) for w in report.warnings
    }
    malformed = authoring.validate(db, classified(countries=["gb"], products=["Current"]))
    assert {e["location"] for e in malformed.errors} == {
        "catalogue.countries[0]",
        "catalogue.products[0]",
    }


def test_a_catalogue_does_not_change_the_hash_of_definitions_without_one() -> None:
    plain = document("WF-1914")
    from app.modules.workflows.definition import WorkflowDefinition

    without = WorkflowDefinition.model_validate(plain)
    assert "catalogue" not in without.canonical_json()
    with_one = WorkflowDefinition.model_validate(classified("WF-1914"))
    assert with_one.content_hash() != without.content_hash()


# --- Search -----------------------------------------------------------------------------------


def test_code_workflows_are_classified_and_searchable(db: Session) -> None:
    lending = service.search_catalogue(db, filters={"department": "Lending"}, limit=500)
    assert {w.workflow_id for w in lending.items} >= {"WF-0003"}
    assert all(w.department == "Lending" for w in lending.items)
    by_product = service.search_catalogue(db, filters={"product": "personal_loan"}, limit=500)
    assert {"WF-0003", "WF-0004"} <= {w.workflow_id for w in by_product.items}
    text = service.search_catalogue(db, "underwriting", limit=500)
    assert "WF-0003" in {w.workflow_id for w in text.items}


def test_facets_count_what_each_choice_would_give(db: Session, author) -> None:
    template = copy.deepcopy(examples.templates()[-1])  # v2 classifies its variants
    assert template["version"] == 2 and "catalogue" in template["body"]
    template.update(template_id="TPL-TEST-CATALOGUE", version=1, id_range=[7200, 7209])
    templates.import_template(db, template, author.id)
    grid = templates.expand(
        {"country_code": ["DE", "GB", "JP"], "account_type": ["current", "savings"]},
        None,
        FIXED,
    )
    templates.generate(db, "TPL-TEST-CATALOGUE", grid, author.id)

    found = service.search_catalogue(
        db, template_id="TPL-TEST-CATALOGUE", filters={"country": "GB"}
    )
    assert found.total == 2
    assert {(w.countries[0], w.products[0]) for w in found.items} == {
        ("GB", "current"),
        ("GB", "savings"),
    }
    assert all(w.department == "Branch Network" for w in found.items)
    facets = {k: {f.value: f.count for f in v} for k, v in found.facets.items()}
    # The country facet ignores the country filter; the others apply it.
    assert facets["country"] == {"DE": 2, "GB": 2, "JP": 2}
    assert facets["product"] == {"current": 1, "savings": 1}
    assert facets["owner"] == {author.username: 2}

    both = service.search_catalogue(
        db,
        template_id="TPL-TEST-CATALOGUE",
        filters={"country": "JP", "product": "savings", "status": "active"},
    )
    assert [(w.countries, w.products) for w in both.items] == [(["JP"], ["savings"])]
    paged = service.search_catalogue(db, template_id="TPL-TEST-CATALOGUE", limit=4, offset=4)
    assert (paged.total, len(paged.items)) == (6, 2)


# --- API --------------------------------------------------------------------------------------


def test_the_catalogue_and_review_api(client: TestClient, db: Session, author, reviewer) -> None:
    writer, checker = auth(author), auth(reviewer)
    employee = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    created = client.post(
        "/api/v1/workflow-definitions", json={"definition": classified("WF-1915")}, headers=writer
    )
    assert created.status_code == 201 and created.json()["definition"]["status"] == "draft"
    base = "/api/v1/workflow-definitions/WF-1915/versions/1"
    assert client.post(f"{base}/submit", headers=employee).status_code == 403
    submitted = client.post(f"{base}/submit", headers=writer).json()
    assert (submitted["status"], submitted["submitted_by_username"]) == (
        "in_review",
        author.username,
    )
    listed = client.get(
        "/api/v1/workflow-catalogue", params={"q": "WF-1915"}, headers=employee
    ).json()
    assert listed["total"] == 1
    assert (listed["items"][0]["status"], listed["items"][0]["in_review"]) == ("in_review", True)

    returned = client.post(f"{base}/return", json={"note": ""}, headers=checker)
    assert returned.status_code == 422  # a return says what to change
    self_approval = client.post(f"{base}/approve", json={}, headers=writer)
    assert self_approval.status_code == 403
    assert self_approval.json()["error"]["details"] == {"rule": "four_eyes"}
    assert client.post(f"{base}/tests", headers=writer).json()["failed"] == 0
    approved = client.post(f"{base}/approve", json={"note": "Fine."}, headers=checker).json()
    assert (approved["status"], approved["reviewed_by_username"], approved["review_note"]) == (
        "active",
        reviewer.username,
        "Fine.",
    )

    search = client.get(
        "/api/v1/workflow-catalogue",
        params={"department": "Customer Onboarding", "country": "DE", "status": "active"},
        headers=employee,
    ).json()
    assert "WF-1915" in {w["workflow_id"] for w in search["items"]}
    assert set(search["facets"]) == {
        "department",
        "country",
        "product",
        "tag",
        "status",
        "source",
        "owner",
    }

    body = {"department": "Branch Network", "countries": ["JP"], "products": ["savings"],
            "tags": ["statements"], "owner_id": str(reviewer.id)}  # fmt: skip
    assert client.put("/api/v1/workflow-catalogue/WF-1915", json=body,
                      headers=employee).status_code == 403  # fmt: skip
    bad = client.put("/api/v1/workflow-catalogue/WF-1915",
                     json={**body, "countries": ["ZZ"]}, headers=writer)  # fmt: skip
    assert bad.status_code == 400 and bad.json()["error"]["details"] == {"countries": ["ZZ"]}
    assert client.put("/api/v1/workflow-catalogue/WF-9999", json=body,
                      headers=writer).status_code == 404  # fmt: skip
    updated = client.put("/api/v1/workflow-catalogue/WF-1915", json=body, headers=writer).json()
    assert (updated["department"], updated["countries"], updated["owner_username"]) == (
        "Branch Network",
        ["JP"],
        reviewer.username,
    )
    detail = client.get("/api/v1/workflows/WF-1915", headers=employee).json()
    assert (detail["department"], detail["owner_username"]) == ("Branch Network", reviewer.username)


def test_the_seed_classification_of_the_examples_is_valid(db: Session) -> None:
    documents = {d["workflow_id"] for d in examples.documents()}
    for workflow_id, catalogue in examples.EXAMPLE_CATALOGUE.items():
        assert workflow_id in documents
        report = authoring.validate(
            db, {**document("WF-1916"), "catalogue": Catalogue(**catalogue).model_dump()}
        )
        assert report.errors == [] and report.warnings == []
