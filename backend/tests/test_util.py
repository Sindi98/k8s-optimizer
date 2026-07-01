"""Unit tests for the resource-quantity parsing/formatting helpers."""
from app.util import (
    cores_to_millicores,
    format_cpu,
    format_memory,
    parse_cpu,
    parse_memory,
    round_memory_mi,
    round_millicores,
)

MI = 1024 ** 2
GI = 1024 ** 3


def test_parse_cpu():
    assert parse_cpu("250m") == 0.25
    assert parse_cpu("1") == 1.0
    assert parse_cpu(2) == 2.0
    assert parse_cpu(None) is None
    assert parse_cpu("") is None
    assert parse_cpu("500000u") == 0.5
    assert parse_cpu("100000000n") == 0.1


def test_parse_memory():
    assert parse_memory("512Mi") == 512 * MI
    assert parse_memory("2Gi") == 2 * GI
    assert parse_memory("1000") == 1000.0
    assert parse_memory("1M") == 1_000_000
    assert parse_memory(None) is None
    assert parse_memory("") is None


def test_format_cpu():
    assert format_cpu(0.25) == "250m"
    assert format_cpu(1.5) == "1.5"
    assert format_cpu(2.0) == "2"
    assert format_cpu(None) == "—"


def test_format_memory():
    assert format_memory(512 * MI) == "512Mi"
    assert format_memory(2 * GI) == "2Gi"
    assert format_memory(None) == "—"


def test_cores_to_millicores():
    assert cores_to_millicores(0.25) == 250
    assert cores_to_millicores(None) is None


def test_rounding_floors():
    # tiny CPU rounds up to the 10m floor
    assert round_millicores(0.0024) == 0.01
    # memory rounds up to at least the 16Mi floor
    assert round_memory_mi(1 * MI) == 16 * MI


def test_rounding_is_ceil_not_nearest():
    # a value just above a step midpoint must round UP, never down below it,
    # so a buffered recommendation never lands under the observed usage
    assert round_millicores(0.041) == 0.045          # 41m -> next 5m step
    assert round_memory_mi(219 * MI) >= 219 * MI      # never below the input
    assert round_memory_mi(219 * MI) == 224 * MI      # 219 -> next 8Mi step
