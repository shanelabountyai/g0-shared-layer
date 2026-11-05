"""The contract registry and exporter (D-13).

`CAPABILITIES` is the ordered list of capability modules. Each exposes
`CAPABILITY`, `TOOL`, `VERSION`, `DESCRIPTION`, `Input`, `Output`, `run`.

`python -m shared_layer.contracts export` writes `contracts/<capability>/v<N>.json`
from the live server's advertised tool schemas: exactly what an MCP client sees.
`tests/contracts/` pins a golden copy of each file; a changed shape fails until
the version is bumped and a new file (and golden) is added.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from shared_layer.capabilities import (
    audience_consent,
    brand_policy,
    claims_registry,
    evaluation,
    health,
    measurement,
    observability,
)

CAPABILITIES: list[ModuleType] = [
    claims_registry,
    brand_policy,
    audience_consent,
    measurement,
    evaluation,
    observability,
    health,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"


def contract_versions() -> dict[str, str]:
    return {m.CAPABILITY: m.VERSION for m in CAPABILITIES}


def contract_path(module: ModuleType, root: Path = CONTRACTS_DIR) -> Path:
    return root / module.CAPABILITY / f"v{module.VERSION}.json"


def build_contracts() -> dict[str, dict[str, Any]]:
    """capability id → contract document, from the live server's tool listing."""
    from shared_layer.server import build_server

    server = build_server(db_path=":memory:")
    listed = {t.name: t for t in server._tool_manager.list_tools()}  # noqa: SLF001 - the SDK's own listing
    docs: dict[str, dict[str, Any]] = {}
    for m in CAPABILITIES:
        tool = listed[m.TOOL]
        docs[m.CAPABILITY] = {
            "capability": m.CAPABILITY,
            "tool": m.TOOL,
            "version": m.VERSION,
            "description": m.DESCRIPTION,
            "input": tool.parameters,
            "output": tool.output_schema,
        }
    return docs


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def export(root: Path = CONTRACTS_DIR) -> list[Path]:
    written = []
    for m, doc in zip(CAPABILITIES, build_contracts().values(), strict=True):
        path = contract_path(m, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(doc), encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args[:1] == ["export"]:
        for p in export():
            print(p.relative_to(REPO_ROOT))
        return 0
    print("usage: python -m shared_layer.contracts export", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
