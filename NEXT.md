# NEXT

State (2026-11-05, end of the unattended G0·C run on Fable): **G0·C built on branch `kickoff`**, one PR open against `main`, unmerged. 117 tests pass (38 contract, 74 unit, 5 end-to-end over stdio); none skipped, none failing. **Cost of live model calls this run: $0.00** — no `ANTHROPIC_API_KEY` was present, so no call was made.

## Done

- Seven versioned contracts in `contracts/` with golden copies and three locks each (`tests/contracts/`).
- SQLite storage, idempotent seeds: 9 claims (evidence brief, safe rows only), brand policy v1 (G1 `brand_voice`, verbatim), 20 synthetic contacts, 3 rubrics.
- Six capabilities + `health`, each with unit tests; one MCP server over stdio (`uv run g0-shared-layer`); end-to-end test through a real MCP client.
- `README.md` for a reviewer; `docs/attach.md` with the G1 before/after counts (7 duplicated rules → 0; 24 copies → 8; 16 integrations → 8); `docs/DECISIONS.md` D-1..D-22; `docs/BACKLOG.md` C0–C12 done.

## Stubbed or deferred (said plainly)

- **evaluation's Claude judge has never run live.** It is implemented (`ClaudeJudge`), capped, logged, and tested with a fake client only. `judge: "auto"` falls back to the deterministic judge without a key. The model id (`claude-sonnet-5-5`) and the price table are **carried from G1 D-8** (cache dated 2026-10-06); the run could not fetch Anthropic's pricing page (URL permission not grantable unattended).
- **`tests/fixtures/evaluation_fixture.json` is a hand-written sample** in the judge's output shape, labelled as such in the file. It is not a recording.
- The SDK's v2 migration guide could not be fetched either; the installed `mcp` 2.3.0 source was read instead (D-11). The API used is small (`MCPServer`, `add_tool`, `run("stdio")`, `Client`, `StdioServerParameters`) and covered by the e2e test.
- No HTTP transport, no auth, no rate limits: stdio, one consumer per process. Fine for G1·C on the owner's Mac; a later card if n8n needs to call C directly.
- `audience.consent` channels are `email|linkedin|sms|phone`. G1 needs none of them; the fixture exists so G2–G5 start with a consent check in place.

## Owner's hand steps

1. **Review the `kickoff` PR.** Merge only on your own say-so; tag `v0.1.0` after merging so consumers can pin it.
2. **Confirm the judge before any live call** (D-19): open Anthropic's pricing page, check the model id and the per-MTok prices in `src/shared_layer/capabilities/evaluation.py` (`PRICES_PER_MTOK`, `DEFAULT_JUDGE_MODEL`), fix them if they moved, then run one live evaluation with `ANTHROPIC_API_KEY` set and `judge: "claude"` and replace `tests/fixtures/evaluation_fixture.json` with the recorded result (keep the `_about` honest).
3. **Replace the old docs-only folder:** `rm -rf ~/Projects/agentic-track/shared && git clone https://github.com/shanelabountyai/g0-shared-layer ~/Projects/agentic-track/shared`.
4. **G0·B — n8n, by hand, from the contracts.** One sub-workflow per capability (seven with `health`):
   - Workflows → new → **Execute Workflow Trigger**; set its input fields to `contracts/<capability>/v1.json → input.properties` (names and types), `version` included.
   - Data Tables: `claims`, `brand_rules`, `contacts`, `consent`, `events`, `run_log`, `health_log`; seed rows from `src/shared_layer/seeds/*.json` (contacts stay synthetic).
   - Logic per capability: `claims.registry` = Code node with the number-normalize + topic-overlap rule from `claims_registry.py`; `brand.policy` = Code node looping the rules table; `audience.consent` = Data Table lookup with the fail-closed branches; `measurement`/`observability` = Data Table insert then a `SUM` for the run total; `evaluation` = Code node with the deterministic checks (model judge optional later); `health` = counts.
   - Return an object shaped like `output` with `version: "1"`, `ok`, `error` (null on success).
   - Acceptance: run each sub-workflow on the example inputs in `tests/contracts/test_contracts.py` and validate the result against the schema (the Code node can `require('ajv')` if allowed, or paste into any JSON Schema validator).
   - Re-point G1·B's prompts the same way `docs/attach.md` §Steps describes for G1·C, then count before/after.
5. **Start G1·C** (`g1-signal-scout` BACKLOG C1–C6) with `docs/attach.md` as the spec for the attachment; pin the layer by tag.
6. **G0·M** after the PR merges: branch in `opsagent`, freeze A2's test cases, swap campaign QA → `brand_policy` + `evaluation`, routing → `audience_consent`, audit log → `observability` + `measurement`; report differences and the A2 before/after counts.

## Next items

- G1·C attach (AC 2: identical digest on a fixed week).
- G0·M (AC 4; AC 5 A2 half).
- v1.1 candidates, each a new contract version: HTTP transport with a token, per-event schemas in `measurement`, a `claims.registry` write path behind an owner approval, brand policy v2 from the personal-brand skill.
