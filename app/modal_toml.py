"""Write a Modal API token pair to ~/.modal.toml. Never print the values."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

MODAL_TOML = Path.home() / ".modal.toml"


def _from_cli(text: str) -> tuple[str, str] | None:
    """Pull --token-id / --token-secret off a pasted modal token set command."""
    import shlex

    try:
        parts = shlex.split(text)
    except ValueError:
        return None
    tid = ""
    secret = ""
    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith("--token-id="):
            tid = part.split("=", 1)[1]
        elif part in ("--token-id", "-t") and i + 1 < len(parts):
            i += 1
            tid = parts[i]
        elif part.startswith("--token-secret="):
            secret = part.split("=", 1)[1]
        elif part in ("--token-secret", "-s") and i + 1 < len(parts):
            i += 1
            secret = parts[i]
        i += 1
    if tid and secret and tid != "-" and secret != "-":
        return tid, secret
    return None


def parse_modal_pair(blob: str) -> tuple[str, str]:
    """Accept a modal token set command, two fields, or token_id=/token_secret=."""
    text = (blob or "").strip()
    if not text:
        raise ValueError("empty token")
    from_cli = _from_cli(text)
    if from_cli:
        return from_cli
    tid = ""
    secret = ""
    for raw in text.splitlines():
        line = raw.strip().strip(",").strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        lower = line.lower()
        if lower.startswith("token_id"):
            tid = line.split("=", 1)[-1].strip().strip("'\"")
        elif lower.startswith("token_secret"):
            secret = line.split("=", 1)[-1].strip().strip("'\"")
        elif line.startswith("ak-") and not tid:
            tid = line
        elif line.startswith("as-") and not secret:
            secret = line
    if tid and secret:
        return tid, secret
    raise ValueError("need token_id and token_secret")


def write_modal_token(
    token_id: str,
    token_secret: str,
    path: Path | None = None,
) -> Path:
    tid = token_id.strip()
    secret = token_secret.strip()
    if not tid or not secret:
        raise ValueError("empty token")
    target = path or MODAL_TOML
    block = (
        "[default]\n"
        f"token_id = {json.dumps(tid)}\n"
        f"token_secret = {json.dumps(secret)}\n"
    )
    existing = ""
    if target.is_file():
        existing = target.read_text(encoding="utf-8")
        if re.search(r"(?m)^\[default\]\s*$", existing):
            updated, n = re.subn(
                r"(?ms)^\[default\].*?(?=^\[|\Z)",
                block + "\n",
                existing,
            )
            text = updated if n else existing.rstrip() + "\n\n" + block
        else:
            text = existing.rstrip() + "\n\n" + block
    else:
        text = block
    target.write_text(text, encoding="utf-8")
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return target


def modal_token_present(path: Path | None = None) -> bool:
    target = path or MODAL_TOML
    if not target.is_file():
        return False
    text = target.read_text(encoding="utf-8")
    return "token_id" in text and "token_secret" in text
