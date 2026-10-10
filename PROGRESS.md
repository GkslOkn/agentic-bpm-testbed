# Work Package 1 progress

2026-10-10: Read both reference documents completely. Created docs/REQUIREMENTS.md before implementation. Inspected existing Docker setup and reused it. Live /v2/topology reports healthy leader and Camunda 8.10.3-SNAPSHOT. Installed image digest recorded in requirement matrix. Existing .venv is Python 3.12; sandbox blocks its Windows Store interpreter, so approved execution outside sandbox is required.

Local datasets: BPIC 2019 XES 728,558,522 bytes; BPIC 2017 CSV 170,230,347 bytes. No dataset download. BPIC 2017 header appears to lack timestamps; verify the full schema before timing extraction. License verification against publisher currently blocked by HTTP 403; do not claim verified permissions for the supplied CSV derivative.

## Delivered and verified on 2026-10-10

Working local WP1 prototype implemented. Camunda owns BPMN execution; Python owns mock-system jobs and the L0 handler. The existing .venv and Docker containers were reused. Neither dataset nor another Camunda distribution was downloaded. WP2 is excluded.

- Existing Camunda 8.10.3-SNAPSHOT, healthy topology, Zeebe/Operate/Tasklist consolidated with H2. Exact engine and connector digests pinned in the existing Compose override; `docker compose ... config --quiet` passed. Docker containers remained healthy. Observed memory: orchestration 944 MiB / 1 GiB, connectors 403 MiB / 512 MiB.
- Three executable BPMN models and DMN: service tasks, conditional review gateway, native user tasks, error boundaries with task resumption, noninterrupting SLA timer, real message catch and publication. Dataset-specific purchasing and loan branches are executed by the engine.
- Python REST workers activate and complete real jobs, record their keys, use run-bounded leases, retry with actual engine failures/backoff, and transactionally deduplicate SQLite mock effects. Batch human approvals and manual dashboard approval both execute native Camunda tasks. Repeated manual approval is idempotent despite stale search results.
- Per-run SQLite customer, inventory, primary/backup transactions, shipment confirmation, resource assignment and tactical compliance evidence audit. Seeded per-case/task streams control synthetic arrivals, duration/failure choices and disruption selection.
- BPIC 2019 bounded streaming XES selection followed by PM4Py ingestion: 1,000 source cases, 15,351 events in the current profile. BPIC 2017 streaming CSV: 1,000 cases, 39,932 events, original lifecycle and resources retained. Case/event schemas, variants, transitions/probabilities, resources, available arrivals, calendar observations, timing proxies and mapping coverage exported.
- PM4Py inductive discovery and diagnostic BPMN for both datasets. Token-replay log fitness: BPIC 2019 0.999169 (95.1% fitting traces), BPIC 2017 1.0 (100% fitting traces), on the bounded discovery samples. These are discovered-model diagnostics, not validation of historical correctness or of the operational abstraction. Executable run validation checks matching evidence/order, settlement/messages and engine completion independently.
- Six YAML disruption types and a separate normative oracle. Five L0 presets: no adaptation, retry only, retry/fallback, full rules, escalate everything. Verified actions change actual job state, provider, native assignment, queue/deadline scheduling, human task routing or compliance audit execution.
- Independent events and PM4Py CSV/XES/OCEL 2 exports, per-request oracle outcomes, completion/stuck/SLA/compliance/cycle/human/cost metrics. Run metadata retains IDs, seeds, config and workload hashes, source identity/hash, model version/hash, software versions and engine digest. New runs also save expanded configuration, semantic model hash and dependency lock hash.
- Strategy comparison uses identical workload hashes and isolated namespaces/databases. Owned stuck instances are canceled; termination is confirmed before proceeding. All diagnostic leftovers were identified and canceled; no active testbed instances remained at cleanup verification.
- FastAPI dashboard preserves the prototype's nine sections, provides dataset/scenario/strategy selection and worker/workload settings, real monitoring and native human approval, exports and comparison tables/bars. Locally vendored bpmn-js 18.6.3 renders the executable models. Installed Edge headless verified actual recorded 200-case events and the purchasing model's rendered SVG elements. The dashboard runs at http://127.0.0.1:8000.

## Automated verification evidence

| Suite | Result | Evidence |
|---|---|---|
| Core + live integration | 21 passed | artifacts/tests-integration.xml |
| Four purchasing branch fixtures | 1 passed | artifacts/tests-variants.xml |
| Native manual dashboard approval | 1 passed | artifacts/tests-manual.xml |
| Final core + manual approval/idempotency | 10 passed, overlapping above | artifacts/tests-final.xml |
| 200-case acceptance (clean/X × three modes) | 6 passed in 580.28 s | artifacts/tests-acceptance.xml |

29 distinct automated test cases passed across these suites. The final smoke run `c8e41cc95f6d4b9c82256f26b38dc82a` also verified the final lease configuration, expanded configuration export, new hashes and real BPIC 2019 execution. Browser artifacts: artifacts/browser-check/72916a2786604480b0b691b1f51dc9eb/.

| Mode | Scenario | Run ID | Completed | Requests | Compliance violations |
|---|---|---|---:|---:|---:|
| BPIC 2019 | clean | de1dae83fd9a4e11ade6bf76e0a2e2e4 | 200/200 | 0 | 0 |
| BPIC 2019 | X | 87e512f90f704c9aaad39bc6a30dd5fa | 200/200 | 415 | 0 |
| BPIC 2017 | clean | 701ccb50c6b74ec6a427abc9f49e851b | 200/200 | 0 | 0 |
| BPIC 2017 | X | b5872e12f5a644c8bcf99cc34e290862 | 200/200 | 220 | 0 |
| Synthetic | clean | 4bc5fe371dec4ba99d7770c3eaab0bf9 | 200/200 | 0 | 0 |
| Synthetic | X | fab3afca72f44926923a5f4917e55265 | 200/200 | 475 | 0 |

All six runs have valid operational invariant checks, XES round trips and no unfinished instance cleanup. Detailed metrics: docs/ACCEPTANCE_EVIDENCE.json and each run's metadata.json. Disrupted per-request oracle success rates: purchasing 69.64%, loan 70%, synthetic 66.74%; failed retries followed by successful fallback are scored as failed individual requests, rather than hiding them behind case completion. Purchasing has 193/200 modeled SLA breaches in both clean and X runs because observed timing proxies exceed the synthetic 48-hour SLA. Completion does not imply SLA compliance.

Initial failures found and fixed: REST long-poll timeout semantics, escalation resume variable propagation, optional Graphviz dependency, eventual cancellation state (`TERMINATED`), API startup metadata race and stale user-task search after completion. Interrupted diagnostics are labeled separately and are not acceptance evidence. Optional PM4Py rustxes and upstream AnyIO deprecation warnings remain; they did not affect tests.

## Limitations and remaining research work

1. **Calibrated Simod/Prosimos integration is incomplete.** Extracted empirical parameters are not advertised as a runnable Prosimos schema. The supplied 2017 CSV lacks timestamps; historical arrivals, durations/calendars and time-based workload are unavailable. BPIC 2019 completion timestamps yield inter-event waiting/service proxies, not identified processing durations. Full historical calibration requires better timing data and validation.
2. Dataset replay uses the bounded first-N sample and a curated operational abstraction. Administrative changes, loops and all historical paths are not preserved. Two-way matching passed an explicitly synthetic branch fixture; it was absent from the first 1,000 purchasing cases. Consignment settlement and the DMN review threshold are synthetic assumptions requiring professor/domain review.
3. Modeled cycle/SLA metrics use duration sums and exclude additional API/worker wall-time queue overhead; wall cycle time is also reported. High acceleration can make native wall timers fire before meaningful model time has elapsed. This prototype is not a calibrated queueing simulation. Stuck-case SLA observations are censored.
4. DataCite metadata now verifies BPIC 2019 CC BY 4.0 and original BPIC 2017 4TU General Terms of Use, superseding the initial direct-page blocker. The local 2017 CSV conversion history remains unknown. Publisher metadata is saved in docs/dataset-publisher-metadata.json.
5. OCEL purchasing objects include observed purchase-document IDs; loan OCEL has case objects only. Richer object links are not inferred. Arbitrary external engine incidents are not automatically repaired; worker/injected conditions and native timers/tasks are monitored. Abrupt OS termination cannot resume the coordinator; owned instances may need manual cleanup.
6. Five-strategy equivalence/isolation is verified on small live comparison runs. The CLI/dashboard supports 200 cases per strategy, but a full 5 × 200 dataset comparison was not run as part of today's acceptance tests.

Next steps before the October 12 deadline: obtain a timestamp-preserving 2017 derivative or original XES without overwriting supplied data; review matching/consignment and normative rule assumptions with the professor; replace timing proxies with validated service/calendar estimates; run 200-case five-strategy repeated-seed comparisons and assess variance. Add future handlers through `Handler.respond`; no WP2 infrastructure needs to replace the L0 worker/coordinator/event interfaces.
