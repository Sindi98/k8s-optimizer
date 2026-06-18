# Reclaim · Kubernetes resource optimizer

[![CI](https://github.com/Sindi98/k8s-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/Sindi98/k8s-optimizer/actions/workflows/ci.yml)

🌐 **English** · [Italiano](README.md)

Analyzes the pods of a Kubernetes cluster using real metrics from **Prometheus**
and the **Kubernetes API**, computes resource optimizations (right-sizing of
`requests`/`limits`, throttling, OOM risk, idle pods) and generates a
**prioritized report** with an artificial intelligence model.

**Everything is configurable from the graphical interface** (the «⚙ Configure»
button): which LLM model to use (provider, model, keys), the Prometheus endpoint
and the analysis window, and every threshold used to optimize the target cluster.
Changes are applied live — without rebuilding the image or touching the
Deployment — and are saved to a persistent volume.

## Design principle

> The numbers are computed by the application, not by the AI.

The metrics and recommendations (CPU/memory requested vs used at p95/max, CFS
throttling, OOMKill, reclaimable headroom) are computed **deterministically** by
the analyzer. The AI model receives the already-computed results and merely
**summarizes and prioritizes** them, producing a readable report with ready-to-use
YAML snippets. The prompt explicitly forbids inventing metrics, so the report
stays anchored to the data.

The app is **read-only** on the cluster: it changes nothing; the recommendations
are applied by hand or via GitOps.

## What it detects

- **Oversized CPU/memory** — request much higher than real usage → wasted resources, with a recommended request.
- **Throttled CPU** — a limit too low that slows down the app.
- **OOM risk** — memory peak close to the limit, or container already OOMKilled.
- **Missing requests/limits** — BestEffort QoS, scheduling/eviction risk.
- **Idle pods** — candidates for scale-to-zero or removal.

For each namespace it shows the **reclaimable** resources (CPU and memory) and a
dashboard with *usage vs request* bars, a per-container detail drawer and an
AI report downloadable in Markdown.

## Quick start (demo, no cluster)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DEMO_MODE=true uvicorn app.main:app --reload --port 8080
# open http://localhost:8080
```

In demo mode the app uses synthetic data (namespaces `mercury-prod`,
`mercury-staging`, `platform`) that exercise every case: no cluster and no
Prometheus required. The default AI provider is `mock` (report generated
locally, zero external calls).

> The `frontend/index.html` dashboard also has demo data embedded: opening it on
> its own in the browser shows the populated interface even without a backend.

## Real cluster

1. **Cluster access** — locally you need a valid kubeconfig (`kubectl` already working).
2. **Prometheus** — expose the endpoint, for example:
   ```bash
   kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
   ```
3. **Start**:
   ```bash
   cd backend
   DEMO_MODE=false \
   PROMETHEUS_URL=http://localhost:9090 \
   ANALYSIS_WINDOW=7d \
   LLM_PROVIDER=mock \
   uvicorn app.main:app --port 8080
   ```

The PromQL queries use the metric names of cAdvisor/kubelet
(`container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`,
`container_cpu_cfs_throttled_periods_total`), exposed by default by
**kube-prometheus-stack**.

## Configuration from the graphical interface

The **«⚙ Configure»** button in the top right opens a panel that lets you
configure the whole system at runtime, in four sections:

- **Data source** — demo mode on/off, in-cluster execution, kubeconfig path.
- **Prometheus** — endpoint URL, analysis window (`24h`, `7d`, `2w`…), timeout.
- **AI model** — provider (`mock` / `ollama` / `anthropic` / `openai`), model,
  report language and credentials. The **«Test connection»** button immediately
  verifies that keys/host work before relying on the provider.
- **Optimization parameters** — sliders for all the deterministic thresholds
  (oversizing, request/limit buffer, OOM risk, throttling, idleness) the analyzer
  uses to decide the recommendations.

Pressing **«Save and re-analyze»** validates, applies and persists the
configuration to `CONFIG_PATH`, the clients (Kubernetes/Prometheus) are recreated
and the current namespace is re-analyzed with the new parameters. API keys are
never sent back to the browser: the UI only shows whether they are set.

The same values remain configurable via environment variables as startup
defaults (see `backend/.env.example`); overrides made from the UI take
precedence.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/api/config` | effective configuration (secrets masked) |
| PUT  | `/api/config` | update and persist a partial configuration |
| POST | `/api/config/test-llm` | verify the configured LLM provider |
| POST | `/api/config/reset` | restore defaults from environment variables |

## Demo on Docker Desktop (local registry)

Install the product on a **Docker Desktop** Kubernetes cluster, using a local
registry on `host.docker.internal:5050`. In this demo the app runs in **live
mode** (it analyzes the cluster's real pods, always read-only) and uses an
included minimal Prometheus that collects the kubelet's cAdvisor metrics (Docker
Desktop doesn't have one of its own).

> 📘 **Complete step-by-step guide** (installing the components, sample
> workloads, diagnostics and troubleshooting): [`docs/DEMO.en.md`](docs/DEMO.en.md).

**Prerequisites**

1. Docker Desktop with **Kubernetes enabled** (Settings → Kubernetes → Enable).
2. The local HTTP registry declared as *insecure* in Docker Desktop →
   Settings → Docker Engine:
   ```json
   { "insecure-registries": ["host.docker.internal:5050"] }
   ```
   Apply and restart. `host.docker.internal` is reachable both from the host
   (`docker push`) and from inside the cluster (the kubelet's pull).

**Start in one command**

```bash
make demo
# or:  ./scripts/demo-deploy.sh
```

The script: starts the registry on `host.docker.internal:5050`, builds and pushes
the `host.docker.internal:5050/kube-optimizer:dev` image, installs the demo's
Prometheus and the optimizer, waits for the rollouts and opens the port-forward on
<http://localhost:8080>.

**Equivalent manual steps**

```bash
docker run -d --restart=always -p 5050:5000 --name kopt-registry registry:2
docker build -t host.docker.internal:5050/kube-optimizer:dev .
docker push host.docker.internal:5050/kube-optimizer:dev

kubectl apply -f k8s/prometheus-demo.yaml
kubectl apply -f k8s/demo-docker-desktop.yaml
kubectl -n kube-optimizer rollout status deploy/kube-optimizer
kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80
```

> Prometheus takes a few minutes to collect enough samples: right after startup
> the live analysis may show little usage data. The window is set to `1h` for the
> demo; raise it (`7d`) for a cluster with history. If you don't want a
> Prometheus, enable **demo mode** from the «⚙ Configure» panel to use the
> synthetic data. To remove everything: `make undeploy`.

## AI providers

Selected with `LLM_PROVIDER` (or from the «⚙ Configure» panel). They all receive the same already-computed numbers.

| Provider    | Data leaves the cluster | Notes |
|-------------|:-----------------------:|-------|
| `mock`      | no                      | report templated from the results, no dependency |
| `ollama`    | no                      | local model (`OLLAMA_HOST`, `OLLAMA_MODEL`) |
| `anthropic` | yes                     | Claude — `pip install anthropic`, `ANTHROPIC_API_KEY` |
| `openai`    | yes                     | `pip install openai`, `OPENAI_API_KEY` |

If the provider fails, the app automatically falls back to the `mock` report so
the interface always shows something useful. See `backend/.env.example` for all
the variables.

## In-cluster deploy

```bash
# build (context = project root)
docker build -t REGISTRY/kube-optimizer:1.0.0 .
docker push REGISTRY/kube-optimizer:1.0.0

# update the image and PROMETHEUS_URL in k8s/deploy.yaml, then:
kubectl apply -f k8s/deploy.yaml
kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80
```

`k8s/deploy.yaml` creates the namespace, ServiceAccount, a **read-only
ClusterRole** (`pods`, `namespaces`, `nodes`), the binding, Deployment (non-root,
read-only filesystem), a **PersistentVolumeClaim** where the UI saves the
configuration (`/data`) and the Service.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/api/health` | status, demo mode, provider, window |
| GET  | `/api/namespaces` | list of namespaces |
| GET  | `/api/analysis?namespace=<ns>` | deterministic analysis of the namespace |
| POST | `/api/report` `{"namespace": "<ns>"}` | AI optimization report |
| GET  | `/api/config` | effective configuration (secrets masked) |
| PUT  | `/api/config` | update and persist the configuration |
| POST | `/api/config/test-llm` | verify the configured LLM provider |
| GET  | `/api/config/ollama-models` | list the models installed on the Ollama host |
| POST | `/api/config/reset` | restore defaults from environment variables |

## Structure

```
kube-optimizer/
├── backend/
│   ├── app/
│   │   ├── config.py       # config from env + runtime override (UI) + persistence
│   │   ├── k8s.py          # read pods/namespaces (read-only)
│   │   ├── prometheus.py   # PromQL queries (cpu/mem/throttle)
│   │   ├── analyzer.py     # deterministic logic + recommendations
│   │   ├── llm.py          # AI providers (mock/anthropic/ollama/openai) + test
│   │   ├── demo.py         # synthetic data for DEMO_MODE
│   │   ├── models.py       # shared dataclasses
│   │   └── main.py         # FastAPI (analysis, report, config) + dashboard
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html          # dashboard + configuration panel
├── k8s/
│   ├── deploy.yaml              # generic in-cluster deploy (+ config PVC)
│   ├── demo-docker-desktop.yaml # live demo on Docker Desktop
│   ├── prometheus-demo.yaml     # minimal Prometheus (cAdvisor) for the demo
│   ├── demo-workloads.yaml      # sample workloads (namespace demo-apps)
│   └── ollama.yaml              # in-cluster Ollama + model pull (local LLM)
├── scripts/
│   ├── demo-deploy.sh      # end-to-end demo (registry+build+push+deploy)
│   └── local-registry.sh   # local registry host.docker.internal:5050
├── docs/
│   └── DEMO.md             # complete guide to the demo environment
├── .github/workflows/
│   └── ci.yml              # CI: lint + test backend, JS, image build
├── pyproject.toml          # ruff + pytest config
├── Makefile
└── Dockerfile
```

## Development and CI

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + pytest + ruff

ruff check app tests conftest.py      # lint
pytest                                # tests (demo mode, no cluster)
```

The **GitHub Actions** pipeline (`.github/workflows/ci.yml`) runs on every push to
`master` and on every pull request:

- **Backend** — `ruff` (lint) + `pytest` (utils, analyzer, runtime configuration and
  API in demo mode, manifest validation).
- **Frontend** — compile-check of the dashboard JS.
- **Image** — container image build (without push).

## Complete settings reference

Every setting can be changed **from the GUI** (the «⚙ Configure» panel) or as an
**environment variable** (startup default). Overrides made from the GUI take
precedence and are persisted to `CONFIG_PATH`.

| GUI section | GUI field | Environment variable | Default | Description |
|---|---|---|---|---|
| Data source | Demo mode | `DEMO_MODE` | `false` | synthetic data, no cluster or Prometheus |
| Data source | In-cluster execution | `IN_CLUSTER` | `false` | use the mounted ServiceAccount |
| Data source | Kubeconfig | `KUBECONFIG` | _(empty = `~/.kube/config`)_ | kubeconfig path (only outside the cluster) |
| Prometheus | Endpoint URL | `PROMETHEUS_URL` | `http://localhost:9090` | Prometheus endpoint |
| Prometheus | Analysis window | `ANALYSIS_WINDOW` | `7d` | PromQL window (`24h`, `7d`, `2w`…) |
| Prometheus | Query timeout (s) | `PROM_TIMEOUT` | `30` | query timeout |
| AI model | Provider | `LLM_PROVIDER` | `mock` | `mock` \| `ollama` \| `anthropic` \| `openai` |
| AI model | Report language | `REPORT_LANGUAGE` | `it` | language of the generated report |
| AI model | API key (Claude) | `ANTHROPIC_API_KEY` | _(empty)_ | Claude credential (masked) |
| AI model | Claude model | `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model |
| AI model | API key (OpenAI) | `OPENAI_API_KEY` | _(empty)_ | OpenAI credential (masked) |
| AI model | OpenAI model | `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |
| AI model | Ollama host | `OLLAMA_HOST` | `http://localhost:11434` | Ollama host (in-cluster: `http://host.docker.internal:11434`) |
| AI model | Ollama model | `OLLAMA_MODEL` | `llama3.1` | Ollama model (any installed one, e.g. `gemma3`) |
| Parameters | Oversizing threshold | `OVERPROV_RATIO` | `0.5` | below this usage % (p95/request) → oversized |
| Parameters | Request buffer | `REQUEST_BUFFER` | `1.2` | margin over p95 for the recommended request |
| Parameters | Limit buffer | `LIMIT_BUFFER` | `1.5` | margin over max for the recommended limit |
| Parameters | OOM risk threshold | `RISK_RATIO` | `0.9` | above this % of the limit (max) → OOM risk |
| Parameters | CPU throttling threshold | `THROTTLE_RATIO` | `0.25` | throttling above this fraction → flagged |
| Parameters | CPU idleness threshold | `IDLE_CPU_CORES` | `0.005` | below this CPU usage (cores, p95) + low mem → idle |
| _(runtime)_ | — | `CONFIG_PATH` | _(temporary file)_ | where the GUI saves the overrides |

### Configuring by hand (without GUI) via API

The same changes can be applied with `curl` (with the port-forward active on `:8080`):

```bash
# read the effective configuration (secrets masked)
curl -s localhost:8080/api/config | python3 -m json.tool

# set Ollama (equivalent to the "⚙ Configure" panel)
curl -X PUT localhost:8080/api/config -H 'Content-Type: application/json' -d '{
  "llm_provider": "ollama",
  "ollama_host": "http://host.docker.internal:11434",
  "ollama_model": "llama3.1"
}'

# adjust the optimization thresholds
curl -X PUT localhost:8080/api/config -H 'Content-Type: application/json' \
  -d '{"overprov_ratio":0.6,"risk_ratio":0.85,"analysis_window":"24h"}'

# verify the LLM provider and the installed Ollama models
curl -X POST localhost:8080/api/config/test-llm | python3 -m json.tool
curl -s  localhost:8080/api/config/ollama-models | python3 -m json.tool

# restore defaults from environment variables
curl -X POST localhost:8080/api/config/reset
```

> Note: the report always states the **provider and model** used. If the provider
> doesn't respond (e.g. Ollama not reachable), the app still generates the report
> with `mock` and clearly flags it (a «fallback» banner), so you always know what
> you read.
