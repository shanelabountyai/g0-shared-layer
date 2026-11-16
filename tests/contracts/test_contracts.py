"""Contract tests (D-3, D-13, D-14; AC 3).

Three locks on every capability:
1. `contracts/<capability>/v<N>.json` equals the golden copy under `tests/contracts/golden/` byte for byte.
2. The live server generates exactly that document (so a model edit without a version bump fails here).
3. Every input and output schema carries `version` with the same const as the file name, the output
   carries `ok` and `error`, and a real call's structured result validates against the output schema.

To change a shape: bump `VERSION` in the capability module, run
`python -m shared_layer.contracts export`, copy the new file to golden, and keep the old file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shared_layer import contracts
from shared_layer.server import build_server

GOLDEN = Path(__file__).parent / "golden"

EXAMPLE_INPUTS: dict[str, dict] = {
    "claims.registry": {"version": "1", "claims": ["88% of orgs use AI in at least one function"]},
    "brand.policy": {"version": "1", "text": "Excited to share a game-changer", "channel": "linkedin"},
    "audience.consent": {"version": "1", "email": "ada.test01@example.com", "channel": "email"},
    "measurement": {"version": "1", "event": "digest.published", "fields": {"items": 7}},
    "evaluation": {"version": "1", "rubric_id": "post_angle_v1", "item": "One real number beats a generality.", "judge": "deterministic"},
    "observability": {"version": "1", "run_id": "run-1", "agent": "Editor", "step": "pick", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001},
    "health": {"version": "1"},
}


@pytest.fixture(scope="module")
def live() -> dict[str, dict]:
    return contracts.build_contracts()


@pytest.fixture(scope="module")
def server():
    return build_server(db_path=":memory:")


def _published(module) -> dict:
    path = contracts.contract_path(module)
    assert path.exists(), f"missing published contract {path}; run `python -m shared_layer.contracts export`"
    return json.loads(path.read_text(encoding="utf-8"))


def _golden(module) -> dict:
    path = GOLDEN / module.CAPABILITY / f"v{module.VERSION}.json"
    assert path.exists(), f"missing golden copy {path}; a new version needs a new golden file"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_capability_has_a_contract_and_a_golden():
    assert len(contracts.CAPABILITIES) == 7
    for m in contracts.CAPABILITIES:
        _published(m)
        _golden(m)


@pytest.mark.parametrize("module", contracts.CAPABILITIES, ids=lambda m: m.CAPABILITY)
def test_published_equals_golden_byte_for_byte(module):
    pub = contracts.contract_path(module).read_bytes()
    gold = (GOLDEN / module.CAPABILITY / f"v{module.VERSION}.json").read_bytes()
    assert pub == gold, f"{module.CAPABILITY}: contracts/ differs from golden; bump the version and add a new file"


@pytest.mark.parametrize("module", contracts.CAPABILITIES, ids=lambda m: m.CAPABILITY)
def test_live_models_generate_the_published_contract(module, live):
    assert live[module.CAPABILITY] == _published(module), (
        f"{module.CAPABILITY}: the models changed shape but contracts/{module.CAPABILITY}/v{module.VERSION}.json did not; "
        "bump VERSION, export, and add a golden copy"
    )


@pytest.mark.parametrize("module", contracts.CAPABILITIES, ids=lambda m: m.CAPABILITY)
def test_version_fields_and_envelope(module):
    doc = _published(module)
    assert doc["version"] == module.VERSION
    assert doc["capability"] == module.CAPABILITY
    assert doc["tool"] == module.TOOL
    for side in ("input", "output"):
        props = doc[side]["properties"]
        assert props["version"]["const"] == module.VERSION, f"{module.CAPABILITY} {side} lacks version const"
    out = doc["output"]["properties"]
    assert out["ok"]["type"] == "boolean"
    assert "error" in out
    assert out["capability"]["const"] == module.CAPABILITY
    assert doc["output"]["additionalProperties"] is False
    assert set(doc["output"].get("required", [])) == set()  # every output field has a default: a refusal is always expressible
    Draft202012Validator.check_schema(doc["input"])
    Draft202012Validator.check_schema(doc["output"])


@pytest.mark.parametrize("module", contracts.CAPABILITIES, ids=lambda m: m.CAPABILITY)
def test_example_input_validates_and_result_matches_output_schema(module, server):
    import anyio

    doc = _published(module)
    example = EXAMPLE_INPUTS[module.CAPABILITY]
    Draft202012Validator(doc["input"]).validate(example)
    module.Input.model_validate(example)

    result = anyio.run(server.call_tool, module.TOOL, example)
    assert not result.is_error
    Draft202012Validator(doc["output"]).validate(result.structured_content)
    assert result.structured_content["ok"] is True
    assert result.structured_content["version"] == module.VERSION


@pytest.mark.parametrize("module", contracts.CAPABILITIES, ids=lambda m: m.CAPABILITY)
def test_input_model_and_advertised_schema_agree(module):
    """The tool signature is derived from the Input model; nothing may be dropped on the way."""
    doc = _published(module)
    model_schema = module.Input.model_json_schema()
    assert set(doc["input"]["properties"]) == set(model_schema["properties"])
    assert set(doc["input"].get("required", [])) == set(model_schema.get("required", []))


def test_a_refusal_fits_the_output_schema(server):
    """D-14: an error travels inside the output contract, not as a protocol error."""
    import anyio

    doc = _published(contracts.evaluation)
    result = anyio.run(server.call_tool, "evaluation", {"rubric_id": "does-not-exist", "item": "x"})
    assert not result.is_error
    Draft202012Validator(doc["output"]).validate(result.structured_content)
    assert result.structured_content["ok"] is False
    assert result.structured_content["error"]["code"] == "UNKNOWN_RUBRIC"


def test_a_changed_shape_is_detected():
    """Simulate editing a model without bumping the version: the generated schema no longer matches."""
    from pydantic import Field, create_model

    Changed = create_model("Changed", __base__=contracts.measurement.Output, surprise=(int, Field(default=0)))
    assert Changed.model_json_schema() != contracts.measurement.Output.model_json_schema()
    assert "surprise" in Changed.model_json_schema()["properties"]
    assert "surprise" not in _published(contracts.measurement)["output"]["properties"]
