import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.core.dependencies import DbSession
from app.core.idempotency import REPLAY_HEADER, IdempotencyKey
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized, CurrentUser
from app.modules.workflows import authoring, engine, service, templates, testing
from app.modules.workflows.graph import GraphOut
from app.modules.workflows.models import DefinitionStatus, ExecutionStatus
from app.modules.workflows.schemas import (
    CancelIn,
    DefinitionDocument,
    DraftPreview,
    ExecutionDetail,
    ExecutionSummary,
    GenerateIn,
    GenerationOut,
    ImportResult,
    LibraryHandlerOut,
    RenderIn,
    RenderOut,
    SignalIn,
    StartExecution,
    StoredDefinitionOut,
    TaskCompletion,
    TaskOut,
    TemplateDetail,
    TemplateDocumentIn,
    TemplateImportResult,
    TemplateOut,
    TemplateReportOut,
    TestRunOut,
    ValidationReportOut,
    VariantOut,
    WorkflowDefinitionOut,
    WorkflowEventOut,
    WorkflowMetrics,
    WorkflowSummary,
)

definitions_router = APIRouter(prefix="/workflows", tags=["workflows"])
authoring_router = APIRouter(prefix="/workflow-definitions", tags=["workflows"])
templates_router = APIRouter(prefix="/workflow-templates", tags=["workflows"])
executions_router = APIRouter(prefix="/workflow-executions", tags=["workflows"])
tasks_router = APIRouter(prefix="/workflow-tasks", tags=["workflows"])


# --- Definitions ---------------------------------------------------------------------------


@definitions_router.get("", response_model=list[WorkflowSummary], summary="Registered workflows")
def list_workflows(
    db: DbSession,
    _: Authorized(Permission.WORKFLOWS_READ),
    q: Annotated[str | None, Query(max_length=100)] = None,
    source: Annotated[Literal["code", "stored"] | None, Query()] = None,
    template_id: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int | None, Query(ge=1, le=10_000, description="At most this many")] = None,
) -> list[WorkflowSummary]:
    return service.list_workflows(db, q, source=source, template_id=template_id, limit=limit)


@definitions_router.get(
    "/{workflow_id}", response_model=WorkflowDefinitionOut, summary="A workflow definition"
)
def get_workflow(
    workflow_id: str,
    db: DbSession,
    _: Authorized(Permission.WORKFLOWS_READ),
    version: Annotated[int | None, Query(ge=1)] = None,
) -> WorkflowDefinitionOut:
    return service.definition_out(db, service.get_definition(db, workflow_id, version))


@definitions_router.get(
    "/{workflow_id}/graph",
    response_model=GraphOut,
    summary="The definition laid out as a graph, with live metrics and test coverage",
)
def workflow_graph(
    workflow_id: str,
    db: DbSession,
    _: Authorized(Permission.WORKFLOWS_READ),
    version: Annotated[int | None, Query(ge=1)] = None,
) -> GraphOut:
    return service.graph_out(db, workflow_id, version)


@definitions_router.get(
    "/{workflow_id}/export",
    response_model=dict[str, Any],
    summary="The definition as an importable document (code or stored)",
)
def export_workflow(
    workflow_id: str,
    db: DbSession,
    _: Authorized(Permission.WORKFLOWS_READ),
    version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    return authoring.export(db, workflow_id, version)


@definitions_router.get(
    "/{workflow_id}/metrics",
    response_model=WorkflowMetrics,
    summary="Per-step throughput, durations and failures (bottleneck analysis)",
)
def workflow_metrics(
    workflow_id: str, db: DbSession, _: Authorized(Permission.WORKFLOWS_READ)
) -> WorkflowMetrics:
    return service.metrics(db, workflow_id)


@definitions_router.post(
    "/{workflow_id}/executions",
    response_model=ExecutionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Start an execution (runs until it waits, completes or fails)",
)
def start_execution(
    workflow_id: str,
    body: StartExecution,
    db: DbSession,
    actor: Authorized(Permission.WORKFLOWS_START),
    idempotency_key: IdempotencyKey = None,
    version: Annotated[int | None, Query(ge=1)] = None,
):
    execution, replayed = engine.start(
        db,
        workflow_id=workflow_id,
        version=version,
        payload=body.input,
        initiator=actor,
        idempotency_key=idempotency_key,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        content=service.execution_detail(db, execution).model_dump(mode="json"),
        headers={REPLAY_HEADER: "true"} if replayed else None,
    )


# --- Stored definitions (import, lifecycle) -----------------------------------------------


@authoring_router.get(
    "", response_model=list[StoredDefinitionOut], summary="Every imported definition version"
)
def list_stored_definitions(
    db: DbSession, _: Authorized(Permission.WORKFLOWS_READ)
) -> list[StoredDefinitionOut]:
    return service.stored_definitions(db)


@authoring_router.get(
    "/handlers",
    response_model=list[LibraryHandlerOut],
    summary="The step-handler library stored definitions may use",
)
def list_library_handlers(_: Authorized(Permission.WORKFLOWS_READ)) -> list[LibraryHandlerOut]:
    return service.library_handlers()


@authoring_router.post(
    "/preview",
    response_model=DraftPreview,
    summary="Validate a draft and lay it out as a graph (the editor's live preview)",
)
def preview_definition(
    body: DefinitionDocument, db: DbSession, _: Authorized(Permission.WORKFLOWS_DEFINE)
) -> DraftPreview:
    return service.draft_preview(db, body.definition)


@authoring_router.post(
    "/validate",
    response_model=ValidationReportOut,
    summary="Validate a definition document without importing it (every problem listed)",
)
def validate_definition(
    body: DefinitionDocument, db: DbSession, _: Authorized(Permission.WORKFLOWS_DEFINE)
) -> ValidationReportOut:
    return service.report_out(authoring.validate(db, body.definition))


@authoring_router.post(
    "",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import a definition version (201; 200 when this exact version is already stored)",
)
def import_definition(
    body: DefinitionDocument, db: DbSession, actor: Authorized(Permission.WORKFLOWS_DEFINE)
):
    record, created, report = authoring.import_definition(db, body.definition, actor.id)
    result = ImportResult(
        created=created,
        definition=service.stored_definition_out(db, record),
        warnings=report.warnings,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


@authoring_router.post(
    "/{workflow_id}/versions/{version}/retire",
    response_model=StoredDefinitionOut,
    summary="Retire a stored version: no new executions; running ones finish on it",
)
def retire_definition(
    workflow_id: str, version: int, db: DbSession, actor: Authorized(Permission.WORKFLOWS_DEFINE)
) -> StoredDefinitionOut:
    record = authoring.set_status(db, workflow_id, version, DefinitionStatus.RETIRED, actor.id)
    return service.stored_definition_out(db, record)


@authoring_router.post(
    "/{workflow_id}/versions/{version}/reactivate",
    response_model=StoredDefinitionOut,
    summary="Make a retired stored version startable again",
)
def reactivate_definition(
    workflow_id: str, version: int, db: DbSession, actor: Authorized(Permission.WORKFLOWS_DEFINE)
) -> StoredDefinitionOut:
    record = authoring.set_status(db, workflow_id, version, DefinitionStatus.ACTIVE, actor.id)
    return service.stored_definition_out(db, record)


@authoring_router.post(
    "/{workflow_id}/versions/{version}/tests",
    response_model=TestRunOut,
    summary="Generate and run path tests for a stored version (rolled back; the run is kept)",
)
def run_definition_tests(
    workflow_id: str, version: int, db: DbSession, actor: Authorized(Permission.WORKFLOWS_DEFINE)
) -> TestRunOut:
    _, run = testing.run_stored(db, workflow_id, version, actor.id)
    return service.test_run_out(db, run)


@authoring_router.get(
    "/{workflow_id}/tests",
    response_model=list[TestRunOut],
    summary="The latest generated-test runs of a stored workflow",
)
def list_definition_tests(
    workflow_id: str, db: DbSession, _: Authorized(Permission.WORKFLOWS_READ)
) -> list[TestRunOut]:
    return service.test_runs(db, workflow_id)


# --- Templates and variants (Phase 19) -------------------------------------------------------


@templates_router.get("", response_model=list[TemplateOut], summary="Every template version")
def list_templates(db: DbSession, _: Authorized(Permission.WORKFLOWS_READ)) -> list[TemplateOut]:
    return service.list_templates(db)


@templates_router.post(
    "/validate",
    response_model=TemplateReportOut,
    summary="Validate a template without importing it (its example is rendered and validated)",
)
def validate_template(
    body: TemplateDocumentIn, db: DbSession, _: Authorized(Permission.WORKFLOWS_DEFINE)
) -> TemplateReportOut:
    return service.template_report_out(templates.validate_template(db, body.template))


@templates_router.post(
    "",
    response_model=TemplateImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import a template version (201; 200 when this exact version is already stored)",
)
def import_template(
    body: TemplateDocumentIn, db: DbSession, actor: Authorized(Permission.WORKFLOWS_DEFINE)
):
    record, created, report = templates.import_template(db, body.template, actor.id)
    result = TemplateImportResult(
        created=created, template=service.template_out(db, record), warnings=report.warnings
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content=result.model_dump(mode="json"),
    )


@templates_router.get(
    "/{template_id}", response_model=TemplateDetail, summary="A template with its body"
)
def get_template(
    template_id: str,
    db: DbSession,
    _: Authorized(Permission.WORKFLOWS_READ),
    version: Annotated[int | None, Query(ge=1)] = None,
) -> TemplateDetail:
    return service.template_out(db, templates.template_record(db, template_id, version), True)


@templates_router.get(
    "/{template_id}/variants",
    response_model=list[VariantOut],
    summary="The workflows generated from a template, with their parameters",
)
def list_variants(
    template_id: str, db: DbSession, _: Authorized(Permission.WORKFLOWS_READ)
) -> list[VariantOut]:
    templates.template_record(db, template_id)
    return service.variants_out(db, template_id)


@templates_router.post(
    "/{template_id}/render",
    response_model=RenderOut,
    summary="Render one parameter set and validate the result (stores nothing)",
)
def render_template(
    template_id: str, body: RenderIn, db: DbSession, _: Authorized(Permission.WORKFLOWS_READ)
) -> RenderOut:
    return service.render_out(db, template_id, body.params, body.version)


@templates_router.post(
    "/{template_id}/generate",
    response_model=GenerationOut,
    summary="Generate one workflow per parameter set; all are stored or none",
)
def generate_variants(
    template_id: str,
    body: GenerateIn,
    db: DbSession,
    actor: Authorized(Permission.WORKFLOWS_DEFINE),
) -> GenerationOut:
    param_sets = templates.expand(body.grid, body.variants, body.fixed)
    report = templates.generate(
        db, template_id, param_sets, actor.id, version=body.version, dry_run=body.dry_run
    )
    return service.generation_out(report)


@templates_router.post(
    "/{template_id}/versions/{version}/retire",
    response_model=TemplateOut,
    summary="Retire a template version: it generates nothing more; its workflows stay",
)
def retire_template(
    template_id: str, version: int, db: DbSession, actor: Authorized(Permission.WORKFLOWS_DEFINE)
) -> TemplateOut:
    record = templates.set_status(db, template_id, version, DefinitionStatus.RETIRED, actor.id)
    return service.template_out(db, record)


@templates_router.post(
    "/{template_id}/versions/{version}/reactivate",
    response_model=TemplateOut,
    summary="Make a retired template version generate again",
)
def reactivate_template(
    template_id: str, version: int, db: DbSession, actor: Authorized(Permission.WORKFLOWS_DEFINE)
) -> TemplateOut:
    record = templates.set_status(db, template_id, version, DefinitionStatus.ACTIVE, actor.id)
    return service.template_out(db, record)


# --- Executions ----------------------------------------------------------------------------


@executions_router.get("", response_model=Page[ExecutionSummary], summary="Execution history")
def list_executions(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.WORKFLOWS_READ),
    workflow_id: Annotated[str | None, Query(max_length=20)] = None,
    status: ExecutionStatus | None = None,
    outcome: Annotated[str | None, Query(max_length=50)] = None,
    business_key: Annotated[str | None, Query(max_length=100)] = None,
    simulation_run_id: Annotated[
        uuid.UUID | None,
        Query(description="List one simulation run's executions instead of live ones."),
    ] = None,
) -> Page[ExecutionSummary]:
    items, total = service.list_executions(
        db,
        page,
        workflow_id=workflow_id,
        status=status,
        outcome=outcome,
        business_key=business_key,
        simulation_run_id=simulation_run_id,
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@executions_router.get(
    "/{execution_id}", response_model=ExecutionDetail, summary="Execution with every step run"
)
def get_execution(
    execution_id: uuid.UUID, db: DbSession, _: Authorized(Permission.WORKFLOWS_READ)
) -> ExecutionDetail:
    return service.execution_detail(db, service.get_execution(db, execution_id))


@executions_router.get(
    "/{execution_id}/history",
    response_model=list[WorkflowEventOut],
    summary="Append-only event history",
)
def get_history(
    execution_id: uuid.UUID, db: DbSession, _: Authorized(Permission.WORKFLOWS_READ)
) -> list[WorkflowEventOut]:
    service.get_execution(db, execution_id)
    return service.history(db, execution_id)


@executions_router.post(
    "/{execution_id}/signals",
    response_model=ExecutionDetail,
    summary="Deliver a signal to a waiting step (e.g. documents_submitted)",
)
def send_signal(
    execution_id: uuid.UUID,
    body: SignalIn,
    db: DbSession,
    actor: Authorized(Permission.WORKFLOWS_START),
) -> ExecutionDetail:
    execution = engine.signal(db, execution_id, body.signal, body.payload, actor.id)
    return service.execution_detail(db, execution)


@executions_router.post(
    "/{execution_id}/resume",
    response_model=ExecutionDetail,
    summary="Run any due steps now (normally done by the runner)",
)
def resume_execution(
    execution_id: uuid.UUID, db: DbSession, _: Authorized(Permission.WORKFLOWS_MANAGE)
) -> ExecutionDetail:
    return service.execution_detail(db, engine.advance(db, execution_id))


@executions_router.post(
    "/{execution_id}/cancel", response_model=ExecutionDetail, summary="Cancel an execution"
)
def cancel_execution(
    execution_id: uuid.UUID,
    body: CancelIn,
    db: DbSession,
    actor: Authorized(Permission.WORKFLOWS_MANAGE),
) -> ExecutionDetail:
    return service.execution_detail(db, engine.cancel(db, execution_id, actor.id, body.reason))


# --- Tasks ---------------------------------------------------------------------------------


@tasks_router.get(
    "",
    response_model=Page[TaskOut],
    summary="Open human tasks and approvals, marked with whether you may act",
)
def list_tasks(
    db: DbSession,
    page: PageParamsDep,
    user: CurrentUser,
    actionable: Annotated[bool, Query(description="Only tasks you may complete")] = False,
) -> Page[TaskOut]:
    items, total = service.open_tasks(db, user, page, actionable_only=actionable)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@tasks_router.post(
    "/{run_id}/complete",
    response_model=ExecutionDetail,
    summary="Complete a task or approval (permission and four-eyes enforced)",
)
def complete_task(
    run_id: uuid.UUID, body: TaskCompletion, db: DbSession, actor: CurrentUser
) -> ExecutionDetail:
    execution = engine.complete_task(
        db, run_id, actor, decision=body.decision, data=body.data, note=body.note
    )
    return service.execution_detail(db, execution)
