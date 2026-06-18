"""The analyzer.

This is where the deterministic work happens. Given pod specs (from the
Kubernetes API) and usage metrics (from Prometheus), it produces per-container
findings: what is over-provisioned, what is at risk of OOM, what is throttled,
what is idle, and a concrete recommended `requests`/`limits` pair with the
amount of CPU/memory that can be reclaimed.

The LLM never computes any of these numbers; it only narrates them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import settings
from .models import (
    PodSpec,
    ContainerMetrics,
    ContainerFinding,
    PodFinding,
    NamespaceAnalysis,
    Issue,
)
from .util import (
    format_cpu,
    format_memory,
    round_millicores,
    round_memory_mi,
)


def _safe_ratio(used: float | None, requested: float | None) -> float | None:
    if used is None or not requested:
        return None
    return used / requested


def analyze_container(c_spec, metrics: ContainerMetrics, qos: str | None) -> ContainerFinding:
    s = settings
    issues: list[Issue] = []

    cpu_req = c_spec.cpu_request
    cpu_lim = c_spec.cpu_limit
    mem_req = c_spec.mem_request
    mem_lim = c_spec.mem_limit

    cpu_p95 = metrics.cpu_p95
    cpu_max = metrics.cpu_max
    mem_p95 = metrics.mem_p95
    mem_max = metrics.mem_max
    throttle = metrics.cpu_throttle or 0.0

    # --- recommendations (defaults: keep current unless we have data) -------
    rec_cpu_req = cpu_req
    rec_cpu_lim = cpu_lim
    rec_mem_req = mem_req
    rec_mem_lim = mem_lim
    reclaim_cpu = 0.0
    reclaim_mem = 0.0

    # ---- Missing requests / limits ----
    if cpu_req is None and mem_req is None:
        issues.append(Issue(
            "missing_requests", "warning", "Requests assenti",
            "Nessuna richiesta di CPU/memoria: lo scheduler non può posizionare il pod "
            "in modo affidabile (QoS BestEffort, primo candidato all'eviction).",
        ))
    if cpu_lim is None and mem_lim is None:
        issues.append(Issue(
            "missing_limits", "info", "Limits assenti",
            "Nessun limite impostato: il container può saturare CPU/memoria del nodo.",
        ))

    # ---- CPU over-provisioning ----
    cpu_ratio = _safe_ratio(cpu_p95, cpu_req)
    if cpu_req and cpu_p95 is not None and cpu_ratio is not None and cpu_ratio < s.overprov_ratio:
        rec_cpu_req = round_millicores(cpu_p95 * s.request_buffer)
        if rec_cpu_req < cpu_req:
            reclaim_cpu = cpu_req - rec_cpu_req
            issues.append(Issue(
                "over_provisioned_cpu", "warning", "CPU sovradimensionata",
                f"Usa {format_cpu(cpu_p95)} al p95 contro una richiesta di {format_cpu(cpu_req)} "
                f"({cpu_ratio*100:.0f}%). Richiesta consigliata: {format_cpu(rec_cpu_req)}.",
            ))
        if cpu_lim and cpu_max is not None:
            rec_cpu_lim = max(round_millicores(cpu_max * s.limit_buffer), rec_cpu_req)

    # ---- CPU throttling / under-provisioning ----
    if throttle >= s.throttle_ratio:
        sev = "critical" if throttle >= 0.5 else "warning"
        if cpu_lim and cpu_max is not None:
            rec_cpu_lim = round_millicores(max(cpu_lim, cpu_max) * s.limit_buffer)
        issues.append(Issue(
            "cpu_throttling", sev, "CPU in throttling",
            f"Il container è in throttling il {throttle*100:.0f}% del tempo: il limite CPU "
            f"({format_cpu(cpu_lim)}) è troppo basso e rallenta l'applicazione.",
        ))

    # ---- Memory OOM risk ----
    mem_ratio_max = _safe_ratio(mem_max, mem_lim)
    if mem_lim and mem_ratio_max is not None and mem_ratio_max >= s.risk_ratio:
        rec_mem_lim = round_memory_mi(mem_max * s.limit_buffer)
        rec_mem_req = max(rec_mem_req or 0, round_memory_mi((mem_p95 or mem_max)))
        issues.append(Issue(
            "oom_risk", "critical", "Rischio OOM",
            f"Il picco di memoria ({format_memory(mem_max)}) è al {mem_ratio_max*100:.0f}% "
            f"del limite ({format_memory(mem_lim)}). Limite consigliato: {format_memory(rec_mem_lim)}.",
        ))

    # ---- Memory over-provisioning ----
    mem_ratio = _safe_ratio(mem_p95, mem_req)
    if mem_req and mem_p95 is not None and mem_ratio is not None and mem_ratio < s.overprov_ratio:
        rec_mem_req = round_memory_mi(mem_p95 * s.request_buffer)
        if rec_mem_req < mem_req:
            reclaim_mem = mem_req - rec_mem_req
            issues.append(Issue(
                "over_provisioned_mem", "warning", "Memoria sovradimensionata",
                f"Usa {format_memory(mem_p95)} al p95 contro una richiesta di {format_memory(mem_req)} "
                f"({mem_ratio*100:.0f}%). Richiesta consigliata: {format_memory(rec_mem_req)}.",
            ))

    # ---- Idle ----
    cpu_low = (cpu_p95 is not None and cpu_p95 < s.idle_cpu_cores)
    mem_low = (mem_p95 is not None and mem_p95 < 32 * 1024 ** 2)  # < 32Mi
    if cpu_low and mem_low and (cpu_req or mem_req):
        issues.append(Issue(
            "idle", "info", "Pod inattivo",
            "Consumo di CPU e memoria quasi nullo nella finestra analizzata: "
            "valuta scale-to-zero, riduzione delle repliche o rimozione.",
        ))

    finding = ContainerFinding(
        name=c_spec.name,
        qos_class=qos,
        spec={
            "cpu_request": cpu_req, "cpu_limit": cpu_lim,
            "mem_request": mem_req, "mem_limit": mem_lim,
            "cpu_request_label": format_cpu(cpu_req), "cpu_limit_label": format_cpu(cpu_lim),
            "mem_request_label": format_memory(mem_req), "mem_limit_label": format_memory(mem_lim),
        },
        usage={
            "cpu_avg": metrics.cpu_avg, "cpu_p95": cpu_p95, "cpu_max": cpu_max,
            "mem_avg": metrics.mem_avg, "mem_p95": mem_p95, "mem_max": mem_max,
            "cpu_throttle": throttle,
            "cpu_p95_label": format_cpu(cpu_p95), "cpu_max_label": format_cpu(cpu_max),
            "mem_p95_label": format_memory(mem_p95), "mem_max_label": format_memory(mem_max),
            # fraction of request used at p95, for the request-vs-reality bars
            "cpu_use_ratio": cpu_ratio, "mem_use_ratio": mem_ratio,
        },
        recommendation={
            "cpu_request": rec_cpu_req, "cpu_limit": rec_cpu_lim,
            "mem_request": rec_mem_req, "mem_limit": rec_mem_lim,
            "cpu_request_label": format_cpu(rec_cpu_req), "cpu_limit_label": format_cpu(rec_cpu_lim),
            "mem_request_label": format_memory(rec_mem_req), "mem_limit_label": format_memory(rec_mem_lim),
            "reclaim_cpu_cores": reclaim_cpu, "reclaim_mem_bytes": reclaim_mem,
            "reclaim_cpu_label": format_cpu(reclaim_cpu) if reclaim_cpu else None,
            "reclaim_mem_label": format_memory(reclaim_mem) if reclaim_mem else None,
        },
        issues=issues,
    )
    return finding, reclaim_cpu, reclaim_mem


def analyze_pod(spec: PodSpec, metrics: dict[tuple[str, str], ContainerMetrics]) -> PodFinding:
    pod = PodFinding(
        name=spec.name,
        namespace=spec.namespace,
        node=spec.node,
        qos_class=spec.qos_class,
        age_hours=spec.age_hours,
        restarts=spec.restarts,
        oom_killed=spec.oom_killed,
    )
    if spec.oom_killed:
        # surfaced at pod level, but reflect on the first container too
        pass

    for c in spec.containers:
        m = metrics.get((spec.name, c.name), ContainerMetrics())
        finding, rc, rm = analyze_container(c, m, spec.qos_class)
        if spec.oom_killed:
            finding.issues.insert(0, Issue(
                "oom_killed", "critical", "OOMKilled in passato",
                "Il container è già stato terminato per esaurimento memoria: "
                "alza la richiesta/limite di memoria.",
            ))
        pod.containers.append(finding)
        pod.reclaimable_cpu += rc
        pod.reclaimable_mem += rm

    return pod


def analyze_namespace(
    specs: list[PodSpec],
    metrics: dict[tuple[str, str], ContainerMetrics],
    window: str,
) -> NamespaceAnalysis:
    pods = [analyze_pod(s, metrics) for s in specs]
    # worst issues first, then biggest reclaimable
    pods.sort(key=lambda p: (
        {"critical": 0, "warning": 1, "info": 2, "ok": 3}[p.severity],
        -(p.reclaimable_cpu + p.reclaimable_mem / 1024 ** 3),
    ))
    ns = specs[0].namespace if specs else ""
    return NamespaceAnalysis(
        namespace=ns,
        window=window,
        pods=pods,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
