from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money import minor_unit_exponent, to_minor_units
from app.modules.accounts.models import Account, AccountRequest
from app.modules.customers.models import Customer
from app.modules.employees.models import Employee
from app.modules.identity.models import User
from app.modules.ledger import service as ledger
from app.modules.organizations.models import Organization
from app.seed import DEMO_USERS, seed_demo
from app.simulation.generators import SyntheticNameGenerator


def test_name_generator_is_deterministic() -> None:
    a, b, c = SyntheticNameGenerator(7), SyntheticNameGenerator(7), SyntheticNameGenerator(8)

    run_a = [a.name() for _ in range(50)]
    assert run_a == [b.name() for _ in range(50)]
    assert run_a != [c.name() for _ in range(50)]


def test_currency_minor_units() -> None:
    assert minor_unit_exponent("USD") == 2
    assert minor_unit_exponent("jpy") == 0
    assert to_minor_units(85_000, "USD") == 8_500_000
    assert to_minor_units(9_000_000, "JPY") == 9_000_000
    assert to_minor_units(10, "KWD") == 10_000


def test_demo_seed_builds_a_consistent_bank_and_is_rerunnable(db: Session) -> None:
    report = seed_demo(db, "demo-password-123", seed=99)

    assert report.organizations == 64
    assert report.employees == 120
    assert sorted(report.users) == sorted(u for u, _, _ in DEMO_USERS)
    # Every employee's currency comes from their country; managers sit in the same country.
    for employee in db.execute(select(Employee)).scalars():
        assert employee.compensation_currency == employee.country.default_currency
        assert employee.email.endswith("@atlasbank.example")
        if employee.manager is not None:
            assert employee.manager.country_id == employee.country_id
    manager_user = db.execute(select(User).where(User.username == "manager")).scalar_one()
    assert manager_user.employee_id is not None

    # Banking activity: every account came from an approved request and the books balance.
    assert report.customers == 150
    assert report.accounts > 0 and report.pending_requests > 0
    accounts = db.execute(select(Account)).scalars().all()
    # Both the banking seed and approved WF-0001 cases open accounts.
    assert len(accounts) >= report.accounts
    for account in accounts:
        assert account.customer.kyc_status == "verified"
        assert account.currency == account.customer.country.default_currency
        assert ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id)) >= 0
    approved = db.execute(
        select(func.count()).where(AccountRequest.status == "approved")
    ).scalar_one()
    assert approved == len(accounts)  # every account came from an approved request
    assert ledger.reconcile(db, None).ok

    # WF-0001 demo cases ran through the real engine and ended in a mix of states.
    from app.modules.workflows.models import WorkflowExecution

    assert report.workflow_cases == 20
    states = Counter(
        (e.status, e.outcome or e.current_steps[0])
        for e in db.execute(select(WorkflowExecution)).scalars()
    )
    assert states[("completed", "approved")] > 0
    assert states[("completed", "rejected")] > 0
    assert states[("waiting", "await_documents")] > 0
    assert sum(n for (status, _), n in states.items() if status == "waiting") > 2
    assert ledger.reconcile(db, None).ok

    customers_before = db.execute(select(func.count()).select_from(Customer)).scalar_one()
    again = seed_demo(db, "demo-password-123", seed=99)

    assert again.skipped_structure and again.users == [] and again.employees == 0
    assert again.skipped_banking and again.customers == 0
    assert again.skipped_workflows and again.workflow_cases == 0
    assert db.execute(select(func.count()).select_from(Organization)).scalar_one() == 64
    assert db.execute(select(func.count()).select_from(Customer)).scalar_one() == customers_before
