"""Configuration.

Two layers, lowest to highest priority:

1. **Environment variables** — the defaults baked in at boot (see `.env.example`).
2. **Runtime overrides** — written from the configuration UI via the API and
   persisted to a JSON file (`CONFIG_PATH`). These win over the environment and
   survive restarts as long as the file lives on a durable volume.

The whole point of this module is that *everything* the operator might want to
tune — the LLM provider, its model/credentials, the Prometheus endpoint, the
analysis window and every optimisation threshold — can be changed live from the
graphical interface, without rebuilding the image or editing the Deployment.

`settings` is a single mutable object: other modules `from .config import
settings` and read attributes at call time, so an in-place update is visible
everywhere. Components that cache a derived client (Prometheus/Kubernetes)
register an `on_change` callback to invalidate themselves.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("config")


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
    # A container below this CPU usage (cores, p95) and below idle_mem_bytes is "idle".
    idle_cpu_cores: float = field(default_factory=lambda: _get_float("IDLE_CPU_CORES", 0.005))
    # Memory (bytes, p95) below which — together with idle CPU — a container is "idle".
    idle_mem_bytes: float = field(default_factory=lambda: _get_float("IDLE_MEM_BYTES", 32 * 1024 ** 2))


settings = Settings()


# ──────────────────────────────────────────────────────────────────────────
# Runtime configuration: schema, validation, persistence
# ──────────────────────────────────────────────────────────────────────────

# Where runtime overrides are stored. In-cluster this points at a mounted
# volume (see k8s manifests). Locally it defaults to a temp file so config
# survives `--reload` restarts. Persistence is best-effort: if the path is not
# writable the app keeps the config in memory and logs a warning.
CONFIG_PATH: str = os.getenv("CONFIG_PATH") or str(
    Path(tempfile.gettempdir()) / "kube-optimizer-config.json"
)

# Fields the UI may change, with the type used to coerce incoming JSON.
EDITABLE_FIELDS: dict[str, type] = {
    "demo_mode": bool,
    "in_cluster": bool,
    "kubeconfig": str,
    "prometheus_url": str,
    "analysis_window": str,
    "prom_timeout": float,
    "llm_provider": str,
    "report_language": str,
    "anthropic_api_key": str,
    "anthropic_model": str,
    "openai_api_key": str,
    "openai_model": str,
    "ollama_host": str,
    "ollama_model": str,
    "overprov_ratio": float,
    "request_buffer": float,
    "limit_buffer": float,
    "risk_ratio": float,
    "throttle_ratio": float,
    "idle_cpu_cores": float,
    "idle_mem_bytes": float,
}

# Never echoed back to the client; only a "<field>_set" boolean is exposed.
SECRET_FIELDS = {"anthropic_api_key", "openai_api_key"}
# Optional string fields that should become None when blank.
NULLABLE_STR_FIELDS = {"kubeconfig", "anthropic_api_key", "openai_api_key"}

VALID_PROVIDERS = {"mock", "anthropic", "ollama", "openai"}
MASK = "••••••••"
_WINDOW_RE = re.compile(r"^(\d+[smhdwy])+$")

_lock = threading.Lock()
_on_change: list[Callable[[], None]] = []
# Whether the current in-memory config is known to be safely persisted to disk.
# Reflects the real outcome of the last write, not merely that the file exists.
_persisted_ok: bool = False


def register_on_change(fn: Callable[[], None]) -> None:
    """Register a callback fired after any successful config change.

    Used by cached clients (Prometheus/Kubernetes) to drop stale instances.
    """
    _on_change.append(fn)


def _coerce(name: str, value: Any) -> Any:
    typ = EDITABLE_FIELDS[name]
    if typ is bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if typ is float:
        return float(value)
    # string
    if value is None:
        return None
    text = str(value).strip()
    if text == "" and name in NULLABLE_STR_FIELDS:
        return None
    return text


def _validate(name: str, value: Any) -> str | None:
    """Return an error message for a (coerced) value, or None if valid."""
    if name == "llm_provider" and value not in VALID_PROVIDERS:
        return f"Provider non valido: '{value}'. Ammessi: {', '.join(sorted(VALID_PROVIDERS))}."
    if name == "analysis_window":
        if not value or not _WINDOW_RE.match(str(value)):
            return "Finestra non valida (es. 24h, 7d, 2w)."
        # a zero-length window (e.g. "0d") passes the regex but breaks every PromQL query
        if all(int(n) == 0 for n in re.findall(r"(\d+)[smhdwy]", str(value))):
            return "La finestra di analisi deve essere maggiore di zero."
    if name == "prometheus_url" and value and not str(value).startswith(("http://", "https://")):
        return "L'URL di Prometheus deve iniziare con http:// o https://."
    if name == "ollama_host" and value and not str(value).startswith(("http://", "https://")):
        return "L'host Ollama deve iniziare con http:// o https://."
    if name == "prom_timeout" and not (0 < float(value) <= 600):
        return "Timeout Prometheus fuori range (0 < t ≤ 600 s)."
    # ratios expressed as a fraction of request/limit
    if name in {"overprov_ratio", "risk_ratio", "throttle_ratio"} and not (0 < float(value) <= 1):
        return f"{name} deve essere compreso tra 0 e 1."
    # buffers are multipliers applied on top of observed usage
    if name in {"request_buffer", "limit_buffer"} and not (1.0 <= float(value) <= 5.0):
        return f"{name} deve essere compreso tra 1.0 e 5.0."
    if name == "idle_cpu_cores" and not (0 <= float(value) <= 1):
        return "idle_cpu_cores deve essere compreso tra 0 e 1 (core)."
    if name == "idle_mem_bytes" and float(value) < 0:
        return "idle_mem_bytes non può essere negativo."
    return None


def _clean_payload(data: dict) -> tuple[dict, dict]:
    """Coerce + validate an incoming payload.

    Returns (clean_values, errors). Unknown keys are ignored. Secret fields that
    arrive empty or still masked are dropped so the existing value is kept.
    """
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, raw in data.items():
        if key not in EDITABLE_FIELDS:
            continue
        if key in SECRET_FIELDS and (raw is None or str(raw).strip() in {"", MASK}):
            continue  # keep the stored secret untouched
        try:
            value = _coerce(key, raw)
        except (TypeError, ValueError):
            errors[key] = f"Valore non valido per {key}: {raw!r}."
            continue
        err = _validate(key, value)
        if err:
            errors[key] = err
        else:
            clean[key] = value
    return clean, errors


def _apply(values: dict) -> None:
    for key, value in values.items():
        setattr(settings, key, value)
    settings.llm_provider = (settings.llm_provider or "mock").lower()


def _persist() -> bool:
    """Persist the current settings atomically. Returns True on success.

    Writes to a temp file in the same directory and ``os.replace``s it over the
    target, so a crash or full disk mid-write can never leave a truncated
    (unparseable) config that would silently wipe every override at next boot.
    """
    global _persisted_ok
    try:
        path = Path(CONFIG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {key: getattr(settings, key) for key in EDITABLE_FIELDS}
        fd, tmp = tempfile.mkstemp(prefix=".kube-optimizer-config-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        log.info("Configurazione salvata in %s", CONFIG_PATH)
        _persisted_ok = True
        return True
    except OSError as exc:
        log.warning("Configurazione non persistita (%s non scrivibile): %s", CONFIG_PATH, exc)
        _persisted_ok = False
        return False


def load_persisted() -> None:
    """Load and apply runtime overrides from disk, if present. Called at boot."""
    global _persisted_ok
    path = Path(CONFIG_PATH)
    if not path.exists():
        return
    try:
        stored = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        log.warning("Impossibile leggere %s: %s", CONFIG_PATH, exc)
        return
    clean, errors = _clean_payload(stored)
    if errors:
        log.warning("Override ignorati (non validi) da %s: %s", CONFIG_PATH, errors)
    _apply(clean)
    _persisted_ok = True
    log.info("Override di configurazione caricati da %s", CONFIG_PATH)


def update(data: dict) -> dict:
    """Validate, apply and persist a partial config update.

    Raises ``ConfigError`` (with a per-field error map) if anything is invalid.
    Fires the on_change callbacks so cached clients refresh.
    """
    clean, errors = _clean_payload(data)
    if errors:
        raise ConfigError(errors)
    with _lock:
        _apply(clean)
        _persist()
    for fn in _on_change:
        try:
            fn()
        except Exception:  # noqa: BLE001 - a bad callback must not break config
            log.exception("on_change callback fallita")
    return public_dict()


def reset() -> dict:
    """Drop all runtime overrides and fall back to environment defaults."""
    global _persisted_ok
    with _lock:
        for key, value in vars(Settings()).items():
            setattr(settings, key, value)
        try:
            Path(CONFIG_PATH).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Impossibile rimuovere %s: %s", CONFIG_PATH, exc)
        _persisted_ok = False
    for fn in _on_change:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("on_change callback fallita")
    return public_dict()


def public_dict() -> dict[str, Any]:
    """Current config for the UI. Secrets are reported only as a boolean flag."""
    out: dict[str, Any] = {}
    for key in EDITABLE_FIELDS:
        if key in SECRET_FIELDS:
            out[f"{key}_set"] = bool(getattr(settings, key))
        else:
            out[key] = getattr(settings, key)
    out["config_path"] = CONFIG_PATH
    # reflect whether the last write actually succeeded — not merely that some
    # (possibly stale) file exists on a read-only mount.
    out["config_persisted"] = _persisted_ok and Path(CONFIG_PATH).exists()
    return out


class ConfigError(ValueError):
    """Raised when a config update fails validation. Carries a field->msg map."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


# Apply any persisted overrides as soon as the module is imported.
load_persisted()
