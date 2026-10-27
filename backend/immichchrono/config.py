from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    immich_url: str = field(default_factory=lambda: _env("IMMICH_URL", "http://immich-server:2283").rstrip("/"))
    immich_public_url: str = field(default_factory=lambda: _env("IMMICH_PUBLIC_URL").rstrip("/"))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "/data")))
    default_tz: str = field(default_factory=lambda: _env("DEFAULT_TZ", _env("TZ", "Europe/Berlin")))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-opus-5-5"))
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL").rstrip("/"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llava:7b"))
    cookie_secure: bool = field(default_factory=lambda: _env("COOKIE_SECURE", "false").lower() == "true")
    session_ttl_hours: int = field(default_factory=lambda: int(_env("SESSION_TTL_HOURS", "720")))
    static_dir: Path = field(
        default_factory=lambda: Path(_env("STATIC_DIR", str(Path(__file__).parent / "static")))
    )
    session_secret: str = field(default_factory=lambda: _env("SESSION_SECRET") or secrets.token_hex(16))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "immichchrono.sqlite"

    @property
    def public_url(self) -> str:
        return self.immich_public_url or self.immich_url


settings = Settings()
