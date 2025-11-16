# Senex Trader Documentation Index

**Last reviewed**: 2025-10-21
**Repository**: `senex_trader_docs`

## Quick Start

- Read `../senex_trader/AI.md` for global rules and workflow expectations.
- Use `STATUS_AND_ROADMAP.md` for the current state of development.
- Track active work in `planning/`; triage proposals in `backlog/`.

## High-Value References

- Streaming patterns — `patterns/WORKING_STREAMING_IMPLEMENTATION.md`
- Real-time data flow — `patterns/REALTIME_DATA_FLOW_PATTERN.md`
- Senex Trident spec — `specifications/SENEX_TRIDENT_STRATEGY_DEFINITION.md`
- TastyTrade SDK guide — `guides/TASTYTRADE_SDK_BEST_PRACTICES.md`
- Code quality checklist — `guides/CODE_QUALITY_CHECKLIST.md`

## Documentation Map

- **patterns/** – Canonical architecture and implementation patterns.
- **specifications/** – Functional specs, API contracts, and strategy definitions.
- **guides/** – How-to references, troubleshooting, tooling.
- **product/** – User workflows, feature requirements, UX notes.
- **risk_management/** – Risk models, sizing rules, guardrails.
- **tastytrade/** – Broker API reference and integration notes.
- **deployment/** – Infrastructure, Ansible, environment ops.
- **docker/** – Container standards and environment shapes.
- **optimization/** – Performance investigations and postmortems.
- **scripts/** – Repo automation and validation tooling.
- **planning/** – Active epics with README + task breakdowns.
- **backlog/** – Proposed work waiting for triage (keep dated).
- **archive/** – Historical material; move completed reports here.

## Working Docs & Ownership

- Keep `STATUS_AND_ROADMAP.md` as the single status source.
- Ensure every doc lists `Last updated`, owner, and intent.
- Record in-flight notes inside the relevant epic folder.

## Historical Records

- Migration and organization summaries now live under `archive/reports/`.
- Retire closed epics to `archive/epics/` once their work is delivered.

## Maintenance Checklist

- Update this index whenever top-level folders change.
- Flag broken links or stale claims with a short note until fixed.
- Prefer succinct bullet lists over duplicating roadmap content.
