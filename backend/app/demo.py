"""Synthetic data for DEMO_MODE.

Lets the whole application (analysis + report) run end-to-end with no Kubernetes
cluster and no Prometheus. The shapes exactly match what the real clients return,
so the analyzer and the UI behave identically.

The fixtures are designed to exercise every finding type: over-provisioning,
OOM risk, CPU throttling, idle pods, missing limits, and healthy pods.
"""
from __future__ import annotations

from .models import PodSpec, ContainerSpec, ContainerMetrics

MI = 1024 ** 2
GI = 1024 ** 3

# namespace -> list of (PodSpec, {container: ContainerMetrics})
_NAMESPACES = ["mercury-prod", "mercury-staging", "platform"]


def list_namespaces() -> list[str]:
    return list(_NAMESPACES)


def _pod(name, ns, qos, containers, node="node-2", restarts=0, oom=False, age_hours=720.0):
    return PodSpec(
        name=name, namespace=ns, qos_class=qos, node=node,
        age_hours=age_hours, restarts=restarts, oom_killed=oom,
        phase="Running", containers=containers,
    )


def _build_prod():
    specs: list[PodSpec] = []
    metrics: dict[tuple[str, str], ContainerMetrics] = {}

    # 1) Java backend, heavily over-provisioned on CPU and memory.
    specs.append(_pod(
        "zaam-api-7d9c8b6f4-q2xkz", "mercury-prod", "Burstable",
        [ContainerSpec("zaam-api", cpu_request=2.0, cpu_limit=4.0,
                       mem_request=4 * GI, mem_limit=6 * GI)],
    ))
    metrics[("zaam-api-7d9c8b6f4-q2xkz", "zaam-api")] = ContainerMetrics(
        cpu_avg=0.18, cpu_p95=0.34, cpu_max=0.62,
        mem_avg=1.1 * GI, mem_p95=1.4 * GI, mem_max=1.7 * GI, cpu_throttle=0.0,
    )

    # 2) NestJS service throttled (CPU limit too low).
    specs.append(_pod(
        "credit-recovery-5f7b9d-h8m2p", "mercury-prod", "Burstable",
        [ContainerSpec("credit-recovery", cpu_request=0.25, cpu_limit=0.5,
                       mem_request=512 * MI, mem_limit=768 * MI)],
    ))
    metrics[("credit-recovery-5f7b9d-h8m2p", "credit-recovery")] = ContainerMetrics(
        cpu_avg=0.42, cpu_p95=0.49, cpu_max=0.5,
        mem_avg=420 * MI, mem_p95=480 * MI, mem_max=510 * MI, cpu_throttle=0.61,
    )

    # 3) MongoDB at OOM risk + already OOMKilled.
    specs.append(_pod(
        "mongodb-0", "mercury-prod", "Burstable",
        [ContainerSpec("mongodb", cpu_request=1.0, cpu_limit=2.0,
                       mem_request=2 * GI, mem_limit=2 * GI)],
        node="node-1", restarts=4, oom=True,
    ))
    metrics[("mongodb-0", "mongodb")] = ContainerMetrics(
        cpu_avg=0.55, cpu_p95=0.9, cpu_max=1.3,
        mem_avg=1.7 * GI, mem_p95=1.9 * GI, mem_max=1.98 * GI, cpu_throttle=0.05,
    )

    # 4) Angular frontend (nginx) over-provisioned + idle-ish.
    specs.append(_pod(
        "zaam-frontend-6c4d8f-7tq9w", "mercury-prod", "Burstable",
        [ContainerSpec("nginx", cpu_request=0.5, cpu_limit=1.0,
                       mem_request=512 * MI, mem_limit=512 * MI)],
        node="node-3",
    ))
    metrics[("zaam-frontend-6c4d8f-7tq9w", "nginx")] = ContainerMetrics(
        cpu_avg=0.004, cpu_p95=0.008, cpu_max=0.03,
        mem_avg=28 * MI, mem_p95=34 * MI, mem_max=48 * MI, cpu_throttle=0.0,
    )

    # 5) Healthy, well-sized worker.
    specs.append(_pod(
        "ai-remediator-849f6c-k3l7m", "mercury-prod", "Guaranteed",
        [ContainerSpec("remediator", cpu_request=0.5, cpu_limit=0.5,
                       mem_request=512 * MI, mem_limit=512 * MI)],
    ))
    metrics[("ai-remediator-849f6c-k3l7m", "remediator")] = ContainerMetrics(
        cpu_avg=0.31, cpu_p95=0.41, cpu_max=0.47,
        mem_avg=360 * MI, mem_p95=410 * MI, mem_max=440 * MI, cpu_throttle=0.02,
    )

    # 6) Batch job with no requests/limits at all.
    specs.append(_pod(
        "nightly-export-28371", "mercury-prod", "BestEffort",
        [ContainerSpec("export")],  # no requests/limits
        restarts=1, age_hours=12.0,
    ))
    metrics[("nightly-export-28371", "export")] = ContainerMetrics(
        cpu_avg=0.6, cpu_p95=1.2, cpu_max=2.1,
        mem_avg=700 * MI, mem_p95=900 * MI, mem_max=1.3 * GI, cpu_throttle=0.0,
    )

    return specs, metrics


def _build_staging():
    specs: list[PodSpec] = []
    metrics: dict[tuple[str, str], ContainerMetrics] = {}

    specs.append(_pod(
        "zaam-api-staging-66bd9-aa11b", "mercury-staging", "Burstable",
        [ContainerSpec("zaam-api", cpu_request=1.0, cpu_limit=2.0,
                       mem_request=2 * GI, mem_limit=3 * GI)],
    ))
    metrics[("zaam-api-staging-66bd9-aa11b", "zaam-api")] = ContainerMetrics(
        cpu_avg=0.05, cpu_p95=0.09, cpu_max=0.2,
        mem_avg=380 * MI, mem_p95=460 * MI, mem_max=600 * MI, cpu_throttle=0.0,
    )

    specs.append(_pod(
        "sqlserver-0", "mercury-staging", "Burstable",
        [ContainerSpec("mssql", cpu_request=2.0, cpu_limit=2.0,
                       mem_request=4 * GI, mem_limit=4 * GI)],
        node="node-1",
    ))
    metrics[("sqlserver-0", "mssql")] = ContainerMetrics(
        cpu_avg=0.3, cpu_p95=0.6, cpu_max=1.1,
        mem_avg=2.1 * GI, mem_p95=2.4 * GI, mem_max=2.7 * GI, cpu_throttle=0.0,
    )
    return specs, metrics


def _build_platform():
    specs: list[PodSpec] = []
    metrics: dict[tuple[str, str], ContainerMetrics] = {}
    specs.append(_pod(
        "prometheus-0", "platform", "Burstable",
        [ContainerSpec("prometheus", cpu_request=0.5, cpu_limit=1.0,
                       mem_request=2 * GI, mem_limit=2 * GI)],
    ))
    metrics[("prometheus-0", "prometheus")] = ContainerMetrics(
        cpu_avg=0.22, cpu_p95=0.38, cpu_max=0.55,
        mem_avg=1.5 * GI, mem_p95=1.7 * GI, mem_max=1.85 * GI, cpu_throttle=0.0,
    )
    return specs, metrics


_BUILDERS = {
    "mercury-prod": _build_prod,
    "mercury-staging": _build_staging,
    "platform": _build_platform,
}


def data_for_namespace(namespace: str):
    builder = _BUILDERS.get(namespace)
    if builder is None:
        return [], {}
    return builder()
