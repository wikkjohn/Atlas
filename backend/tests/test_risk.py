"""Phase 47: risk — credit ratings, obligor limits, exposure and ECL provisioning."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.customers.models import Customer
from app.modules.ledger import service as ledger
from app.modules.lending import servicing
from app.modules.lending.models import LoanStatus
from app.modules.risk import service as risk
from app.modules.risk.models import ProvisionLine
from tests.factories import auth, make_loan, make_staff, make_user, principal

ON = date(2040, 3, 25)  # two instalments missed: 44 days past due (see test_loan_servicing)


def _exposure(kind="loan", ead=1_000_000, dpd=0, years="2", frozen=False):
    import uuid

    return risk.Exposure(uuid.uuid4(), kind, "X", "GBP", ead, dpd, Decimal(years), frozen)


def test_stages_and_expected_credit_loss() -> None:
    # Stage 1: a year's PD (grade 4: 0.25 %) times LGD (unsecured 45 %).
    assert risk.ecl_of(_exposure(), 4) == (1, 25, 4_500, 1_125)
    # Stage 2 at 30 days past due: lifetime PD over the two remaining years.
    assert risk.ecl_of(_exposure(dpd=30), 4) == (2, 50, 4_500, 2_250)
    assert risk.ecl_of(_exposure(frozen=True, kind="facility"), 4)[0] == 2
    assert risk.ecl_of(_exposure(), 8)[0] == 2  # grade 8 or worse
    # Stage 3 at 90 days or in default: certain default.
    assert risk.ecl_of(_exposure(dpd=90), 4) == (3, 10_000, 4_500, 450_000)
    assert risk.ecl_of(_exposure(kind="mortgage", dpd=120), 4)[3] == 150_000  # LGD 15 %
    # Lifetime PD is capped at five years and at 100 %.
    assert risk.ecl_of(_exposure(dpd=45, years="30"), 7)[1] == 1_000


def test_ratings_follow_the_model_or_need_approval(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    customer = db.get(Customer, loan.customer_id)
    servicing.run(db, ON, principal(staff.manager))
    grade, factors = risk.suggest_grade(db, customer, ON)
    assert grade == 6 and factors["worst_days_past_due"] == 44  # low risk 4, +2 in arrears
    model = risk.rate(db, customer, None, staff.manager.id, today=ON)
    assert model.status == "approved" and model.grade == 6 and model.pd_bps == 100
    with pytest.raises(BusinessRuleViolation, match="Explain"):
        risk.rate(db, customer, 3, staff.manager.id, today=ON)
    departing = risk.rate(db, customer, 8, staff.manager.id, "Sector under stress", today=ON)
    assert departing.status == "pending"
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        risk.decide_rating(db, departing, staff.manager.id, approve=True)
    risk.decide_rating(db, departing, executive.id, approve=True)
    assert risk.grade_of(db, customer, ON) == 8
    with pytest.raises(ConflictError):
        risk.decide_rating(db, departing, executive.id, approve=False)


def test_limits_and_exposure(db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff, principal=600_000)  # 6,000.00 in the account's currency
    customer = db.get(Customer, loan.customer_id)
    view = risk.obligor(db, customer, ON)
    assert view["grade"] == 4 and view["limit_source"] == "grade"
    assert view["limit_usd"] == 10_000_000 and view["excess_usd"] == 0
    assert [e["type"] for e in view["exposures"]] == ["loan"]
    assert view["exposure_usd"] >= 6_000
    risk.set_limit(db, customer, 5_000, staff.admin.id, "Reduced")
    view = risk.obligor(db, customer, ON)
    assert view["limit_source"] == "set" and view["excess_usd"] == view["exposure_usd"] - 5_000
    assert customer.customer_number in [b["customer_number"] for b in risk.breaches(db, ON)]


def test_provision_runs_are_posted_by_a_second_person(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    servicing.run(db, ON, principal(staff.manager))  # 44 days past due: stage 2
    run = risk.calculate(db, staff.manager.id, today=ON)
    assert run.run_number.startswith("PRV-") and run.status == "calculated"
    line = db.execute(
        select(ProvisionLine).where(ProvisionLine.run_id == run.id,
                                    ProvisionLine.reference == loan.loan_number)
    ).scalar_one()  # fmt: skip
    assert line.stage == 2 and line.days_past_due == 44 and line.ecl > 0
    gbp = run.totals[loan.currency]
    assert gbp["stage_2"] >= line.ecl and gbp["change"] == gbp["ecl"] - gbp["previous"]
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        risk.post_run(db, run, staff.manager.id)
    risk.post_run(db, run, executive.id)
    assert run.status == "posted"
    allowance = ledger.balance(db, risk.allowance_account(db, loan.currency))
    assert allowance == gbp["ecl"]
    assert ledger.balance(db, risk.impairment_account(db, loan.currency)) == gbp["ecl"]
    # A second run with nothing changed posts nothing more; an older run is refused.
    again = risk.calculate(db, staff.manager.id, today=ON)
    assert again.totals[loan.currency]["change"] == 0
    old = risk.calculate(db, staff.manager.id, today=date(2040, 3, 1))
    risk.post_run(db, again, executive.id)
    with pytest.raises(BusinessRuleViolation, match="later provision run"):
        risk.post_run(db, old, executive.id)
    risk.reject_run(db, old, executive.id, "Superseded")
    assert old.status == "rejected"


def test_the_risk_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    customer = db.get(Customer, loan.customer_id)
    db.commit()
    teller, manager, boss = auth(staff.employee), auth(staff.manager), auth(executive)
    url = f"/api/v1/risk/obligors/{customer.customer_number}"
    assert client.get(url, headers=teller).status_code == 403
    assert client.get(url, headers=manager).json()["grade"] == 4
    body = {"customer_number": customer.customer_number, "grade": 7,
            "rationale": "Weak trading outlook"}  # fmt: skip
    rating = client.post("/api/v1/risk/ratings", json=body, headers=manager)
    assert rating.status_code == 201 and rating.json()["status"] == "pending"
    decide = f"/api/v1/risk/ratings/{rating.json()['id']}/approve"
    assert client.post(decide, headers=manager).status_code == 403
    assert client.post(decide, headers=boss).json()["status"] == "approved"
    limit = {"customer_number": customer.customer_number, "limit_usd": 1}
    assert client.put("/api/v1/risk/limits", json=limit, headers=manager).status_code == 403
    assert client.put("/api/v1/risk/limits", json=limit, headers=boss).json()["excess_usd"] > 0
    run = client.post("/api/v1/risk/provisions", headers=manager)
    assert run.status_code == 201 and run.json()["exposures"] >= 1
    lines = client.get(f"/api/v1/risk/provisions/{run.json()['id']}/lines", headers=boss)
    assert lines.json()["items"][0]["ecl"] >= lines.json()["items"][-1]["ecl"]
    posted = client.post(f"/api/v1/risk/provisions/{run.json()['id']}/post", headers=boss)
    assert posted.json()["status"] == "posted"
    counts = client.get("/api/v1/risk/summary/counts", headers=boss).json()
    assert counts["last_posted_run"] == run.json()["run_number"]


def test_postings_release_and_order_and_one_pending_rating(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    customer = db.get(Customer, loan.customer_id)
    # A second override while one waits is a conflict, not a database error.
    risk.rate(db, customer, 8, staff.manager.id, "Sector under stress", today=ON)
    with pytest.raises(ConflictError, match="already awaiting approval"):
        risk.rate(db, customer, 9, staff.manager.id, "Worse than that", today=ON)
    # Of two runs on the same day, the earlier cannot be posted after the later.
    first = risk.calculate(db, staff.manager.id, today=ON)
    second = risk.calculate(db, staff.manager.id, today=ON)
    risk.post_run(db, second, executive.id)
    with pytest.raises(BusinessRuleViolation, match="later provision run"):
        risk.post_run(db, first, executive.id)
    ccy = loan.currency
    line_ecl = db.execute(
        select(ProvisionLine.ecl).where(ProvisionLine.run_id == second.id,
                                        ProvisionLine.reference == loan.loan_number)
    ).scalar_one()  # fmt: skip
    assert line_ecl > 0
    # Once the exposure is gone, the next run measures it at zero and posting releases it.
    loan.status, loan.closed_at = LoanStatus.REPAID.value, datetime(2040, 3, 25, tzinfo=UTC)
    db.flush()
    after = risk.calculate(db, staff.manager.id, today=ON)
    assert after.totals[ccy]["ecl"] == second.totals[ccy]["ecl"] - line_ecl
    risk.post_run(db, after, executive.id)
    assert ledger.balance(db, risk.allowance_account(db, ccy)) == after.totals[ccy]["ecl"]
