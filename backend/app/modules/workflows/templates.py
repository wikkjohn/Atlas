"""Workflow templates and the deterministic variant generator (Phase 19).

A template is a definition body with `{{param}}` placeholders, a JSON Schema for the
parameters, an example parameter set and the range of workflow ids its variants take:

    {"template_id": "TPL-PAPER-STATEMENT", "version": 1, "name": …, "description": …,
     "id_range": [2000, 2999], "parameters": {JSON Schema}, "example": {…}, "body": {…}}

Rendering replaces placeholders in the body:

- a string that is exactly `{{name}}` becomes the parameter's value with its type (a
  number, a list, a boolean); placeholders inside longer strings are interpolated as text;
- with a `country_code` parameter, `{{country.code|name|currency|region|minor_exponent}}`
  come from the countries reference data;
- `{{amount|minor}}` converts a whole major-unit amount into minor units of the country's
  currency (5 → 500 for GBP, 5 for JPY);
- a step with `"$include": "{{flag}}"` is left out when the flag is false, and every route
  to it goes to its `next` instead.

The generator renders a template for each parameter set and imports the result through
the same validation as any stored definition. A parameter set's canonical JSON is its
`variant_key`; the first generation gives it the lowest free workflow id in the template's
range, recorded in `workflow_variants`, and every later generation reuses that id. A
variant whose rendered content is unchanged keeps its version; a changed one gets the next
version. Generating the same template version with the same parameters is a no-op.
"""

import copy
import itertools
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import minor_unit_exponent, to_minor_units
from app.modules.workflows import authoring, registry, validation
from app.modules.workflows.definition import problem
from app.modules.workflows.models import (
    DefinitionStatus,
    WorkflowDefinitionRecord,
    WorkflowTemplateRecord,
    WorkflowVariant,
)

PLACEHOLDER = re.compile(
    r"\{\{\s*([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)\s*(?:\|\s*(minor)\s*)?\}\}"
)
COUNTRY_FIELDS = ("code", "name", "currency", "region", "minor_exponent")
RESERVED_BODY_KEYS = ("workflow_id", "version", "origin")
MAX_VARIANTS_PER_REQUEST = 1_000
ROUTE_FIELDS = ("next", "on_failure", "join")


class TemplateInvalid(BusinessRuleViolation):
    code = "template_invalid"


class TemplateDocument(BaseModel):
    template_id: str = Field(pattern=r"^TPL-[A-Z0-9][A-Z0-9-]{1,35}$")
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    id_range: tuple[int, int]
    parameters: dict[str, Any]
    example: dict[str, Any]
    body: dict[str, Any]

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _range(self) -> "TemplateDocument":
        low, high = self.id_range
        if not 1000 <= low <= high <= 9999:
            raise ValueError("id_range must be [low, high] with 1000 <= low <= high <= 9999.")
        return self

    def canonical_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def content_hash(self) -> str:
        import hashlib

        payload = json.dumps(self.canonical_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


class RenderError(Exception):
    def __init__(self, location: str, message: str) -> None:
        super().__init__(message)
        self.location = location
        self.message = message


# --- Rendering -------------------------------------------------------------------------------


def variant_key(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def placeholders(body: Any) -> set[str]:
    if isinstance(body, dict):
        return set().union(*(placeholders(v) for v in body.values())) if body else set()
    if isinstance(body, list):
        return set().union(*(placeholders(v) for v in body)) if body else set()
    if isinstance(body, str):
        return {m.group(1) for m in PLACEHOLDER.finditer(body)}
    return set()


def _country(db: Session | None, code: Any) -> dict[str, Any]:
    from app.modules.countries.models import Country

    if db is None:
        raise RenderError("country_code", "Country data needs the database.")
    found = db.execute(
        select(Country).where(Country.iso_country_code == str(code))
    ).scalar_one_or_none()
    if found is None:
        raise RenderError("country_code", f"Unknown country '{code}'.")
    return {
        "code": found.iso_country_code,
        "name": found.country_name,
        "currency": found.default_currency,
        "region": found.region,
        "minor_exponent": minor_unit_exponent(found.default_currency),
        # Reference data (Phase 23).
        "alpha3": found.iso_alpha3,
        "timezone": found.default_timezone,
        "language": found.supported_languages[0],
        "calling_code": found.calling_code,
        "regulator": (found.regulator or {}).get("abbreviation"),
    }


def _values(db: Session | None, params: dict[str, Any]) -> dict[str, Any]:
    values = dict(params)
    if "country_code" in params:
        values["country"] = _country(db, params["country_code"])
    return values


def _lookup(values: dict[str, Any], name: str, transform: str | None, at: str) -> Any:
    root, _, leaf = name.partition(".")
    if root not in values or (leaf and leaf not in (values[root] or {})):
        raise RenderError(at, f"No value for '{{{{{name}}}}}'.")
    value = values[root][leaf] if leaf else values[root]
    if transform == "minor":
        country = values.get("country")
        if country is None:
            raise RenderError(at, "'|minor' needs a country_code parameter.")
        if not isinstance(value, int) or isinstance(value, bool):
            raise RenderError(at, f"'|minor' needs a whole number, not {value!r}.")
        value = to_minor_units(value, country["currency"])
    return value


def _substitute(node: Any, values: dict[str, Any], at: str) -> Any:
    if isinstance(node, dict):
        return {k: _substitute(v, values, f"{at}.{k}") for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, values, f"{at}[{i}]") for i, v in enumerate(node)]
    if isinstance(node, str):
        whole = PLACEHOLDER.fullmatch(node)
        if whole:
            return _lookup(values, whole.group(1), whole.group(2), at)
        return PLACEHOLDER.sub(lambda m: str(_lookup(values, m.group(1), m.group(2), at)), node)
    return node


def _drop_excluded(body: dict[str, Any]) -> dict[str, Any]:
    """Remove steps whose `$include` is false and route around them."""
    steps = body.get("steps") or []
    bypass: dict[str, str] = {}
    kept = []
    for step in steps:
        include = step.pop("$include", True)
        if not isinstance(include, bool):
            raise RenderError(f"steps.{step.get('id')}.$include", "$include must be a boolean.")
        if include:
            kept.append(step)
        elif not step.get("next"):
            raise RenderError(
                f"steps.{step.get('id')}", "An optional step needs a `next` to route around it."
            )
        else:
            bypass[step["id"]] = step["next"]

    def through(target: Any) -> Any:
        seen = set()
        while isinstance(target, str) and target in bypass and target not in seen:
            seen.add(target)
            target = bypass[target]
        return target

    for step in kept:
        for name in ROUTE_FIELDS:
            if name in step:
                step[name] = through(step[name])
        for transition in step.get("transitions") or []:
            transition["to"] = through(transition.get("to"))
        if "branches" in step:
            step["branches"] = [through(b) for b in step["branches"]]
        if isinstance(step.get("timeout"), dict) and "to" in step["timeout"]:
            step["timeout"]["to"] = through(step["timeout"]["to"])
    body["steps"] = kept
    if "start" in body:
        body["start"] = through(body["start"])
    return body


def render(
    db: Session | None,
    template: TemplateDocument,
    params: dict[str, Any],
    *,
    workflow_id: str,
    version: int,
) -> dict[str, Any]:
    """The definition document for one parameter set."""
    values = _values(db, params)
    body = _drop_excluded(_substitute(copy.deepcopy(template.body), values, "body"))
    return {
        **body,
        "workflow_id": workflow_id,
        "version": version,
        "origin": {
            "template_id": template.template_id,
            "template_version": template.version,
            "variant_key": variant_key(params),
        },
    }


# --- Template validation and import -----------------------------------------------------------


@dataclass
class TemplateReport:
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    template: TemplateDocument | None = None
    existing: Literal["new", "identical"] | None = None
    preview: dict[str, Any] | None = None  # the example rendered

    @property
    def valid(self) -> bool:
        return not self.errors


def _params_errors(template: TemplateDocument, params: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(template.parameters)
    return [
        f"{'.'.join(map(str, e.absolute_path)) or 'parameters'}: {e.message}"
        for e in sorted(validator.iter_errors(params), key=lambda e: list(e.absolute_path))
    ]


def validate_template(db: Session | None, document: dict[str, Any]) -> TemplateReport:
    report = TemplateReport()
    try:
        template = TemplateDocument.model_validate(document)
    except ValidationError as exc:
        for e in exc.errors():
            location = ".".join(str(p) for p in e["loc"]) or "document"
            report.errors.append(problem(location, e["type"], e["msg"]))
        return report
    report.template = template

    def error(location: str, code: str, message: str) -> None:
        report.errors.append(problem(location, code, message))

    try:
        Draft202012Validator.check_schema(template.parameters)
    except SchemaError as exc:
        error("parameters", "schema_invalid", exc.message)
        return report
    if template.parameters.get("type") != "object":
        error("parameters", "schema_not_object", "Parameters must be a JSON Schema object.")
        return report
    declared = set((template.parameters.get("properties") or {}).keys())
    used = placeholders(template.body)
    for name in sorted(used):
        root = name.partition(".")[0]
        if root == "country":
            if "country_code" not in declared:
                error(
                    "body",
                    "country_needs_code",
                    f"'{{{{{name}}}}}' needs a country_code parameter.",
                )
            elif name.partition(".")[2] not in COUNTRY_FIELDS:
                error(
                    "body",
                    "unknown_country_field",
                    f"'{{{{{name}}}}}': countries have {', '.join(COUNTRY_FIELDS)}.",
                )
        elif root not in declared:
            error("body", "unknown_parameter", f"'{{{{{name}}}}}' is not a declared parameter.")
    for name in sorted(declared - {n.partition(".")[0] for n in used} - {"country_code"}):
        report.warnings.append(
            problem("parameters", "unused_parameter", f"'{name}' is never used in the body.")
        )
    for key in RESERVED_BODY_KEYS:
        if key in template.body:
            error(f"body.{key}", "reserved", f"The generator sets `{key}`; leave it out.")
    if registry.get_definition(f"WF-{template.id_range[0]:04d}") is not None:
        error("id_range", "owned_by_code", "The range overlaps workflows registered in code.")
    for message in _params_errors(template, template.example):
        error("example", "invalid_example", message)
    if not report.valid:
        return report

    # The example, rendered, must be a valid definition.
    try:
        preview = render(
            db, template, template.example, workflow_id=f"WF-{template.id_range[0]:04d}", version=1
        )
    except RenderError as exc:
        error(f"example → {exc.location}", "render_error", exc.message)
        return report
    report.preview = preview
    rendered = validation.validate(db, preview, versions=False, generated=True)
    for e in rendered.errors:
        if e["code"] != "owned_by_template":
            error(f"example → {e['location']}", e["code"], e["message"])
    report.warnings.extend(
        problem(f"example → {w['location']}", w["code"], w["message"]) for w in rendered.warnings
    )
    if db is not None and report.valid:
        rows = dict(
            db.execute(
                select(WorkflowTemplateRecord.version, WorkflowTemplateRecord.content_hash).where(
                    WorkflowTemplateRecord.template_id == template.template_id
                )
            ).all()
        )
        if template.version in rows:
            if rows[template.version] == template.content_hash():
                report.existing = "identical"
            else:
                error(
                    "version",
                    "version_exists",
                    f"{template.template_id} v{template.version} "
                    "is already stored with different content; import a new version.",
                )
        elif template.version <= max(rows, default=0):
            error(
                "version",
                "version_not_increasing",
                f"The latest version of "
                f"{template.template_id} is {max(rows)}; a new version must be higher.",
            )
        else:
            report.existing = "new"
    return report


def import_template(
    db: Session, document: dict[str, Any], actor_id: uuid.UUID
) -> tuple[WorkflowTemplateRecord, bool, TemplateReport]:
    report = validate_template(db, document)
    if not report.valid:
        raise TemplateInvalid(
            f"The template has {len(report.errors)} problem(s); nothing was imported.",
            {"errors": report.errors, "warnings": report.warnings},
        )
    template = report.template
    assert template is not None
    if report.existing == "identical":
        return template_record(db, template.template_id, template.version), False, report
    record = WorkflowTemplateRecord(
        template_id=template.template_id,
        version=template.version,
        name=template.name,
        document=template.canonical_json(),
        content_hash=template.content_hash(),
        status=DefinitionStatus.ACTIVE,
        imported_by=actor_id,
    )
    db.add(record)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="workflow_template.imported",
        entity_type="workflow_template",
        entity_id=record.id,
        metadata={"template_id": template.template_id, "version": template.version},
    )
    return record, True, report


def template_record(
    db: Session, template_id: str, version: int | None = None
) -> WorkflowTemplateRecord:
    """A version, or (without one) the latest active version."""
    query = select(WorkflowTemplateRecord).where(WorkflowTemplateRecord.template_id == template_id)
    if version is not None:
        query = query.where(WorkflowTemplateRecord.version == version)
    else:
        query = query.where(WorkflowTemplateRecord.status == DefinitionStatus.ACTIVE)
    found = db.execute(
        query.order_by(WorkflowTemplateRecord.version.desc()).limit(1)
    ).scalar_one_or_none()
    if found is None:
        raise NotFoundError(
            f"Template {template_id}" + (f" v{version}" if version else "") + " not found."
        )
    return found


def set_status(
    db: Session, template_id: str, version: int, status: DefinitionStatus, actor_id: uuid.UUID
) -> WorkflowTemplateRecord:
    record = template_record(db, template_id, version)
    if record.status != status:
        record.status = status
        record_audit_event(
            db,
            actor_id=actor_id,
            action=f"workflow_template.{'retired' if status == 'retired' else 'reactivated'}",
            entity_type="workflow_template",
            entity_id=record.id,
            metadata={"template_id": template_id, "version": version},
        )
    return record


# --- Generation ------------------------------------------------------------------------------


@dataclass
class VariantResult:
    variant_key: str
    params: dict[str, Any]
    workflow_id: str | None
    version: int | None
    status: Literal["created", "updated", "unchanged", "invalid"]
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class GenerationReport:
    template_id: str
    template_version: int
    dry_run: bool
    results: list[VariantResult]

    def count(self, status: str) -> int:
        return sum(r.status == status for r in self.results)

    @property
    def valid(self) -> bool:
        return self.count("invalid") == 0


def expand(
    grid: dict[str, list[Any]] | None,
    variants: list[dict[str, Any]] | None,
    fixed: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """The parameter sets: the grid's cartesian product and the explicit variants, each
    merged over `fixed`, de-duplicated and in variant-key order."""
    fixed = fixed or {}
    sets: list[dict[str, Any]] = []
    if grid:
        names = sorted(grid)
        for combination in itertools.product(*(grid[n] for n in names)):
            sets.append({**fixed, **dict(zip(names, combination, strict=True))})
    for variant in variants or []:
        sets.append({**fixed, **variant})
    if not grid and not variants:
        sets.append(dict(fixed))
    unique = {variant_key(s): s for s in sets}
    return [unique[k] for k in sorted(unique)]


def _used_ids(db: Session) -> set[int]:
    stored = db.execute(select(WorkflowDefinitionRecord.workflow_id).distinct()).scalars()
    variants = db.execute(select(WorkflowVariant.workflow_id)).scalars()
    ids = {d.workflow_id for d in registry.all_definitions()} | set(stored) | set(variants)
    return {int(i[3:]) for i in ids if re.fullmatch(r"WF-\d{4}", i)}


def generate(
    db: Session,
    template_id: str,
    param_sets: list[dict[str, Any]],
    actor_id: uuid.UUID | None,
    *,
    version: int | None = None,
    dry_run: bool = False,
    limit: int | None = MAX_VARIANTS_PER_REQUEST,
) -> GenerationReport:
    """Render, validate and (unless a dry run, and only when every variant is valid)
    import one definition per parameter set."""
    record = template_record(db, template_id, version)
    if record.status != DefinitionStatus.ACTIVE:
        raise ConflictError(f"{template_id} v{record.version} is retired.")
    if limit is not None and len(param_sets) > limit:
        raise BusinessRuleViolation(f"At most {limit} variants per request.")
    template = TemplateDocument.model_validate(record.document)
    # Ids are allocated in variant-key order, so they never depend on the input's order.
    unique = {variant_key(p): p for p in param_sets}
    param_sets = [unique[k] for k in sorted(unique)]
    known = {
        v.variant_key: v
        for v in db.execute(
            select(WorkflowVariant).where(WorkflowVariant.template_id == template_id)
        ).scalars()
    }
    used = _used_ids(db)
    low, high = template.id_range
    free = (n for n in range(low, high + 1) if n not in used)

    results: list[VariantResult] = []
    reports: dict[str, validation.Report] = {}
    for params in param_sets:
        key = variant_key(params)
        errors = _params_errors(template, params)
        if errors:
            results.append(
                VariantResult(
                    key,
                    params,
                    None,
                    None,
                    "invalid",
                    [problem("params", "invalid_params", m) for m in errors],
                )
            )
            continue
        existing = known.get(key)
        if existing is not None:
            workflow_id = existing.workflow_id
        else:
            number = next(free, None)
            if number is None:
                results.append(
                    VariantResult(
                        key,
                        params,
                        None,
                        None,
                        "invalid",
                        [
                            problem(
                                "id_range", "range_full", f"No free workflow id in {low}-{high}."
                            )
                        ],
                    )
                )
                continue
            workflow_id = f"WF-{number:04d}"
        try:
            current = existing.definition_version if existing else 0
            document = render(
                db, template, params, workflow_id=workflow_id, version=max(current, 1)
            )
        except RenderError as exc:
            results.append(
                VariantResult(
                    key,
                    params,
                    workflow_id,
                    None,
                    "invalid",
                    [problem(exc.location, "render_error", exc.message)],
                )
            )
            continue
        status: Literal["created", "updated", "unchanged"] = "created"
        report = validation.validate(db, document, generated=True)
        if existing is not None:
            if report.existing == "identical":
                status = "unchanged"
            else:  # changed content: the next version of the same workflow
                document["version"] = existing.definition_version + 1
                status = "updated"
                report = validation.validate(db, document, generated=True)
        if not report.valid:
            results.append(
                VariantResult(
                    key, params, workflow_id, document["version"], "invalid", report.errors
                )
            )
            continue
        reports[key] = report
        results.append(VariantResult(key, params, workflow_id, document["version"], status))

    outcome = GenerationReport(template_id, record.version, dry_run, results)
    if dry_run or not outcome.valid:
        return outcome
    for result in results:
        variant = known.get(result.variant_key)
        if result.status == "unchanged":
            assert variant is not None
            variant.template_version = record.version
            continue
        authoring.store_validated(db, reports[result.variant_key], actor_id)
        if variant is None:
            variant = WorkflowVariant(
                template_id=template_id,
                variant_key=result.variant_key,
                workflow_id=result.workflow_id,
                params=result.params,
            )
            db.add(variant)
        variant.template_version = record.version
        variant.definition_version = result.version
        variant.generated_by = actor_id
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="workflow_template.generated",
        entity_type="workflow_template",
        entity_id=record.id,
        metadata={
            "template_id": template_id,
            "version": record.version,
            **{s: outcome.count(s) for s in ("created", "updated", "unchanged")},
        },
    )
    return outcome
