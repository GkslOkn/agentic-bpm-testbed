# Agentic BPM Testbed — Work Package 1

Python workers execute real Camunda 8 jobs. FastAPI serves a dashboard based on the supplied prototype; BPMN execution happens in Camunda. Work Package 2 is excluded.

## Start the project after closing the terminal or restarting Windows

1. Open Docker Desktop and wait until its engine is ready.
2. Open PowerShell in the project root (the directory containing this README). Use the existing Python 3.12 `.venv`.
3. Start the existing Camunda stack:

```powershell
docker compose --project-directory camunda_8_docker -f camunda_8_docker/docker-compose.yaml -f camunda_8_docker/docker-compose.pinned.yaml up -d
```

4. Check that Camunda is ready:

```powershell
.\.venv\Scripts\python.exe -m testbed doctor
```

If the check fails while Camunda is starting, wait briefly and run it again. Once it succeeds, start the dashboard:

```powershell
.\.venv\Scripts\python.exe -m testbed serve
```

5. Open **http://127.0.0.1:8000**. Keep the PowerShell window open while using the dashboard. Press **Ctrl+C** to stop the dashboard; Camunda continues running in Docker. Closing the Codex window does not replace this startup sequence: start the dashboard from your own terminal or PyCharm when you need it.

Launch experiments from the dashboard, or open a second PowerShell window in the project root:

```powershell
.\.venv\Scripts\python.exe -m testbed run --dataset bpic2019 --scenario X --seed 42 --instances 200
```

Workers start automatically with each experiment; there is no separate worker startup command. Previous results remain in `artifacts/` and appear in the dashboard after restarting. Allow an active experiment to finish before stopping its terminal or restarting Windows.

Operate and Tasklist are at http://localhost:8080/operate and http://localhost:8080/tasklist, with the existing local `demo` / `demo` account.

### Run the dashboard from PyCharm

Select `.venv\Scripts\python.exe` as the project interpreter. Create a Python run configuration using **Module name** `testbed`, **Parameters** `serve`, and the project root as the **Working directory**. Start Docker Desktop and Camunda first, then run this configuration and open http://127.0.0.1:8000.

The existing Docker stack is reused. Its consolidated orchestration image contains Zeebe, Operate, and Tasklist, using H2 secondary storage. Exact installed images are pinned by digest in `camunda_8_docker/docker-compose.pinned.yaml`. To start the same stack when needed:

```powershell
docker compose --project-directory camunda_8_docker -f camunda_8_docker/docker-compose.yaml -f camunda_8_docker/docker-compose.pinned.yaml up -d
```

Do not launch a second stack. The tested gateway is **8.10.3-SNAPSHOT**, pinned to its installed digest; this is a reproducible snapshot, not a stable-release support claim. The existing 1 GB engine and 512 MB connector memory limits are retained. Engine address defaults to `http://localhost:8080`; set `CAMUNDA_URL` to change it. The supplied engine has locally unprotected REST APIs. Its authentication settings remain in the existing configuration.

Dependencies are installed in the existing `.venv`; `requirements.lock.txt` records the full resolved Windows environment. If reinstalling:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

## Camunda and dataset sources

The Camunda Docker Compose distribution is available from the official [Camunda distributions releases](https://github.com/camunda/camunda-distributions/releases). This project uses the existing local `camunda_8_docker/` setup and its pinned override; restarting does not require downloading or creating another stack.

Dataset mirror links provided for this project:

| Dataset | Source link | Required local file |
|---|---|---|
| BPIC 2019 (primary) | [BPI Challenge 2019 dataset on Kaggle](https://www.kaggle.com/datasets/aaminaalzeri/bpi-challenge-2019-dataset) | `datasets/bpi_challenge_2019.xes` (XES) |
| BPIC 2017 (secondary) | [BPI challenge 2017 dataset on Kaggle](https://www.kaggle.com/datasets/waquarhaseeb/bpi-challenge-2017-dataset) | `datasets/bpi_challenge_2017.csv` (CSV) |

Both datasets are already present locally; do not download them again for normal startup. For a fresh checkout, obtain the missing files separately and verify their format and schema against the dataset mapping. Renaming a CSV file to `.xes` does not convert it. The supplied BPIC 2017 CSV has no timestamps, so its timing parameters are explicitly synthetic.

Original publisher records: [BPIC 2019, 4TU.ResearchData](https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1) and [BPIC 2017, 4TU.ResearchData](https://doi.org/10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b). See [methodology and dataset licenses](docs/METHODOLOGY.md) for attribution, verified publisher terms, and the supplied CSV's provenance limitations. Datasets are excluded from this repository by `.gitignore`.

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
