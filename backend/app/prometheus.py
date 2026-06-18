"""Prometheus client.

Runs a small set of PromQL queries per namespace and returns usage metrics
keyed by (pod, container). All queries are instant queries against
`/api/v1/query`; range/quantile aggregation is done inside PromQL via subqueries.

Metric names assume cAdvisor / kubelet (`container_*`) which is what the
kube-prometheus-stack exposes by default.
"""
from __future__ import annotations

import logging

import httpx

from .config import settings
from .models import ContainerMetrics

log = logging.getLogger("prometheus")

# container!="" and container!="POD" drops the pod sandbox / pause container.
_FILTER = 'namespace="{ns}", container!="", container!="POD"'


def _queries(ns: str, window: str) -> dict[str, str]:
    f = _FILTER.format(ns=ns)
    return {
        "cpu_avg": f'avg by (pod, container) (rate(container_cpu_usage_seconds_total{{{f}}}[{window}]))',
        "cpu_p95": (
            f'quantile_over_time(0.95, sum by (pod, container) '
            f'(rate(container_cpu_usage_seconds_total{{{f}}}[5m]))[{window}:5m])'
        ),
        "cpu_max": (
            f'max_over_time(sum by (pod, container) '
            f'(rate(container_cpu_usage_seconds_total{{{f}}}[5m]))[{window}:5m])'
        ),
        "mem_avg": f'avg by (pod, container) (avg_over_time(container_memory_working_set_bytes{{{f}}}[{window}]))',
        "mem_p95": f'max by (pod, container) (quantile_over_time(0.95, container_memory_working_set_bytes{{{f}}}[{window}]))',
        "mem_max": f'max by (pod, container) (max_over_time(container_memory_working_set_bytes{{{f}}}[{window}]))',
        "cpu_throttle": (
            f'sum by (pod, container) (rate(container_cpu_cfs_throttled_periods_total{{{f}}}[{window}])) '
            f'/ clamp_min(sum by (pod, container) (rate(container_cpu_cfs_periods_total{{{f}}}[{window}])), 1)'
        ),
    }


class PrometheusClient:
    def __init__(self) -> None:
        self.base = settings.prometheus_url.rstrip("/")
        self.timeout = settings.prom_timeout

    def _query(self, promql: str) -> list[dict]:
        url = f"{self.base}/api/v1/query"
        try:
            r = httpx.get(url, params={"query": promql}, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001 - surface as empty, log for debugging
            log.warning("Prometheus query failed: %s", exc)
            return []
        if data.get("status") != "success":
            log.warning("Prometheus returned non-success: %s", data.get("error"))
            return []
        return data["data"]["result"]

    def metrics_for_namespace(self, namespace: str) -> dict[tuple[str, str], ContainerMetrics]:
        """Return {(pod, container): ContainerMetrics} for the namespace."""
        result: dict[tuple[str, str], ContainerMetrics] = {}

        def ensure(pod: str, container: str) -> ContainerMetrics:
            key = (pod, container)
            if key not in result:
                result[key] = ContainerMetrics()
            return result[key]

        for field_name, promql in _queries(namespace, settings.analysis_window).items():
            for series in self._query(promql):
                metric = series.get("metric", {})
                pod = metric.get("pod")
                container = metric.get("container")
                if not pod or not container:
                    continue
                try:
                    value = float(series["value"][1])
                except (KeyError, ValueError, TypeError):
                    continue
                setattr(ensure(pod, container), field_name, value)

        return result
