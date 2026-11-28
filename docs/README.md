# Documentation index

Start here. Status labels used everywhere: **Done**, **Partial**, **Roadmap** (what exists) and **VERIFIED**, **PARTIALLY VERIFIED**, **UNVERIFIED** (what was actually run). Competitor (OBS, Streamlabs, XSplit) numbers are UNKNOWN throughout; only a method is given.

## Existing documents

| File | Purpose |
|---|---|
| [INSTALLING.md](INSTALLING.md) | beginner desktop and mobile-companion install paths, checksums, FFmpeg, unsigned warnings, uninstall and troubleshooting |
| [FEATURES.md](FEATURES.md) | detailed feature guides, window layouts, web demo, known limitations, portable mode, standalone builds (moved out of the top README in 0.14) |
| [ROADMAP.md](ROADMAP.md) | status table per area |
| [ARCHITECTURE-NOTES.md](ARCHITECTURE-NOTES.md) | auto-scale design and alternatives, v0.16 guardian decisions and the dependabot workflow observation, optimizer notes, 0.12 platform v2 decisions from measured spikes |
| [BENCHMARKS.md](BENCHMARKS.md) | measured numbers from one Linux sandbox, web page weight through v0.18, v0.12 spikes, v0.13 import cost, v0.15 audio/highlights/Benchmark Lab, v0.16 idle budgets, v0.17 remote idle comparison, runtime bitrate change, overlay cost and synthetic predictor results |
| [architecture/V018-MAP.md](architecture/V018-MAP.md) | v0.18 architecture/status map (self-test, desktop package plans, release provenance, installable companion, native mobile boundary) |
| [architecture/V017-MAP.md](architecture/V017-MAP.md) | v0.17 feature map (phone remote, session timeline, race test), security design (threat model), final status and suite tables |
| [architecture/V016-MAP.md](architecture/V016-MAP.md) | v0.16 feature map (guardian, auto-survival, predictor, profiles, timeline, portable audit), roadmap decisions, final status and suite tables |
| [PROFILES.md](PROFILES.md) | one-click profiles `potato_pc`, `office_laptop`, `budget_gaming` and `recommend_profile` rules |
| [architecture/V015-MAP.md](architecture/V015-MAP.md) | v0.15 upgrade paths mapped to existing code (existing, extended, new, roadmap) with decisions and the 0.14 test baseline |
| [architecture/MULTI-DEVICE.md](architecture/MULTI-DEVICE.md) | dashboard panel map, viewer and relay design, OBS-style layers, Moonlight/Parsec class feasibility (covers remote play and P2P) |
| [ARCHITECTURE-NOTES.md#diagrams-012](ARCHITECTURE-NOTES.md#diagrams-012) | Mermaid diagrams (process topology, recovery state machine, data flow) and refactoring recommendations |
| [ROADMAP.md](ROADMAP.md) | v0.12 scorecards: 15 areas and 6 headline features with status and reason |
| [RELEASING.md](RELEASING.md) | how to cut a release |
| [DEV-RENDERING.md](DEV-RENDERING.md) | dev-only GUI and web screenshots (`tools/ui_snapshots.py`) and how the stack was obtained |

## v0.10 audit and blueprint

| File | Purpose |
|---|---|
| [audit/EVIDENCE.md](audit/EVIDENCE.md) | raw measurements, security review, defect list |
| [audit/AUDIT.md](audit/AUDIT.md) | debt, scalability, maintainability, performance, security, five scores with rubric |
| [architecture/BLUEPRINT.md](architecture/BLUEPRINT.md) | target design, section per subsystem |
| [architecture/DELIVERY.md](architecture/DELIVERY.md) | testing, DevOps, release roadmap, benchmark method, advantages |
| [architecture/PLUGIN-PROTOCOL.md](architecture/PLUGIN-PROTOCOL.md) | plugin protocol v1 (subprocess, JSON lines, permissions, kill switch); implemented as library and CLI, not wired into streaming; folder layout decision and Benchmark Lab method are in DELIVERY.md |
| [audit/TOP-100.md](audit/TOP-100.md) | 100 ranked improvements, three Top 10 lists, hackathon mode |

## Phase 18 deliverables

The 14 deliverables, in order. Statuses follow [ROADMAP.md](ROADMAP.md).

| # | Deliverable | Where | Status |
|---|---|---|---|
| 1 | Repository audit | [AUDIT.md](audit/AUDIT.md) (sections 1 to 6), raw data in [EVIDENCE.md](audit/EVIDENCE.md) | Done (documentation) |
| 2 | Technical debt analysis | [AUDIT.md](audit/AUDIT.md#1-technical-debt) | Done (documentation) |
| 3 | New architecture blueprint | [BLUEPRINT.md](architecture/BLUEPRINT.md#1-architecture-and-target-tiers) and [budgets](architecture/BLUEPRINT.md#2-performance-memory-cpu-and-gpu-budgets) | Partial design |
| 4 | Streaming engine redesign | [BLUEPRINT.md](architecture/BLUEPRINT.md#3-streaming-engine) | Partial (backup endpoints, VP9 and AV1 are Roadmap) |
| 5 | Performance optimization plan | [BLUEPRINT.md](architecture/BLUEPRINT.md#4-performance-plan-emergency-mode-and-weak-connection-mode) and [AUDIT.md](audit/AUDIT.md#4-performance) | Roadmap (emergency and weak connection modes) |
| 6 | Scene system architecture | [BLUEPRINT.md](architecture/BLUEPRINT.md#5-scene-system) | Partial |
| 7 | Audio subsystem design | [BLUEPRINT.md](architecture/BLUEPRINT.md#6-audio-subsystem) | Partial (profiles and chains Done; meter and mixing Roadmap) |
| 8 | Smart optimization engine | [BLUEPRINT.md](architecture/BLUEPRINT.md#7-smart-optimization-engine) | Partial |
| 9 | AI assistant architecture | [BLUEPRINT.md](architecture/BLUEPRINT.md#8-ai-assistant-local-and-cloud) | Partial (rule based); Roadmap (language model) |
| 10 | Plugin ecosystem design | [BLUEPRINT.md](architecture/BLUEPRINT.md#9-plugin-ecosystem-and-sdk), [PLUGIN-PROTOCOL.md](architecture/PLUGIN-PROTOCOL.md) | Partial (runtime library and CLI in 0.15; stream wiring is Roadmap) |
| 11 | UI modernization strategy | [BLUEPRINT.md](architecture/BLUEPRINT.md#10-ui-modernization-and-design-system) | Partial (window); Roadmap (dark mode, compact mode, shortcuts) |
| 12 | Testing strategy | [DELIVERY.md](architecture/DELIVERY.md#1-testing-strategy) | Partial |
| 13 | DevOps strategy | [DELIVERY.md](architecture/DELIVERY.md#2-devops-strategy) | Partial (CI workflows never ran) |
| 14 | Release roadmap | [DELIVERY.md](architecture/DELIVERY.md#3-release-roadmap-v010-to-v10) | Roadmap |

## Lists and modes

| Item | Where |
|---|---|
| Top 100 improvements | [audit/TOP-100.md](audit/TOP-100.md) |
| Top 10 for hackathon judges | [audit/TOP-100.md](audit/TOP-100.md#top-10-for-hackathon-judges) |
| Top 10 for low-end streamers | [audit/TOP-100.md](audit/TOP-100.md#top-10-for-low-end-streamers) |
| Top 10 OBS differentiators | [audit/TOP-100.md](audit/TOP-100.md#top-10-obs-differentiators) |
| Hackathon mode (Phase 19), demo script, limitations | [audit/TOP-100.md](audit/TOP-100.md#hackathon-mode-phase-19) |
| Competitive benchmark method (results UNKNOWN) | [DELIVERY.md](architecture/DELIVERY.md#competitive-benchmark-methodology) |
