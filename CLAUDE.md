# Shared Capability Layer (G0)

Agentic AI track, build-log G0 (·C Python MCP server, ·B n8n, ·M A2 migration). Spec: `docs/prd.md`. Start: `KICKOFF.md`. Status: `NEXT.md`. Decisions: `docs/DECISIONS.md`.

Rules for any Claude Code session here:
- Every agent in the track depends on this. A contract shape change needs a version bump and passing contract tests; never a silent edit.
- Synthetic contacts only; no real contact data anywhere in this repo.
- Never touch opsagent's main branch. No merges, deploys or account changes without the owner's explicit go.
- Log tokens and cost per run. Hard cap on live model calls: $10 unless the owner raises it.
- Keep NEXT.md and docs/DECISIONS.md current. Commit per task on branch `kickoff`; no secrets.
