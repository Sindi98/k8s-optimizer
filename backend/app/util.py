"""Helpers for parsing Kubernetes resource quantities and formatting values."""
from __future__ import annotations

import math
import re

# --- CPU --------------------------------------------------------------------
# Kubernetes CPU is expressed in cores. "250m" = 0.25 cores, "1" = 1 core.

def parse_cpu(value: str | float | int | None) -> float | None:
    """Parse a Kubernetes CPU quantity into a float number of cores."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip()
    if value == "":
        return None
    if value.endswith("m"):
        return float(value[:-1]) / 1000.0
    if value.endswith("n"):  # nanocores
        return float(value[:-1]) / 1_000_000_000.0
    if value.endswith("u"):  # microcores
        return float(value[:-1]) / 1_000_000.0
    return float(value)


# --- Memory -----------------------------------------------------------------
_MEM_SUFFIXES = {
    "Ki": 1024,
    "Mi": 1024 ** 2,
    "Gi": 1024 ** 3,
    "Ti": 1024 ** 4,
    "Pi": 1024 ** 5,
    "K": 1000,
    "M": 1000 ** 2,
    "G": 1000 ** 3,
    "T": 1000 ** 4,
    "P": 1000 ** 5,
    "k": 1000,
}


def parse_memory(value: str | float | int | None) -> float | None:
    """Parse a Kubernetes memory quantity into bytes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip()
    if value == "":
        return None
    m = re.match(r"^([0-9.]+)([A-Za-z]*)$", value)
    if not m:
        return None
    num, suffix = m.group(1), m.group(2)
    factor = _MEM_SUFFIXES.get(suffix, 1)
    return float(num) * factor


# --- Formatting -------------------------------------------------------------

def cores_to_millicores(cores: float | None) -> int | None:
    if cores is None:
        return None
    return int(round(cores * 1000))


def format_cpu(cores: float | None) -> str:
    if cores is None:
        return "—"
    if cores < 1:
        return f"{int(round(cores * 1000))}m"
    return f"{cores:.2f}".rstrip("0").rstrip(".")


def format_memory(num_bytes: float | None) -> str:
    if num_bytes is None:
        return "—"
    gi = 1024 ** 3
    mi = 1024 ** 2
    if num_bytes >= gi:
        return f"{num_bytes / gi:.2f}".rstrip("0").rstrip(".") + "Gi"
    return f"{num_bytes / mi:.0f}Mi"


def round_millicores(cores: float, floor_m: int = 10, step_m: int = 5) -> float:
    """Round a recommended CPU value up to a sensible millicore step.

    Rounds *up* (ceil) to the step: a recommendation must never land below the
    buffered target it was derived from, otherwise the tool could suggest a
    request/limit under the observed usage of the very container it flagged.
    """
    m = max(floor_m, cores * 1000)
    m = step_m * math.ceil(m / step_m)
    return max(floor_m, m) / 1000.0


def round_memory_mi(num_bytes: float, floor_mi: int = 16, step_mi: int = 8) -> float:
    """Round a recommended memory value up to a sensible Mi step (ceil, see above)."""
    mi = 1024 ** 2
    val = max(floor_mi, num_bytes / mi)
    val = step_mi * math.ceil(val / step_mi)
    return max(floor_mi, val) * mi
