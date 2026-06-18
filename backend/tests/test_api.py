"""End-to-end API tests (demo mode) via FastAPI's TestClient."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["demo_mode"] is True


def test_namespaces():
    r = client.get("/api/namespaces")
    assert r.status_code == 200
    assert "mercury-prod" in r.json()["namespaces"]


def test_analysis():
    r = client.get("/api/analysis", params={"namespace": "mercury-prod"})
    assert r.status_code == 200
    body = r.json()
    assert body["namespace"] == "mercury-prod"
    assert body["summary"]["pods_total"] > 0


def test_report_mock():
    r = client.post("/api/report", json={"namespace": "mercury-prod"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "mock"
    assert body["markdown"]
    # the response always reports which model was used (None for mock)
    assert "model" in body


def test_ollama_models_endpoint():
    # no Ollama running in CI: endpoint must still respond cleanly (ok=False)
    r = client.get("/api/config/ollama-models")
    assert r.status_code == 200
    body = r.json()
    assert "models" in body and isinstance(body["models"], list)
    assert "ok" in body


def test_config_get_masks_secrets():
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert "anthropic_api_key" not in body
    assert body["anthropic_api_key_set"] is False


def test_config_put_valid():
    r = client.put("/api/config", json={"overprov_ratio": 0.4})
    assert r.status_code == 200
    assert r.json()["overprov_ratio"] == 0.4


def test_config_put_invalid_returns_400():
    r = client.put("/api/config", json={"llm_provider": "nope"})
    assert r.status_code == 400
    assert "errors" in r.json()["detail"]


def test_config_test_llm_mock():
    client.put("/api/config", json={"llm_provider": "mock"})
    r = client.post("/api/config/test-llm")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_config_reset():
    r = client.post("/api/config/reset")
    assert r.status_code == 200
    assert r.json()["overprov_ratio"] == 0.5
