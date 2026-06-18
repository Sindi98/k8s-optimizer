# Guida completa — Ambiente di demo su Docker Desktop

Questa guida installa da zero un ambiente di demo per **Reclaim · Kube Optimizer**
su **Docker Desktop (Kubernetes)**, usando una registry locale su
`host.docker.internal:5050`. L'optimizer gira in **modalità live** (analizza i pod
reali del cluster, sempre in **sola lettura**).

Indice:

1. [Architettura della demo](#1-architettura-della-demo)
2. [Prerequisiti e installazione dei componenti](#2-prerequisiti-e-installazione-dei-componenti)
3. [Installazione rapida (un comando)](#3-installazione-rapida-un-comando)
4. [Installazione passo-passo](#4-installazione-passo-passo)
5. [Workload di esempio (consigliato)](#5-workload-di-esempio-consigliato)
6. [Uso dell'interfaccia](#6-uso-dellinterfaccia)
7. [Provider LLM: mock, Ollama, Claude, OpenAI](#7-provider-llm-mock-ollama-claude-openai)
8. [Verifica e diagnostica](#8-verifica-e-diagnostica)
9. [Troubleshooting](#9-troubleshooting)
10. [Aggiornare l'immagine dopo una modifica](#10-aggiornare-limmagine-dopo-una-modifica)
11. [Pulizia](#11-pulizia)

---

## 1. Architettura della demo

```
            Host (Docker Desktop)
┌─────────────────────────────────────────────────────────────┐
│  Registry locale            Cluster Kubernetes (docker-desktop)│
│  ┌───────────────┐          ┌──────────────────────────────┐  │
│  │ registry:2    │  pull    │ ns kube-optimizer            │  │
│  │ :5050         │◀─────────│  Deploy kube-optimizer (live)│  │
│  └───────▲───────┘          │   • legge pod/namespace (RO) │  │
│          │ push             │   • PVC /data (config UI)    │  │
│   docker build/push         │                              │  │
│                             │ ns monitoring                │  │
│                             │  Deploy prometheus (cAdvisor)│  │
│                             │                              │  │
│                             │ ns demo-apps (facoltativo)   │  │
│                             │  workload di esempio         │  │
│                             └──────────────────────────────┘  │
│   Browser ──▶ http://localhost:8080 (kubectl port-forward)     │
└─────────────────────────────────────────────────────────────┘
```

`host.docker.internal` è speciale: risolve all'host **sia** dal terminale
(`docker push`) **sia** da dentro il cluster (pull del kubelet). Per questo la
stessa stringa `host.docker.internal:5050/...` funziona per push e pull.

Componenti installati:

| Componente | Dove | Come | Obbligatorio |
|---|---|---|---|
| Docker Desktop + Kubernetes | host | installer | sì |
| Registry locale `:5050` | container Docker | `registry:2` | sì |
| Prometheus (cAdvisor) | ns `monitoring` | `k8s/prometheus-demo.yaml` | sì (per le metriche) |
| Kube Optimizer | ns `kube-optimizer` | `k8s/demo-docker-desktop.yaml` | sì |
| Workload di esempio | ns `demo-apps` | `k8s/demo-workloads.yaml` | consigliato |
| Ollama (LLM locale) | host o cluster | facoltativo | no |

---

## 2. Prerequisiti e installazione dei componenti

### 2.1 Docker Desktop

- **macOS** (Homebrew):
  ```bash
  brew install --cask docker
  open -a Docker            # primo avvio, completa il setup
  ```
  In alternativa scarica da <https://www.docker.com/products/docker-desktop/>.
- **Windows** (winget, richiede WSL2):
  ```powershell
  winget install -e --id Docker.DockerDesktop
  ```
- **Linux**: pacchetto Docker Desktop (`.deb`/`.rpm`) dal sito ufficiale.

Verifica:
```bash
docker version
```

### 2.2 Abilitare Kubernetes in Docker Desktop

Docker Desktop → **Settings → Kubernetes → Enable Kubernetes → Apply & Restart**.
Attendi che lo stato in basso diventi verde ("Kubernetes running").

Verifica e seleziona il contesto:
```bash
kubectl config use-context docker-desktop
kubectl get nodes
# NAME             STATUS   ROLES           AGE   VERSION
# docker-desktop   Ready    control-plane   ...   v1.xx
```

### 2.3 kubectl

`kubectl` è incluso in Docker Desktop. Se manca dal PATH puoi installarlo a parte:
```bash
# macOS
brew install kubectl
# Windows
winget install -e --id Kubernetes.kubectl
# Linux
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

### 2.4 Dichiarare la registry locale come "insecure"

La registry locale parla **HTTP** (non HTTPS), quindi Docker deve fidarsene.
Docker Desktop → **Settings → Docker Engine** e aggiungi `host.docker.internal:5050`
all'elenco `insecure-registries`:

```json
{
  "insecure-registries": ["host.docker.internal:5050"]
}
```

Premi **Apply & Restart**. Questo vale sia per `docker push` (dall'host) sia per
il pull del kubelet (Docker Desktop condivide lo stesso engine).

### 2.5 Il progetto

```bash
git clone https://github.com/Sindi98/k8s-optimizer.git
cd k8s-optimizer
```

### 2.6 (Facoltativo) Ollama per il report con LLM locale

Vedi la [sezione 7](#7-provider-llm-mock-ollama-claude-openai). Non è richiesto:
il provider di default è `mock` (report generato localmente, nessuna dipendenza).

---

## 3. Installazione rapida (un comando)

Dopo aver completato la sezione 2 (Kubernetes attivo + registry insecure):

```bash
make demo
```

Lo script `scripts/demo-deploy.sh`:

1. avvia la registry locale su `host.docker.internal:5050`;
2. fa `docker build` e `docker push` di `host.docker.internal:5050/kube-optimizer:dev`;
3. installa il Prometheus della demo (`k8s/prometheus-demo.yaml`);
4. installa l'optimizer in modalità live (`k8s/demo-docker-desktop.yaml`);
5. attende i rollout e apre il **port-forward** su <http://localhost:8080>.

Per installare anche i workload di esempio nello stesso passaggio:
```bash
WITH_WORKLOADS=1 make demo
```

> Se preferisci capire ogni passo, segui la sezione 4. Per i soli workload di
> esempio (a deploy già fatto): `make demo-workloads`.

---

## 4. Installazione passo-passo

```bash
# 1. Registry locale su host.docker.internal:5050
docker run -d --restart=always -p 5050:5000 --name kopt-registry registry:2
#    (oppure: make registry)

# 2. Build & push dell'immagine
docker build -t host.docker.internal:5050/kube-optimizer:dev .
docker push host.docker.internal:5050/kube-optimizer:dev

# 3. Prometheus della demo (raccoglie cAdvisor dal kubelet)
kubectl apply -f k8s/prometheus-demo.yaml

# 4. Kube Optimizer (live, sola lettura)
kubectl apply -f k8s/demo-docker-desktop.yaml

# 5. Attendi che i pod siano pronti
kubectl -n monitoring rollout status deploy/prometheus --timeout=180s
kubectl -n kube-optimizer rollout status deploy/kube-optimizer --timeout=180s

# 6. Esponi la dashboard in locale
kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80
```

Apri **<http://localhost:8080>**. Il badge in alto a destra deve mostrare
**"Live · mock"**.

---

## 5. Workload di esempio (consigliato)

Su Docker Desktop appena installato ci sono solo pod di sistema. Per vedere
l'optimizer "in azione" installa i workload di esempio, dimensionati apposta per
innescare ogni rilevazione:

```bash
kubectl apply -f k8s/demo-workloads.yaml
# oppure: make demo-workloads
```

| Workload | Problema dimostrato | Severità |
|---|---|---|
| `overprovisioned-web` | CPU/memoria sovradimensionate, pod inattivo | warning |
| `cpu-throttled` | CPU in throttling (limite troppo basso) | critical |
| `memory-pressure` | rischio OOM (uso ~91% del limite di memoria) | critical |
| `besteffort-worker` | requests/limits assenti (QoS BestEffort) | warning |
| `node-exporter` | sovradimensionato + inattivo; target Prometheus reale | warning |

**Come Prometheus monitora questi pod.** L'optimizer analizza l'**uso delle
risorse** preso da **cAdvisor**, che il Prometheus della demo raccoglie per
*ogni* pod del cluster: per questo i workload sopra sono già pienamente misurati,
senza bisogno di annotazioni. Il pod `node-exporter` è inoltre **esplicitamente
abilitato a Prometheus** con le annotazioni `prometheus.io/scrape|port|path` ed
espone davvero `/metrics`: viene raccolto dal job `kubernetes-pods` del Prometheus
della demo (vedi `k8s/prometheus-demo.yaml`). Puoi verificarlo su
`http://localhost:9090/targets` (target `kubernetes-pods` = UP).

Verifica che siano in esecuzione:
```bash
kubectl -n demo-apps get pods
```

> **Importante:** Prometheus deve raccogliere qualche minuto di campioni prima
> che le barre "uso vs richiesta" si popolino. Per la demo conviene una finestra
> breve: apri **⚙ Configura → Prometheus → Finestra di analisi** e imposta `15m`
> (poi "Salva e rianalizza"). Dopo ~5 minuti seleziona il namespace `demo-apps`.

---

## 6. Uso dell'interfaccia

1. **Namespace** (in alto a sinistra): scegli `demo-apps` (o un altro namespace
   reale). La tabella mostra ogni pod con barre *uso vs richiesta*, throttling,
   restart e risorse recuperabili.
2. Clicca una riga per aprire il **drawer** di dettaglio: problemi rilevati,
   confronto *attuale → consigliato* e snippet `resources:` YAML pronto da copiare.
3. **✦ Genera report AI**: produce un report prioritizzato in Markdown
   (scaricabile) a partire dai numeri già calcolati. In alto trovi **provider e
   modello** usati; se il provider AI non risponde, l'app genera comunque il
   report con `mock` e lo segnala con un banner «fallback» (così sai sempre cosa
   stai leggendo).
4. **⚙ Configura**: il pannello con cui si configura tutto il sistema a caldo —
   sorgente dati, Prometheus, modello AI (con "Test connessione") e le soglie di
   ottimizzazione. "Salva e rianalizza" applica e ricalcola subito.

La configurazione modificata dalla UI viene salvata sul volume persistente
(`/data/config.json`) e sopravvive ai riavvii del pod.

---

## 7. Provider LLM: mock, Ollama, Claude, OpenAI

Tutti i provider sono già inclusi nell'immagine e selezionabili da **⚙ Configura
→ Modello AI**. Usa "Test connessione" per validare subito chiavi/host.

- **mock** (default): report generato localmente, nessuna chiamata esterna.
- **Ollama** — LLM in locale, nessun dato esce dalla tua macchina. Tre passi:

  **1. Installa Ollama** sull'host:
  ```bash
  # macOS
  brew install ollama          # oppure scarica l'app da https://ollama.com/download
  # Linux
  curl -fsSL https://ollama.com/install.sh | sh
  # Windows: installer da https://ollama.com/download
  ```

  **2. Avvia il server in ascolto su tutte le interfacce.** È il passo che fa
  inciampare: di default Ollama ascolta solo su `127.0.0.1`, perciò rifiuta le
  connessioni che arrivano dal pod (→ `[Errno 111] Connection refused`). Esponilo
  su `0.0.0.0`:
  ```bash
  OLLAMA_HOST=0.0.0.0:11434 ollama serve
  ```
  (App macOS/Windows: imposta la variabile d'ambiente `OLLAMA_HOST=0.0.0.0:11434`
  e riavvia Ollama.)

  **3. Scarica un modello** (un nome che esiste davvero) e verifica:
  ```bash
  ollama pull llama3.1         # oppure: gemma3, qwen2.5, mistral …
  ollama list                  # elenca i modelli installati
  curl http://localhost:11434/api/tags   # deve rispondere con la lista in JSON
  ```

  Nella UI (**⚙ Configura → Modello AI**): provider `ollama`, **Host Ollama** =
  `http://host.docker.internal:11434` (l'app gira *nel* cluster, quindi `localhost`
  sarebbe il pod stesso — `host.docker.internal` punta invece al tuo host; nel
  manifest della demo questo valore è già preimpostato), **Modello Ollama** =
  esattamente il nome scaricato. Usa **«Carica modelli installati»** per popolare
  l'elenco direttamente dall'host e sceglierne uno (va bene qualsiasi modello
  installato, anche `gemma4` se l'hai scaricato), poi «Test connessione».

  > Se esegui il backend in locale (`make run-local`, non nel cluster), usa invece
  > **Host Ollama** = `http://localhost:11434`.

  **Alternativa: Ollama dentro il cluster** (nessun Ollama sull'host). Installa
  Ollama come pod e scarica il modello con il manifest dedicato:
  ```bash
  kubectl apply -f k8s/ollama.yaml            # oppure: make ollama
  kubectl -n ollama rollout status deploy/ollama
  kubectl -n ollama logs job/ollama-pull -f   # avanzamento del download del modello
  ```
  Poi nella UI: **Host Ollama** = `http://ollama.ollama.svc:11434`, **Modello
  Ollama** = `gemma4` (lo stesso scaricato dal Job). Se `gemma4` non è nel registry
  Ollama, cambia `MODEL` nel Job (es. `gemma3:1b`, `gemma2:2b`, `qwen2.5:3b`) — vedi
  <https://ollama.com/library>. L'inferenza gira su CPU: assegna a Docker Desktop
  ≥ 8 GB di RAM (Settings → Resources) e preferisci un modello piccolo.
- **Claude (anthropic)**: provider `anthropic`, incolla la `ANTHROPIC_API_KEY`,
  modello es. `claude-sonnet-4-6`. Richiede rete in uscita verso le API esterne.
- **OpenAI**: provider `openai`, incolla la `OPENAI_API_KEY`, modello es.
  `gpt-4o-mini`.

> Le chiavi non vengono mai rimandate al browser: la UI mostra solo se sono
> impostate. In caso di errore del provider, l'app ricade automaticamente sul
> report `mock`.

---

## 8. Verifica e diagnostica

```bash
# Tutti i pod della demo
kubectl get pods -n kube-optimizer -o wide
kubectl get pods -n monitoring -o wide
kubectl get pods -A | grep -E 'kube-optimizer|prometheus|demo-apps'

# Salute e configurazione dell'app
curl -s localhost:8080/api/health   | python3 -m json.tool
curl -s localhost:8080/api/config   | python3 -m json.tool
curl -s 'localhost:8080/api/namespaces' | python3 -m json.tool

# Log dell'optimizer
kubectl -n kube-optimizer logs -f deploy/kube-optimizer     # (o: make logs)

# Prometheus: controlla che i target cAdvisor siano "up"
kubectl -n monitoring port-forward deploy/prometheus 9090:9090
#   poi apri http://localhost:9090/targets  (job kubernetes-cadvisor = UP)
#   query di prova: container_cpu_usage_seconds_total{namespace="demo-apps"}
```

---

## 9. Troubleshooting

| Sintomo | Causa probabile | Soluzione |
|---|---|---|
| `ImagePullBackOff` / `ErrImagePull` su `host.docker.internal:5050/...` | registry non "insecure", non avviata, o immagine non pushata | Configura `insecure-registries` (§2.4) e riavvia Docker Desktop; `make registry`; ripeti `docker push`; poi `kubectl -n kube-optimizer rollout restart deploy/kube-optimizer` |
| `docker push` → `http: server gave HTTP response to HTTPS client` | registry non dichiarata insecure | §2.4, poi Apply & Restart |
| `docker push` → `connection refused` | container registry spento | `make registry` (riavvia `kopt-registry`) |
| Pod `Pending`, PVC non si lega | manca una StorageClass di default | Su Docker Desktop esiste `hostpath`; verifica `kubectl get storageclass`. Se assente, riattiva Kubernetes da Docker Desktop |
| Dashboard ok ma barre d'uso vuote / "—" | Prometheus ha pochi campioni o finestra troppo lunga | Attendi 5 min; imposta finestra `15m` da ⚙ Configura; verifica i target cAdvisor (§8) |
| `Analisi fallita` / 502 nella UI | cluster o Prometheus non raggiungibili | Controlla `PROMETHEUS_URL` da ⚙ Configura (`http://prometheus.monitoring.svc:9090`) e che il pod Prometheus sia Ready |
| Nessun namespace nell'elenco / 403 nei log | RBAC | I manifest creano già la ClusterRole read-only; riapplica `k8s/demo-docker-desktop.yaml` |
| `host.docker.internal` non risolve (Linux) | mapping host assente | Su Docker Desktop è gestito; se usi un altro runtime, sostituisci con l'IP dell'host o usa una registry in-cluster |
| `cpu-throttled`/`memory-pressure` non mostrano dati | servono alcuni minuti di scrape | Attendi; verifica `kubectl -n demo-apps get pods` (Running) |
| Test connessione Ollama → `[Errno 111] Connection refused` | host errato o Ollama legato a `127.0.0.1` | In-cluster usa `http://host.docker.internal:11434` **e** avvia Ollama con `OLLAMA_HOST=0.0.0.0:11434 ollama serve`; verifica con `curl localhost:11434/api/tags` (vedi §7) |
| Report Ollama → modello non trovato | nome modello inesistente (es. `gemma4`) | Usa un nome reale: `ollama list` / `ollama pull llama3.1` e impostalo in «Modello Ollama» |
| `memory-pressure` va in `OOMKilled`/`CrashLoopBackOff` | poco headroom sul nodo | È un caso limite: alza il limite a `300Mi` in `k8s/demo-workloads.yaml` o abbassa l'allocazione (`--vm-bytes 220M`) |

---

## 10. Aggiornare l'immagine dopo una modifica

Dopo aver cambiato il codice:
```bash
make push        # build + push su host.docker.internal:5050
kubectl -n kube-optimizer rollout restart deploy/kube-optimizer
kubectl -n kube-optimizer rollout status deploy/kube-optimizer
```
(Il Deployment usa `imagePullPolicy: Always`, quindi al riavvio ripull­a il tag `dev`.)

---

## 11. Pulizia

```bash
# Rimuove optimizer + Prometheus
make undeploy
#   = kubectl delete -f k8s/demo-docker-desktop.yaml
#     kubectl delete -f k8s/prometheus-demo.yaml

# Rimuove i workload di esempio
kubectl delete -f k8s/demo-workloads.yaml

# Ferma e rimuove la registry locale
docker rm -f kopt-registry

# (Facoltativo) disabilita Kubernetes da Docker Desktop se non ti serve più
```
