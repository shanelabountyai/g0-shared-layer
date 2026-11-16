"""health — is the layer up, seeded and writable? Also the uptime log (D-21)."""

from __future__ import annotations

import json
from importlib import metadata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared_layer.errors import ToolError
from shared_layer.storage import Database, now_iso

CAPABILITY = "health"
TOOL = "health"
VERSION = "1"
DESCRIPTION = (
    "Report the layer's health: database path and writability, seed counts, contract versions, seeded "
    "rubric and policy ids, server version and uptime. Writes one row to the uptime log. Call first when a "
    "consumer starts, and when any other tool returns ok=false with code STORAGE_ERROR."
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    capability: Literal["health"] = "health"
    ok: bool = True
    error: ToolError | None = None
    status: Literal["ok", "degraded"] = "ok"
    server_version: str = ""
    db_path: str = ""
    db_writable: bool = False
    seeds: dict[str, int] = Field(default_factory=dict)
    contracts: dict[str, str] = Field(default_factory=dict, description="capability → contract version")
    rubrics: list[str] = Field(default_factory=list)
    policy_versions: list[str] = Field(default_factory=list)
    uptime_s: float = 0.0
    checked_at: str = ""


def server_version() -> str:
    try:
        return metadata.version("g0-shared-layer")
    except metadata.PackageNotFoundError:  # pragma: no cover
        return "0.0.0-dev"


def run(db: Database, inp: Input, contracts: dict[str, str] | None = None) -> Output:
    writable = db.writable()
    seeds = db.seed_counts()
    degraded = (not writable) or any(v == 0 for k, v in seeds.items() if k != "brand_policies")
    out = Output(
        status="degraded" if degraded else "ok",
        server_version=server_version(),
        db_path=db.path,
        db_writable=writable,
        seeds=seeds,
        contracts=contracts or {},
        rubrics=[r[0] for r in db.conn.execute("SELECT id FROM rubrics ORDER BY id")],
        policy_versions=[r[0] for r in db.conn.execute("SELECT policy_version FROM brand_policies ORDER BY policy_version")],
        uptime_s=db.uptime_s(),
        checked_at=now_iso(),
    )
    if writable:
        with db.conn:
            db.conn.execute("INSERT INTO health_log (checked_at, status, detail) VALUES (?,?,?)",
                            (out.checked_at, out.status, json.dumps({"seeds": seeds, "uptime_s": out.uptime_s})))
    return out
