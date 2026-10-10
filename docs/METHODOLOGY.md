# Dataset provenance and experimental methodology

## Sources and licenses

No datasets were downloaded. The supplied files are:

| Dataset | Local file | SHA-256 | Verified publisher metadata |
|---|---|---|---|
| BPIC 2019 | datasets/bpi_challenge_2019.xes, 728,558,522 bytes | af63bc687fc4152f2123b05c3af7772b37ef3fce2d3f67f812666c9e356baae7 | Creative Commons Attribution 4.0 International |
| BPIC 2017 | datasets/bpi_challenge_2017.csv, 170,230,347 bytes | 94a6c450d9af3ea76816417607ea28946ae6e33a5a2cab07d570478442d7a970 | Original dataset: 4TU General Terms of Use |

Attribution: van Dongen, Boudewijn. BPI Challenge 2019, 4TU.ResearchData, [DOI](https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1). BPI Challenge 2017, 4TU.ResearchData, [DOI](https://doi.org/10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b). [2019 license](https://creativecommons.org/licenses/by/4.0/legalcode), [2017 terms](https://doi.org/10.4121/resource:terms_of_use).

Direct publisher pages returned HTTP 403 to automated requests. DataCite's registered DOI metadata was retrieved on 2026-10-10 and saved in `docs/dataset-publisher-metadata.json`; this verifies publisher-declared license identifiers, not the provenance of this particular CSV transformation. The original 2017 release is XES; the supplied derivative is CSV with no conversion manifest. Its transformation history and preservation completeness remain unverified. Retain original attribution and review the publisher's terms before redistribution. No converted source dataset is committed.

If files are missing on another machine, acquire them manually from the DOI landing pages after reviewing their terms, place the 2019 XES at the configured path, and provide the 2017 CSV with the documented schema. Do not rename an XES file as CSV. This project contains no automatic acquisition/downloading step.

## Bounded ingestion and normalization

BPIC 2019's 729 MB XML is streamed into a bounded complete-trace XES, then imported by PM4Py. This is PM4Py XES ingestion with a streaming preselection step. BPIC 2017 is scanned with Python's CSV reader; the first N distinct application IDs are retained and all their rows are collected, including non-contiguous rows. Default N=1,000; cap=10,000. Case IDs, original attributes, activity names, available resources, lifecycle, and existing dates are retained. The first-N sample is potentially biased and is not a representative random sample of the full population. A seeded selection within this sample supplies distinct execution cases. Source size, modification time and SHA-256 are recorded; cache refresh is available through the Python `load(..., refresh=True)` function.

Profiles report schema, activities, resources, lifecycle, matching/application variants, arrivals, observed weekday/hour activity counts, directly-follows frequencies and probabilities, and average nonnegative inter-event gaps. Profiles also distinguish mapped historical activities, omitted activities and synthetic operational tasks. The first 1,000 purchasing cases include invoice-before-GR, invoice-after-GR and consignment; two-way matching is supported by the executable mapping but was not observed in that initial sample.

PM4Py inductive discovery generates a diagnostic BPMN and token-replay fitness report. Its discovered BPMN is not deployed. Graphviz's native `dot` executable is absent; discovery/export works with auto-layout disabled. The dashboard displays separately generated executable models with their own BPMN DI.

## Executable mapping

Each dataset has a separate executable artifact and YAML mapping. The implementation uses a curated operational abstraction, not a lossless conversion of all historical paths. Common runtime plumbing is shared, while labels, matching branches, outcome branches and disruption targets are dataset-specific.

Purchasing executes validation, registration, a DMN review decision, optional native human review, variant-dependent invoice/receipt ordering, matching, compliance, payment, notification, an actual message catch, archival and closure. Three-way matching checks both invoice and receipt; two-way matching skips receipt; consignment skips the invoice step under an explicitly simplified settlement assumption. This simplification requires domain review before scientific consignment comparisons. Unknown categories default to the three-way after-GR abstraction; no unknown-category policy is inferred as historical truth.

Loan replay uses the requested amount, application attributes, event order and resource profile. Observed `A_Denied`, `A_Cancelled`, and `A_Pending` outcomes drive an executable outcome gateway. Denied/canceled applications close without settlement/confirmation; pending applications continue. Missing terminal outcomes default to pending as a recorded replay assumption. This reproduces an observed branching input, not a correct lending policy or an adaptation oracle. Review selection uses a synthetic DMN threshold (>8,000) or forced review during resource disruption, not an inferred bank rule. Human approvals in batch mode are synthetic and always affirmative; historical `Accepted` fields remain available in source inputs but are not an approval oracle.

Tactical rule changes activate an additional SQLite evidence audit in the existing compliance task. The audit requires completed data validation and document/application assessment, records tactical-v2 and the evidence, and sets the compliance result before real settlement. The static strategy continues without the new audit and records a compliance violation for applicable completed cases.

## Timing and simulation extraction limits

BPIC 2019 contains completion/event timestamps, not reliable start/end service-time pairs. Inter-event gaps combine service and waiting. They are used as declared timing proxies, not claimed processing times. Calendars are observed activity histograms, not contractual availability. Prosimos/Simod calibration would require validated lifecycle pairing, resource calendars, a supported toolchain and external validation. `simulation-parameters.json` is an empirical extraction report, explicitly not a Prosimos-compatible simulation configuration. This is the smallest viable executable alternative; calibrated Simod/Prosimos integration is unfinished.

The supplied 2017 CSV has **no timestamp column**. Historical arrivals, task duration, calendar and time-based workload cannot be reconstructed. Preserve lifecycle order and resources; use seeded Poisson arrivals and exponential durations for the operational experiment and label them synthetic. No dates are invented in the normalized source log. A timestamp-preserving CSV or original XES would be required for historical timing calibration.

Synthetic mode uses seeded Poisson arrivals (six/hour), lognormal amounts, customer type and region. Independent hash-derived per-case/task RNG streams ensure disruptions and timings do not depend on strategy execution order. Recorded seeds reproduce inputs, stochastic selections and modeled task durations; UUIDs, real engine keys and wall timestamps intentionally differ. Manual responses and concurrent REST timing are not deterministically reproducible.

Task deadlines and arrival schedules are divided by acceleration. Native SLA timers are real wall timers, so API overhead at high acceleration can trigger warnings on nearly every instance. Primary SLA/cycle metrics therefore use **modeled duration sums**, separately reporting wall cycle time. Modeled cycle time includes dataset inter-event proxies and synthetic human/retry delays, and excludes arrival time and extra wall/API queue overhead. It is not a calibrated queueing simulation. Worker queue ordering and capacity change actual completion scheduling. Stuck cases have censored SLA duration and are reported separately rather than automatically claimed as breaches.

## Adaptation and outcome evaluation

Disruptions are YAML-defined and apply according to dataset targets, seeded probability and model-time windows. Missing data refers to the synthetic operational validation record; it does not claim the source lacked a shipping address or loan attribute. Resource shortage targets native review tasks and either leaves them unresolved, assigns a backup reviewer, or assigns a supervisor. SLA risk injects synthetic delay; prioritisation removes the injected delay, uses a priority worker queue and reduces service duration. These actions change real completion times. No historical staff availability is invented.

Retry uses a Camunda job failure with positive retries and recorded backoff; exhausted no-adaptation/retry-only cases create engine incidents. Fallback executes the SQLite backup payment channel. Escalation throws a BPMN error, opens a native user task, then resumes the affected task after approval. Lookup fixes the operational record. Rule update executes the additional evidence audit. Cost weights are synthetic units: retry .1, lookup .2, fallback/reassign 1, priority 2, human escalation 3, rule update .25.

The oracle is defined separately from the handler and observed history. Success requires an allowed response and downstream case completion, plus current compliance for rule change. A failed retry followed by fallback is not credited as a successful retry; each request is scored separately. Consequently an outage resolved by two failed retries and a successful fallback has per-request success 1/3 even though the case completes. No-adaptation can complete tactical/SLA disruptions with violations; it stalls for unresolved service/data/resource failures.

Monitor coverage includes worker-observed injected failures/data conditions, retry exhaustion, native user-task conditions, engine-reported instance state and native SLA timer jobs. It does not implement a general external incident repair monitor for arbitrary malformed BPMN/DMN or out-of-band administrative mutations. Those cases time out, remain visible in Operate, and are cleaned up as owned stuck cases.

## Logging, validation and isolation

Independent SQLite events retain run/case/activity/lifecycle/time/resource/disruption/request/action/outcome and real job keys. XES and CSV describe actual runtime events with actual timestamps. OCEL 2 uses verified case objects and observed purchasing-document IDs; 2017 has only case objects, so its OCEL is a valid but degenerate object-centric representation. No causal invoice/customer object links are invented.

Operational validation checks required evidence, purchasing variant order, settlement/message effects where applicable, and engine completion records. Discovered-model token replay validates the bounded historical sample separately. Neither is proof that the abstraction matches every historical variant or that observed human decisions were correct.

Unique namespaces isolate worker types, decisions, process definitions, message names/correlations and per-run SQLite state. Owned unfinished instances are canceled, and eventual-consistency reads are polled until termination is visible. Strategy comparison verifies equivalent workload hashes before publishing its result. Read-only historical engine records remain in Camunda; they cannot be consumed by a subsequent run's workers. Local SQLite effects are atomic and idempotent, but arbitrary external systems would need their own idempotency/outbox implementation. An abruptly killed coordinator can leave owned instances active; automatic run resumption is not implemented.

Future handlers can implement the typed `Handler.respond` contract without replacing the coordinator, mock systems, event store or Camunda worker interface. No WP2 agent, governance or provenance component is present.
