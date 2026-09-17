import logging
import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("app.config")

_INSECURE_DEFAULT_JWT_SECRET = "dev-secret-change-me"


def _quote_conninfo(value: str) -> str:
    """Escape a libpq conninfo value: wrap in single quotes if it is empty or
    contains whitespace/quotes, escaping backslashes and quotes within."""
    if value and not any(c.isspace() or c in "'\\" for c in value):
        return value
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "control_assessment"
    postgres_user: str = ""
    postgres_password: str = ""

    jwt_secret: str = _INSECURE_DEFAULT_JWT_SECRET
    jwt_expiry_hours: int = 24

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-5.2-chat"
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_embedding_deployment: str = "text-embedding-ada-002"

    storage_root: str = "../storage"

    cors_origins: str = "http://localhost:8090"

    # Frontend origin used to build links embedded in outbound emails (e.g.
    # the justification-response page) — distinct from cors_origins, which
    # can list several. Defaults to the first CORS origin if unset.
    app_base_url: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_use_tls: bool = True

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_address)

    def _conninfo_for(self, dbname: str) -> str:
        """Build a libpq conninfo string from the discrete Postgres settings.

        Uses keyword/value form rather than a URL so that passwords containing
        URL-special characters (@, /, ?, #) need no percent-encoding. Empty
        user/password are omitted so libpq falls back to its own defaults
        (the OS user, and ~/.pgpass) exactly as it would with no setting at all.
        """
        parts = {
            "host": self.postgres_host,
            "port": str(self.postgres_port),
            "dbname": dbname,
        }
        if self.postgres_user:
            parts["user"] = self.postgres_user
        if self.postgres_password:
            parts["password"] = self.postgres_password
        return " ".join(f"{k}={_quote_conninfo(v)}" for k, v in parts.items())

    @property
    def postgres_conninfo(self) -> str:
        return self._conninfo_for(self.postgres_db)

    @property
    def postgres_maintenance_conninfo(self) -> str:
        """Conninfo for the always-present `postgres` maintenance database —
        used only to check for / create `postgres_db` itself before the app's
        own pool (which connects straight to `postgres_db`) is ever opened."""
        return self._conninfo_for("postgres")

    @property
    def storage_path(self) -> Path:
        return (Path(__file__).resolve().parent.parent / self.storage_root).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def frontend_base_url(self) -> str:
        if self.app_base_url:
            return self.app_base_url.rstrip("/")
        origins = self.cors_origin_list
        return origins[0].rstrip("/") if origins else ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.jwt_secret == _INSECURE_DEFAULT_JWT_SECRET:
        if settings.environment != "development":
            print(
                f"FATAL: JWT_SECRET is still the insecure default in environment={settings.environment!r}. "
                "Set a real JWT_SECRET in .env before starting outside development.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        logger.warning(
            "JWT_SECRET is the insecure default (%r) — fine for local development, "
            "but must be overridden before this ever runs anywhere else.",
            _INSECURE_DEFAULT_JWT_SECRET,
        )
    return settings
