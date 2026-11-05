# Attaching a consumer to the shared layer

How an agent stops carrying its own rules and calls this layer instead. G1·C is the first consumer; G2–G5 and the A2 migration (G0·M) follow the same steps.

## The counts for G1 (from `g1-signal-scout/docs/duplication-log.md`, branch `kickoff`, 2026-11-05)

G1 has four agents (Researcher, Summarizer, Editor, Writer). The log lists what each carried.

**Rules duplicated in prompts**

| Rule | Carried by | Copies before | After attaching | Where it lives after |
|---|---|---|---|---|
| `topic_brief` | Researcher, Summarizer, Editor, Writer | 4 | 1 | G1·C's own config: it is G1's topic, not a shared capability. One constant, injected into each prompt. |
| `claim_rule` | Researcher, Summarizer, Editor, Writer | 4 | 1 | **G0** — `claims_registry` checks every number; `evaluation` rubric `claim_rule_v1` checks numbers, URLs and quotes against the source item. The prompt keeps a one-line pointer, not the rule. |
| `brand_voice` | Editor, Writer | 2 | 1 | **G0** — brand policy v1 (`brand_policy`) + rubric `post_angle_v1` (`evaluation`). |
| `run_logging` | Researcher, Summarizer, Editor, Writer | 4 | 1 | **G0** — `observability` (per-step log, run total, cap). |

**Rules duplicated in code**

| Rule | Copies before | After | Where |
|---|---|---|---|
| Join model output back to the record by id; drop unknown ids | 3 | 1 | G1·C helper (G1-specific plumbing). |
| Parse the first text block of a structured-output response | 3 | 1 | G1·C helper, or the Anthropic SDK's typed response. |
| Messages API request shape | 3 (+3 HTTP nodes) | 1 | G1·C via the SDK; `observability` receives the `usage` block. |
| Token and cost accounting at D-8 prices | 1 in n8n, a 2nd planned for G1·C | 1 | **G0** — `observability` holds the cap; `evaluation` holds the price table. |

**Totals for G1**

| | Before | After |
|---|---|---|
| Rules carried by more than one agent | **7** (4 prompt + 3 code) | **0** |
| Copies of the 8 shared rules | **24** (14 prompt + 10 code) | **8** (4 in G0, 4 single helpers in G1·C) |
| Integrations (agents × capabilities each would carry itself) | **16** (4 agents × 4 capabilities G1 uses: claims, brand, evaluation, observability) | **8** (4 agents × 1 MCP connection + 4 capabilities built once) — or 10 counting all 6 capabilities in the layer |

AC 5 (G1 half) is this table. The A2 half is produced by G0·M.

## Steps for G1·C (BACKLOG C1–C6 in `g1-signal-scout`)

1. **Pin the layer.** In G1·C's `pyproject.toml`:
   ```toml
   dependencies = ["g0-shared-layer @ git+https://github.com/shanelabountyai/g0-shared-layer@v0.1.0"]
   ```
   (tag after the kickoff PR merges; until then pin the commit SHA). The local clone `~/Projects/agentic-track/shared` is for reading, not importing.
2. **Start the layer** as an MCP server over stdio from the agent process, or call the capability modules in-process (same code, no transport):
   ```python
   from shared_layer.storage import open_database
   from shared_layer.capabilities import claims_registry, brand_policy, evaluation, observability
   db = open_database()  # G0_DB_PATH or ~/.g0-shared-layer/layer.sqlite
   ```
   The Claude Agent SDK path is the MCP one: register `uv run --directory <clone> g0-shared-layer` as a stdio server and give the agents the seven tools. Over MCP every result is the contract in `contracts/`; in-process it is the same Pydantic `Output`.
3. **Call `health` first** in `scout --dry-run`; refuse to run if `status` is `degraded`.
4. **Replace the prompt rules.** Keep `topic_brief` as one constant in G1·C. Replace the verbatim `claim_rule`, `brand_voice` and `run_logging` blocks with one line each ("Numbers are checked by the claims registry; angles by the brand policy; every call is logged"), and enforce:
   - after Summarizer and Editor: `evaluation(rubric_id="claim_rule_v1", item=<summary or angle>, context=<the feed item>)` → drop or flag items that fail;
   - after Editor and Writer: `brand_policy(text=<post_angle>, channel="post_angle")` and `brand_policy(text=<post>, channel="linkedin")`, then `evaluation(rubric_id="post_angle_v1", …)`;
   - before the digest is written: `claims_registry(text=<digest>)` → any `unsupported` is a defect, any `needs_source` is shown to the owner as such.
5. **Log every model call** with `observability(run_id=<week>, agent, step, model, input_tokens, output_tokens, cost_usd)` using the `usage` block the API returns; stop the run when `over_cap` is true. Delete G1·C's own price table; costs are computed once from the response usage with the prices in `evaluation.PRICES_PER_MTOK` (owner-confirmed, see NEXT.md).
6. **Record the digest** with `measurement(event="digest.published", fields={"week", "items", "drafts"}, run_id, agent="scout")` after the Drive write succeeds, before marking items seen (G1's rule stays: seen is marked only after the write).
7. **Prove AC 2.** Run G1·C on the fixture week with the layer attached and diff the digest against G1·B's for the same week; every difference is either a caught violation (good) or a bug.
8. **Update `docs/duplication-log.md` in G1** with the after column above and cite this file.

## Rules for every consumer

- Pin a tag or SHA; never a branch. Move the pin on purpose.
- Treat `ok: false` as a result, not an exception: read `error.next`.
- Never write to the layer's SQLite file except through the tools.
- Synthetic contacts only. If a consumer has real contacts, it keeps them in its own store and asks `audience_consent` by id through an adapter the owner approves — a change that gets its own decision entry.
- A capability the consumer needs and the layer lacks is a new contract version here, not a local copy there.

## G0·B (n8n) — the same contracts by hand

Each sub-workflow starts with an Execute Workflow Trigger whose input fields are the `input.properties` of `contracts/<capability>/v1.json` and returns an object shaped like `output`, `version` included. Registries and logs go in n8n Data Tables (`claims`, `brand_rules`, `contacts`+`consent`, `events`, `run_log`), seeded from `src/shared_layer/seeds/*.json`. The acceptance test for B is the same as C's contract test: run each sub-workflow on the example inputs in `tests/contracts/test_contracts.py` and validate the output against the schema.
