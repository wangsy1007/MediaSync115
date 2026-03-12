import json

from app.services.runtime_settings_service import RuntimeSettingsService


def test_env_backed_settings_persist_to_runtime_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    service = RuntimeSettingsService()
    updated = service.update_bulk(
        {
            "tmdb_api_key": "tmdb-test-key",
            "emby_url": "http://emby.local:8096",
            "emby_api_key": "emby-test-key",
            "http_proxy": "http://127.0.0.1:7890",
        }
    )

    runtime_path = tmp_path / "data" / "runtime_settings.json"
    assert runtime_path.exists()

    persisted = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert persisted["tmdb_api_key"] == "tmdb-test-key"
    assert persisted["emby_url"] == "http://emby.local:8096"
    assert persisted["emby_api_key"] == "emby-test-key"
    assert persisted["http_proxy"] == "http://127.0.0.1:7890"
    assert updated["tmdb_api_key"] == "tmdb-test-key"


def test_runtime_settings_do_not_create_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    service = RuntimeSettingsService()
    service.update_bulk({"tmdb_api_key": "tmdb-test-key"})

    assert not (tmp_path / ".env").exists()


def test_runtime_file_values_override_env_values_even_when_cleared(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMDB_API_KEY", "env-only-key")

    runtime_dir = tmp_path / "data"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = runtime_dir / "runtime_settings.json"
    runtime_path.write_text(
        json.dumps(
            {
                "tmdb_api_key": "",
                "auth_username": "admin",
                "auth_password_hash": "hash",
                "auth_secret": "secret",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = RuntimeSettingsService()

    assert service.get_tmdb_api_key() == ""
