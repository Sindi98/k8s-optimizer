"""Thin wrapper over the Kubernetes API to read pod specs and status.

Only read operations are used. In-cluster it relies on the mounted
ServiceAccount; locally it loads the kubeconfig.
"""
from __future__ import annotations

import datetime
import logging

from .config import settings
from .models import PodSpec, ContainerSpec
from .util import parse_cpu, parse_memory

log = logging.getLogger("k8s")


class KubernetesClient:
    def __init__(self) -> None:
        # Imported lazily so the app can boot in demo mode without the package.
        from kubernetes import client, config as k8s_config

        if settings.in_cluster:
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config(config_file=settings.kubeconfig)
        self._core = client.CoreV1Api()

    def list_namespaces(self) -> list[str]:
        items = self._core.list_namespace().items
        return sorted(ns.metadata.name for ns in items)

    def list_pod_specs(self, namespace: str) -> list[PodSpec]:
        pods = self._core.list_namespaced_pod(namespace=namespace).items
        out: list[PodSpec] = []
        now = datetime.datetime.now(datetime.timezone.utc)
        for p in pods:
            spec = self._pod_to_spec(p, now)
            if spec is not None:
                out.append(spec)
        return out

    # -- internals -----------------------------------------------------------
    def _pod_to_spec(self, p, now) -> PodSpec | None:
        meta = p.metadata
        status = p.status

        age_hours = None
        if meta.creation_timestamp:
            age_hours = (now - meta.creation_timestamp).total_seconds() / 3600.0

        workload = None
        for ref in (meta.owner_references or []):
            if ref.kind in {"ReplicaSet", "StatefulSet", "DaemonSet", "Deployment", "Job"}:
                # strip the ReplicaSet hash to approximate the Deployment name
                name = ref.name
                if ref.kind == "ReplicaSet" and "-" in name:
                    name = name.rsplit("-", 1)[0]
                workload = f"{ref.kind if ref.kind != 'ReplicaSet' else 'Deployment'}/{name}"
                break

        restarts = 0
        oom = False
        # Include init containers: a crash-looping init container (failed
        # migration / wait-for-dependency) is a real reliability signal too.
        statuses = list(status.container_statuses or []) + list(status.init_container_statuses or [])
        for cs in statuses:
            restarts += cs.restart_count or 0
            # OOMKilled can be in the CURRENT state (terminated, not yet restarted)
            # or in the PREVIOUS state (last_state) after a restart.
            for st in (getattr(cs, "state", None), getattr(cs, "last_state", None)):
                term = getattr(st, "terminated", None) if st else None
                if term and getattr(term, "reason", None) == "OOMKilled":
                    oom = True

        containers: list[ContainerSpec] = []
        for c in (p.spec.containers or []):
            req = (c.resources.requests if c.resources else None) or {}
            lim = (c.resources.limits if c.resources else None) or {}
            containers.append(
                ContainerSpec(
                    name=c.name,
                    cpu_request=parse_cpu(req.get("cpu")),
                    cpu_limit=parse_cpu(lim.get("cpu")),
                    mem_request=parse_memory(req.get("memory")),
                    mem_limit=parse_memory(lim.get("memory")),
                )
            )

        return PodSpec(
            name=meta.name,
            namespace=meta.namespace,
            qos_class=status.qos_class,
            node=p.spec.node_name,
            age_hours=age_hours,
            workload=workload,
            restarts=restarts,
            oom_killed=oom,
            phase=status.phase,
            containers=containers,
        )
