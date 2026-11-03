from pathlib import Path

import pytest

from app.modal_toml import modal_token_present, parse_modal_pair, write_modal_token
from app.nara_keyfile import nara_key_present, write_nara_key
from app.term_gate import _is_form


def test_write_nara_key_is_mode_600(tmp_path: Path) -> None:
    path = tmp_path / "catalog-api-key"
    wrote = write_nara_key("test-nara-not-real", path)
    assert wrote == path
    assert path.read_text(encoding="utf-8") == "test-nara-not-real"
    assert (path.stat().st_mode & 0o777) == 0o600
    assert nara_key_present(path) is True


def test_write_nara_key_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty key"):
        write_nara_key("   ", tmp_path / "catalog-api-key")


def test_term_gate_routes_form_paths() -> None:
    assert _is_form(b"GET /nara-key-box HTTP/1.1\r\n")
    assert _is_form(b"POST /set-nara-key HTTP/1.1\r\n")
    assert _is_form(b"GET /key-box HTTP/1.1\r\n")
    assert _is_form(b"GET /modal-token-box HTTP/1.1\r\n")
    assert _is_form(b"POST /set-modal-token HTTP/1.1\r\n")
    assert not _is_form(b"GET / HTTP/1.1\r\n")
    assert not _is_form(b"GET /ws HTTP/1.1\r\n")


def test_write_modal_token_is_mode_600(tmp_path: Path) -> None:
    path = tmp_path / ".modal.toml"
    wrote = write_modal_token("ak-test-not-real", "as-test-not-real", path)
    assert wrote == path
    text = path.read_text(encoding="utf-8")
    assert "ak-test-not-real" in text
    assert "as-test-not-real" in text
    assert (path.stat().st_mode & 0o777) == 0o600
    assert modal_token_present(path) is True


def test_parse_modal_pair_from_blob() -> None:
    tid, secret = parse_modal_pair("token_id=ak-one\ntoken_secret=as-two")
    assert tid == "ak-one"
    assert secret == "as-two"


def test_parse_modal_pair_from_cli_command() -> None:
    tid, secret = parse_modal_pair(
        "modal token set --token-id ak-one --token-secret as-two"
    )
    assert tid == "ak-one"
    assert secret == "as-two"
