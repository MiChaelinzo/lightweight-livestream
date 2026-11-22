# Documentation index

Start here. Status labels used everywhere: **Done**, **Partial**, **Roadmap** (what exists) and **VERIFIED**, **PARTIALLY VERIFIED**, **UNVERIFIED** (what was actually run). Competitor (OBS, Streamlabs, XSplit) numbers are UNKNOWN throughout; only a method is given.

## Existing documents

| File | Purpose |
|---|---|
| [ROADMAP.md](ROADMAP.md) | status table per area |
| [ARCHITECTURE-NOTES.md](ARCHITECTURE-NOTES.md) | auto-scale design and alternatives, optimizer notes |
| [BENCHMARKS.md](BENCHMARKS.md) | measured numbers from one Linux sandbox |
| [RELEASING.md](RELEASING.md) | how to cut a release |

## v0.10 audit and blueprint

| File | Purpose |
|---|---|
| [audit/EVIDENCE.md](audit/EVIDENCE.md) | raw measurements, security review, defect list |
| [audit/AUDIT.md](audit/AUDIT.md) | debt, scalability, maintainability, performance, security, five scores with rubric |
| [architecture/BLUEPRINT.md](architecture/BLUEPRINT.md) | target design, section per subsystem |
| [architecture/DELIVERY.md](architecture/DELIVERY.md) | testing, DevOps, release roadmap, benchmark method, advantages |
| [audit/TOP-100.md](audit/TOP-100.md) | 100 ranked improvements, three Top 10 lists, hackathon mode |

## Phase 18 deliverables

The original Phase 18 wording is not stored in this repository. This mapping is the author's grouping of the 14 deliverables, so check it against the request if the numbering differs.

| # | Deliverable | Where | Status |
|---|---|---|---|
| 1 | Audit reports (debt, scalability, maintainability, performance, security) | [AUDIT.md](audit/AUDIT.md) sections 1 to 5 | Done (documentation) |
| 2 | Scores with rubric | [AUDIT.md](audit/AUDIT.md) section 6 | Done |
| 3 | New architecture blueprint, tiers, budgets | [BLUEPRINT.md](architecture/BLUEPRINT.md) sections 1 and 2 | Partial design |
| 4 | Streaming engine redesign (platforms, backup endpoints, VP9 and AV1) | [BLUEPRINT.md](architecture/BLUEPRINT.md) section 3 | Partial |
| 5 | Performance plan (emergency mode, weak connection mode) | [BLUEPRINT.md](architecture/BLUEPRINT.md) section 4 | Roadmap |
| 6 | Scene system and audio subsystem | [BLUEPRINT.md](architecture/BLUEPRINT.md) sections 5 and 6 | Partial |
| 7 | Smart optimization and AI assistant | [BLUEPRINT.md](architecture/BLUEPRINT.md) sections 7 and 8 | Partial |
| 8 | Plugin ecosystem and SDK | [BLUEPRINT.md](architecture/BLUEPRINT.md) section 9 | Roadmap |
| 9 | UI modernization, design system, dashboard | [BLUEPRINT.md](architecture/BLUEPRINT.md) sections 10 and 11 | Partial |
| 10 | Mobile companion API and creator tools | [BLUEPRINT.md](architecture/BLUEPRINT.md) sections 12 and 13 | Roadmap and Partial |
| 11 | Network optimization and security hardening | [BLUEPRINT.md](architecture/BLUEPRINT.md) sections 14 and 15 | Partial |
| 12 | Testing strategy | [DELIVERY.md](architecture/DELIVERY.md#1-testing-strategy) | Partial |
| 13 | DevOps strategy | [DELIVERY.md](architecture/DELIVERY.md#2-devops-strategy) | Partial |
| 14 | Release roadmap v0.10 to v1.0 | [DELIVERY.md](architecture/DELIVERY.md#3-release-roadmap-v010-to-v10) | Roadmap |

## Lists and modes

| Item | Where |
|---|---|
| Top 100 improvements | [audit/TOP-100.md](audit/TOP-100.md) |
| Top 10 for hackathon judges | [audit/TOP-100.md](audit/TOP-100.md#top-10-for-hackathon-judges) |
| Top 10 for low-end streamers | [audit/TOP-100.md](audit/TOP-100.md#top-10-for-low-end-streamers) |
| Top 10 OBS differentiators | [audit/TOP-100.md](audit/TOP-100.md#top-10-obs-differentiators) |
| Hackathon mode (Phase 19), demo script, limitations | [audit/TOP-100.md](audit/TOP-100.md#hackathon-mode-phase-19) |
| Competitive benchmark method (results UNKNOWN) | [DELIVERY.md](architecture/DELIVERY.md#competitive-benchmark-methodology) |
