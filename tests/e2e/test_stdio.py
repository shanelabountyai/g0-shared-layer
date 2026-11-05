"""C10 (AC 1): the real server, as a subprocess over stdio, driven by a real MCP client.

What is asserted is what a consumer sees: seven tools listed with the contract
schemas, every tool answering, refusals arriving inside the output schema,
and a malformed argument arriving as a protocol-level error.
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from shared_layer import contracts

REPO = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def connect(tmp_path):
    """The server as a subprocess over stdio. A context manager, not an async fixture:
    pytest-asyncio tears async fixtures down in another task, which anyio's cancel
    scopes refuse."""
    env = {
        "G0_DB_PATH": str(tmp_path / "e2e.sqlite"),
        "G0_EVAL_FIXTURE": str(REPO / "tests" / "fixtures" / "evaluation_fixture.json"),
        "G0_RUN_CAP_USD": "10",
        "PYTHONPATH": str(REPO / "src"),
        "ANTHROPIC_API_KEY": "",  # the e2e run never makes a live model call
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "shared_layer.server"], env=env, cwd=str(REPO))
    async with Client(params) as c:
        yield c


def _published(capability: str) -> dict:
    module = next(m for m in contracts.CAPABILITIES if m.CAPABILITY == capability)
    return json.loads(contracts.contract_path(module).read_text(encoding="utf-8"))


async def test_tools_list_matches_the_published_contracts(tmp_path):
    async with connect(tmp_path) as client:
        listed = {t.name: t for t in (await client.list_tools()).tools}
        assert sorted(listed) == sorted(m.TOOL for m in contracts.CAPABILITIES)
        for m in contracts.CAPABILITIES:
            doc = _published(m.CAPABILITY)
            tool = listed[m.TOOL]
            assert tool.input_schema == doc["input"], f"{m.TOOL}: advertised inputSchema differs from contracts/"
            assert tool.output_schema == doc["output"], f"{m.TOOL}: advertised outputSchema differs from contracts/"
            assert tool.description == m.DESCRIPTION
            assert tool.meta["contract_version"] == m.VERSION and tool.meta["capability"] == m.CAPABILITY
        assert listed["claims_registry"].annotations.read_only_hint is True
        assert listed["measurement"].annotations.read_only_hint is False


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content
    data = result.structured_content
    Draft202012Validator(_published(next(m.CAPABILITY for m in contracts.CAPABILITIES if m.TOOL == name))["output"]).validate(data)
    return data


async def test_every_tool_answers_over_stdio(tmp_path):
    async with connect(tmp_path) as client:
        h = await call(client, "health", {})
        assert h["ok"] and h["status"] == "ok" and h["seeds"]["contacts"] == 20 and h["db_path"].endswith("e2e.sqlite")

        c = await call(client, "claims_registry", {"text": "Only 39% of companies report any EBIT impact from AI. Pilots stall on ownership."})
        assert c["ok"] and len(c["results"]) == 1 and c["results"][0]["status"] == "supported"

        b = await call(client, "brand_policy", {"text": "Humbled to announce a game-changer.", "channel": "post_angle"})
        assert b["ok"] and b["passed"] is False and {v["rule_id"] for v in b["violations"]} == {"never_use.humbled", "never_use.game_changer"}

        a = await call(client, "audience_consent", {"email": "ada.test01@example.com", "channel": "email"})
        assert a["ok"] and a["allowed"] and a["contact_id"] == "ct-001"
        a2 = await call(client, "audience_consent", {"contact_id": "ct-007", "channel": "sms"})
        assert not a2["allowed"] and a2["reason"] == "do_not_contact"

        m = await call(client, "measurement", {"event": "digest.published", "fields": {"items": 7}, "run_id": "e2e-1", "agent": "Editor"})
        assert m["ok"] and m["event_id"].startswith("evt_")

        o1 = await call(client, "observability", {"run_id": "e2e-1", "agent": "Editor", "step": "pick", "model": "claude-sonnet-5-5", "input_tokens": 4000, "output_tokens": 500, "cost_usd": 0.013})
        o2 = await call(client, "observability", {"run_id": "e2e-1", "agent": "Writer", "step": "draft", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001})
        assert o1["run_total"]["calls"] == 1 and o2["run_total"]["calls"] == 2 and o2["run_total"]["cost_usd"] == pytest.approx(0.014) and not o2["over_cap"]

        e = await call(client, "evaluation", {"rubric_id": "post_angle_v1", "item": "Twelve intake steps became one; the queue vanished in a week.", "judge": "auto"})
        assert e["ok"] and e["judge"] == "deterministic" and e["passed"] and e["usage"] is None
        f = await call(client, "evaluation", {"rubric_id": "claim_rule_v1", "item": "x", "judge": "fixture"})
        assert f["judge"] == "fixture" and f["passed"] and f["usage"]["model"] == "claude-sonnet-5-5"

        h2 = await call(client, "health", {})
        assert h2["uptime_s"] >= h["uptime_s"]


async def test_refusals_are_typed_results_inside_the_output_schema(tmp_path):
    async with connect(tmp_path) as client:
        e = await call(client, "evaluation", {"rubric_id": "missing", "item": "x"})
        assert e["ok"] is False and e["error"]["code"] == "UNKNOWN_RUBRIC" and e["error"]["next"]["tool"] == "health"

        j = await call(client, "evaluation", {"rubric_id": "post_angle_v1", "item": "x", "judge": "claude"})
        assert j["ok"] is False and j["error"]["code"] == "JUDGE_UNAVAILABLE"

        a = await call(client, "audience_consent", {"channel": "email"})
        assert a["ok"] is False and a["error"]["code"] == "INVALID_ARGUMENT"

        p = await call(client, "brand_policy", {"text": "x", "channel": "email", "policy_version": "42"})
        assert p["ok"] is False and p["error"]["code"] == "UNKNOWN_POLICY" and p["error"]["field"] == "policy_version"


async def test_a_malformed_argument_is_a_protocol_error(tmp_path):
    async with connect(tmp_path) as client:
        result = await client.call_tool("brand_policy", {"text": "x", "channel": "carrier-pigeon"})
        assert result.is_error
        assert "channel" in result.content[0].text


async def test_state_persists_across_calls_in_the_same_db(tmp_path):
    async with connect(tmp_path) as client:
        await call(client, "measurement", {"event": "a.b"})
        await call(client, "measurement", {"event": "a.b"})
        import sqlite3

        n = sqlite3.connect(tmp_path / "e2e.sqlite").execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert n == 2
