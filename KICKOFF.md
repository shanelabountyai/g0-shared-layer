# Kickoff — Shared Capability Layer, G0·C (Build Log G0, Agentic AI track)

Owner's reorder (2026-11-05): G0·C (code) is built first and unattended on Fable; G0·B (n8n) the owner builds by hand afterwards from the contracts; G0·M (A2 migration) comes after G0·C. The gate "start only after G1·B passes" is cleared: G1·B shipped 2026-11-05 and `docs/duplication-log.md` exists on `g1-signal-scout` branch `kickoff`.

The block below is the prompt of the scheduled cloud run. Keep this file in sync with any later run.

```
You are starting a new build: the Shared Capability Layer, code version (Build Log G0·C,
Agentic AI track), in the repo shanelabountyai/g0-shared-layer. Clone it, read docs/prd.md,
CLAUDE.md and README.md fully before doing anything. Work on branch `kickoff`; commit after
every task; push the branch; open ONE pull request against main when done and do NOT merge it.

Source material (read-only; clone each, never push to them):
- shanelabountyai/g1-signal-scout, branch `kickoff` (NOT main — main has only the PRD):
  docs/duplication-log.md (the rules G1's agents carried separately — this is G0's input),
  n8n/prompts.py (the verbatim rule text), docs/DECISIONS.md, docs/BACKLOG.md (its C1–C6
  rows describe G1·C, the first consumer of this layer).
- shanelabountyai/li-lead-gen-tools: docs/research/stalled-pilot-evidence-brief.md. Only
  the rows under "Verified stats — safe to use" seed the claims registry; nothing else from
  that file.
- shanelabountyai/bookable-appointment-service (public), apps/mcp/: the A1 MCP server. Reuse
  its pattern, not its language: reviewer-facing README, contract tests, errors as typed
  results, nothing exposed that the caller cannot be trusted with.

Decisions already made by the owner. Record each as a numbered D- entry in
docs/DECISIONS.md (date 2026-11-05 unless noted) before writing any code:
- Six capabilities: claims.registry, brand.policy, audience.consent, measurement,
  evaluation, observability. Built once, called as tools. (2026-11-02)
- Built after G1 and before G2; G2–G5 attach here instead of carrying their own rules.
- The layer is a single point of failure: it gets its own contract tests, health check and
  change control. A contract shape change means a version bump, never a silent edit.
- Build order inside G0: C first (this run), then the owner builds B by hand in n8n from
  the published contracts, then M. The PRD's B→C→M recommendation is superseded.
- The layer lives in its own public repo, g0-shared-layer. G1·C and G2–G5 depend on it as
  a pinned git dependency; the local folder ~/Projects/agentic-track/shared is a clone.
- Storage: SQLite, one file, path from an env var with a sane default.
- Brand-policy seed v1 = the `brand_voice` rule from G1's duplication log (including its
  never-use phrase list). The owner's personal-brand skill may extend it later as a new
  policy version.
- Claims-registry seed = the safe-to-use rows of the evidence brief, with their sources.
- Consent: synthetic contacts only. Generate a fixture of ~20 obviously fake contacts
  (example.com addresses) with per-channel consent flags. No real contact data anywhere.
- The owner chose (2026-11-02) to migrate the shipped A2 Marketing-Ops Agent onto this
  layer. That is G0·M, a later run; do not touch opsagent in this run.

Working rules:
- Contracts first. contracts/<capability>/v1.json: one JSON Schema per capability for input
  and output, with a `version` field in every input and output. Then tests/contracts/ that
  pin every schema (a golden copy; a changed shape fails until the version is bumped and a
  new file added). Only then implement.
- Python 3.12, uv or a plain venv, pyproject.toml. Pydantic v2 models generated from or
  validated against the schemas. One MCP server exposing six tools, stdio transport, plus a
  `health` tool. Confirm the current Python MCP SDK name, version and API from its docs
  before writing server code; record what you found in DECISIONS.md.
- No live model calls are needed for v1 of five capabilities: claims.registry (string
  match + normalized number match against the registry), brand.policy (rule engine over the
  seeded rules), audience.consent (lookup), measurement (insert), observability (insert).
  evaluation MAY call a Claude model as a rubric judge: if you do, confirm current model IDs
  and prices from Anthropic's docs, log tokens and cost per call, and stay under a $10 hard
  cap for the whole run. If no API key is present in the environment, implement evaluation
  with a pluggable judge and ship a deterministic fallback plus a recorded fixture, and say
  so in NEXT.md.
- Tests: pytest. Contract tests, a unit test per capability, and one end-to-end test that
  starts the server over stdio and calls each tool through an MCP client.
- Docs: README.md rewritten for a reviewer (what it does, the six contracts with examples,
  how to run, how to bump a contract version, the single-point-of-failure argument and what
  mitigates it). docs/attach.md: exactly how a consumer attaches (G1·C first), with a count
  of integrations and duplicated rules before and after for G1 (from the duplication log).
- Keep NEXT.md current: what is done, what is next, exact hand steps for the owner
  (including the n8n G0·B hand build and the G1·C start).
- No merges to main, no deploys, no account changes, no secrets committed.

Order of work:
1. docs/DECISIONS.md from the list above; docs/BACKLOG.md splitting the run into tasks
   with acceptance criteria from the PRD; commit.
2. contracts/ + tests/contracts/; commit.
3. Storage + seeds (SQLite schema, seed loader, fixtures); commit.
4. Six capabilities + health, each with its unit test; commit per capability.
5. MCP server + end-to-end test; commit.
6. README.md, docs/attach.md, NEXT.md; commit; push; open the PR with a summary of what
   passes, what is stubbed, cost spent, and the owner's hand steps.
If something blocks you, write it to NEXT.md and keep going with what is not blocked.
```
