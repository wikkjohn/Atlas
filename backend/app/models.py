"""Imports every model so `Base.metadata` is complete (for Alembic and tests)."""

from app.core import audit, idempotency, system  # noqa: F401
from app.modules.accounts import models as accounts  # noqa: F401
from app.modules.countries import models as countries  # noqa: F401
from app.modules.customers import models as customers  # noqa: F401
from app.modules.employees import models as employees  # noqa: F401
from app.modules.identity import models as identity  # noqa: F401
from app.modules.ledger import models as ledger  # noqa: F401
from app.modules.organizations import models as organizations  # noqa: F401
from app.modules.workflows import models as workflows  # noqa: F401
