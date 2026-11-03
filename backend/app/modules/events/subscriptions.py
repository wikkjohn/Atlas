"""Every department's subscriptions, imported once by the outbox (see `outbox._load`)."""

from app.modules.access import subscribers as access  # noqa: F401
from app.modules.hr import subscribers as hr  # noqa: F401
from app.modules.workflows import wf0004  # noqa: F401  (collections: lending.arrears_changed)
