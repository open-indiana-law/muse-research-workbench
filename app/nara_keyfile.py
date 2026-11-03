"""Write the NARA Catalog API key to a mode-600 local file. Never print it."""

from __future__ import annotations

import os
import stat
from pathlib import Path

NARA_KEY_PATH = Path.home() / ".config" / "nara" / "catalog-api-key"


def write_nara_key(key: str, path: Path | None = None) -> Path:
    secret = key.strip()
    if not secret:
        raise ValueError("empty key")
    target = path or NARA_KEY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(secret, encoding="utf-8")
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.environ["NARA_CATALOG_API_KEY"] = secret
    return target


def nara_key_present(path: Path | None = None) -> bool:
    target = path or NARA_KEY_PATH
    if not target.is_file():
        return False
    return bool(target.read_text(encoding="utf-8").strip())
