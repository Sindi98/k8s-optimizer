# Reclaim · Kube Optimizer — comandi di sviluppo e demo
#
# Demo rapida su Docker Desktop (registry host.docker.internal:5050):
#   make demo
#
# Variabili override:  REGISTRY=… TAG=…
REGISTRY ?= host.docker.internal:5050
IMAGE    ?= $(REGISTRY)/kube-optimizer
TAG      ?= dev
REF      := $(IMAGE):$(TAG)

.PHONY: help run-local registry build push deploy demo demo-workloads undeploy port-forward logs

help: ## Mostra questo aiuto
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

run-local: ## Avvia il backend in locale in modalità demo (http://localhost:8080)
	cd backend && (test -d .venv || python3 -m venv .venv) && \
		. .venv/bin/activate && pip install -q -r requirements.txt && \
		DEMO_MODE=true uvicorn app.main:app --reload --port 8080

registry: ## Avvia la registry locale su host.docker.internal:5050
	bash scripts/local-registry.sh

build: ## Builda l'immagine container
	docker build -t $(REF) .

push: build ## Builda e pusha l'immagine sulla registry locale
	docker push $(REF)

deploy: ## Applica i manifest (Prometheus demo + optimizer live)
	kubectl apply -f k8s/prometheus-demo.yaml
	kubectl apply -f k8s/demo-docker-desktop.yaml
	kubectl -n kube-optimizer rollout restart deploy/kube-optimizer
	kubectl -n kube-optimizer rollout status deploy/kube-optimizer --timeout=180s

demo: ## Demo completa su Docker Desktop (registry + build + push + deploy + port-forward)
	bash scripts/demo-deploy.sh

demo-workloads: ## Installa i workload di esempio (namespace demo-apps)
	kubectl apply -f k8s/demo-workloads.yaml
	kubectl -n demo-apps rollout status deploy/overprovisioned-web --timeout=120s

port-forward: ## Port-forward del servizio su http://localhost:8080
	kubectl -n kube-optimizer port-forward svc/kube-optimizer 8080:80

logs: ## Segui i log dell'optimizer
	kubectl -n kube-optimizer logs -f deploy/kube-optimizer

undeploy: ## Rimuove tutto dal cluster
	-kubectl delete -f k8s/demo-workloads.yaml
	-kubectl delete -f k8s/demo-docker-desktop.yaml
	-kubectl delete -f k8s/prometheus-demo.yaml
