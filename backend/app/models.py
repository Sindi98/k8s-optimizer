"""Data models shared across the optimizer.

Numbers flow through here as plain floats (CPU in cores, memory in bytes) so the
analyzer can do deterministic math. The LLM only ever sees the computed result.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from .util import format_cpu, format_memory, cores_to_millicores

# Severity ordering for sorting / colour mapping in the UI.
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "ok": 3}


@dataclass
class ContainerSpec:
    name: str
    cpu_request: float | None = None      # cores
    cpu_limit: float | None = None        # cores
    mem_request: float | None = None      # bytes
    mem_limit: float | None = None        # bytes


@dataclass
class ContainerMetrics:
    cpu_avg: float | None = None          # cores
    cpu_p95: float | None = None          # cores
    cpu_max: float | None = None          # cores
    mem_avg: float | None = None          # bytes
    mem_p95: float | None = None          # bytes
    mem_max: float | None = None          # bytes
    cpu_throttle: float | None = None     # 0..1


@dataclass
class PodSpec:
    name: str
    namespace: str
    qos_class: str | None = None
    node: str | None = None
    age_hours: float | None = None
    workload: str | None = None           # owning Deployment/StatefulSet, if known
    restarts: int = 0
    oom_killed: bool = False
    phase: str | None = None
    containers: list[ContainerSpec] = field(default_factory=list)


@dataclass
class Issue:
    """A single optimisation finding on a container."""
    kind: str            # over_provisioned_cpu, oom_risk, cpu_throttling, missing_limits, idle...
    severity: str        # critical | warning | info
    title: str
    detail: str


@dataclass
class ContainerFinding:
    name: str
    qos_class: str | None
    spec: dict[str, Any]
    usage: dict[str, Any]
    recommendation: dict[str, Any]       # recommended requests/limits + reclaimable
    issues: list[Issue] = field(default_factory=list)

    @property
    def severity(self) -> str:
        if not self.issues:
            return "ok"
        return min((i.severity for i in self.issues), key=lambda s: SEVERITY_ORDER[s])


@dataclass
class PodFinding:
    name: str
    namespace: str
    node: str | None
    qos_class: str | None
    age_hours: float | None
    restarts: int
    oom_killed: bool
    containers: list[ContainerFinding] = field(default_factory=list)
    reclaimable_cpu: float = 0.0          # cores
    reclaimable_mem: float = 0.0          # bytes

    @property
    def severity(self) -> str:
        sev = [c.severity for c in self.containers]
        if not sev:
            return "ok"
        return min(sev, key=lambda s: SEVERITY_ORDER[s])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity
        d["reclaimable_cpu_m"] = cores_to_millicores(self.reclaimable_cpu)
        d["reclaimable_mem_mi"] = round(self.reclaimable_mem / (1024 ** 2)) if self.reclaimable_mem else 0
        return d


@dataclass
class NamespaceAnalysis:
    namespace: str
    window: str
    pods: list[PodFinding] = field(default_factory=list)
    generated_at: str | None = None

    def summary(self) -> dict[str, Any]:
        reclaim_cpu = sum(p.reclaimable_cpu for p in self.pods)
        reclaim_mem = sum(p.reclaimable_mem for p in self.pods)
        counts = {"critical": 0, "warning": 0, "info": 0, "ok": 0}
        for p in self.pods:
            counts[p.severity] += 1
        # current requested totals across analysed pods
        req_cpu = sum(
            (c.spec.get("cpu_request") or 0) for p in self.pods for c in p.containers
        )
        req_mem = sum(
            (c.spec.get("mem_request") or 0) for p in self.pods for c in p.containers
        )
        return {
            "pods_total": len(self.pods),
            "reclaimable_cpu_cores": round(reclaim_cpu, 3),
            "reclaimable_cpu_label": format_cpu(reclaim_cpu) if reclaim_cpu else "0m",
            "reclaimable_mem_bytes": reclaim_mem,
            "reclaimable_mem_label": format_memory(reclaim_mem) if reclaim_mem else "0Mi",
            "requested_cpu_cores": round(req_cpu, 3),
            "requested_mem_bytes": req_mem,
            "cpu_savings_pct": round(100 * reclaim_cpu / req_cpu, 1) if req_cpu else 0,
            "mem_savings_pct": round(100 * reclaim_mem / req_mem, 1) if req_mem else 0,
            "counts": counts,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "window": self.window,
            "generated_at": self.generated_at,
            "summary": self.summary(),
            "pods": [p.to_dict() for p in self.pods],
        }
