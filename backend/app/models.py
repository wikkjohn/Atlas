"""Imports every model so `Base.metadata` is complete (for Alembic and tests)."""

from app.core import audit, idempotency, system  # noqa: F401
from app.jobs import models as jobs  # noqa: F401
from app.modules.accounts import models as accounts  # noqa: F401
from app.modules.ai_tools import models as ai_tools  # noqa: F401
from app.modules.cards import models as cards  # noqa: F401
from app.modules.clearing import models as clearing  # noqa: F401
from app.modules.commercial import models as commercial  # noqa: F401
from app.modules.countries import models as countries  # noqa: F401
from app.modules.customers import models as customers  # noqa: F401
from app.modules.employees import models as employees  # noqa: F401
from app.modules.experiments import models as experiments  # noqa: F401
from app.modules.fx import models as fx  # noqa: F401
from app.modules.identity import models as identity  # noqa: F401
from app.modules.ledger import models as ledger  # noqa: F401
from app.modules.lending import models as lending  # noqa: F401
from app.modules.mortgages import models as mortgages  # noqa: F401
from app.modules.organizations import models as organizations  # noqa: F401
from app.modules.payments import models as payments  # noqa: F401
from app.modules.retail import models as retail  # noqa: F401
from app.modules.rules import models as rules  # noqa: F401
from app.modules.trade import models as trade  # noqa: F401
from app.modules.treasury import models as treasury  # noqa: F401
from app.modules.wealth import models as wealth  # noqa: F401
from app.modules.workflows import models as workflows
from app.observability import models as observability  # noqa: F401
from app.simulation import models as simulation  # noqa: F401

# Partitions (e.g. workflow_events_live) are created by migrations, not declared as models;
# schema comparisons (Alembic autogenerate, the migration test) leave them out.
PARTITIONS = frozenset(
    workflows.partition_name(table, realm)
    for table in workflows.PARTITIONED_TABLES
    for realm in workflows.Realm
)


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    return not (type_ == "table" and name in PARTITIONS)


def include_object(obj, name: str | None, type_: str, reflected: bool, compare_to) -> bool:
    # PostgreSQL reports a foreign key into a partitioned table once more per partition
    # (internal clones of the declared key); only the declared one is modelled.
    return not (
        type_ == "foreign_key_constraint" and reflected and obj.referred_table.name in PARTITIONS
    )


COMPARE_OPTIONS = {"include_name": include_name, "include_object": include_object}
