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
        "available",
        "Global → regional → country → division → department → team hierarchy.",
    ),
    ModuleInfo(
        "countries",
        "Countries",
        2,
        "available",
        "Country configuration registry: currency, timezone, languages, status.",
    ),
    ModuleInfo(
        "employees",
        "Employees",
        2,
        "available",
        "Synthetic workforce registry with reporting relationships.",
    ),
    ModuleInfo(
        "identity",
        "Identity & access",
        2,
        "available",
        "Authentication, roles and backend-enforced permissions.",
    ),
    ModuleInfo("audit", "Audit", 2, "available", "Append-only audit events with correlation IDs."),
    ModuleInfo(
        "customers",
        "Customers",
        3,
        "available",
        "Synthetic individual and business customers with KYC status.",
    ),
    ModuleInfo(
        "accounts", "Accounts", 3, "available", "Bank accounts opened only by an approved request."
    ),
    ModuleInfo(
        "ledger", "Ledger", 3, "available", "Double-entry general ledger in integer minor units."
    ),
    ModuleInfo(
        "workflows",
        "Workflow engine",
        4,
        "available",
        "Durable, database-backed workflow execution (WF-0001 Retail Account Opening).",
    ),
    ModuleInfo(
        "compliance",
        "Compliance",
        4,
        "available",
        "Compliance rule evaluation and human review routing (inside WF-0001).",
    ),
    ModuleInfo(
        "simulation",
        "Simulation engine",
        5,
        "available",
        "Simulation clock, scenarios, seeded synthetic data and run registry.",
    ),
    ModuleInfo(
        "ai_tools",
        "AI Innovation Lab",
        6,
        "available",
        "Provider-independent AI tool registry, adapters and A/B/C experiments.",
    ),
    ModuleInfo(
        "experiments",
        "Experiments & benchmarking",
        7,
        "available",
        "Baseline vs. candidate evaluation with transparent cost assumptions and reports.",
    ),
    ModuleInfo(
        "analytics",
        "Analytics",
        8,
        "available",
        "Operational metrics backing the enterprise dashboard.",
    ),
)
