"""Load a gitignored .env without logging values."""

from __future__ import annotations

import os
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ALLOWED = {
    "INDIANA_MCP_URL",
    "MODEL_API_KEY",
    "MODEL_API_BASE_URL",
    "MODEL_ID",
}


def load_env(path: Path | None = None) -> bool:
    """Fill missing process env from a local .env. Existing values win."""
    target = path or ENV_PATH
    if not target.is_file():
        return False
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key not in ALLOWED:
            continue
        value = value.strip().strip("'").strip('"')
        if not value:
            continue
        os.environ.setdefault(key, value)
    return True


def write_key(key: str, path: Path | None = None) -> Path:
    """Write MODEL_API_KEY into a mode-600 .env. Never print the key."""
    secret = key.strip()
    if not secret:
        raise ValueError("empty key")
    target = path or ENV_PATH
    lines = [
        "INDIANA_MCP_URL=https://mcp.openindianalaw.org/mcp",
        f"MODEL_API_KEY={secret}",
        "MODEL_API_BASE_URL=https://api.meta.ai/v1",
        "MODEL_ID=muse-spark-1.3",
        "",
    ]
    if target.exists():
        kept: list[str] = []
        replaced = False
        for raw in target.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if stripped.startswith("MODEL_API_KEY=") or stripped == "# MODEL_API_KEY=":
                kept.append(f"MODEL_API_KEY={secret}")
                replaced = True
            else:
                kept.append(raw)
        if not replaced:
            kept.append(f"MODEL_API_KEY={secret}")
        lines = [line.rstrip("\n") for line in kept]
        if lines and lines[-1] != "":
            lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.environ["MODEL_API_KEY"] = secret
    return target
