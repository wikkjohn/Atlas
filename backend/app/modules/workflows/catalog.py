"""Imports every business workflow so its definitions and handlers are registered, and the
handler library that stored definitions use."""

from app.modules.workflows import library, wf0001, wf0002, wf0003, wf0004  # noqa: F401
