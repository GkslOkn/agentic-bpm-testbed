# Work Package 1 requirement matrix and implementation plan

Authority: references/2026-10-08-deney-duzenegi-yonergeleri.docx, sections 1 and 2, read in full on 2026-10-10. UI reference: references/v1-testbed-l0.html, read in full. Section 3 is excluded.

| Requirement | Implementation target | Verification evidence required |
|---|---|---|
| 1.1 pinned Camunda, Zeebe, Operate, Tasklist | Reuse existing consolidated 8.10.3-SNAPSHOT engine; digest override | topology, Docker health, deployment tests |
| 1.2 10–12 steps, service/DMN/gateway/user/timer/error/message | Separate P2P, loan and synthetic executable BPMN plus DMN | real deployment and branch execution |
| 1.3 SQLite stock/customer/payment/carrier mocks | Per-run SQLite transactions and idempotency keys | state and repeated execution tests |
| 1.4 seeded workers, duration/failure/delay/data effects | REST workers with deterministic per-case/task streams | real job keys, retries, effects |
| 1.5 Poisson synthetic generator | Seeded inputs; dataset mode uses historical arrivals | matching input hashes across strategies |
| 1.6 six YAML disruptions and separate oracle | Process-specific activity mappings and acceptable-response configuration | disruptive integration runs |
| 1.7 monitor, independent L0 contract | Typed request/response; retry/fallback/escalation/reassign/priority/rule update | changed execution, request/action/outcome records |
| 1.8 independent event logs, CSV/XES/OCEL | SQLite event store, PM4Py exports | PM4Py round trip, object relationship validation |
| 1.9 reproducibility | Seeds, config/model/data hashes, versions, engine digest | persisted metadata |
| 1.10 200-case CLI, clean and disrupted | python -m testbed run | live engine acceptance runs |
| Section 2 local datasets, license/schema/profile | Bounded XES sample then PM4Py import; streaming CSV | both local files profiled, source/license report |
| Section 2 discovery and extraction | PM4Py discovery plus empirical arrivals, transitions, resources and timing proxies | model artifacts and mapping coverage |
| Section 2 executable mapping | Curated dataset-specific operational models, never direct deployment of discovered BPMN | documented abstraction and replay limits |
| Dashboard prototype sections, bpmn-js | FastAPI static dashboard and real REST run state | API tests and live HTTP checks |
| Five strategy comparison, isolation | Sequential isolated runs, unique worker types/messages/databases | identical workload hashes, no remaining instances |

Architecture: FastAPI and CLI share a Python execution coordinator; Camunda owns all BPMN tokens, DMN evaluation, user tasks, timers and messages. Python polls scoped REST jobs and native user tasks. SQLite per run stores mock state, events and adaptation results. PM4Py handles discovery and exports. No browser simulation, LLM or WP2 code.

Repository: testbed/ (client, datasets, models, adaptation, storage, runner, API, CLI), config/ (dataset mappings, scenarios, oracle), models/ (generated executable artifacts), static/ (dashboard), tests/, docs/, artifacts/ (profiles and runs).

Pins: Python 3.12 existing .venv; FastAPI 0.115.12, uvicorn 0.34.2, httpx 0.28.1, PyYAML 6.0.2, PM4Py 2.7.17, pytest 8.3.5. Capture complete resolved dependency lock after installation. Installed Camunda image digest cb3408f10bfbac29be4d1f3b13955d2003c9f1a1c19becab329f818ade895cb7. Existing stack has H2 secondary storage and memory caps; do not create another stack.

Milestones: (1) existing engine compatibility; (2) live BPMN/DMN/workers; (3) bounded ingestion/profiles; (4) dataset-specific replay; (5) real disruptions/L0; (6) export/metrics/comparison; (7) dashboard; (8) integration tests and evidence. Test each increment. Completion status belongs in PROGRESS.md and must cite actual evidence.

## Verification status, 2026-10-10

Milestones 1–8 have working prototype implementations and corresponding live/test evidence in PROGRESS.md and docs/ACCEPTANCE_EVIDENCE.json. Six 200-case clean/disrupted acceptance runs passed. The calibrated Simod/Prosimos subrequirement remains incomplete; empirical PM4Py extraction plus separately validated executable operational abstractions are the documented viable alternative. BPIC 2017 historical timing cannot be restored from this timestamp-free CSV. Full historical variant/trace equivalence and research-grade simulation calibration are not claimed. Native manual approval, idempotency, four purchasing branches and actual bpmn-js browser rendering have separate verification evidence.
