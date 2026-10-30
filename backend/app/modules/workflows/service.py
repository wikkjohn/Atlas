"""Read models for the workflow API: definitions, executions, history, tasks, metrics."""

import uuid

from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.workflows import graph, library, registry, store, templates, validation
from app.modules.workflows.definition import Catalogue, StepType, WorkflowDefinition
from app.modules.workflows.engine import check_task_access
from app.modules.workflows.models import (
    STEP_RUN_EXECUTION,
    DefinitionSource,
    DefinitionStatus,
    Realm,
    RunStatus,
    WorkflowCatalogueEntry,
    WorkflowDefinitionRecord,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowStepRun,
    WorkflowTemplateRecord,
    WorkflowTestRun,
    WorkflowVariant,
)
from app.modules.workflows.schemas import (
    CatalogueFacet,
    CatalogueIn,
    CatalogueOut,
    DraftPreview,
    ExecutionDetail,
    ExecutionSummary,
    GenerationOut,
    LibraryHandlerOut,
    RenderOut,
    StepMetric,
    StepRunOut,
    StoredDefinitionOut,
    TaskOut,
    TemplateDetail,
    TemplateOut,
    TemplateReportOut,
    TestRunOut,
    TestSummary,
    ValidationReportOut,
    VariantOut,
    VariantResultOut,
    WorkflowDefinitionOut,
    WorkflowEventOut,
    WorkflowMetrics,
    WorkflowSummary,
)


def summary(
    definition: WorkflowDefinition,
    versions: list[int],
    source: str = "code",
    status: str = "active",
) -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id=definition.workflow_id,
        name=definition.name,
        version=definition.version,
        versions=versions,
        description=definition.description,
        business_owner=definition.business_owner,
        trigger_type=definition.trigger_type,
        step_count=len(definition.steps),
        source=source,
        status=status,
        template_id=definition.origin.template_id if definition.origin else None,
    )


def _catalogue(db: Session) -> dict[str, WorkflowSummary]:
    """Each workflow's latest active version (else its latest) as a summary, classified.
    Stored ones are summarised in SQL from their JSON, without loading or parsing whole
    definitions (thousands of generated variants are listed this way)."""
    found: dict[str, WorkflowSummary] = {}
    for definition in registry.all_definitions():  # sorted by version, so last wins
        previous = found.get(definition.workflow_id)
        versions = [*(previous.versions if previous else []), definition.version]
        found[definition.workflow_id] = summary(definition, versions)
    d = WorkflowDefinitionRecord.definition
    rows = db.execute(
        select(
            WorkflowDefinitionRecord.workflow_id,
            WorkflowDefinitionRecord.version,
            WorkflowDefinitionRecord.status,
            WorkflowDefinitionRecord.name,
            d["description"].astext,
            d["business_owner"].astext,
            d["trigger_type"].astext,
            func.jsonb_array_length(d["steps"]),
            d["origin"]["template_id"].astext,
        )
        .where(WorkflowDefinitionRecord.source == DefinitionSource.STORED)
        .order_by(WorkflowDefinitionRecord.workflow_id, WorkflowDefinitionRecord.version)
    ).all()
    by_workflow: dict[str, list] = {}
    for row in rows:
        by_workflow.setdefault(row[0], []).append(row)
    for workflow_id, versions in by_workflow.items():
        active = [r for r in versions if r[2] == DefinitionStatus.ACTIVE]
        shown = (active or versions)[-1]
        found[workflow_id] = WorkflowSummary(
            workflow_id=workflow_id,
            name=shown[3],
            version=shown[1],
            versions=[r[1] for r in versions],
            description=shown[4] or "",
            business_owner=shown[5] or "",
            trigger_type=shown[6] or "api",
            step_count=shown[7] or 0,
            source="stored",
            status=shown[2],
            template_id=shown[8],
            in_review=any(r[2] == DefinitionStatus.IN_REVIEW for r in versions),
        )
    entries = {e.workflow_id: e for e in db.execute(select(WorkflowCatalogueEntry)).scalars()}
    names = _usernames(db, {e.owner_id for e in entries.values()})
    for workflow_id, item in found.items():
        _apply_catalogue(item, entries.get(workflow_id), names)
    return dict(sorted(found.items()))


def _apply_catalogue(
    item: WorkflowSummary, entry: WorkflowCatalogueEntry | None, names: dict[uuid.UUID, str]
) -> None:
    """A stored classification, else the one registered in code, else none."""
    found = entry or registry.catalogue_of(item.workflow_id)
    if found is None:
        return
    item.department, item.countries = found.department, list(found.countries)
    item.products, item.tags = list(found.products), list(found.tags)
    if entry is not None and entry.owner_id is not None:
        item.owner_id, item.owner_username = entry.owner_id, names.get(entry.owner_id)


def _classify(db: Session, item: WorkflowSummary) -> None:
    entry = db.execute(
        select(WorkflowCatalogueEntry).where(WorkflowCatalogueEntry.workflow_id == item.workflow_id)
    ).scalar_one_or_none()
    _apply_catalogue(item, entry, _usernames(db, {entry.owner_id if entry else None}))


CATALOGUE_FACETS = ("department", "country", "product", "tag", "status", "source", "owner")


def _facet_values(w: WorkflowSummary, facet: str) -> list[str]:
    match facet:
        case "department":
            return [w.department] if w.department else []
        case "country":
            return w.countries
        case "product":
            return w.products
        case "tag":
            return w.tags
        case "status":
            return [w.status, *(["in_review"] if w.in_review and w.status != "in_review" else [])]
        case "source":
            return [w.source]
        case "owner":
            return [w.owner_username] if w.owner_username else []
    return []


def _matches_text(w: WorkflowSummary, needle: str) -> bool:
    return (
        needle
        in (
            f"{w.workflow_id} {w.name} {w.description} {w.business_owner} {w.template_id or ''} "
            f"{w.department or ''} {' '.join(w.products)} {' '.join(w.tags)}"
        ).casefold()
    )


def search_catalogue(
    db: Session,
    q: str | None = None,
    *,
    filters: dict[str, str | None] | None = None,
    template_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CatalogueOut:
    """Search the catalogue: free text plus one value per facet (department, country,
    product, tag, status, source, owner), with counts for every facet's values."""
    chosen = {k: v for k, v in (filters or {}).items() if v}
    base = list(_catalogue(db).values())
    if template_id:
        base = [w for w in base if w.template_id == template_id]
    if q:
        needle = q.casefold()
        base = [w for w in base if _matches_text(w, needle)]

    def keep(w: WorkflowSummary, skip: str | None = None) -> bool:
        return all(
            v.casefold() in (x.casefold() for x in _facet_values(w, k))
            for k, v in chosen.items()
            if k != skip
        )

    items = [w for w in base if keep(w)]
    facets: dict[str, list[CatalogueFacet]] = {}
    for facet in CATALOGUE_FACETS:
        counts: dict[str, int] = {}
        for w in base:
            if keep(w, facet):
                for value in set(_facet_values(w, facet)):
                    counts[value] = counts.get(value, 0) + 1
        facets[facet] = [
            CatalogueFacet(value=v, count=n)
            for v, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
    return CatalogueOut(items=items[offset : offset + limit], total=len(items), facets=facets)


def list_workflows(
    db: Session,
    q: str | None = None,
    *,
    source: str | None = None,
    template_id: str | None = None,
    limit: int | None = None,
) -> list[WorkflowSummary]:
    items = list(_catalogue(db).values())
    if source:
        items = [w for w in items if w.source == source]
    if template_id:
        items = [w for w in items if w.template_id == template_id]
    if q:
        needle = q.casefold()
        items = [w for w in items if _matches_text(w, needle)]
    return items[:limit] if limit else items


def get_definition(db: Session, workflow_id: str, version: int | None = None) -> WorkflowDefinition:
    definition = store.resolve(db, workflow_id, version)
    if definition is None:
        raise NotFoundError(f"Workflow {workflow_id} is not registered.")
    return definition


def definition_out(db: Session, definition: WorkflowDefinition) -> WorkflowDefinitionOut:
    if store.is_code(definition.workflow_id):
        versions = [d.version for d in registry.all_definitions()
                    if d.workflow_id == definition.workflow_id]  # fmt: skip
        source, status = "code", "active"
    else:
        rows = db.execute(
            select(WorkflowDefinitionRecord.version, WorkflowDefinitionRecord.status)
            .where(
                WorkflowDefinitionRecord.workflow_id == definition.workflow_id,
                WorkflowDefinitionRecord.source == DefinitionSource.STORED,
            )
            .order_by(WorkflowDefinitionRecord.version)
        ).all()
        versions = [v for v, _ in rows]
        source, status = "stored", dict(rows).get(definition.version, "active")
    shown = summary(definition, versions, source, status)
    _classify(db, shown)
    if source == "stored":
        shown.in_review = DefinitionStatus.IN_REVIEW in {s for _, s in rows}
    return WorkflowDefinitionOut(
        **shown.model_dump(),
        origin=definition.origin.model_dump() if definition.origin else None,
        last_test=last_test(db, definition.workflow_id, definition.version)
        if source == "stored"
        else None,
        start=definition.start,
        input_schema=definition.input_schema,
        presentation=(
            definition.presentation.model_dump(exclude_none=True)
            if definition.presentation
            else None
        ),
        steps=[s.model_dump(mode="json", exclude_none=True) for s in definition.steps],
        transition_rules=definition.transition_rules(),
        approval_policies=definition.approval_policies(),
        failure_policies=definition.failure_policies(),
        timeout_policies=definition.timeout_policies(),
    )


def _usernames(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.username).where(User.id.in_(ids))).all())


def _summary(db: Session, e: WorkflowExecution, names: dict[uuid.UUID, str]) -> ExecutionSummary:
    duration = (
        int((e.completed_at - e.started_at).total_seconds() * 1000) if e.completed_at else None
    )
    return ExecutionSummary(
        id=e.id,
        workflow_id=e.workflow_id,
        workflow_version=e.workflow_version,
        status=e.status,
        outcome=e.outcome,
        current_steps=e.current_steps,
        business_key=e.business_key,
        subject=store.present(db, e)["subject"],
        initiated_by=e.initiated_by,
        initiated_by_username=names.get(e.initiated_by),
        correlation_id=e.correlation_id,
        started_at=e.started_at,
        completed_at=e.completed_at,
        duration_ms=duration,
        simulation_run_id=e.simulation_run_id,
    )


def list_executions(
    db: Session,
    params: PageParams,
    *,
    workflow_id: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
    business_key: str | None = None,
    simulation_run_id: uuid.UUID | None = None,
) -> tuple[list[ExecutionSummary], int]:
    query = select(WorkflowExecution).order_by(
        WorkflowExecution.started_at.desc(), WorkflowExecution.id
    )
    # Simulated executions are listed only for their own run.
    query = query.where(
        and_(
            WorkflowExecution.realm == Realm.SIMULATION,
            WorkflowExecution.simulation_run_id == simulation_run_id,
        )
        if simulation_run_id
        else WorkflowExecution.realm == Realm.LIVE
    )
    if workflow_id:
        query = query.where(WorkflowExecution.workflow_id == workflow_id)
    if status:
        query = query.where(WorkflowExecution.status == status)
    if outcome:
        query = query.where(WorkflowExecution.outcome == outcome)
    if business_key:
        query = query.where(WorkflowExecution.business_key == business_key)
    items, total = paginate(db, query, params)
    names = _usernames(db, {e.initiated_by for e in items})
    return [_summary(db, e, names) for e in items], total


def get_execution(db: Session, execution_id: uuid.UUID) -> WorkflowExecution:
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None:
        raise NotFoundError("Workflow execution not found.")
    return execution


def _step_name(db: Session, execution: WorkflowExecution, step_id: str) -> str:
    definition = store.for_execution(db, execution)
    try:
        return definition.step(step_id).name if definition else step_id
    except KeyError:
        return step_id


def execution_detail(db: Session, execution: WorkflowExecution) -> ExecutionDetail:
    runs = list(
        db.execute(
            select(WorkflowStepRun)
            .where(WorkflowStepRun.execution_id == execution.id)
            .order_by(WorkflowStepRun.sequence)
        ).scalars()
    )
    names = _usernames(db, {execution.initiated_by} | {r.actor_id for r in runs})
    return ExecutionDetail(
        **_summary(db, execution, names).model_dump(),
        context=execution.context,
        error=execution.error,
        steps=[
            StepRunOut(
                id=r.id,
                sequence=r.sequence,
                step_id=r.step_id,
                step_name=_step_name(db, execution, r.step_id),
                step_type=r.step_type,
                status=r.status,
                branch=r.branch,
                attempt=r.attempt,
                required_permissions=r.required_permissions,
                actor_id=r.actor_id,
                actor_username=names.get(r.actor_id) if r.actor_id else None,
                output=r.output,
                error=r.error,
                created_at=r.created_at,
                started_at=r.started_at,
                completed_at=r.completed_at,
                duration_ms=r.duration_ms,
                not_before=r.not_before,
                due_at=r.due_at,
                escalated_at=r.escalated_at,
            )
            for r in runs
        ],
    )


def history(db: Session, execution_id: uuid.UUID) -> list[WorkflowEventOut]:
    events = db.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.execution_id == execution_id)
        .order_by(WorkflowEvent.seq)
    ).scalars()
    return [
        WorkflowEventOut(
            id=e.id,
            event_type=e.event_type,
            occurred_at=e.occurred_at,
            step_run_id=e.step_run_id,
            actor_id=e.actor_id,
            data=e.data,
        )
        for e in events
    ]


def open_tasks(
    db: Session, user: AuthenticatedUser, params: PageParams, *, actionable_only: bool
) -> tuple[list[TaskOut], int]:
    """Open human tasks and approvals, each marked with whether `user` may act on it."""
    rows = db.execute(
        select(WorkflowStepRun, WorkflowExecution)
        .join(WorkflowExecution, STEP_RUN_EXECUTION)
        .where(
            WorkflowStepRun.status == RunStatus.WAITING,
            WorkflowStepRun.step_type.in_([StepType.APPROVAL, StepType.HUMAN_TASK]),
            WorkflowExecution.realm == Realm.LIVE,
        )
        .order_by(WorkflowStepRun.due_at.asc().nullslast(), WorkflowStepRun.created_at)
    ).all()
    names = _usernames(db, {e.initiated_by for _, e in rows})
    tasks: list[TaskOut] = []
    for run, execution in rows:
        definition = store.for_execution(db, execution)
        if definition is None:
            continue
        step = definition.step(run.step_id)
        blocked = None
        try:
            check_task_access(db, execution, step, user)
        except DomainError as exc:
            blocked = exc.message
        if actionable_only and blocked:
            continue
        shown = store.present(db, execution)
        tasks.append(
            TaskOut(
                run_id=run.id,
                execution_id=execution.id,
                workflow_id=execution.workflow_id,
                step_id=run.step_id,
                step_name=step.name,
                step_type=run.step_type,
                opened_at=run.started_at,
                due_at=run.due_at,
                overdue=run.escalated_at is not None,
                required_permissions=run.required_permissions,
                can_act=blocked is None,
                blocked_reason=blocked,
                subject=shown["subject"],
                risk_rating=shown["risk_rating"],
                flags=shown["flags"],
                initiated_by_username=names.get(execution.initiated_by),
            )
        )
    total = len(tasks)
    return tasks[params.offset : params.offset + params.limit], total


def metrics(db: Session, workflow_id: str) -> WorkflowMetrics:
    """Throughput, durations and failures per step: where cases slow down or break."""
    definition = get_definition(db, workflow_id)
    statuses = dict(
        db.execute(
            select(WorkflowExecution.status, func.count())
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.realm == Realm.LIVE,
            )
            .group_by(WorkflowExecution.status)
        ).all()
    )
    outcomes = dict(
        db.execute(
            select(WorkflowExecution.outcome, func.count())
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.realm == Realm.LIVE,
                WorkflowExecution.outcome.is_not(None),
            )
            .group_by(WorkflowExecution.outcome)
        ).all()
    )
    avg_execution = db.execute(
        select(
            func.avg(
                func.extract("epoch", WorkflowExecution.completed_at - WorkflowExecution.started_at)
                * 1000
            )
        ).where(
            WorkflowExecution.workflow_id == workflow_id,
            WorkflowExecution.realm == Realm.LIVE,
            WorkflowExecution.completed_at.is_not(None),
        )
    ).scalar_one()
    rows = {
        row.step_id: row
        for row in db.execute(
            select(
                WorkflowStepRun.step_id,
                func.count().label("runs"),
                func.count()
                .filter(WorkflowStepRun.status == RunStatus.COMPLETED)
                .label("completed"),
                func.count().filter(WorkflowStepRun.status == RunStatus.FAILED).label("failed"),
                func.count()
                .filter(WorkflowStepRun.status.in_([RunStatus.PENDING, RunStatus.WAITING]))
                .label("open"),
                func.coalesce(func.sum(func.greatest(WorkflowStepRun.attempt - 1, 0)), 0).label(
                    "retries"
                ),
                func.avg(WorkflowStepRun.duration_ms).label("avg_ms"),
                func.percentile_cont(0.5).within_group(WorkflowStepRun.duration_ms).label("p50"),
                func.percentile_cont(0.95).within_group(WorkflowStepRun.duration_ms).label("p95"),
                func.max(WorkflowStepRun.duration_ms).label("max_ms"),
            )
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.realm == Realm.LIVE,
            )
            .group_by(WorkflowStepRun.step_id)
        ).all()
    }
    steps = []
    for step in definition.steps:
        row = rows.get(step.id)
        steps.append(
            StepMetric(
                step_id=step.id,
                step_name=step.name,
                step_type=step.type.value,
                runs=row.runs if row else 0,
                completed=row.completed if row else 0,
                failed=row.failed if row else 0,
                open=row.open if row else 0,
                retries=int(row.retries) if row else 0,
                avg_ms=float(row.avg_ms) if row and row.avg_ms is not None else None,
                p50_ms=float(row.p50) if row and row.p50 is not None else None,
                p95_ms=float(row.p95) if row and row.p95 is not None else None,
                max_ms=row.max_ms if row else None,
            )
        )
    measured = [s for s in steps if s.p95_ms is not None]
    bottleneck = max(measured, key=lambda s: s.p95_ms or 0).step_id if measured else None
    return WorkflowMetrics(
        workflow_id=workflow_id,
        executions={str(k): v for k, v in statuses.items()},
        outcomes={str(k): v for k, v in outcomes.items()},
        avg_execution_ms=float(avg_execution) if avg_execution is not None else None,
        bottleneck_step=bottleneck,
        steps=steps,
    )


def stored_definition_out(
    db: Session, record: WorkflowDefinitionRecord, names: dict[uuid.UUID, str] | None = None
) -> StoredDefinitionOut:
    people = {record.imported_by, record.submitted_by, record.reviewed_by}
    names = names if names is not None else _usernames(db, people)
    executions = db.execute(
        select(func.count()).where(WorkflowExecution.definition_id == record.id)
    ).scalar_one()
    return StoredDefinitionOut(
        id=record.id,
        workflow_id=record.workflow_id,
        version=record.version,
        name=record.name,
        status=record.status,
        content_hash=record.content_hash,
        step_count=len(record.definition.get("steps", [])),
        imported_by=record.imported_by,
        imported_by_username=names.get(record.imported_by) if record.imported_by else None,
        imported_at=record.registered_at,
        status_changed_at=record.status_changed_at,
        executions=executions,
        submitted_by_username=names.get(record.submitted_by) if record.submitted_by else None,
        submitted_at=record.submitted_at,
        reviewed_by_username=names.get(record.reviewed_by) if record.reviewed_by else None,
        reviewed_at=record.reviewed_at,
        review_note=record.review_note,
    )


def stored_definitions(db: Session, workflow_id: str | None = None) -> list[StoredDefinitionOut]:
    records = store.stored_records(db, workflow_id)
    names = _usernames(
        db, {p for r in records for p in (r.imported_by, r.submitted_by, r.reviewed_by)}
    )
    return [stored_definition_out(db, r, names) for r in records]


def library_handlers() -> list[LibraryHandlerOut]:
    return [
        LibraryHandlerOut(
            name=h.name,
            step_type=h.step_type.value,
            summary=h.summary,
            output=h.output,
            effect=h.effect,
            requires_approval=h.requires_approval,
            params_schema=h.params_schema(),
        )
        for h in sorted(library.LIBRARY.values(), key=lambda h: h.name)
    ]


def report_out(report: validation.Report) -> ValidationReportOut:
    d = report.definition
    return ValidationReportOut(
        valid=report.valid,
        workflow_id=d.workflow_id if d else None,
        version=d.version if d else None,
        content_hash=d.content_hash() if d else None,
        existing=report.existing if report.valid else None,
        errors=report.errors,
        warnings=report.warnings,
        effects=report.effects,
    )


# --- Templates (Phase 19) --------------------------------------------------------------------


def template_out(
    db: Session, record: WorkflowTemplateRecord, detail: bool = False
) -> TemplateOut | TemplateDetail:
    document = record.document
    variants = db.execute(
        select(func.count()).where(WorkflowVariant.template_id == record.template_id)
    ).scalar_one()
    fields = dict(
        id=record.id,
        template_id=record.template_id,
        version=record.version,
        name=record.name,
        description=document["description"],
        status=record.status,
        content_hash=record.content_hash,
        id_range=tuple(document["id_range"]),
        parameters=document["parameters"],
        example=document["example"],
        imported_by_username=_usernames(db, {record.imported_by}).get(record.imported_by)
        if record.imported_by
        else None,
        imported_at=record.imported_at,
        variants=variants,
    )
    return TemplateDetail(**fields, body=document["body"]) if detail else TemplateOut(**fields)


def list_templates(db: Session) -> list[TemplateOut]:
    records = db.execute(
        select(WorkflowTemplateRecord).order_by(
            WorkflowTemplateRecord.template_id, WorkflowTemplateRecord.version
        )
    ).scalars()
    return [template_out(db, r) for r in records]


def template_report_out(report: templates.TemplateReport) -> TemplateReportOut:
    t = report.template
    return TemplateReportOut(
        valid=report.valid,
        template_id=t.template_id if t else None,
        version=t.version if t else None,
        existing=report.existing if report.valid else None,
        errors=report.errors,
        warnings=report.warnings,
        preview=report.preview,
    )


def generation_out(report: templates.GenerationReport) -> GenerationOut:
    return GenerationOut(
        template_id=report.template_id,
        template_version=report.template_version,
        dry_run=report.dry_run,
        stored=not report.dry_run and report.valid,
        created=report.count("created"),
        updated=report.count("updated"),
        unchanged=report.count("unchanged"),
        invalid=report.count("invalid"),
        results=[
            VariantResultOut(
                variant_key=r.variant_key,
                params=r.params,
                workflow_id=r.workflow_id,
                version=r.version,
                status=r.status,
                errors=r.errors,
            )
            for r in report.results
        ],
    )


def variants_out(db: Session, template_id: str) -> list[VariantOut]:
    rows = db.execute(
        select(WorkflowVariant)
        .where(WorkflowVariant.template_id == template_id)
        .order_by(WorkflowVariant.workflow_id)
    ).scalars()
    return [
        VariantOut(
            workflow_id=v.workflow_id,
            variant_key=v.variant_key,
            params=v.params,
            template_version=v.template_version,
            definition_version=v.definition_version,
            generated_at=v.generated_at,
        )
        for v in rows
    ]


def render_out(
    db: Session, template_id: str, params: dict, version: int | None = None
) -> RenderOut:
    """Preview one variant: the rendered definition and its validation report."""
    record = templates.template_record(db, template_id, version)
    template = templates.TemplateDocument.model_validate(record.document)
    errors = templates._params_errors(template, params)
    known = db.execute(
        select(WorkflowVariant.workflow_id).where(
            WorkflowVariant.template_id == template_id,
            WorkflowVariant.variant_key == templates.variant_key(params),
        )
    ).scalar_one_or_none()
    workflow_id = known or f"WF-{template.id_range[0]:04d}"
    if errors:
        report = validation.Report()
        for message in errors:
            report.error("params", "invalid_params", message)
        return RenderOut(definition=None, report=report_out(report))
    try:
        document = templates.render(db, template, params, workflow_id=workflow_id, version=1)
    except templates.RenderError as exc:
        report = validation.Report()
        report.error(exc.location, "render_error", exc.message)
        return RenderOut(definition=None, report=report_out(report))
    report = validation.validate(db, document, versions=False, generated=True)
    report.errors = [e for e in report.errors if e["code"] != "owned_by_template"]
    return RenderOut(definition=document, report=report_out(report))


# --- Generated tests (Phase 20) --------------------------------------------------------------


def test_run_out(db: Session, run: WorkflowTestRun) -> TestRunOut:
    return TestRunOut(
        id=run.id,
        workflow_id=run.workflow_id,
        version=run.version,
        passed=run.passed,
        failed=run.failed,
        skipped=sum(c.get("status") == "skipped" for c in run.cases),
        step_coverage=run.step_coverage,
        route_coverage=run.route_coverage,
        cases=run.cases,
        uncovered=run.uncovered,
        duration_ms=run.duration_ms,
        ran_at=run.ran_at,
        ran_by_username=_usernames(db, {run.ran_by}).get(run.ran_by) if run.ran_by else None,
    )


def test_runs(db: Session, workflow_id: str, limit: int = 20) -> list[TestRunOut]:
    runs = db.execute(
        select(WorkflowTestRun)
        .where(WorkflowTestRun.workflow_id == workflow_id)
        .order_by(WorkflowTestRun.ran_at.desc(), WorkflowTestRun.id)
        .limit(limit)
    ).scalars()
    return [test_run_out(db, r) for r in runs]


def last_test(db: Session, workflow_id: str, version: int) -> TestSummary | None:
    run = db.execute(
        select(WorkflowTestRun)
        .where(WorkflowTestRun.workflow_id == workflow_id, WorkflowTestRun.version == version)
        .order_by(WorkflowTestRun.ran_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    return TestSummary(
        passed=run.passed,
        failed=run.failed,
        step_coverage=run.step_coverage,
        route_coverage=run.route_coverage,
        ran_at=run.ran_at,
    )


# --- Graph (Phase 21) ------------------------------------------------------------------------


def graph_out(db: Session, workflow_id: str, version: int | None = None) -> graph.GraphOut:
    definition = get_definition(db, workflow_id, version)
    layout = graph.layout(definition)
    test_run = db.execute(
        select(WorkflowTestRun)
        .where(
            WorkflowTestRun.workflow_id == definition.workflow_id,
            WorkflowTestRun.version == definition.version,
        )
        .order_by(WorkflowTestRun.ran_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return graph.overlay(layout, metrics(db, definition.workflow_id), test_run)


def draft_preview(db: Session, document: dict) -> DraftPreview:
    report = validation.validate(db, document)
    drawn = None
    if report.definition is not None:
        ids = {s.id for s in report.definition.steps}
        if report.definition.start in ids:
            drawn = graph.layout(report.definition).model_dump(mode="json")
    return DraftPreview(report=report_out(report), graph=drawn)


# --- Catalogue (Phase 22) --------------------------------------------------------------------


def classify(
    db: Session, workflow_id: str, body: CatalogueIn, actor_id: uuid.UUID
) -> WorkflowSummary:
    """Set a workflow's classification and owner; countries and owner must exist."""
    from app.modules.countries.models import Country
    from app.modules.workflows import authoring

    if store.resolve(db, workflow_id) is None:
        raise NotFoundError(f"Workflow {workflow_id} is not registered.")
    try:
        catalogue = Catalogue.model_validate(body.model_dump(exclude={"owner_id"}))
    except ValidationError as exc:
        raise DomainError(
            "The classification is not valid.",
            {
                "errors": [
                    {"location": ".".join(map(str, e["loc"])), "message": e["msg"]}
                    for e in exc.errors()
                ]
            },  # fmt: skip
        ) from exc
    known = set(
        db.execute(
            select(Country.iso_country_code).where(
                Country.iso_country_code.in_(catalogue.countries)
            )
        ).scalars()
    )
    if missing := sorted(set(catalogue.countries) - known):
        raise DomainError(f"Unknown countries: {', '.join(missing)}.", {"countries": missing})
    if body.owner_id is not None:
        owner = db.get(User, body.owner_id)
        if owner is None or not owner.is_active:
            raise DomainError("The owner must be an active user.", {"owner_id": "unknown"})
    authoring.classify(db, workflow_id, catalogue, actor_id, owner_id=body.owner_id)
    return _catalogue(db)[workflow_id]
