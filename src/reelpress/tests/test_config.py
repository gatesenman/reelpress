import json
import tomllib
from pathlib import Path

from reelpress.config import load_settings, mask_secret, public_settings, save_user_settings


def test_example_config_parses():
    path = Path(__file__).resolve().parents[1] / "config.example.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == ""
    assert data["video"]["aspect"] == "9:16"


def test_env_overrides_file_and_ui(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ("REELPRESS_CONFIG", "REELPRESS_DATA_DIR", "REELPRESS_LLM_API_KEY", "REELPRESS_LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "config.toml").write_text(
        "\n".join(
            [
                "[app]",
                'data_dir = "data"',
                "[llm]",
                'api_key = "file-key"',
                'model = "from-file"',
                'base_url = "https://api.deepseek.com/v1"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("REELPRESS_LLM_API_KEY", "env-key")
    loaded = load_settings()
    assert loaded.llm_api_key == "env-key"
    assert loaded.llm_model == "from-file"
    assert loaded.llm_configured()
    save_user_settings({"llm_api_key": "ui-key", "llm_model": "ui-model"}, loaded)
    again = load_settings()
    assert again.llm_api_key == "env-key"
    assert again.llm_model == "ui-model"
    public = public_settings(again)
    assert "env-key" not in json.dumps(public)
    assert public["llm_api_key"]["from_env"] is True
    assert public["llm_api_key"]["hint"] != "env-key"


def test_masked_secret_is_not_written_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REELPRESS_LLM_API_KEY", raising=False)
    monkeypatch.setenv("REELPRESS_DATA_DIR", str(tmp_path / "data"))
    loaded = load_settings()
    save_user_settings({"llm_api_key": "abcd1234"}, loaded)
    assert mask_secret("abcd1234") == "ab****34"
    save_user_settings({"llm_api_key": "ab****34"}, load_settings())
    assert load_settings().llm_api_key == "abcd1234"


def test_defaults_have_no_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REELPRESS_LLM_API_KEY", raising=False)
    monkeypatch.setenv("REELPRESS_DATA_DIR", str(tmp_path / "data"))
    loaded = load_settings()
    assert loaded.llm_api_key == ""
    assert loaded.pexels_api_key == ""
    assert loaded.youtube_client_secret == ""
