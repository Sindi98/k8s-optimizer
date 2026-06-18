# Complete guide — Demo environment on Docker Desktop

🌐 **English** · [Italiano](DEMO.md)

This guide installs from scratch a demo environment for **Reclaim · Kube Optimizer**
on **Docker Desktop (Kubernetes)**, using a local registry on
`host.docker.internal:5050`. The optimizer runs in **live mode** (it analyzes the
cluster's real pods, always **read-only**).

Table of contents:

1. [Demo architecture](#1-demo-architecture)
2. [Prerequisites and component installation](#2-prerequisites-and-component-installation)
3. [Quick install (one command)](#3-quick-install-one-command)
4. [Step-by-step installation](#4-step-by-step-installation)
5. [Sample workloads (recommended)](#5-sample-workloads-recommended)
6. [Using the interface](#6-using-the-interface)
7. [LLM providers: mock, Ollama, Claude, OpenAI](#7-llm-providers-mock-ollama-claude-openai)
8. [Verification and diagnostics](#8-verification-and-diagnostics)
9. [Troubleshooting](#9-troubleshooting)
10. [Updating the image after a change](#10-updating-the-image-after-a-change)
11. [Cleanup](#11-cleanup)

---

## 1. Demo architecture

```
            Host (Docker Desktop)
┌─────────────────────────────────────────────────────────────┐
│  Local registry             Kubernetes cluster (docker-desktop)│
│  ┌───────────────┐          ┌──────────────────────────────┐  │
│  │ registry:2    │  pull    │ ns kube-optimizer            │  │
│  │ :5050         │◀─────────│  Deploy kube-optimizer (live)│  │
│  └───────▲───────┘          │   • reads pods/namespaces(RO)│  │
│          │ push             │   • PVC /data (UI config)    │  │
│   docker build/push         │                              │  │
│                             │ ns monitoring                │  │
│                             │  Deploy prometheus (cAdvisor)│  │
│                             │                              │  │
│                             │ ns demo-apps (optional)      │  │
│                             │  sample workloads            │  │
│                             └──────────────────────────────┘  │
│   Browser ──▶ http://localhost:8080 (kubectl port-forward)     │
└─────────────────────────────────────────────────────────────┘
```

`host.docker.internal` is special: it resolves to the host **both** from the
terminal (`docker push`) **and** from inside the cluster (the kubelet's pull).
That's why the same `host.docker.internal:5050/...` string works for both push
and pull.

Installed components:

| Component | Where | How | Required |
|---|---|---|---|
| Docker Desktop + Kubernetes | host | installer | yes |
| Local registry `:5050` | Docker container | `registry:2` | yes |
| Prometheus (cAdvisor) | ns `monitoring` | `k8s/prometheus-demo.yaml` | yes (for the metrics) |
| Kube Optimizer | ns `kube-optimizer` | `k8s/demo-docker-desktop.yaml` | yes |
| Sample workloads | ns `demo-apps` | `k8s/demo-workloads.yaml` | recommended |
| Ollama (local LLM) | host or cluster | optional | no |

---

## 2. Prerequisites and component installation

### 2.1 Docker Desktop

- **macOS** (Homebrew):
  ```bash
  brew install --cask docker
  open -a Docker            # first launch, complete the setup
  ```
  Alternatively download from <https://www.docker.com/products/docker-desktop/>.
- **Windows** (winget, requires WSL2):
  ```powershell
  winget install -e --id Docker.DockerDesktop
  ```
- **Linux**: Docker Desktop package (`.deb`/`.rpm`) from the official site.

Verify:
```bash
docker version
```

### 2.2 Enable Kubernetes in Docker Desktop

Docker Desktop → **Settings → Kubernetes → Enable Kubernetes → Apply & Restart**.
Wait until the status at the bottom turns green ("Kubernetes running").

Verify and select the context:
```bash
kubectl config use-context docker-desktop
kubectl get nodes
# NAME             STATUS   ROLES           AGE   VERSION
# docker-desktop   Ready    control-plane   ...   v1.xx
```

### 2.3 kubectl

`kubectl` is included in Docker Desktop. If it's missing from the PATH you can
install it separately:
```bash
# macOS
brew install kubectl
# Windows
winget install -e --id Kubernetes.kubectl
# Linux
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

### 2.4 Declare the local registry as "insecure"

The local registry speaks **HTTP** (not HTTPS), so Docker must trust it.
Docker Desktop → **Settings → Docker Engine** and add `host.docker.internal:5050`
to the `insecure-registries` list:

```json
{
  "insecure-registries": ["host.docker.internal:5050"]
}
```

Press **Apply & Restart**. This applies both to `docker push` (from the host) and
to the kubelet's pull (Docker Desktop shares the same engine).

### 2.5 The project

```bash
git clone https://github.com/Sindi98/k8s-optimizer.git
cd k8s-optimizer
```

### 2.6 (Optional) Ollama for the report with a local LLM

See [section 7](#7-llm-providers-mock-ollama-claude-openai). It's not required:
the default provider is `mock` (report generated locally, no dependency).

---

## 3. Quick install (one command)

After completing section 2 (Kubernetes enabled + insecure registry):

```bash
make demo
```

The `scripts/demo-deploy.sh` script:

1. starts the local registry on `host.docker.internal:5050`;
2. runs `docker build` and `docker push` of `host.docker.internal:5050/kube-optimizer:dev`;
3. installs the demo's Prometheus (`k8s/prometheus-demo.yaml`);
4. installs the optimizer in live mode (`k8s/demo-docker-desktop.yaml`);
5. waits for the rollouts and opens the **port-forward** on <http://localhost:8080>.

To also install the sample workloads in the same step:
```bash
WITH_WORKLOADS=1 make demo
```

> If you prefer to understand each step, follow section 4. For the sample
> workloads only (after the deploy is done): `make demo-workloads`.

---

## 4. Step-by-step installation

```bash
# 1. Local registry on host.docker.internal:5050
docker run -d --restart=always -p 5050:5000 --name kopt-registry registry:2
#    (or: make registry)

# 2. Build & push the image
docker build -t host.docker.internal:5050/kube-optimizer:dev .
docker push host.docker.internal:5050/kube-optimizer:dev

# 3. Demo Prometheus (collects cAdvisor from the kubelet)
kubectl apply -f k8s/prometheus-demo.yaml

# 4. Kube Optimizer (live, read-only)
kubectl apply -f k8s/demo-docker-desktop.yaml

# 5. Wait for the pods to be ready
kubectl -n monitoring rollout status deploy/prometheus --timeout=180s
kubectl -n kube-optimizer rollout status deploy/kube-optimizer --timeout=180s

# 6. Expose the dashboard locally
kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80
```

Open **<http://localhost:8080>**. The badge in the top right should show
**"Live · mock"**.

---

## 5. Sample workloads (recommended)

On a freshly installed Docker Desktop there are only system pods. To see the
optimizer "in action" install the sample workloads, sized specifically to
trigger each detection:

```bash
kubectl apply -f k8s/demo-workloads.yaml
# or: make demo-workloads
```

| Workload | Demonstrated problem | Severity |
|---|---|---|
| `overprovisioned-web` | oversized CPU/memory, idle pod | warning |
| `cpu-throttled` | throttled CPU (limit too low) | critical |
| `memory-pressure` | OOM risk (usage ~91% of the memory limit) | critical |
| `besteffort-worker` | missing requests/limits (BestEffort QoS) | warning |
| `node-exporter` | oversized + idle; real Prometheus target | warning |

**How Prometheus monitors these pods.** The optimizer analyzes the **resource
usage** taken from **cAdvisor**, which the demo's Prometheus collects for *every*
pod in the cluster: that's why the workloads above are already fully measured,
without needing annotations. The `node-exporter` pod is moreover **explicitly
enabled for Prometheus** with the `prometheus.io/scrape|port|path` annotations and
actually exposes `/metrics`: it is collected by the demo Prometheus's
`kubernetes-pods` job (see `k8s/prometheus-demo.yaml`). You can verify this at
`http://localhost:9090/targets` (target `kubernetes-pods` = UP).

Verify they are running:
```bash
kubectl -n demo-apps get pods
```

> **Important:** Prometheus must collect a few minutes of samples before the
> "usage vs request" bars fill up. For the demo a short window is convenient:
> open **⚙ Configure → Prometheus → Analysis window** and set `15m`
> (then "Save and re-analyze"). After ~5 minutes select the `demo-apps` namespace.

---

## 6. Using the interface

1. **Namespace** (top left): choose `demo-apps` (or another real namespace). The
   table shows each pod with *usage vs request* bars, throttling, restarts and
   reclaimable resources.
2. Click a row to open the detail **drawer**: detected problems, *current →
   recommended* comparison and a ready-to-copy `resources:` YAML snippet.
3. **✦ Generate AI report**: produces a prioritized report in Markdown
   (downloadable) starting from the already-computed numbers. At the top you find
   the **provider and model** used; if the AI provider doesn't respond, the app
   still generates the report with `mock` and flags it with a «fallback» banner
   (so you always know what you are reading).
4. **⚙ Configure**: the panel with which the whole system is configured live —
   data source, Prometheus, AI model (with "Test connection") and the
   optimization thresholds. "Save and re-analyze" applies and recomputes
   immediately.

The configuration modified from the UI is saved to the persistent volume
(`/data/config.json`) and survives pod restarts.

---

## 7. LLM providers: mock, Ollama, Claude, OpenAI

All providers are already included in the image and selectable from **⚙ Configure
→ AI model**. Use "Test connection" to immediately validate keys/host.

- **mock** (default): report generated locally, no external call.
- **Ollama** — local LLM, no data leaves your machine. Three steps:

  **1. Install Ollama** on the host:
  ```bash
  # macOS
  brew install ollama          # or download the app from https://ollama.com/download
  # Linux
  curl -fsSL https://ollama.com/install.sh | sh
  # Windows: installer from https://ollama.com/download
  ```

  **2. Start the server listening on all interfaces.** This is the step that
  trips people up: by default Ollama listens only on `127.0.0.1`, so it refuses
  connections coming from the pod (→ `[Errno 111] Connection refused`). Expose it
  on `0.0.0.0`:
  ```bash
  OLLAMA_HOST=0.0.0.0:11434 ollama serve
  ```
  (macOS/Windows app: set the environment variable `OLLAMA_HOST=0.0.0.0:11434`
  and restart Ollama.)

  **3. Pull a model** (a name that actually exists) and verify:
  ```bash
  ollama pull llama3.1         # or: gemma3, qwen2.5, mistral …
  ollama list                  # list the installed models
  curl http://localhost:11434/api/tags   # must respond with the list in JSON
  ```

  In the UI (**⚙ Configure → AI model**): provider `ollama`, **Ollama host** =
  `http://host.docker.internal:11434` (the app runs *in* the cluster, so
  `localhost` would be the pod itself — `host.docker.internal` instead points to
  your host; in the demo manifest this value is already preset), **Ollama model** =
  exactly the name you pulled. Use **«Load installed models»** to populate the
  list directly from the host and pick one (any installed model is fine, even
  `gemma4` if you pulled it), then "Test connection".

  > If you run the backend locally (`make run-local`, not in the cluster), use
  > instead **Ollama host** = `http://localhost:11434`.

  **Alternative: Ollama inside the cluster** (no Ollama on the host). Install
  Ollama as a pod and pull the model with the dedicated manifest:
  ```bash
  kubectl apply -f k8s/ollama.yaml            # or: make ollama
  kubectl -n ollama rollout status deploy/ollama
  kubectl -n ollama logs job/ollama-pull -f   # model download progress
  ```
  Then in the UI: **Ollama host** = `http://ollama.ollama.svc:11434`, **Ollama
  model** = `gemma4` (the same one pulled by the Job). If `gemma4` is not in the
  Ollama registry, change `MODEL` in the Job (e.g. `gemma3:1b`, `gemma2:2b`,
  `qwen2.5:3b`) — see <https://ollama.com/library>. Inference runs on CPU: give
  Docker Desktop ≥ 8 GB of RAM (Settings → Resources) and prefer a small model.
- **Claude (anthropic)**: provider `anthropic`, paste the `ANTHROPIC_API_KEY`,
  model e.g. `claude-sonnet-4-6`. Requires outbound network to the external APIs.
- **OpenAI**: provider `openai`, paste the `OPENAI_API_KEY`, model e.g.
  `gpt-4o-mini`.

> The keys are never sent back to the browser: the UI only shows whether they are
> set. If the provider fails, the app automatically falls back to the `mock`
> report.

---

## 8. Verification and diagnostics

```bash
# All the demo pods
kubectl get pods -n kube-optimizer -o wide
kubectl get pods -n monitoring -o wide
kubectl get pods -A | grep -E 'kube-optimizer|prometheus|demo-apps'

# App health and configuration
curl -s localhost:8080/api/health   | python3 -m json.tool
curl -s localhost:8080/api/config   | python3 -m json.tool
curl -s 'localhost:8080/api/namespaces' | python3 -m json.tool

# Optimizer logs
kubectl -n kube-optimizer logs -f deploy/kube-optimizer     # (or: make logs)

# Prometheus: check that the cAdvisor targets are "up"
kubectl -n monitoring port-forward deploy/prometheus 9090:9090
#   then open http://localhost:9090/targets  (job kubernetes-cadvisor = UP)
#   test query: container_cpu_usage_seconds_total{namespace="demo-apps"}
```

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ImagePullBackOff` / `ErrImagePull` on `host.docker.internal:5050/...` | registry not "insecure", not started, or image not pushed | Configure `insecure-registries` (§2.4) and restart Docker Desktop; `make registry`; repeat `docker push`; then `kubectl -n kube-optimizer rollout restart deploy/kube-optimizer` |
| `docker push` → `http: server gave HTTP response to HTTPS client` | registry not declared insecure | §2.4, then Apply & Restart |
| `docker push` → `connection refused` | registry container down | `make registry` (restart `kopt-registry`) |
| Pod `Pending`, PVC won't bind | a default StorageClass is missing | On Docker Desktop `hostpath` exists; check `kubectl get storageclass`. If absent, re-enable Kubernetes from Docker Desktop |
| Dashboard ok but usage bars empty / "—" | Prometheus has few samples or the window is too long | Wait 5 min; set the window to `15m` from ⚙ Configure; check the cAdvisor targets (§8) |
| `Analysis failed` / 502 in the UI | cluster or Prometheus not reachable | Check `PROMETHEUS_URL` from ⚙ Configure (`http://prometheus.monitoring.svc:9090`) and that the Prometheus pod is Ready |
| No namespace in the list / 403 in the logs | RBAC | The manifests already create the read-only ClusterRole; reapply `k8s/demo-docker-desktop.yaml` |
| `host.docker.internal` doesn't resolve (Linux) | host mapping missing | On Docker Desktop it's handled; if you use another runtime, replace it with the host IP or use an in-cluster registry |
| `cpu-throttled`/`memory-pressure` show no data | a few minutes of scraping are needed | Wait; check `kubectl -n demo-apps get pods` (Running) |
| Ollama test connection → `[Errno 111] Connection refused` | wrong host or Ollama bound to `127.0.0.1` | In-cluster use `http://host.docker.internal:11434` **and** start Ollama with `OLLAMA_HOST=0.0.0.0:11434 ollama serve`; verify with `curl localhost:11434/api/tags` (see §7) |
| Ollama report → model not found | non-existent model name (e.g. `gemma4`) | Use a real name: `ollama list` / `ollama pull llama3.1` and set it in «Ollama model» |
| `memory-pressure` goes into `OOMKilled`/`CrashLoopBackOff` | little headroom on the node | It's an edge case: raise the limit to `300Mi` in `k8s/demo-workloads.yaml` or lower the allocation (`--vm-bytes 220M`) |

---

## 10. Updating the image after a change

After changing the code:
```bash
make push        # build + push to host.docker.internal:5050
kubectl -n kube-optimizer rollout restart deploy/kube-optimizer
kubectl -n kube-optimizer rollout status deploy/kube-optimizer
```
(The Deployment uses `imagePullPolicy: Always`, so on restart it re-pulls the `dev` tag.)

---

## 11. Cleanup

```bash
# Remove optimizer + Prometheus
make undeploy
#   = kubectl delete -f k8s/demo-docker-desktop.yaml
#     kubectl delete -f k8s/prometheus-demo.yaml

# Remove the sample workloads
kubectl delete -f k8s/demo-workloads.yaml

# Stop and remove the local registry
docker rm -f kopt-registry

# (Optional) disable Kubernetes from Docker Desktop if you no longer need it
```
