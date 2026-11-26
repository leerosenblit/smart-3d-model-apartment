"""Application settings loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    image_to_3d_provider: str = "mock"  # tripo3d | meshy | mock
    tripo_api_key: str = ""
    meshy_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    openai_model: str = "gpt-4o-mini"

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'roomcraft.db').as_posix()}"
    storage_dir: str = str(BACKEND_DIR / "storage")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    catalog_snapshot: str = str(BACKEND_DIR / "data" / "catalog.json.gz")  # empty string disables

    mock_generation_seconds: float = 2.0
    max_upload_mb: int = 15

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)

    @property
    def catalog_snapshot_path(self) -> Path:
        return Path(self.catalog_snapshot)

    @property
    def floorplans_dir(self) -> Path:
        return self.storage_path / "floorplans"

    @property
    def models_dir(self) -> Path:
        return self.storage_path / "models"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
