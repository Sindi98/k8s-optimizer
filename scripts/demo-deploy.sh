#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# Demo end-to-end su Docker Desktop (Kubernetes) con registry locale.
#
#   1. avvia la registry locale (host.docker.internal:5050)
#   2. builda l'immagine e la pusha sulla registry
#   3. installa il Prometheus della demo (cAdvisor)
#   4. installa Reclaim · Kube Optimizer in modalità LIVE (read-only)
#   5. apre il port-forward su http://localhost:8080
#
# Prerequisiti: Docker Desktop con Kubernetes attivo, kubectl, e
# "host.docker.internal:5050" tra le insecure-registries di Docker Desktop.
#
# Uso:    ./scripts/demo-deploy.sh
# Var:    REGISTRY, TAG, NO_PORT_FORWARD=1, SKIP_REGISTRY=1, WITH_WORKLOADS=1
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGISTRY="${REGISTRY:-host.docker.internal:5050}"
IMAGE="${IMAGE:-${REGISTRY}/kube-optimizer}"
TAG="${TAG:-dev}"
REF="${IMAGE}:${TAG}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "▸ Cluster corrente: $(kubectl config current-context 2>/dev/null || echo '???')"
case "$(kubectl config current-context 2>/dev/null || true)" in
  docker-desktop|docker-for-desktop) ;;
  *) echo "⚠  Il contesto kubectl non sembra 'docker-desktop'. Continuo comunque tra 3s…"; sleep 3 ;;
esac

if [[ "${SKIP_REGISTRY:-0}" != "1" ]]; then
  echo "▸ [1/5] Registry locale"
  bash "${ROOT}/scripts/local-registry.sh"
fi

echo "▸ [2/5] Build & push immagine: ${REF}"
docker build -t "${REF}" "${ROOT}"
docker push "${REF}"

echo "▸ [3/5] Prometheus (demo)"
kubectl apply -f "${ROOT}/k8s/prometheus-demo.yaml"

echo "▸ [4/5] Reclaim · Kube Optimizer (live, read-only)"
kubectl apply -f "${ROOT}/k8s/demo-docker-desktop.yaml"
# Assicura il pull dell'ultima immagine pushata anche se il tag non cambia.
kubectl -n kube-optimizer rollout restart deploy/kube-optimizer >/dev/null 2>&1 || true

if [[ "${WITH_WORKLOADS:-0}" == "1" ]]; then
  echo "▸ Workload di esempio (namespace demo-apps)"
  kubectl apply -f "${ROOT}/k8s/demo-workloads.yaml"
fi

echo "▸ Attendo i rollout…"
kubectl -n monitoring rollout status deploy/prometheus --timeout=180s
kubectl -n kube-optimizer rollout status deploy/kube-optimizer --timeout=180s

echo
echo "✓ Demo pronta."
echo "  Prometheus impiega qualche minuto a raccogliere abbastanza campioni."
echo "  Dalla UI ('⚙ Configura') puoi cambiare provider LLM, soglie ed endpoint."
echo

if [[ "${NO_PORT_FORWARD:-0}" == "1" ]]; then
  echo "  Avvia il port-forward con:"
  echo "    kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80"
else
  echo "▸ [5/5] Port-forward su http://localhost:8080  (Ctrl-C per fermare)"
  kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80
fi
