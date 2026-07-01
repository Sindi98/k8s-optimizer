"""Tests for the runtime configuration layer (validation, persistence, secrets)."""
import json
from pathlib import Path

import pytest

from app import config


def test_public_dict_masks_secrets():
    cfg = config.public_dict()
    assert "anthropic_api_key" not in cfg
    assert "openai_api_key" not in cfg
    assert cfg["anthropic_api_key_set"] is False
    assert "config_path" in cfg


def test_update_applies_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    res = config.update({"overprov_ratio": 0.4, "analysis_window": "3d", "llm_provider": "ollama"})
    assert config.settings.overprov_ratio == 0.4
    assert config.settings.llm_provider == "ollama"
    assert res["analysis_window"] == "3d"
    saved = json.loads(Path(config.CONFIG_PATH).read_text())
    assert saved["overprov_ratio"] == 0.4
    assert saved["analysis_window"] == "3d"


def test_invalid_update_raises_with_field_errors():
    with pytest.raises(config.ConfigError) as exc:
        config.update({"overprov_ratio": 5, "llm_provider": "foo", "analysis_window": "banana"})
    assert set(exc.value.errors) == {"overprov_ratio", "llm_provider", "analysis_window"}


def test_zero_length_window_rejected():
    # "0d" matches the format regex but is an invalid PromQL range
    with pytest.raises(config.ConfigError) as exc:
        config.update({"analysis_window": "0d"})
    assert "analysis_window" in exc.value.errors


def test_ollama_host_scheme_validated():
    with pytest.raises(config.ConfigError) as exc:
        config.update({"ollama_host": "not-a-url"})
    assert "ollama_host" in exc.value.errors


def test_idle_mem_bytes_editable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    config.update({"idle_mem_bytes": 64 * 1024 * 1024})
    assert config.settings.idle_mem_bytes == 64 * 1024 * 1024


def test_secret_set_and_preserved_on_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    config.update({"anthropic_api_key": "sk-secret"})
    assert config.settings.anthropic_api_key == "sk-secret"
    # blank value must NOT wipe the stored secret
    config.update({"anthropic_api_key": ""})
    assert config.settings.anthropic_api_key == "sk-secret"
    assert config.public_dict()["anthropic_api_key_set"] is True


def test_reset_reverts_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    config.update({"overprov_ratio": 0.3})
    assert config.settings.overprov_ratio == 0.3
    config.reset()
    assert config.settings.overprov_ratio == 0.5  # env default
    assert not Path(config.CONFIG_PATH).exists()
