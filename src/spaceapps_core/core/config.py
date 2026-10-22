from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "spaceapps-core"
    app_env: str = "dev"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    cors_origins: str = "*"

    default_lat: float = -5.19
    default_lon: float = -80.63

    cache_dir: str = ".cache"
    cache_ttl_forecast: int = 1800
    cache_ttl_history: int = 86400
    cache_ttl_projections: int = 604800
    cache_ttl_satellite: int = 43200

    http_timeout: float = 30.0
    http_retries: int = 3

    earthdata_username: str = Field(default="")
    earthdata_password: str = Field(default="")

    copernicus_client_id: str = Field(default="")
    copernicus_client_secret: str = Field(default="")

    @field_validator("cors_origins")
    @classmethod
    def _strip_cors(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def earthdata_configured(self) -> bool:
        return bool(self.earthdata_username and self.earthdata_password)

    @property
    def copernicus_configured(self) -> bool:
        return bool(self.copernicus_client_id and self.copernicus_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
