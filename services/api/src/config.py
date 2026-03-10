from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_secret_key: str = "change_me_in_production"
    debug: bool = False
    demo_mode: bool = True
    admin_password: str = "admin123"

    # DuckDB — local file path; set MOTHERDUCK_TOKEN to use MotherDuck instead
    duckdb_path: str = "data/db/jonas.duckdb"
    motherduck_token: str = ""
    # Set to true when MOTHERDUCK_TOKEN is set to give each tenant its own MD database.
    # Requires new deployments — migrating from schema-per-tenant needs a data migration.
    motherduck_db_per_tenant: bool = False

    # Parquet storage root.
    # Local:  "data/parquet"  (default)
    # S3:     "s3://my-bucket/jonas"  (requires S3_ACCESS_KEY + S3_SECRET_KEY)
    # GCS:    "gs://my-bucket/jonas"  (requires GCS credentials in env)
    parquet_root: str = "data/parquet"

    # S3 / MinIO credentials for cloud parquet storage.
    # Leave empty to use local filesystem parquet.
    s3_endpoint: str = ""  # e.g. "http://localhost:9000" for MinIO; empty = AWS
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Observable Framework dashboard output root
    dashboards_root: str = "data/dashboards"

    # LLM provider config
    # Supported providers: openai, google, ollama, claude (anthropic)
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2"

    # LLM tier: "small" uses a compact system prompt (for <3B models),
    # "large" uses the full prompt. Auto-detected from model name if empty.
    llm_tier: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # Google Gemini (OpenAI-compatible endpoint)
    google_api_key: str = ""
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"

    # Ollama (OpenAI-compatible endpoint)
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: str = "ollama"

    # Anthropic / Claude (OpenAI-compatible endpoint)
    claude_api_key: str = ""
    claude_base_url: str = "https://api.anthropic.com/v1"

    # SMTP (Mailpit in dev, real SMTP in prod)
    smtp_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "noreply@jonas.local"

    # Frontend base URL — used to construct invite links
    app_base_url: str = "http://localhost:5173"

    # Redis — used for silver/gold entity caching and GraphQL query layer
    # Set empty to disable caching (falls back to direct DuckDB queries).
    redis_url: str = ""

    # CORS allowed origins — comma-separated list; defaults to local Vite dev server.
    # Example: CORS_ORIGINS=https://app.example.com,https://staging.example.com
    cors_origins: str = "http://localhost:5173"

    # Connector config encryption key (Fernet, base64-encoded 32 bytes).
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # noqa: E501
    # If empty, connector configs are stored as plaintext (dev default).
    connector_encrypt_key: str = ""


settings = Settings()
