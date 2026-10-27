from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money import minor_unit_exponent, to_minor_units
from app.modules.employees.models import Employee
from app.modules.identity.models import User
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

    again = seed_demo(db, "demo-password-123", seed=99)

    assert again.skipped_structure and again.users == [] and again.employees == 0
    assert db.execute(select(func.count()).select_from(Organization)).scalar_one() == 64
