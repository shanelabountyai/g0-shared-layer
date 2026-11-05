"""measurement v1 — store an event. Append-only (D-22)."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared_layer.errors import ToolError
from shared_layer.storage import Database, new_id, now_iso

CAPABILITY = "measurement"
TOOL = "measurement"
VERSION = "1"
DESCRIPTION = (
    "Store one measurement event: `event` (a dotted name such as `digest.published`) and `fields` (any JSON "
    "object). Optional `occurred_at` (ISO 8601; defaults to now), `run_id`, `agent`. Returns the stored "
    "`event_id`. Append-only: nothing is updated or deleted. Do not put personal data in `fields`."
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    event: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)*$", description="Dotted lower-case event name.")
    fields: dict[str, Any] = Field(default_factory=dict, description="Event payload; stored as JSON.")
    occurred_at: str | None = Field(default=None, description="ISO 8601 timestamp; defaults to now (UTC).")
    run_id: str | None = None
    agent: str | None = None


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    capability: Literal["measurement"] = "measurement"
    ok: bool = True
    error: ToolError | None = None
    event_id: str = ""
    event: str = ""
    stored_at: str = ""


def run(db: Database, inp: Input) -> Output:
    event_id = new_id("evt")
    stored = now_iso()
    with db.conn:
        db.conn.execute(
            "INSERT INTO events (event_id, event, fields, run_id, agent, occurred_at, stored_at) VALUES (?,?,?,?,?,?,?)",
            (event_id, inp.event, json.dumps(inp.fields, sort_keys=True), inp.run_id, inp.agent, inp.occurred_at or stored, stored),
        )
    return Output(event_id=event_id, event=inp.event, stored_at=stored)
