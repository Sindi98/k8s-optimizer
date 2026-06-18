"""Configuration loaded from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # --- Runtime / cluster connection ---
    demo_mode: bool = field(default_factory=lambda: _get_bool("DEMO_MODE", False))
    in_cluster: bool = field(default_factory=lambda: _get_bool("IN_CLUSTER", False))
    kubeconfig: str | None = field(default_factory=lambda: os.getenv("KUBECONFIG") or None)

    # --- Prometheus ---
    prometheus_url: str = field(
        default_factory=lambda: os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    )
    # Analysis window (e.g. 7d, 24h, 3d). Used by range/subquery PromQL.
    analysis_window: str = field(default_factory=lambda: os.getenv("ANALYSIS_WINDOW", "7d"))
    prom_timeout: float = field(default_factory=lambda: _get_float("PROM_TIMEOUT", 30.0))

    # --- LLM provider ---
    # one of: mock | anthropic | ollama | openai
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock").lower())
    report_language: str = field(default_factory=lambda: os.getenv("REPORT_LANGUAGE", "it"))

    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None)
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"))

    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1"))

    # --- Analysis thresholds (all tunable) ---
    # A container using less than this fraction of its request (at p95) is "over-provisioned".
    overprov_ratio: float = field(default_factory=lambda: _get_float("OVERPROV_RATIO", 0.5))
    # Headroom buffer applied on top of observed p95 usage when recommending a new request.
    request_buffer: float = field(default_factory=lambda: _get_float("REQUEST_BUFFER", 1.2))
    # Buffer applied on top of observed max usage when recommending a new limit.
    limit_buffer: float = field(default_factory=lambda: _get_float("LIMIT_BUFFER", 1.5))
    # Usage above this fraction of the limit (at max) flags an under-provisioning / OOM risk.
    risk_ratio: float = field(default_factory=lambda: _get_float("RISK_RATIO", 0.9))
    # CPU throttling above this fraction is flagged.
    throttle_ratio: float = field(default_factory=lambda: _get_float("THROTTLE_RATIO", 0.25))
    # A container below this CPU usage (cores, p95) and near-zero memory is "idle".
    idle_cpu_cores: float = field(default_factory=lambda: _get_float("IDLE_CPU_CORES", 0.005))


settings = Settings()
