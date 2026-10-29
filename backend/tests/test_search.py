"""Phase 13: searches rewritten for scale still find the same things."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ledger import service as ledger
from app.modules.ledger.models import LedgerAccountType
from tests.factories import auth, funded_account, make_staff, make_user


def test_account_search_matches_number_or_customer_name(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    first = funded_account(db, staff, name="Ottilie Zabriskie")
    second = funded_account(db, staff, name="Bram Quennell")
    headers = auth(staff.manager)

    def numbers(q: str) -> set[str]:
        body = client.get("/api/v1/accounts", params={"q": q, "limit": 100}, headers=headers).json()
        return {a["account_number"] for a in body["items"]}

    assert numbers("zabrisk") == {first.account_number}  # name, case-insensitive
    assert numbers(second.account_number[4:12]) >= {second.account_number}  # part of number
    assert numbers("no-such-customer") == set()
    listing = client.get("/api/v1/accounts", params={"limit": 2}, headers=headers).json()
    assert len(listing["items"]) == 2 and listing["total"] >= 2


def test_ledger_accounts_filter_by_code_prefix(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.AUDITOR))
    ledger.cash_account(db, "USD")
    ledger.ensure_ledger_account(
        db,
        code="1000_X-USD",  # "_" is a LIKE wildcard: the prefix must match it literally
        name="Lookalike",
        account_type=LedgerAccountType.ASSET,
        currency="USD",
    )

    def codes(prefix: str) -> set[str]:
        return {
            a["code"]
            for a in client.get(
                "/api/v1/ledger/accounts", params={"code_prefix": prefix}, headers=headers
            ).json()["items"]
        }

    cash = codes("1000-")
    assert "1000-USD" in cash and all(code.startswith("1000-") for code in cash)
    # Unescaped, "1000_" would also match every "1000-" code.
    assert codes("1000_") == {"1000_X-USD"}
