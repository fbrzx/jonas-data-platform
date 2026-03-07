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

    # Parquet storage root (local filesystem or future cloud path)
    parquet_root: str = "data/parquet"

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

    # CORS allowed origins — comma-separated list; defaults to local Vite dev server.
    # Example: CORS_ORIGINS=https://app.example.com,https://staging.example.com
    cors_origins: str = "http://localhost:5173"


settings = Settings()
