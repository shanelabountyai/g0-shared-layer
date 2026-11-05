# Backlog — G0 Shared Capability Layer

Each task ends with a passing test and a commit on `kickoff`. Acceptance criteria (AC) are the PRD's (`docs/prd.md` §Acceptance criteria), narrowed to G0·C where the PRD speaks of B and M:

- **AC 1 (C half):** all six capabilities callable over MCP, each with a contract test.
- **AC 3:** a breaking contract change fails the contract tests until the version is bumped.
- **AC 5 (G1 half):** a before/after count of integrations and duplicated rules for G1.
- AC 2 (G1 re-pointed, identical digest) and AC 4 (A2 migration) belong to G1·C and G0·M, not this run.

Status: `todo` · `doing` · `done` · `blocked`.

## G0·C (this run)

| # | Task | Done when | Status |
|---|---|---|---|
| C0 | Decisions and backlog. `docs/DECISIONS.md` carries the owner's ten decisions plus the run's own; this file splits the run. | Both files committed before any code. | done |
| C1 | Contracts. `contracts/<capability>/v1.json` for the six capabilities and `health`: the advertised input and output schema, `version` in both. `tests/contracts/` pins a golden copy and checks the live models generate the same schema. | `pytest tests/contracts` passes; editing a model field without bumping the version fails it (AC 3). | todo |
| C2 | Storage and seeds. SQLite schema (`claims`, `brand_policies`, `brand_rules`, `contacts`, `consent`, `events`, `run_log`, `health_log`, `rubrics`, `evaluations`), seed loader, seeds: claims from the evidence brief's safe rows, brand policy v1 from G1's `brand_voice`, ~20 synthetic contacts, three rubrics. | Fresh db seeds idempotently; counts match the seed files; no `example.com`-free email anywhere in `contacts`. | todo |
| C3 | `claims.registry`: text or claims list → supported / unsupported / needs_source with source. Unit test on the seeded registry. | Known stat is supported with its source; wrong number is unsupported; unknown topic needs a source. | todo |
| C4 | `brand.policy`: text + channel → pass/fail with violations (rule id, excerpt, fix). Unit test. | Every never-use phrase, emoji, and a 26-word post angle are caught; clean text passes. | todo |
| C5 | `audience.consent`: contact id or email + channel → allowed / blocked + reason. Unit test. | Fixture flags are honoured; unknown contact and `do_not_contact` are blocked. | todo |
| C6 | `measurement`: event + fields → stored event id. Unit test. | Row round-trips; id is unique; fields stored as JSON. | todo |
| C7 | `observability`: run id, agent, step, tokens, cost, status → logged, with run total and cap flag. Unit test. | Total accumulates per run; `over_cap` flips past $10. | todo |
| C8 | `evaluation`: rubric id + item → scores, pass/fail, notes; pluggable judge, deterministic fallback, fixture. Unit test. | Deterministic judge scores the three rubrics; fixture judge replays; Claude judge refuses without a key and past the cap. | todo |
| C9 | `health` tool + uptime log. Unit test. | Reports db, seeds, contract versions; writes a `health_log` row. | todo |
| C10 | MCP server over stdio exposing the seven tools, errors as typed results; end-to-end test that starts the server as a subprocess and calls every tool through an MCP client. | `pytest tests/e2e` passes; `tools/list` shows seven tools with input and output schemas equal to the contracts (AC 1). | todo |
| C11 | Docs: `README.md` for a reviewer; `docs/attach.md` with the G1 before/after counts (AC 5); `NEXT.md` with the owner's hand steps (G0·B n8n build, G1·C start, judge confirmation). | Reviewer can run the tests and the server from the README alone. | todo |
| C12 | Push `kickoff`; open one PR against `main`; do not merge. | PR open with test counts, stubs, cost and hand steps. | todo |

## Later runs

| # | Task | Status |
|---|---|---|
| B | G0·B: one n8n sub-workflow per capability, built by the owner from `contracts/`. | todo (owner) |
| M | G0·M: A2 (`opsagent`) migration on a branch after G0·C merges; frozen test cases, before/after counts (AC 4, AC 5 A2 half). | todo |
| G1·C | First consumer: attach per `docs/attach.md`; identical digest on a fixed week (AC 2). | todo |
