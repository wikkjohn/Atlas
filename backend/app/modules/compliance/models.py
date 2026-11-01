"""Compliance (Phase 45, roadmap Milestone D step 17): AML transaction monitoring, alerts,
investigation cases, suspicious activity reports and periodic KYC reviews.

A monitoring run reads customer accounts' ledger activity over a window and raises an alert
for each rule an account breaks. Alerts are dismissed, or investigated in a case. A case is
closed with no action (by someone other than the investigator) or escalated: a suspicious
activity report is drafted and filed with the (synthetic) financial intelligence unit by a
second compliance officer. KYC reviews fall due by risk rating.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

RUN_SEQUENCE = Sequence("monitoring_run_number_seq", start=1)
ALERT_SEQUENCE = Sequence("aml_alert_number_seq", start=1)
CASE_SEQUENCE = Sequence("compliance_case_number_seq", start=1)
SAR_SEQUENCE = Sequence("sar_number_seq", start=1)
REVIEW_SEQUENCE = Sequence("kyc_review_number_seq", start=1)

RULES = ("large_cash", "structuring", "rapid_movement", "high_risk_turnover")


class MonitoringRun(UUIDPrimaryKey, Base):
    __tablename__ = "monitoring_runs"

    run_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    accounts_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_raised: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertStatus(StrEnum):
    OPEN = "open"
    IN_CASE = "in_case"  # being investigated
    DISMISSED = "dismissed"  # a false positive, closed without a case
    CLOSED = "closed"  # its case closed with no action
    ESCALATED = "escalated"  # its case led to a suspicious activity report


class AmlAlert(UUIDPrimaryKey, Base):
    __tablename__ = "aml_alerts"
    __table_args__ = (
        CheckConstraint(
            "rule IN ('large_cash', 'structuring', 'rapid_movement', 'high_risk_turnover')",
            name="rule_valid",
        ),
        CheckConstraint(
            "status IN ('open', 'in_case', 'dismissed', 'closed', 'escalated')",
            name="status_valid",
        ),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        UniqueConstraint("account_id", "rule", "window_end", name="uq_aml_alerts_window"),
    )

    alert_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("monitoring_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rule: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # the activity flagged
    # What the rule saw: the transactions, totals and the threshold.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("compliance_cases.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CaseStatus(StrEnum):
    INVESTIGATING = "investigating"
    SAR_DRAFTED = "sar_drafted"
    SAR_FILED = "sar_filed"
    CLOSED = "closed"  # no action


class ComplianceCase(UUIDPrimaryKey, Base):
    __tablename__ = "compliance_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('investigating', 'sar_drafted', 'sar_filed', 'closed')",
            name="status_valid",
        ),
        CheckConstraint("closed_by IS NULL OR closed_by <> opened_by", name="four_eyes"),
        # One case under way per customer.
        Index(
            "uq_compliance_cases_open",
            "customer_id",
            unique=True,
            postgresql_where=text("status IN ('investigating', 'sar_drafted')"),
        ),
    )

    case_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    opened_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SarStatus(StrEnum):
    DRAFT = "draft"
    FILED = "filed"


class SuspiciousActivityReport(UUIDPrimaryKey, Base):
    __tablename__ = "suspicious_activity_reports"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'filed')", name="status_valid"),
        CheckConstraint("filed_by IS NULL OR filed_by <> prepared_by", name="four_eyes"),
        UniqueConstraint("case_id", name="uq_sar_case"),
    )

    sar_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("compliance_cases.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    prepared_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    filed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    filing_reference: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewStatus(StrEnum):
    DUE = "due"
    COMPLETED = "completed"


class KycReview(UUIDPrimaryKey, Base):
    """A periodic KYC review. At most one is due per customer at a time."""

    __tablename__ = "kyc_reviews"
    __table_args__ = (
        CheckConstraint("status IN ('due', 'completed')", name="status_valid"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('confirmed', 'raised', 'lowered')",
            name="outcome_valid",
        ),
        Index(
            "uq_kyc_reviews_due",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'due'"),
        ),
    )

    review_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    due_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    risk_before: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_after: Mapped[str | None] = mapped_column(String(20), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    completed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
