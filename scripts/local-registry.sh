#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# Avvia una registry Docker locale su host.docker.internal:5050 per la demo.
#
# Docker Desktop deve fidarsi di questa registry HTTP (insecure). In
# Docker Desktop → Settings → Docker Engine, aggiungi:
#
#   { "insecure-registries": ["host.docker.internal:5050"] }
#
# e applica/riavvia. host.docker.internal è raggiungibile sia dall'host
# (docker push) sia da dentro il cluster Kubernetes di Docker Desktop (pull).
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGISTRY_NAME="${REGISTRY_NAME:-kopt-registry}"
REGISTRY_PORT="${REGISTRY_PORT:-5050}"

if docker ps --format '{{.Names}}' | grep -qx "${REGISTRY_NAME}"; then
  echo "✓ Registry '${REGISTRY_NAME}' già in esecuzione su :${REGISTRY_PORT}"
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${REGISTRY_NAME}"; then
  echo "→ Riavvio della registry '${REGISTRY_NAME}'…"
  docker start "${REGISTRY_NAME}" >/dev/null
else
  echo "→ Avvio di una nuova registry '${REGISTRY_NAME}' su :${REGISTRY_PORT}…"
  docker run -d --restart=always -p "${REGISTRY_PORT}:5000" --name "${REGISTRY_NAME}" registry:2 >/dev/null
fi

echo "✓ Registry pronta su host.docker.internal:${REGISTRY_PORT}"
echo "  (assicurati che 'host.docker.internal:${REGISTRY_PORT}' sia tra le insecure-registries di Docker Desktop)"
