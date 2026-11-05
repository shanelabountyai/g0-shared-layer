# G0 Shared Capability Layer — PRD v0.1

Nov 4, 2026 · @Shane LaBounty

## Summary

Agentic AI track, build-log G0. The shared layer (L2) every later agent attaches to. Six capabilities are built once and called as tools: **claims.registry, brand.policy, audience.consent, measurement, evaluation, observability**.

Three cards:

- **G0·B (n8n):** each capability is a sub-workflow any agent can call as a tool, with a fixed input and output shape.
- **G0·C (code):** the six capabilities behind one Python MCP server with typed, versioned contracts. Reuses the A1 MCP build pattern.
- **G0·M (migration):** move the shipped A2 Marketing-Ops Agent off its own copies of campaign QA, routing and audit logging onto the shared layer, proving no regression.

**From the build-log cards (already set):** built after G1, before G2; extracted from G1 (built without it on purpose); the "Fruit Basket Problem" framing: 3 agents × 6 tools is 18 integrations and 3 copies of the rules, with a shared layer it's 9 and 1 copy; the cost of the design is that L2 becomes a single point of failure, so it needs its own tests, uptime and change control. You chose (Nov 2) to also migrate A2 onto it.

**Everything else here is a proposal.**

## Why it's in the portfolio

It's the thesis of the track: agentic work scales through shared capabilities, not more agents. It's also the piece closest to what an applied-AI leader actually owns: one governed set of rules every agent uses, with change control.

## The six contracts (proposed shapes)

| Capability | Input | Output |
| --- | --- | --- |
| claims.registry | text, or a list of claims | each claim: supported / unsupported / needs source, with the matching source |
| brand.policy | text + channel | pass/fail, violations (rule id, excerpt, fix) |
| audience.consent | contact id or email + channel | allowed / blocked + reason |
| measurement | event name + fields | stored event id |
| evaluation | rubric id + item | scores per criterion, pass/fail, notes |
| observability | run id, agent, step, tokens, cost, status | logged |

Every contract carries a `version`. Changing a shape means a new version, never a silent edit.

## Where the content comes from

- **Rules:** `../g1-signal-scout/docs/duplication-log.md` (written during G1) lists every rule G1's agents carried separately. G0 pulls those into the capabilities.
- **Claims registry seed:** the verified stats in the Stalled-Pilot evidence brief (safe-to-use rows only).
- **Brand policy seed:** your LinkedIn voice rules (from the personal-brand skill), if you confirm that's the source.
- **Consent:** synthetic contact list for demos; no real contacts.

## G0·B (n8n) build notes

- One sub-workflow per capability, each started by an Execute Workflow Trigger with a fixed input schema
- Storage: n8n Data Tables or Google Sheets for registries and logs
- Re-point G1·B to call the sub-workflows; count integrations and duplicated rules before and after

## G0·C (code) build notes

- Python 3.12 MCP server exposing six tools with Pydantic-typed inputs and outputs
- Contract versions in the tool schemas; a contract test suite every change must pass
- SQLite for registries, events and logs
- Health check and a simple uptime log, since every agent depends on it

## G0·M (A2 migration) build notes

- Freeze a fixed set of A2 test cases and record current outputs
- Swap A2's built-in campaign QA, routing and audit log for calls to the shared layer
- Re-run the same cases; any difference is either fixed or written down as an intended change
- Report integrations and duplicated rules removed

## Acceptance criteria (proposed)

1. All six capabilities callable from n8n (B) and over MCP (C), each with a contract test.
2. G1 re-pointed to the shared layer with identical digest output on a fixed input week.
3. A breaking contract change fails the contract tests until the version is bumped.
4. **M:** A2's frozen test cases pass after migration, with differences explained.
5. A before/after count of integrations and duplicated rules for G1 and A2.

## Decisions needed (one at a time)

**1. Build order inside G0** *Recommendation: G0·B → G0·C → G0·M.* Same pattern as the other G projects, and M needs the code version to call.

**2. Storage for G0·B** Options: n8n Data Tables / Google Sheets. *Recommendation: Data Tables* if your n8n version has them; otherwise Sheets.

**3. Where the shared layer lives** *Recommendation: `agentic-track/shared/`,* so G2–G5 point at one place.

## Questions for you

1. Should the brand policy seed come from your personal-brand skill's voice rules?
2. Is A2 (`opsagent`) safe to change on a branch, or do you want the migration in a copy?

---

*Decisions 1 and 3 and question 1 were settled 2026-11-05; see `docs/DECISIONS.md` (written by the G0·C kickoff run) and `KICKOFF.md`.*
