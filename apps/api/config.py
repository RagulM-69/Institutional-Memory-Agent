"""
Application settings loaded from environment variables.

All secrets are typed as SecretStr so they never appear in repr, logs,
or error messages. The root-level .env file is located relative to this
module's path so the app can be launched from any working directory.
"""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve repo root: this file is at apps/api/config.py → go up three levels.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        # Silently ignore any extra variables present in .env that are not
        # declared here (e.g. shell variables, future vars not yet used).
        extra="ignore",
    )

    # ── Supabase ──────────────────────────────────────────────────────
    supabase_url: str = ""
    # Service role key: backend-only. Never log, never expose to frontend.
    supabase_service_role_key: SecretStr = SecretStr("")
    # JWT secret for verifying HS256-signed user tokens from Supabase Auth.
    # If your project uses RS256, this field will be replaced with a JWKS URL
    # when the auth module is implemented.
    supabase_jwt_secret: SecretStr = SecretStr("")

    # ── Groq ──────────────────────────────────────────────────────────
    groq_api_key: SecretStr = SecretStr("")
    # Model name is kept in configuration, not hardcoded.
    # Verify available free-tier models at console.groq.com before use.
    groq_model: str = "llama-3.3-70b-versatile"

    # ── Connectors (populated when each connector module is built) ────
    github_token: SecretStr = SecretStr("")
    jira_base_url: str = ""
    jira_token: SecretStr = SecretStr("")
    slack_bot_token: SecretStr = SecretStr("")

    # ── Agent ─────────────────────────────────────────────────────────
    agent_max_tool_calls: int = 6

    # ── Embeddings ────────────────────────────────────────────────────
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"


# Module-level singleton. Import `settings` wherever config values are needed.
settings = Settings()

