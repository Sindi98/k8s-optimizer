"""Report generation.

The analyzer hands us a fully computed `NamespaceAnalysis`. This module turns it
into a prioritised, human-readable optimisation report.

Providers:
  - mock      : deterministic templated report, no external call (default).
  - anthropic : Claude via the official SDK.
  - ollama    : a local model via the Ollama HTTP API.
  - openai    : OpenAI via the official SDK.

For every provider except `mock`, the model is given the already-computed numbers
and is explicitly told NOT to invent any metric. This keeps the report grounded.
"""
from __future__ import annotations

import json
import logging

import httpx

from .config import settings
from .models import NamespaceAnalysis

log = logging.getLogger("llm")

SYSTEM_PROMPT = (
    "Sei un esperto di ottimizzazione di risorse Kubernetes (right-sizing, QoS, HPA). "
    "Ricevi un'analisi GIÀ CALCOLATA di un namespace con metriche reali da Prometheus. "
    "Regole tassative:\n"
    "1. Usa ESCLUSIVAMENTE i numeri presenti nei dati forniti. Non inventare, stimare o "
    "arrotondare metriche non presenti.\n"
    "2. Scrivi un report operativo, conciso e prioritizzato (prima i problemi 'critical', "
    "poi 'warning').\n"
    "3. Per i container da correggere fornisci uno snippet YAML `resources:` pronto all'uso, "
    "usando i valori consigliati (recommendation) dei dati.\n"
    "4. Suggerisci HPA solo dove ha senso (carico variabile) e segnala i rischi (OOM, throttling) "
    "in modo esplicito.\n"
    "5. Output in Markdown. Lingua: {lang}.\n"
)


def _compact_findings(analysis: NamespaceAnalysis) -> dict:
    """A trimmed view of the analysis for the prompt (labels + key numbers)."""
    pods = []
    for p in analysis.pods:
        if p.severity == "ok":
            continue  # only send pods that need attention
        containers = []
        for c in p.containers:
            if not c.issues:
                continue
            containers.append({
                "container": c.name,
                "issues": [{"kind": i.kind, "severity": i.severity, "detail": i.detail} for i in c.issues],
                "current": {
                    "cpu_request": c.spec["cpu_request_label"], "cpu_limit": c.spec["cpu_limit_label"],
                    "mem_request": c.spec["mem_request_label"], "mem_limit": c.spec["mem_limit_label"],
                },
                "observed": {
                    "cpu_p95": c.usage["cpu_p95_label"], "cpu_max": c.usage["cpu_max_label"],
                    "mem_p95": c.usage["mem_p95_label"], "mem_max": c.usage["mem_max_label"],
                    "cpu_throttle_pct": round((c.usage["cpu_throttle"] or 0) * 100),
                },
                "recommended": {
                    "cpu_request": c.recommendation["cpu_request_label"], "cpu_limit": c.recommendation["cpu_limit_label"],
                    "mem_request": c.recommendation["mem_request_label"], "mem_limit": c.recommendation["mem_limit_label"],
                },
            })
        pods.append({
            "pod": p.name, "qos": p.qos_class, "severity": p.severity,
            "restarts": p.restarts, "oom_killed": p.oom_killed,
            "containers": containers,
        })
    return {
        "namespace": analysis.namespace,
        "window": analysis.window,
        "summary": analysis.summary(),
        "pods_needing_attention": pods,
    }


def _user_prompt(analysis: NamespaceAnalysis) -> str:
    data = _compact_findings(analysis)
    return (
        "Analisi del namespace (JSON):\n```json\n"
        + json.dumps(data, ensure_ascii=False, indent=2)
        + "\n```\n\nGenera il report di ottimizzazione."
    )


# --- providers --------------------------------------------------------------

def _report_anthropic(analysis: NamespaceAnalysis) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2000,
        system=SYSTEM_PROMPT.format(lang=settings.report_language),
        messages=[{"role": "user", "content": _user_prompt(analysis)}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")


def _report_openai(analysis: NamespaceAnalysis) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(lang=settings.report_language)},
            {"role": "user", "content": _user_prompt(analysis)},
        ],
    )
    return resp.choices[0].message.content or ""


def _report_ollama(analysis: NamespaceAnalysis) -> str:
    url = f"{settings.ollama_host.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(lang=settings.report_language)},
            {"role": "user", "content": _user_prompt(analysis)},
        ],
    }
    r = httpx.post(url, json=payload, timeout=120.0)
    r.raise_for_status()
    return r.json()["message"]["content"]


def _report_mock(analysis: NamespaceAnalysis) -> str:
    """A deterministic, dependency-free report built directly from the findings."""
    s = analysis.summary()
    lines: list[str] = []
    lines.append(f"# Report di ottimizzazione — namespace `{analysis.namespace}`")
    lines.append("")
    lines.append(f"_Finestra di analisi: {analysis.window} · generato {analysis.generated_at}_")
    lines.append("")
    lines.append("## Sintesi")
    lines.append("")
    lines.append(
        f"- Pod analizzati: **{s['pods_total']}** "
        f"({s['counts']['critical']} critici, {s['counts']['warning']} da rivedere, "
        f"{s['counts']['ok']} ok)"
    )
    lines.append(
        f"- CPU recuperabile: **{s['reclaimable_cpu_label']}** "
        f"({s['cpu_savings_pct']}% del richiesto)"
    )
    lines.append(
        f"- Memoria recuperabile: **{s['reclaimable_mem_label']}** "
        f"({s['mem_savings_pct']}% del richiesto)"
    )
    lines.append("")

    critical = [p for p in analysis.pods if p.severity == "critical"]
    warning = [p for p in analysis.pods if p.severity == "warning"]

    if critical:
        lines.append("## 🔴 Priorità alta — rischio affidabilità")
        lines.append("")
        for p in critical:
            lines += _pod_block(p)
    if warning:
        lines.append("## 🟠 Priorità media — spreco di risorse")
        lines.append("")
        for p in warning:
            lines += _pod_block(p)

    if not critical and not warning:
        lines.append("Nessun problema rilevato: le risorse del namespace sono ben dimensionate.")

    return "\n".join(lines)


def _pod_block(p) -> list[str]:
    out = [f"### `{p.name}`  ·  QoS: {p.qos_class or 'n/d'}"]
    if p.oom_killed:
        out.append("> ⚠️ Già terminato per OOM in passato.")
    out.append("")
    for c in p.containers:
        if not c.issues:
            continue
        for i in c.issues:
            out.append(f"- **{i.title}** ({c.name}): {i.detail}")
        rec = c.recommendation
        # emit a YAML snippet only when we changed something
        changed = (
            rec["cpu_request"] != c.spec["cpu_request"] or rec["cpu_limit"] != c.spec["cpu_limit"]
            or rec["mem_request"] != c.spec["mem_request"] or rec["mem_limit"] != c.spec["mem_limit"]
        )
        if changed:
            out.append("")
            out.append("```yaml")
            out.append(f"# {c.name}")
            out.append("resources:")
            out.append("  requests:")
            out.append(f"    cpu: {rec['cpu_request_label']}")
            out.append(f"    memory: {rec['mem_request_label']}")
            out.append("  limits:")
            out.append(f"    cpu: {rec['cpu_limit_label']}")
            out.append(f"    memory: {rec['mem_limit_label']}")
            out.append("```")
        out.append("")
    return out


_PROVIDERS = {
    "mock": _report_mock,
    "anthropic": _report_anthropic,
    "openai": _report_openai,
    "ollama": _report_ollama,
}


def _model_for(provider: str) -> str | None:
    """The model name a provider would use (None for the dependency-free mock)."""
    return {
        "anthropic": settings.anthropic_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
    }.get(provider)


def generate_report(analysis: NamespaceAnalysis) -> dict:
    provider = settings.llm_provider
    model = _model_for(provider)
    fn = _PROVIDERS.get(provider)
    if fn is None:
        # unknown provider: still return a useful mock report
        return {"provider": provider, "model": model, "markdown": _report_mock(analysis),
                "error": f"Provider sconosciuto: {provider}", "fallback": True}
    try:
        markdown = fn(analysis)
        return {"provider": provider, "model": model, "markdown": markdown}
    except Exception as exc:  # noqa: BLE001
        log.exception("Report generation failed with provider %s", provider)
        # graceful fallback so the UI always shows something useful
        return {
            "provider": provider,
            "model": model,
            "error": f"{type(exc).__name__}: {exc}",
            "markdown": _report_mock(analysis),
            "fallback": True,
        }


# --- connection test (used by the configuration UI) -------------------------

def test_provider() -> dict:
    """Cheaply validate that the currently configured LLM provider works.

    Returns ``{"ok": bool, "provider": str, ...}``. Used by the settings panel's
    "Test connessione" button so the operator gets immediate feedback on the
    credentials/host before relying on them for a real report.
    """
    provider = settings.llm_provider
    try:
        if provider == "mock":
            return {"ok": True, "provider": provider,
                    "detail": "Report generato localmente, nessuna chiamata esterna."}

        if provider == "anthropic":
            if not settings.anthropic_api_key:
                return {"ok": False, "provider": provider, "error": "ANTHROPIC_API_KEY mancante."}
            import anthropic
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            client.messages.create(
                model=settings.anthropic_model, max_tokens=4,
                messages=[{"role": "user", "content": "ping"}],
            )
            return {"ok": True, "provider": provider, "model": settings.anthropic_model,
                    "detail": "Connessione a Claude riuscita."}

        if provider == "openai":
            if not settings.openai_api_key:
                return {"ok": False, "provider": provider, "error": "OPENAI_API_KEY mancante."}
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key)
            client.chat.completions.create(
                model=settings.openai_model, max_tokens=4,
                messages=[{"role": "user", "content": "ping"}],
            )
            return {"ok": True, "provider": provider, "model": settings.openai_model,
                    "detail": "Connessione a OpenAI riuscita."}

        if provider == "ollama":
            host = settings.ollama_host.rstrip("/")
            target = settings.ollama_model
            try:
                r = httpx.get(f"{host}/api/tags", timeout=10.0)
                r.raise_for_status()
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                return {
                    "ok": False, "provider": provider, "model": target,
                    "error": f"Impossibile raggiungere Ollama su {host} ({exc}).",
                    "hint": "Avvia Ollama in ascolto su tutte le interfacce "
                            "(OLLAMA_HOST=0.0.0.0:11434 ollama serve). Se l'app gira nel "
                            "cluster usa http://host.docker.internal:11434, non localhost.",
                }
            models = [m.get("name", "") for m in r.json().get("models", [])]
            has_model = any(m == target or m.startswith(f"{target}:") or target in m for m in models)
            detail = f"Ollama raggiungibile su {host}: {len(models)} modelli installati."
            if models and not has_model:
                shown = ", ".join(models[:8])
                detail += f" Attenzione: '{target}' non è tra i modelli installati ({shown})."
            return {"ok": True, "provider": provider, "model": target, "models": models, "detail": detail}

        return {"ok": False, "provider": provider, "error": f"Provider sconosciuto: {provider}"}
    except Exception as exc:  # noqa: BLE001
        log.warning("Test provider %s fallito: %s", provider, exc)
        return {"ok": False, "provider": provider, "error": f"{type(exc).__name__}: {exc}"}


def list_ollama_models() -> dict:
    """Return the models installed on the configured Ollama host (for the UI)."""
    host = settings.ollama_host.rstrip("/")
    try:
        r = httpx.get(f"{host}/api/tags", timeout=10.0)
        r.raise_for_status()
        models = sorted(m.get("name", "") for m in r.json().get("models", []) if m.get("name"))
        return {"ok": True, "host": host, "models": models}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "host": host, "models": [], "error": f"{type(exc).__name__}: {exc}"}
