# Reclaim · Kubernetes resource optimizer

Analizza i pod di un cluster Kubernetes usando le metriche reali di **Prometheus**
e il **Kubernetes API**, calcola le ottimizzazioni di risorse (right-sizing di
`requests`/`limits`, throttling, rischio OOM, pod inattivi) e genera un **report
prioritizzato** con un modello di intelligenza artificiale.

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

## Provider AI

Si seleziona con `LLM_PROVIDER`. Tutti ricevono gli stessi numeri già calcolati.

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
filesystem read-only) e Service.

## API

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET  | `/api/health` | stato, modalità demo, provider, finestra |
| GET  | `/api/namespaces` | elenco namespace |
| GET  | `/api/analysis?namespace=<ns>` | analisi deterministica del namespace |
| POST | `/api/report` `{"namespace": "<ns>"}` | report AI di ottimizzazione |

## Struttura

```
kube-optimizer/
├── backend/
│   ├── app/
│   │   ├── config.py       # configurazione da env
│   │   ├── k8s.py          # lettura pod/namespace (read-only)
│   │   ├── prometheus.py   # query PromQL (cpu/mem/throttle)
│   │   ├── analyzer.py     # logica deterministica + raccomandazioni
│   │   ├── llm.py          # provider AI (mock/anthropic/ollama/openai)
│   │   ├── demo.py         # dati sintetici per DEMO_MODE
│   │   ├── models.py       # dataclass condivise
│   │   └── main.py         # FastAPI + serve la dashboard
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html          # dashboard self-contained
├── k8s/
│   └── deploy.yaml
└── Dockerfile
```

## Soglie (tutte configurabili)

Default sensati in `config.py`, sovrascrivibili via env: sovradimensionamento
sotto il 50% di utilizzo (`OVERPROV_RATIO`), buffer +20% sulla richiesta e +50%
sul limite (`REQUEST_BUFFER`/`LIMIT_BUFFER`), rischio sopra il 90% del limite
(`RISK_RATIO`), throttling oltre il 25% (`THROTTLE_RATIO`).
