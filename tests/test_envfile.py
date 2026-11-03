from pathlib import Path

from app.envfile import load_env, write_key


def test_load_env_fills_missing_and_keeps_existing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("INDIANA_MCP_URL", "https://already.set.example/mcp")
    path = tmp_path / ".env"
    path.write_text(
        "INDIANA_MCP_URL=https://from.file.example/mcp\n"
        "MODEL_API_KEY=test-not-a-real-key\n"
        "IGNORED=nope\n",
        encoding="utf-8",
    )
    assert load_env(path) is True
    assert path.read_text(encoding="utf-8").count("test-not-a-real-key") == 1
    from os import environ

    assert environ["MODEL_API_KEY"] == "test-not-a-real-key"
    assert environ["INDIANA_MCP_URL"] == "https://already.set.example/mcp"


def test_write_key_is_mode_600_and_gitignored_name(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("# MODEL_API_KEY=\nINDIANA_MCP_URL=https://mcp.openindianalaw.org/mcp\n")
    wrote = write_key("test-not-a-real-key", path)
    assert wrote == path
    text = path.read_text(encoding="utf-8")
    assert "MODEL_API_KEY=test-not-a-real-key" in text
    assert path.stat().st_mode & 0o777 == 0o600
    from os import environ

    assert environ["MODEL_API_KEY"] == "test-not-a-real-key"


def test_write_key_rejects_empty(tmp_path: Path):
    try:
        write_key("   ", tmp_path / ".env")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("expected empty key to fail")
