"""Shared dotenv loader.

Extracted from lane_a_refine.py's `_load_local_env` (previously duplicated
per-module). Loads two files, neither overriding an already-set env var:

  service/.env       -- GROQ_API_KEY
  <repo-root>/.env    -- EXPO_PUBLIC_SUPABASE_URL, EXPO_PUBLIC_SUPABASE_ANON_KEY
                          (the Expo app's own env file; the Supabase creds
                          already live there under the EXPO_PUBLIC_ prefix,
                          so nothing needs duplicating into service/.env)

Never prints or logs key values.
"""

from __future__ import annotations

import os
from pathlib import Path

_SERVICE_DIR = Path(__file__).parent
_REPO_ROOT = _SERVICE_DIR.parent

_loaded = False


def _load_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip("'").strip('"')
    except OSError:
        return


def load_env() -> None:
    """Idempotent: safe to call from every module that needs env vars."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    _load_file(_SERVICE_DIR / ".env")
    _load_file(_REPO_ROOT / ".env")


def get_supabase() -> tuple[str | None, str | None]:
    """(url, anon_key), or (None, None) if either is missing.

    Reads the repo-root .env's EXPO_PUBLIC_ prefixed vars -- that's where
    the Expo app already keeps them, not a service/.env duplicate.
    """
    load_env()
    url = os.environ.get("EXPO_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = os.environ.get("EXPO_PUBLIC_SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        return None, None
    return url, key
