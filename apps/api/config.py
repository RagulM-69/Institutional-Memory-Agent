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

    # ── Application & Frontend ─────────────────────────────────────────
    frontend_base_url: str = "http://localhost:3000"

    # ── Supabase ──────────────────────────────────────────────────────
    supabase_url: str = ""
    # Service role key: backend-only. Never log, never expose to frontend.
    supabase_service_role_key: SecretStr = SecretStr("")
    # JWT secret for verifying HS256-signed user tokens from Supabase Auth.
    # If your project uses RS256/ES256, verification will use JWKS.
    supabase_jwt_secret: SecretStr = SecretStr("")
    # Allowed Supabase JWT algorithm: "HS256", "RS256", or "ES256". Defaults to "HS256".
    supabase_jwt_algorithm: str = "HS256"
    # Optional explicit JWKS URL for asymmetric key verification
    supabase_jwks_url: str = ""

    # ── Database Connections (PostgreSQL Restricted Roles) ────────────
    # Application runtime role connection string (pooler port 6543)
    database_url: SecretStr = SecretStr("")
    # Direct PostgreSQL connection fallback (port 5432)
    direct_database_url: SecretStr = SecretStr("")
    # Worker ingest role connection string (backend sync worker only)
    worker_database_url: SecretStr = SecretStr("")

    # ── Groq ──────────────────────────────────────────────────────────
    groq_api_key: SecretStr = SecretStr("")
    # Model name is kept in configuration, not hardcoded.
    # Verify available free-tier models at console.groq.com before use.
    groq_model: str = "llama-3.3-70b-versatile"

    # ── Connectors & Credentials ──────────────────────────────────────
    # Optional dedicated 32-byte encryption key for credentials at rest.
    # If empty, a key is securely derived from supabase_jwt_secret.
    credential_encryption_key: SecretStr = SecretStr("")

    # Fallback server-level tokens (used only if source has no per-org credential)
    github_token: SecretStr = SecretStr("")
    jira_base_url: str = ""
    jira_email: str = ""
    jira_token: SecretStr = SecretStr("")
    slack_bot_token: SecretStr = SecretStr("")

    # ── Multi-Tenant OAuth Configurations ─────────────────────────────
    # GitHub App or OAuth App
    github_client_id: str = ""
    github_client_secret: SecretStr = SecretStr("")
    github_redirect_uri: str = "http://localhost:3000/api/sources/oauth/github/callback"

    # Jira Cloud OAuth 2.0 (3LO)
    jira_client_id: str = ""
    jira_client_secret: SecretStr = SecretStr("")
    jira_redirect_uri: str = "http://localhost:3000/api/sources/oauth/jira/callback"

    # Slack App OAuth 2.0
    slack_client_id: str = ""
    slack_client_secret: SecretStr = SecretStr("")
    slack_redirect_uri: str = "http://localhost:3000/api/sources/oauth/slack/callback"

    # ── Agent ─────────────────────────────────────────────────────────
    agent_max_tool_calls: int = 6

    # ── Embeddings ────────────────────────────────────────────────────
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"


# Module-level singleton. Import `settings` wherever config values are needed.
settings = Settings()

