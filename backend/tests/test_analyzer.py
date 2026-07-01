"""Tests for the deterministic analyzer — the numbers the LLM never computes."""
from app.analyzer import analyze_container
from app.models import ContainerMetrics, ContainerSpec

MI = 1024 ** 2
GI = 1024 ** 3


def _kinds(finding):
    return {i.kind for i in finding.issues}


def test_overprovisioned_cpu_and_memory():
    spec = ContainerSpec("c", cpu_request=1.0, cpu_limit=2.0, mem_request=2 * GI, mem_limit=2 * GI)
    m = ContainerMetrics(cpu_avg=0.05, cpu_p95=0.1, cpu_max=0.2,
                         mem_avg=0.15 * GI, mem_p95=0.2 * GI, mem_max=0.3 * GI, cpu_throttle=0.0)
    finding, reclaim_cpu, reclaim_mem = analyze_container(spec, m, "Burstable")
    kinds = _kinds(finding)
    assert "over_provisioned_cpu" in kinds
    assert "over_provisioned_mem" in kinds
    assert reclaim_cpu > 0
    assert reclaim_mem > 0
    assert finding.severity == "warning"


def test_oom_risk():
    spec = ContainerSpec("c", cpu_request=0.2, cpu_limit=0.5, mem_request=128 * MI, mem_limit=256 * MI)
    m = ContainerMetrics(cpu_p95=0.1, cpu_max=0.15, mem_p95=230 * MI, mem_max=245 * MI, cpu_throttle=0.0)
    finding, _, _ = analyze_container(spec, m, "Burstable")
    assert "oom_risk" in _kinds(finding)
    assert finding.severity == "critical"


def test_cpu_throttling():
    spec = ContainerSpec("c", cpu_request=0.1, cpu_limit=0.1, mem_request=64 * MI, mem_limit=128 * MI)
    m = ContainerMetrics(cpu_p95=0.1, cpu_max=0.1, mem_p95=50 * MI, mem_max=60 * MI, cpu_throttle=0.6)
    finding, _, _ = analyze_container(spec, m, "Burstable")
    assert "cpu_throttling" in _kinds(finding)
    assert finding.severity == "critical"


def test_missing_requests_and_limits():
    spec = ContainerSpec("c")  # no requests/limits
    finding, _, _ = analyze_container(spec, ContainerMetrics(), "BestEffort")
    kinds = _kinds(finding)
    assert "missing_requests" in kinds
    assert "missing_limits" in kinds


def test_half_specified_container_is_flagged():
    # CPU set but memory absent must still be flagged (per-dimension, not "both missing")
    spec = ContainerSpec("c", cpu_request=0.5, cpu_limit=1.0)  # memory req/lim absent
    m = ContainerMetrics(cpu_p95=0.2, cpu_max=0.3, mem_p95=100 * MI, mem_max=150 * MI)
    finding, _, _ = analyze_container(spec, m, "Burstable")
    kinds = _kinds(finding)
    assert "missing_requests" in kinds
    assert "missing_limits" in kinds


def test_besteffort_with_usage_gets_recommendation():
    # no requests/limits but real usage -> concrete starting point, no phantom reclaim
    spec = ContainerSpec("c")
    m = ContainerMetrics(cpu_p95=1.0, cpu_max=2.0, mem_p95=500 * MI, mem_max=800 * MI)
    finding, reclaim_cpu, reclaim_mem = analyze_container(spec, m, "BestEffort")
    rec = finding.recommendation
    assert rec["cpu_request"] is not None and rec["cpu_request"] >= 1.0
    assert rec["mem_request"] is not None
    assert rec["cpu_limit"] >= rec["cpu_request"]
    assert rec["mem_limit"] >= rec["mem_request"]
    # a new allocation is not a reduction: reclaim totals must not be inflated
    assert reclaim_cpu == 0 and reclaim_mem == 0


def test_idle():
    spec = ContainerSpec("c", cpu_request=0.5, cpu_limit=1.0, mem_request=512 * MI, mem_limit=1 * GI)
    m = ContainerMetrics(cpu_p95=0.001, cpu_max=0.002, mem_p95=10 * MI, mem_max=12 * MI, cpu_throttle=0.0)
    finding, _, _ = analyze_container(spec, m, "Burstable")
    assert "idle" in _kinds(finding)


def test_healthy_has_no_issues():
    spec = ContainerSpec("c", cpu_request=0.5, cpu_limit=1.0, mem_request=512 * MI, mem_limit=1 * GI)
    m = ContainerMetrics(cpu_p95=0.4, cpu_max=0.45, mem_p95=400 * MI, mem_max=450 * MI, cpu_throttle=0.0)
    finding, reclaim_cpu, reclaim_mem = analyze_container(spec, m, "Burstable")
    assert finding.issues == []
    assert finding.severity == "ok"
    assert reclaim_cpu == 0 and reclaim_mem == 0
