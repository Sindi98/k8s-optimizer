# Reclaim · Kubernetes resource optimizer

Analizza i pod di un cluster Kubernetes usando le metriche reali di **Prometheus**
e il **Kubernetes API**, calcola le ottimizzazioni di risorse (right-sizing di
`requests`/`limits`, throttling, rischio OOM, pod inattivi) e genera un **report
prioritizzato** con un modello di intelligenza artificiale.

**Tutto è configurabile dall'interfaccia grafica** (pulsante «⚙ Configura»): quale
modello LLM usare (provider, modello, chiavi), l'endpoint Prometheus e la finestra
di analisi, e ogni soglia con cui ottimizzare il cluster di destinazione. Le
modifiche si applicano a caldo — senza ricostruire l'immagine o toccare il
Deployment — e vengono salvate su un volume persistente.

## Principio di design

> I numeri li calcola l'applicazione, non l'AI.

Le metriche e le raccomandazioni (CPU/memoria richieste vs usate al p95/max,
throttling CFS, OOMKill, headroom recuperabile) sono calcolate in modo
**deterministico** dall'analizzatore. Il modello AI riceve i risultati già
calcolati e si limita a **sintetizzare e prioritizzare**, producendo un report
leggibile con snippet YAML pronti all'uso. Il prompt vieta esplicitamente di
inventare metriche, quindi il report resta ancorato ai dati.

L'app è **in sola lettura** sul cluster: non modifica nulla, le raccomandazioni
si applicano a mano o via GitOps.

## Cosa rileva

- **CPU/memoria sovradimensionata** — richiesta molto superiore all'uso reale → risorse sprecate, con richiesta consigliata.
- **CPU in throttling** — limite troppo basso che rallenta l'app.
- **Rischio OOM** — picco di memoria vicino al limite, o container già OOMKilled.
- **Requests/limits assenti** — QoS BestEffort, rischio scheduling/eviction.
- **Pod inattivi** — candidati a scale-to-zero o rimozione.

Per ogni namespace mostra le risorse **recuperabili** (CPU e memoria) e una
dashboard con barre *uso vs richiesta*, drawer di dettaglio per container e
report AsAI scaricabile in Markdown.

## Avvio rapido (demo, senza cluster)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DEMO_MODE=true uvicorn app.main:app --reload --port 8080
# apri http://localhost:8080
```

In demo mode l'app usa dati sintetici (namespace `mercury-prod`,
`mercury-staging`, `platform`) che esercitano tutti i casi: nessun cluster e
nessun Prometheus necessari. Il provider AI di default è `mock` (report generato
localmente, zero chiamate esterne).

> La dashboard `frontend/index.html` ha anche i dati demo incorporati: aprendola
> da sola nel browser mostra l'interfaccia popolata anche senza backend.

## Cluster reale

1. **Accesso al cluster** — in locale serve un kubeconfig valido (`kubectl` già funzionante).
2. **Prometheus** — esponi l'endpoint, ad esempio:
   ```bash
   kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
   ```
3. **Avvio**:
   ```bash
   cd backend
   DEMO_MODE=false \
   PROMETHEUS_URL=http://localhost:9090 \
   ANALYSIS_WINDOW=7d \
   LLM_PROVIDER=mock \
   uvicorn app.main:app --port 8080
   ```

Le query PromQL usano i metric name di cAdvisor/kubelet
(`container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`,
`container_cpu_cfs_throttled_periods_total`), esposti di default da
**kube-prometheus-stack**.

## Configurazione da interfaccia grafica

Il pulsante **«⚙ Configura»** in alto a destra apre un pannello che permette di
configurare l'intero sistema a runtime, in quattro sezioni:

- **Sorgente dati** — modalità demo on/off, esecuzione in-cluster, path kubeconfig.
- **Prometheus** — URL dell'endpoint, finestra di analisi (`24h`, `7d`, `2w`…), timeout.
- **Modello AI** — provider (`mock` / `ollama` / `anthropic` / `openai`), modello,
  lingua del report e credenziali. Il pulsante **«Test connessione»** verifica
  subito che chiavi/host funzionino prima di affidarsi al provider.
- **Parametri di ottimizzazione** — slider per tutte le soglie deterministiche
  (sovradimensionamento, buffer su richiesta/limite, rischio OOM, throttling,
  inattività) con cui l'analizzatore decide le raccomandazioni.

Premendo **«Salva e rianalizza»** la configurazione viene validata, applicata e
persistita su `CONFIG_PATH`, i client (Kubernetes/Prometheus) vengono ricreati e
il namespace corrente viene rianalizzato con i nuovi parametri. Le chiavi API non
vengono mai rimandate al browser: la UI mostra solo se sono impostate.

Gli stessi valori restano configurabili da variabili d'ambiente come default di
avvio (vedi `backend/.env.example`); gli override fatti da UI hanno la precedenza.

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET  | `/api/config` | configurazione effettiva (segreti mascherati) |
| PUT  | `/api/config` | aggiorna e persiste una configurazione parziale |
| POST | `/api/config/test-llm` | verifica il provider LLM configurato |
| POST | `/api/config/reset` | ripristina i default da variabili d'ambiente |

## Demo su Docker Desktop (registry locale)

Installa il prodotto su un cluster Kubernetes di **Docker Desktop**, usando una
registry locale su `host.docker.internal:5050`. In questa demo l'app gira in
**modalità live** (analizza i pod reali del cluster, sempre in sola lettura) e
usa un Prometheus minimale incluso che raccoglie le metriche cAdvisor del kubelet
(Docker Desktop non ne ha uno di suo).

> 📘 **Guida completa passo-passo** (installazione dei componenti, workload di
> esempio, diagnostica e troubleshooting): [`docs/DEMO.md`](docs/DEMO.md).

**Prerequisiti**

1. Docker Desktop con **Kubernetes attivo** (Settings → Kubernetes → Enable).
2. La registry HTTP locale dichiarata come *insecure* in Docker Desktop →
   Settings → Docker Engine:
   ```json
   { "insecure-registries": ["host.docker.internal:5050"] }
   ```
   Applica e riavvia. `host.docker.internal` è raggiungibile sia dall'host
   (`docker push`) sia da dentro il cluster (pull del kubelet).

**Avvio in un comando**

```bash
make demo
# oppure:  ./scripts/demo-deploy.sh
```

Lo script: avvia la registry su `host.docker.internal:5050`, builda e pusha
l'immagine `host.docker.internal:5050/kube-optimizer:dev`, installa il Prometheus
della demo e l'optimizer, attende i rollout e apre il port-forward su
<http://localhost:8080>.

**Passi manuali equivalenti**

```bash
docker run -d --restart=always -p 5050:5000 --name kopt-registry registry:2
docker build -t host.docker.internal:5050/kube-optimizer:dev .
docker push host.docker.internal:5050/kube-optimizer:dev

kubectl apply -f k8s/prometheus-demo.yaml
kubectl apply -f k8s/demo-docker-desktop.yaml
kubectl -n kube-optimizer rollout status deploy/kube-optimizer
kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80
```

> Prometheus impiega qualche minuto a raccogliere abbastanza campioni: appena
> dopo l'avvio l'analisi live può mostrare pochi dati d'uso. La finestra è
> impostata a `1h` per la demo; alzala (`7d`) per un cluster con storia. Se non
> vuoi un Prometheus, attiva la **modalità demo** dal pannello «⚙ Configura» per
> usare i dati sintetici. Per rimuovere tutto: `make undeploy`.

## Provider AI

Si seleziona con `LLM_PROVIDER` (o dal pannello «⚙ Configura»). Tutti ricevono gli stessi numeri già calcolati.

| Provider    | Dati fuori dal cluster | Note |
|-------------|:----------------------:|------|
| `mock`      | no                     | report templato dai risultati, nessuna dipendenza |
| `ollama`    | no                     | modello locale (`OLLAMA_HOST`, `OLLAMA_MODEL`) |
| `anthropic` | sì                     | Claude — `pip install anthropic`, `ANTHROPIC_API_KEY` |
| `openai`    | sì                     | `pip install openai`, `OPENAI_API_KEY` |

In caso di errore del provider, l'app ricade automaticamente sul report `mock`
così l'interfaccia mostra sempre qualcosa di utile. Vedi `backend/.env.example`
per tutte le variabili.

## Deploy in-cluster

```bash
# build (context = root del progetto)
docker build -t REGISTRY/kube-optimizer:1.0.0 .
docker push REGISTRY/kube-optimizer:1.0.0

# aggiorna l'image e PROMETHEUS_URL in k8s/deploy.yaml, poi:
kubectl apply -f k8s/deploy.yaml
kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80
```

`k8s/deploy.yaml` crea namespace, ServiceAccount, una **ClusterRole in sola
lettura** (`pods`, `namespaces`, `nodes`), il binding, Deployment (non-root,
filesystem read-only), un **PersistentVolumeClaim** dove la UI salva la
configurazione (`/data`) e il Service.

## API

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET  | `/api/health` | stato, modalità demo, provider, finestra |
| GET  | `/api/namespaces` | elenco namespace |
| GET  | `/api/analysis?namespace=<ns>` | analisi deterministica del namespace |
| POST | `/api/report` `{"namespace": "<ns>"}` | report AI di ottimizzazione |
| GET  | `/api/config` | configurazione effettiva (segreti mascherati) |
| PUT  | `/api/config` | aggiorna e persiste la configurazione |
| POST | `/api/config/test-llm` | verifica il provider LLM configurato |
| POST | `/api/config/reset` | ripristina i default da variabili d'ambiente |

## Struttura

```
kube-optimizer/
├── backend/
│   ├── app/
│   │   ├── config.py       # config da env + override runtime (UI) + persistenza
│   │   ├── k8s.py          # lettura pod/namespace (read-only)
│   │   ├── prometheus.py   # query PromQL (cpu/mem/throttle)
│   │   ├── analyzer.py     # logica deterministica + raccomandazioni
│   │   ├── llm.py          # provider AI (mock/anthropic/ollama/openai) + test
│   │   ├── demo.py         # dati sintetici per DEMO_MODE
│   │   ├── models.py       # dataclass condivise
│   │   └── main.py         # FastAPI (analisi, report, config) + dashboard
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html          # dashboard + pannello di configurazione
├── k8s/
│   ├── deploy.yaml              # deploy in-cluster generico (+ PVC config)
│   ├── demo-docker-desktop.yaml # demo live su Docker Desktop
│   ├── prometheus-demo.yaml     # Prometheus minimale (cAdvisor) per la demo
│   └── demo-workloads.yaml      # workload di esempio (namespace demo-apps)
├── scripts/
│   ├── demo-deploy.sh      # demo end-to-end (registry+build+push+deploy)
│   └── local-registry.sh   # registry locale host.docker.internal:5050
├── docs/
│   └── DEMO.md             # guida completa all'ambiente di demo
├── Makefile
└── Dockerfile
```

## Soglie (tutte configurabili)

Default sensati in `config.py`, sovrascrivibili via env: sovradimensionamento
sotto il 50% di utilizzo (`OVERPROV_RATIO`), buffer +20% sulla richiesta e +50%
sul limite (`REQUEST_BUFFER`/`LIMIT_BUFFER`), rischio sopra il 90% del limite
(`RISK_RATIO`), throttling oltre il 25% (`THROTTLE_RATIO`).
