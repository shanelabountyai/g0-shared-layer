"""observability v1 — log one model call (or step) and return the run's running total
against the cost cap (D-18). This is G1's `run_logging` rule in one place."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared_layer.errors import ToolError
from shared_layer.storage import Database, new_id, now_iso

CAPABILITY = "observability"
TOOL = "observability"
VERSION = "1"
DESCRIPTION = (
    "Log one step of a run: `run_id`, `agent`, `step`, tokens in/out, `cost_usd`, `status` (ok|error|skipped), "
    "optional `model`, `duration_ms`, `note`. Returns the log id and the run's running total (calls, tokens, "
    "cost) against the cap, with `over_cap`. Logging is never refused; when `over_cap` is true the caller "
    "should stop making model calls. Append-only."
)

DEFAULT_CAP_USD = 10.0


def cap_usd() -> float:
    try:
        return float(os.environ.get("G0_RUN_CAP_USD", DEFAULT_CAP_USD))
    except ValueError:
        return DEFAULT_CAP_USD


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    run_id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    step: str = Field(min_length=1)
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    status: Literal["ok", "error", "skipped"] = "ok"
    duration_ms: int | None = Field(default=None, ge=0)
    note: str | None = None


class RunTotal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    capability: Literal["observability"] = "observability"
    ok: bool = True
    error: ToolError | None = None
    log_id: str = ""
    logged_at: str = ""
    run_total: RunTotal | None = None
    cap_usd: float = DEFAULT_CAP_USD
    over_cap: bool = False


def run_total(db: Database, run_id: str) -> RunTotal:
    row = db.conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens),0) AS i, COALESCE(SUM(output_tokens),0) AS o, COALESCE(SUM(cost_usd),0) AS c FROM run_log WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return RunTotal(run_id=run_id, calls=int(row["calls"]), input_tokens=int(row["i"]), output_tokens=int(row["o"]), cost_usd=round(float(row["c"]), 6))


def run(db: Database, inp: Input) -> Output:
    log_id = new_id("log")
    logged = now_iso()
    with db.conn:
        db.conn.execute(
            "INSERT INTO run_log (log_id, run_id, agent, step, model, input_tokens, output_tokens, cost_usd, status, duration_ms, note, logged_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (log_id, inp.run_id, inp.agent, inp.step, inp.model, inp.input_tokens, inp.output_tokens, inp.cost_usd, inp.status, inp.duration_ms, inp.note, logged),
        )
    total = run_total(db, inp.run_id)
    cap = cap_usd()
    return Output(log_id=log_id, logged_at=logged, run_total=total, cap_usd=cap, over_cap=total.cost_usd > cap)
