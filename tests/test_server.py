from fastapi.testclient import TestClient

from app.server import app


def test_health_reports_spark_closed(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = TestClient(app)
    data = client.get("/health").json()
    assert data["ok"] is True
    assert data["spark_ready"] is False
    assert data["bind"] == "127.0.0.1"
    assert data["voice_transcribe"] is False
    assert data["spark_model"] == "muse-spark-1.3"
    assert data["voice_model"] == "muse-voice-transcribe-1.0"
    assert data["spend"]["spent_usd"] is None
    assert data["spend"]["spark_closed"] is True
    assert "modal_token_present" in data


def test_transcribe_stays_closed_without_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = TestClient(app)
    response = client.post("/transcribe", files={"audio": ("clip.wav", b"xxxx", "audio/wav")})
    assert response.status_code == 409


def test_voice_cannot_bypass_typed_demo_credit_guard(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "offline-test-key")
    def forbidden(**_):
        raise AssertionError("Voice HTTP must remain closed")
    monkeypatch.setattr("app.voice_client.httpx.AsyncClient", forbidden)
    client = TestClient(app)
    assert client.get("/health").json()["voice_transcribe"] is False
    response = client.post("/transcribe", files={"audio": ("clip.wav", b"xxxx", "audio/wav")})
    assert response.status_code == 409


def test_index_served():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Open Indiana Law" in response.text
    assert "Open Horton and tell me what it cites." in response.text
    assert "Muse Transcribe is closed" in response.text


def test_set_key_form_does_not_echo_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    monkeypatch.setattr("app.envfile.ENV_PATH", env_path)
    monkeypatch.setattr("app.server.write_key", lambda key: __import__("app.envfile", fromlist=["write_key"]).write_key(key, env_path))
    client = TestClient(app)
    page = client.get("/set-key")
    assert page.status_code == 200
    assert "MODEL_API_KEY" in page.text
    assert 'name="key"' in page.text
    assert "Paste from clipboard" in page.text
    box = client.get("/key-box")
    assert box.status_code == 200
    saved = client.post("/set-key", data={"key": "test-not-a-real-key"})
    assert saved.status_code == 200
    assert "spark_ready: true" in saved.text
    assert "test-not-a-real-key" not in saved.text
    assert env_path.read_text(encoding="utf-8").count("test-not-a-real-key") == 1
    env_path.write_text("", encoding="utf-8")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    uploaded = client.post(
        "/set-key",
        data={"key": ""},
        files={"keyfile": ("key.txt", b"test-file-key\n", "text/plain")},
    )
    assert uploaded.status_code == 200
    assert "test-file-key" not in uploaded.text
    assert "MODEL_API_KEY=test-file-key" in env_path.read_text(encoding="utf-8")


def test_nara_key_form_does_not_echo_secret(tmp_path, monkeypatch):
    key_path = tmp_path / "catalog-api-key"
    monkeypatch.setattr("app.nara_keyfile.NARA_KEY_PATH", key_path)
    monkeypatch.setattr(
        "app.server.write_nara_key",
        lambda key: __import__("app.nara_keyfile", fromlist=["write_nara_key"]).write_nara_key(key, key_path),
    )
    monkeypatch.setattr(
        "app.server.nara_key_present",
        lambda: __import__("app.nara_keyfile", fromlist=["nara_key_present"]).nara_key_present(key_path),
    )
    client = TestClient(app)
    page = client.get("/nara-key-box")
    assert page.status_code == 200
    assert "NARA Catalog API key" in page.text
    assert "Paste from clipboard" in page.text
    saved = client.post("/set-nara-key", data={"key": "test-nara-not-real"})
    assert saved.status_code == 200
    assert "nara_key_present: true" in saved.text
    assert "test-nara-not-real" not in saved.text
    assert key_path.read_text(encoding="utf-8") == "test-nara-not-real"
    assert (key_path.stat().st_mode & 0o777) == 0o600


def test_modal_token_form_does_not_echo_secret(tmp_path, monkeypatch):
    toml_path = tmp_path / ".modal.toml"
    monkeypatch.setattr("app.modal_toml.MODAL_TOML", toml_path)
    monkeypatch.setattr(
        "app.server.write_modal_token",
        lambda tid, secret: __import__(
            "app.modal_toml", fromlist=["write_modal_token"]
        ).write_modal_token(tid, secret, toml_path),
    )
    monkeypatch.setattr(
        "app.server.modal_token_present",
        lambda: __import__(
            "app.modal_toml", fromlist=["modal_token_present"]
        ).modal_token_present(toml_path),
    )
    client = TestClient(app)
    page = client.get("/modal-token-box")
    assert page.status_code == 200
    assert "Set Modal API token" in page.text
    saved = client.post(
        "/set-modal-token",
        data={"token_id": "ak-test-not-real", "token_secret": "as-test-not-real"},
    )
    assert saved.status_code == 200
    assert "modal_token_present: true" in saved.text
    assert "ak-test-not-real" not in saved.text
    assert "as-test-not-real" not in saved.text
    text = toml_path.read_text(encoding="utf-8")
    assert "ak-test-not-real" in text
    assert (toml_path.stat().st_mode & 0o777) == 0o600


def test_title_and_captions_served():
    client = TestClient(app)
    title = client.get("/title")
    assert title.status_code == 200
    assert "Open Indiana Law" in title.text
    captions = client.get("/captions.vtt")
    assert captions.status_code == 200
    assert "WEBVTT" in captions.text
    assert "IC 31-16-15-25" in captions.text
    end = client.get("/end")
    assert end.status_code == 200
    assert "Danielle Teagarden" in end.text
