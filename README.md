# g0-shared-layer — Shared Capability Layer (G0·C)

Six capabilities every agent in the Agentic AI track needs — **claims.registry, brand.policy, audience.consent, measurement, evaluation, observability** — built once, behind one Python MCP server, with versioned contracts. G1 was built without this layer on purpose and carried every rule in every agent's prompt (`g1-signal-scout/docs/duplication-log.md`). This repo is where those rules now live. G1·C, G2–G5 and the migrated A2 Marketing-Ops Agent attach here instead of carrying their own copies.

This README is written for someone deciding whether the engineering is sound. The spec is `docs/prd.md`; every decision is numbered in `docs/DECISIONS.md`; how a consumer attaches is `docs/attach.md`; current state and the owner's hand steps are in `NEXT.md`.

## What it does

| An agent asks… | Tool | What is guaranteed |
|---|---|---|
| "Is '88% of orgs use AI' a number I may publish?" | `claims_registry` | Checked against the seeded registry (the evidence brief's **safe-to-use rows only**, each with publisher, sample, date and URL). `supported` comes with its source; a wrong number against a known stat is `unsupported` and names the row it contradicts; anything the registry cannot speak to is `needs_source`, never silently passed. No model call, no web search. |
| "Does this post angle break the brand voice?" | `brand_policy` | The G1 `brand_voice` rule, verbatim, is the policy text; the never-use list, emoji and beginner voice are enforced on every channel, the one-sentence/25-word limit on `post_angle`. Every violation carries the rule id, the excerpt and a fix. What a rule engine cannot judge (hype, pitch) is explicitly left to `evaluation`. |
| "May I email this contact?" | `audience_consent` | Fails closed: unknown contact, unknown channel, missing flag or do-not-contact is `allowed: false` with a reason. Only synthetic contacts exist in this repo (20, all `@example.com`); the seed loader refuses anything else. The result never carries a name or an email. |
| "Record that the digest went out." | `measurement` | Append-only insert with a stored id. No schema per event; the event name is the contract. No personal data belongs in `fields`. |
| "Score this item against the rubric." | `evaluation` | A pluggable judge. Deterministic by default (one check per criterion); a Claude judge when a key is present, with tokens and cost logged per call and refused past the cap; a fixture judge for tests. Pass/fail is decided in one place from required criteria and a threshold. |
| "Log this model call; am I over budget?" | `observability` | G1's `run_logging` rule in one place: per-step tokens and cost, the run's running total, and `over_cap` against the $10 cap. Logging is never refused, so an overrun is visible, not hidden. |
| "Is the layer up?" | `health` | DB path and writability, seed counts, contract versions, rubric and policy ids, uptime; writes a row to the uptime log. |

Deliberately **not** exposed: anything that edits or deletes a registry row, a contact, a policy or a log. Seeds change through a commit and a version, not through a tool a model can call.

## The contracts

Every tool's input and output is a JSON Schema in `contracts/<capability>/v1.json` — the file is the tool's advertised `inputSchema` and `outputSchema`, generated from the Pydantic models, so **what n8n (G0·B) is built against is exactly what the MCP client sees** (D-13). Every input and output carries `version`; every output carries `ok` and, when `ok` is false, `error: {code, message, field, next: {tool, why}}` **inside the schema** (D-14), so a client that validates structured results — Claude's do — never rejects a refusal. Only an unknown tool or an argument that fails the input schema is a protocol-level `isError`.

| Capability | Tool | Input (required in bold) | Output |
|---|---|---|---|
| `claims.registry` v1 | `claims_registry` | `text` *or* `claims[]` | `results[]: {claim, status: supported\|unsupported\|needs_source, matched_on, source{registry_id, publisher, title, sample, url, stat}, note}`, `registry_size` |
| `brand.policy` v1 | `brand_policy` | **`text`**, **`channel`** ∈ linkedin\|email\|digest\|post_angle\|other, `policy_version`="1" | `passed`, `violations[]: {rule_id, severity, excerpt, fix}`, `policy_version`, `rules_checked` |
| `audience.consent` v1 | `audience_consent` | `contact_id` *or* `email`, **`channel`** ∈ email\|linkedin\|sms\|phone | `allowed`, `reason` ∈ consented\|not_consented\|do_not_contact\|unknown_contact\|no_flag_for_channel, `contact_id`, `checked_at` |
| `measurement` v1 | `measurement` | **`event`** (dotted lower-case), `fields{}`, `occurred_at`, `run_id`, `agent` | `event_id`, `event`, `stored_at` |
| `evaluation` v1 | `evaluation` | **`rubric_id`**, **`item`** (string or object), `context`, `judge` ∈ auto\|deterministic\|claude\|fixture, `run_id` | `evaluation_id`, `judge`, `scores[]: {criterion, score 0–1, weight, required, note}`, `total`, `passed`, `notes`, `usage{model, tokens, cost_usd}` or null |
| `observability` v1 | `observability` | **`run_id`**, **`agent`**, **`step`**, `model`, `input_tokens`, `output_tokens`, `cost_usd`, `status` ∈ ok\|error\|skipped, `duration_ms`, `note` | `log_id`, `logged_at`, `run_total{calls, input_tokens, output_tokens, cost_usd}`, `cap_usd`, `over_cap` |
| `health` v1 | `health` | — | `status` ∈ ok\|degraded, `db_path`, `db_writable`, `seeds{}`, `contracts{}`, `rubrics[]`, `policy_versions[]`, `uptime_s` |

Examples (input → the part of the output that matters):

```jsonc
// claims_registry
{"version":"1","claims":["95% of orgs use AI in at least one function"]}
// → results[0]: {"status":"unsupported","matched_on":"topic",
//     "source":{"registry_id":"mckinsey-2025-adoption-ebit","publisher":"McKinsey",…,"stat":"88% of orgs use AI …"},
//     "note":"Shares 3 topic words with the McKinsey row but its number(s) ['95%'] are not that row's ['39%','5%','88%'] …"}

// brand_policy
{"version":"1","text":"Excited to share this game-changer 🚀","channel":"linkedin"}
// → {"passed":false,"violations":[{"rule_id":"never_use.excited_to_share","excerpt":"Excited to share this game-…","fix":"Cut the opener; start with the moment or the number."}, …]}

// audience_consent
{"version":"1","email":"ada.test01@example.com","channel":"email"}
// → {"allowed":true,"reason":"consented","contact_id":"ct-001"}

// measurement
{"version":"1","event":"digest.published","fields":{"items":7},"run_id":"2026-11-09","agent":"Editor"}
// → {"event_id":"evt_…","stored_at":"2026-11-05T22:42:28.602Z"}

// evaluation
{"version":"1","rubric_id":"post_angle_v1","item":"At 1,000 projects a year, the intake form was the bottleneck, not the people."}
// → {"judge":"deterministic","total":1.0,"passed":true,"scores":[{"criterion":"one_sentence","score":1.0,…},…],"usage":null}

// observability
{"version":"1","run_id":"2026-11-09","agent":"Editor","step":"pick","model":"claude-sonnet-5-5","input_tokens":4000,"output_tokens":500,"cost_usd":0.013}
// → {"run_total":{"calls":1,"cost_usd":0.013,…},"cap_usd":10.0,"over_cap":false}

// a refusal, inside the output schema
{"version":"1","rubric_id":"does-not-exist","item":"x"}
// → {"ok":false,"error":{"code":"UNKNOWN_RUBRIC","message":"No rubric 'does-not-exist'. Known: […]","field":"rubric_id","next":{"tool":"health","why":"lists the seeded rubrics"}}}
```

Error codes: `INVALID_ARGUMENT`, `NOT_FOUND`, `UNKNOWN_RUBRIC`, `UNKNOWN_POLICY`, `JUDGE_UNAVAILABLE`, `OVER_CAP`, `STORAGE_ERROR` (`src/shared_layer/errors.py`).

## How it is built

- **Python 3.12, `uv`, `pyproject.toml`**, src layout. Package `shared_layer`, distribution `g0-shared-layer`, console script `g0-shared-layer` (the stdio server). Dependencies: `mcp` 2.3 (the official Python MCP SDK; `MCPServer`, formerly `FastMCP` — D-11), `pydantic` 2. The Anthropic SDK is an optional extra (`[judge]`).
- **One capability = one module** in `src/shared_layer/capabilities/`: `Input`, `Output`, `VERSION`, `DESCRIPTION`, `run(db, input)`. The server (`server.py`) builds every tool the same way: the argument signature is derived from `Input` (constraints and descriptions included), the return type is `Output`, and every `Refusal` becomes `Output(ok=False, error=…)`.
- **Storage is SQLite, one file** (`G0_DB_PATH`, default `~/.g0-shared-layer/layer.sqlite`). Seeds ship inside the package (`src/shared_layer/seeds/*.json`) and load idempotently on start; consumer rows (events, run_log, health_log, evaluations) are never touched by seeding.
- **Seeds:** 9 claims (the evidence brief's safe rows, with sources), brand policy v1 (G1's `brand_voice`, verbatim, plus 12 enforceable rules), 20 synthetic contacts with per-channel flags, 3 rubrics (`post_angle_v1`, `claim_rule_v1`, `digest_item_v1`) whose criteria come from G1's shared rules.
- **No live model call is needed** for five capabilities. `evaluation` may call Claude; in this build no key was present, so no call was made and the Claude judge is exercised only with a fake client in tests (D-19).

## How it is tested

117 tests, all without network or a model call: `uv run pytest`.

- **`tests/contracts/`** (38) — three locks per capability: the published file equals the golden copy byte for byte; the live models generate exactly the published file; `version`/`ok`/`error` are present and a real call's result validates against the output schema. One test shows a shape edit without a bump is caught. **A breaking contract change fails here until the version is bumped** (AC 3).
- **`tests/unit/`** (74) — storage and seeds (synthetic-only enforcement, the banned figures from the brief are absent, idempotence), and one file per capability. The evaluation tests drive the Claude judge with a fake Anthropic client: cost arithmetic, the run-log entry, the cap refusal with zero calls made, the no-key refusal.
- **`tests/e2e/test_stdio.py`** (5) — the server as a **subprocess over stdio**, driven by the SDK's `Client`: `tools/list` equals `contracts/` on the wire, every tool answers, refusals arrive inside the output schema, a malformed argument is a protocol error, state persists in the file.

## Running it

```bash
uv sync --all-groups --extra judge      # Python 3.12 venv, dev tools, optional Anthropic SDK
uv run pytest                           # 117 tests, ~6 s, no network
uv run g0-shared-layer                  # the server over stdio (nothing on stdout but protocol)

# Register with Claude Code / Claude Desktop
claude mcp add --transport stdio g0 --env G0_DB_PATH=$HOME/.g0-shared-layer/layer.sqlite -- uv run --directory /path/to/g0-shared-layer g0-shared-layer

# Regenerate the published contracts from the models (only when bumping a version)
uv run python -m shared_layer.contracts export
```

Environment (names in `.env.example`; values never in the repo): `G0_DB_PATH`, `G0_RUN_CAP_USD` (default 10), `G0_JUDGE_MODEL` (default `claude-sonnet-5-5`), `G0_EVAL_FIXTURE`, `ANTHROPIC_API_KEY` (only for the Claude judge).

## How to bump a contract version

A shape change is a new version, never an edit (D-3). The tests make the lazy path fail:

1. Change the `Input`/`Output` model in `src/shared_layer/capabilities/<capability>.py` **and** set `VERSION = "2"` there (both `Literal["…"]` fields follow).
2. `uv run python -m shared_layer.contracts export` → writes `contracts/<capability>/v2.json`. Leave `v1.json` in place; consumers pinned to v1 keep reading it.
3. Copy `v2.json` to `tests/contracts/golden/<capability>/v2.json`.
4. Add a D- entry to `docs/DECISIONS.md` saying what changed and why; tag the release; consumers move their pin on their own schedule.

If you change a model and skip step 1, `test_live_models_generate_the_published_contract` fails. If you re-export over `v1.json`, `test_published_equals_golden_byte_for_byte` fails. If you edit the golden too, the diff in the PR shows a contract edit without a version — which is what review is for.

## The single point of failure, and what mitigates it

Three agents carrying six tools each is 18 integrations and 3 copies of the rules; with the layer it is 9 and 1 copy (G1's own count: `docs/attach.md`). The price is that everything now depends on one thing. What this build does about that:

- **Contract tests as change control.** No shape moves without a version and a golden file; every consumer pins a tag.
- **Refusals the caller can act on.** Every failure is a typed result with `code`, `field` and `next`; a consumer never has to parse an exception string.
- **A health tool and an uptime log.** A consumer calls `health` first; a degraded seed or an unwritable file is reported, not discovered mid-run.
- **No network inside the layer.** Five capabilities are deterministic and local (SQLite); only the optional Claude judge leaves the process, and it is capped, logged and refusable. The layer's own failure modes are a missing file or a bad seed, both tested.
- **A one-file store.** Backup is `cp`; the schema is created on open; seeds reload idempotently.
- **Logging never blocks.** `observability` returns `over_cap` but never refuses a write, so the audit trail is complete even on a bad run.

What it does **not** do yet, honestly: no HTTP transport or auth (stdio only, one consumer per process); no rate limits; the Claude judge has never run live (prices and model id are carried from G1 and must be confirmed before the first call — `NEXT.md`); the evaluation fixture is a hand-written sample, not a recording; rubric criteria for "specific" and "no hype" are heuristics and say so in their notes.

## Layout

```
contracts/<capability>/v1.json      published contracts (what the client sees)
docs/{prd,DECISIONS,BACKLOG,attach}.md
src/shared_layer/
  server.py          MCPServer, seven tools, stdio
  contracts.py       registry of capabilities + exporter
  storage.py         SQLite schema, seed loader
  errors.py          the error envelope and Refusal
  text.py            deterministic text helpers
  capabilities/      one module per capability + health
  seeds/             claims, brand policy v1, synthetic contacts, rubrics
tests/{contracts,unit,e2e}/, tests/fixtures/evaluation_fixture.json
```
