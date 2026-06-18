"""Validate that the Kubernetes manifests (and embedded Prometheus config) parse."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "k8s"


def test_all_manifests_parse():
    files = sorted(K8S.glob("*.yaml"))
    assert files, "no manifests found"
    for f in files:
        docs = [d for d in yaml.safe_load_all(f.read_text()) if d]
        assert docs, f"{f.name} produced no documents"
        for d in docs:
            assert "kind" in d, f"{f.name}: a document has no kind"


def test_prometheus_embedded_scrape_config():
    docs = list(yaml.safe_load_all((K8S / "prometheus-demo.yaml").read_text()))
    cm = next(d for d in docs if d and d["kind"] == "ConfigMap")
    prom = yaml.safe_load(cm["data"]["prometheus.yml"])
    jobs = {j["job_name"] for j in prom["scrape_configs"]}
    assert {"kubernetes-cadvisor", "kubernetes-pods"} <= jobs


def test_demo_workloads_namespace_and_annotations():
    docs = [d for d in yaml.safe_load_all((K8S / "demo-workloads.yaml").read_text()) if d]
    ns = next(d for d in docs if d["kind"] == "Namespace")
    assert ns["metadata"]["name"] == "demo-apps"
    node_exporter = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "node-exporter")
    annotations = node_exporter["spec"]["template"]["metadata"]["annotations"]
    assert annotations["prometheus.io/scrape"] == "true"
