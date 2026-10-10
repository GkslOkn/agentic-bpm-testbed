# Agentic BPM Testbed — Work Package 1

Python workers execute real Camunda 8 jobs. FastAPI serves a dashboard based on the supplied prototype; BPMN execution happens in Camunda. Work Package 2 is excluded.

From PowerShell in this directory, using the existing Python 3.12 virtual environment:

```powershell
.\.venv\Scripts\python.exe -m testbed doctor
.\.venv\Scripts\python.exe -m testbed run --dataset bpic2019 --scenario X --seed 42 --instances 200
.\.venv\Scripts\python.exe -m testbed serve
```

Open **http://127.0.0.1:8000**. Operate and Tasklist are at http://localhost:8080/operate and http://localhost:8080/tasklist, with the existing local `demo` / `demo` account. PyCharm: select `.venv\Scripts\python.exe`, use a Python module run configuration with module `testbed`, parameters `serve`, and this repository as the working directory.

The existing Docker stack is reused. Its consolidated orchestration image contains Zeebe, Operate, and Tasklist, using H2 secondary storage. Exact installed images are pinned by digest in `camunda_8_docker/docker-compose.pinned.yaml`. To start the same stack when needed:

```powershell
docker compose --project-directory camunda_8_docker -f camunda_8_docker/docker-compose.yaml -f camunda_8_docker/docker-compose.pinned.yaml up -d
```

Do not launch a second stack. The tested gateway is **8.10.3-SNAPSHOT**, pinned to its installed digest; this is a reproducible snapshot, not a stable-release support claim. The existing 1 GB engine and 512 MB connector memory limits are retained. Engine address defaults to `http://localhost:8080`; set `CAMUNDA_URL` to change it. The supplied engine has locally unprotected REST APIs. Its authentication settings remain in the existing configuration.

Dependencies are installed in the existing `.venv`; `requirements.lock.txt` records the full resolved Windows environment. If reinstalling:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

Other commands:

```powershell
# Primary dataset: clean baseline and disrupted run
.\.venv\Scripts\python.exe -m testbed run --dataset bpic2019 --scenario clean --seed 42 --instances 200
.\.venv\Scripts\python.exe -m testbed run --dataset bpic2019 --scenario X --seed 42 --instances 200
# Secondary dataset; timing limitations are recorded in every run
.\.venv\Scripts\python.exe -m testbed run --dataset bpic2017 --scenario X --seed 42 --instances 200
# Required dataset-free invocation uses seeded synthetic workloads
.\.venv\Scripts\python.exe -m testbed run --scenario X --seed 42 --instances 200
.\.venv\Scripts\python.exe -m testbed compare --dataset bpic2019 --scenario X --seed 42 --instances 200
.\.venv\Scripts\python.exe -m testbed profile --dataset bpic2019 --limit 1000
.\.venv\Scripts\python.exe -m testbed discover --dataset bpic2017 --limit 1000
.\.venv\Scripts\python.exe -m testbed validate-run --run-id <32-character-run-id>
```

Scenarios: `clean`, `X` (mixed), `service_outage`, `timeout`, `missing_data`, `resource_shortage`, `sla_risk`, `rule_change`. Definitions live in `config/scenarios.yaml`; normative acceptable responses live separately in `config/oracle.yaml`. Each dataset has explicit disruption targets and activity mappings. Strategies: `none`, `retry`, `retry_fallback`, `full`, `escalate`. The default is `full`.

Runs write `artifacts/runs/<run-id>/`: BPMN, DMN, original normalized inputs, SQLite mock state/events/adaptations, CSV, PM4Py XES, OCEL 2 JSON, metadata, metrics, and operational validation. Completion is recorded only after Camunda reports `COMPLETED`. Non-completing owned instances are canceled and termination is confirmed before the coordinator returns. Unique job types, definition IDs, DMN IDs, message correlation keys, and databases isolate runs. Comparisons verify identical workload hashes and preserve all five run records.

Use `--acceleration 10000000` (default) for fast demonstrations. Values mean model seconds per wall second. `--timeout-seconds 300` bounds a demonstration; slower acceleration needs a larger timeout. `--sample-limit 1000` bounds profile/replay memory, and accepts at most 10,000 cases. A run selects seeded distinct cases from that bounded initial sample. `--human-mode manual --timeout-seconds 600` leaves native user tasks for dashboard approval or Tasklist; batch mode uses deterministic synthetic approvals. Manual escalation requires the run dashboard approval action so the resume variables are supplied.

The dashboard provides engine status, a locally vendored bpmn-js viewer, worker and workload settings, scenarios/oracle, L0 contracts, actual cases/events/tasks, exports, and recorded five-strategy comparison tables and completion bars. The backend API documentation is at http://127.0.0.1:8000/docs. No browser simulator remains.

Testing:

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not acceptance" -q
$env:TESTBED_ACCEPTANCE = "1"
.\.venv\Scripts\python.exe -m pytest -m acceptance -q
```

Integration tests require the real running Camunda stack and local datasets; they fail if infrastructure is unavailable. The six larger acceptance tests cover 200 clean and disrupted instances per dataset/mode. Read [PROGRESS.md](PROGRESS.md) for actual evidence, [requirements](docs/REQUIREMENTS.md) for the matrix, and [methodology](docs/METHODOLOGY.md) for the research limits before interpreting results.
