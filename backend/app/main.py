"""FastAPI application wiring everything together.

Endpoints
  GET  /api/health        runtime info (demo flag, provider, window)
  GET  /api/namespaces    list of namespaces
  GET  /api/analysis      deterministic analysis for ?namespace=
  POST /api/report        AI optimisation report for {"namespace": "..."}

The dashboard (single HTML file) is served at /.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from . import analyzer, demo, llm

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(title="Kube Optimizer", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# --- data sources -----------------------------------------------------------
@lru_cache(maxsize=1)
def _k8s():
    from .k8s import KubernetesClient
    return KubernetesClient()


@lru_cache(maxsize=1)
def _prom():
    from .prometheus import PrometheusClient
    return PrometheusClient()


def _collect(namespace: str):
    """Return (pod specs, metrics) for a namespace from the live cluster or demo."""
    if settings.demo_mode:
        return demo.data_for_namespace(namespace)
    specs = _k8s().list_pod_specs(namespace)
    metrics = _prom().metrics_for_namespace(namespace)
    return specs, metrics


def _run_analysis(namespace: str):
    specs, metrics = _collect(namespace)
    return analyzer.analyze_namespace(specs, metrics, settings.analysis_window)


# --- API --------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "llm_provider": settings.llm_provider,
        "analysis_window": settings.analysis_window,
        "prometheus_url": settings.prometheus_url if not settings.demo_mode else None,
    }


@app.get("/api/namespaces")
def namespaces():
    try:
        if settings.demo_mode:
            return {"namespaces": demo.list_namespaces()}
        return {"namespaces": _k8s().list_namespaces()}
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to list namespaces")
        raise HTTPException(status_code=502, detail=f"Errore connessione al cluster: {exc}")


@app.get("/api/analysis")
def analysis(namespace: str = Query(..., min_length=1)):
    try:
        result = _run_analysis(namespace)
        return result.to_dict()
    except Exception as exc:  # noqa: BLE001
        log.exception("Analysis failed")
        raise HTTPException(status_code=502, detail=f"Analisi fallita: {exc}")


class ReportRequest(BaseModel):
    namespace: str


@app.post("/api/report")
def report(req: ReportRequest):
    try:
        result = _run_analysis(req.namespace)
    except Exception as exc:  # noqa: BLE001
        log.exception("Analysis failed before report")
        raise HTTPException(status_code=502, detail=f"Analisi fallita: {exc}")
    return JSONResponse(llm.generate_report(result))


# --- frontend ---------------------------------------------------------------
@app.get("/")
def index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"detail": "frontend non trovato"}, status_code=404)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
