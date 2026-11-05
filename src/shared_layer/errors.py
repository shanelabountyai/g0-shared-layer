"""The error envelope every capability returns (D-14).

One shape for every refusal, carried INSIDE the output contract as `error`
with `ok: false`, so a client that validates `structuredContent` against the
tool's output schema (Claude's clients do) accepts the refusal and the model
can read `code`, fix `field`, and know which tool comes `next`.

A1 (bookable-appointment-service) found the opposite design — an error
payload outside the output schema — reaches the model as an exception. This
module is the one place the codes are defined.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ErrorCode = Literal[
    "INVALID_ARGUMENT",
    "NOT_FOUND",
    "UNKNOWN_RUBRIC",
    "UNKNOWN_POLICY",
    "JUDGE_UNAVAILABLE",
    "OVER_CAP",
    "STORAGE_ERROR",
]


class NextStep(BaseModel):
    """What to do next. Absent when the caller cannot fix it alone."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(description="Tool to call next.")
    why: str = Field(description="What calling it will get you.")


class ToolError(BaseModel):
    """The envelope. `message` is plain words a model can show a human as-is."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    field: str | None = Field(default=None, description="Which input argument to change, when one is.")
    next: NextStep | None = None


class Refusal(Exception):
    """Raised inside a capability to refuse with a specific envelope.

    The server catches it and returns the capability's output model with
    `ok=False` and `error` set; it never becomes a protocol-level error.
    """

    def __init__(self, envelope: ToolError) -> None:
        super().__init__(envelope.message)
        self.envelope = envelope


def invalid_argument(field: str, message: str, next: NextStep | None = None) -> Refusal:
    return Refusal(ToolError(code="INVALID_ARGUMENT", message=message, field=field, next=next))


def not_found(what: str, field: str, next: NextStep | None = None) -> Refusal:
    return Refusal(ToolError(code="NOT_FOUND", message=f"No {what} matches that {field}.", field=field, next=next))
