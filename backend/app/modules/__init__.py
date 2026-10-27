"""Banking and platform modules.

Each sub-package is a bounded module of the modular monolith. Modules talk to each other
through their service interfaces, never by reaching into another module's tables.

`MODULE_REGISTRY` is the single source of truth for which modules exist and which
implementation phase delivers them. It is exposed by `GET /api/system/info`.
"""

from dataclasses import asdict, dataclass
from typing import Literal

ModuleStatus = Literal["available", "planned"]


@dataclass(frozen=True)
class ModuleInfo:
    key: str
    name: str
    phase: int
    status: ModuleStatus
    description: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


MODULE_REGISTRY: tuple[ModuleInfo, ...] = (
    ModuleInfo(
        "platform",
        "Platform core",
        1,
        "available",
        "Configuration, database, migrations, health checks, logging, correlation IDs.",
    ),
    ModuleInfo(
        "organizations",
        "Organizations",
        2,
        "planned",
        "Global → regional → country → division → department → team hierarchy.",
    ),
    ModuleInfo(
        "countries",
        "Countries",
        2,
        "planned",
        "Country configuration registry: currency, timezone, languages, status.",
    ),
    ModuleInfo(
        "employees",
        "Employees",
        2,
        "planned",
        "Synthetic workforce registry with reporting relationships.",
    ),
    ModuleInfo(
        "identity",
        "Identity & access",
        2,
        "planned",
        "Authentication, roles and backend-enforced permissions.",
    ),
    ModuleInfo("audit", "Audit", 2, "planned", "Append-only audit events with correlation IDs."),
    ModuleInfo(
        "customers",
        "Customers",
        3,
        "planned",
        "Synthetic individual and business customers with KYC status.",
    ),
    ModuleInfo(
        "accounts", "Accounts", 3, "planned", "Bank accounts opened only after workflow approval."
    ),
    ModuleInfo(
        "ledger", "Ledger", 3, "planned", "Double-entry general ledger in integer minor units."
    ),
    ModuleInfo(
        "workflows",
        "Workflow engine",
        4,
        "planned",
        "Durable, database-backed workflow execution (WF-0001 Retail Account Opening).",
    ),
    ModuleInfo(
        "compliance",
        "Compliance",
        4,
        "planned",
        "Compliance rule evaluation and human review routing.",
    ),
    ModuleInfo(
        "simulation",
        "Simulation engine",
        5,
        "planned",
        "Simulation clock, scenarios, seeded synthetic data and run registry.",
    ),
    ModuleInfo(
        "ai_tools",
        "AI Innovation Lab",
        6,
        "planned",
        "Provider-independent AI tool registry and adapters.",
    ),
    ModuleInfo(
        "experiments",
        "Experiments & benchmarking",
        7,
        "planned",
        "Baseline vs. candidate comparison with transparent cost assumptions.",
    ),
    ModuleInfo(
        "analytics",
        "Analytics",
        8,
        "planned",
        "Operational metrics backing the enterprise dashboard.",
    ),
)
