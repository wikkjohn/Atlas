"""Phase 89: the decision records, runbooks and contributor guide stay true to the code.

No database needed. Each check reads the documents and compares what they name with what
exists: files and directories in the repository, CLI commands (by running their own
`--help`), and `/api/v1` routes (against the reviewed authorization matrix, which is read
from the routes themselves).
"""

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from app import cli

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
ADRS = sorted(p for p in (DOCS / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
RUNBOOKS = sorted(p for p in (DOCS / "runbooks").glob("*.md") if p.name != "README.md")
CHECKED = [
    *ADRS, *RUNBOOKS, DOCS / "adr" / "README.md", DOCS / "runbooks" / "README.md",
    REPO / "CONTRIBUTING.md", REPO / "README.md", DOCS / "architecture.md",
    DOCS / "security.md", DOCS / "backup-recovery.md", DOCS / "dashboard-drilldown.md",
]  # fmt: skip
MATRIX = json.loads((REPO / "backend" / "tests" / "authorization_matrix.json").read_text())

CODE = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\(([^)\s]+)\)")
ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE) (/api/v1/[A-Za-z0-9_{}/.-]+)")
CLI = re.compile(r"python -m app\.cli ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")
PATH_PREFIXES = ("backend/", "frontend/", "docs/", "app/", "scripts/", ".github/")


def _name(path: Path) -> str:
    return str(path.relative_to(REPO))


def _shape(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.rstrip("/"))


ROUTES = {(m, _shape(p)) for m, p in (key.split(" ", 1) for key in MATRIX)}


def test_every_decision_record_has_its_sections_and_is_indexed() -> None:
    assert len(ADRS) >= 12
    index = (DOCS / "adr" / "README.md").read_text()
    for number, adr in enumerate(ADRS, start=1):
        text = adr.read_text()
        assert adr.name.startswith(f"{number:04d}-"), f"{adr.name}: numbers must be consecutive"
        assert text.startswith(f"# ADR {number:04d}: "), adr.name
        for heading in ("## Context", "## Decision", "## Consequences", "## Evidence"):
            assert heading in text, f"{adr.name} lacks {heading}"
        status = re.search(r"- \*\*Status:\*\* (.+)", text)
        assert status and re.fullmatch(
            r"Proposed|Accepted|Superseded by ADR \d{4}", status.group(1).strip()
        ), f"{adr.name}: status"
        assert f"]({adr.name})" in index, f"{adr.name} is not in the index"


def test_every_runbook_has_its_sections_and_is_indexed() -> None:
    assert len(RUNBOOKS) >= 9
    index = (DOCS / "runbooks" / "README.md").read_text()
    for book in RUNBOOKS:
        text = book.read_text()
        assert text.startswith("# Runbook: "), book.name
        assert "**Severity when it happens:**" in text, book.name
        for heading in ("## Symptoms", "## Checks", "## Actions", "## Verify", "## Escalation"):
            assert heading in text, f"{book.name} lacks {heading}"
        assert f"]({book.name})" in index, f"{book.name} is not in the index"


@pytest.mark.parametrize("document", CHECKED, ids=_name)
def test_links_and_paths_exist(document: Path) -> None:
    text = document.read_text()
    missing = []
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if not (document.parent / target.split("#", 1)[0]).exists():
            missing.append(f"link {target}")
    for code in CODE.findall(text):
        token = code.split()[0] if code.split() else ""
        if not token.startswith(PATH_PREFIXES) or any(c in token for c in "<>{}*…"):
            continue
        root = REPO / "backend" if token.startswith("app/") else REPO
        if not (root / token).exists():
            missing.append(f"path {token}")
    assert not missing, f"{document.name} names what does not exist: {missing}"


@pytest.mark.parametrize("document", CHECKED, ids=_name)
def test_named_routes_exist(document: Path) -> None:
    unknown = [
        f"{method} {path}"
        for method, path in ROUTE.findall(document.read_text())
        if (method, _shape(path)) not in ROUTES
    ]
    assert not unknown, f"{document.name} names routes that do not exist: {unknown}"


def _cli_accepts(*args: str) -> bool:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            cli.main([*args, "--help"])
        except SystemExit as exit_:
            return exit_.code == 0
    return False


@pytest.mark.parametrize("document", CHECKED, ids=_name)
def test_named_cli_commands_exist(document: Path) -> None:
    unknown = []
    for command, action in CLI.findall(document.read_text()):
        if not _cli_accepts(command):
            unknown.append(command)
        elif action and _cli_accepts(command, action) is False and _has_actions(command):
            unknown.append(f"{command} {action}")
    assert not unknown, f"{document.name} names CLI commands that do not exist: {unknown}"


def _has_actions(command: str) -> bool:
    """Whether the command takes a sub-action (then the named one must exist)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        with contextlib.suppress(SystemExit):
            cli.main([command, "--help"])
    return "{" in out.getvalue().split("options:")[0]


def test_the_checks_catch_what_does_not_exist(tmp_path: Path) -> None:
    """The checks themselves: an invented route, command and path are all caught."""
    assert ("GET", "/api/v1/backups") in ROUTES
    assert ("GET", "/api/v1/no-such-route") not in ROUTES
    assert _cli_accepts("backup") and _cli_accepts("backup", "drill")
    assert not _cli_accepts("no-such-command")
    assert _has_actions("backup") and not _cli_accepts("backup", "no-such-action")
    assert not (REPO / "backend/app/no_such_module.py").exists()
