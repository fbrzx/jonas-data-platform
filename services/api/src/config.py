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

    # DuckDB — local file path; set MOTHERDUCK_TOKEN to use MotherDuck instead
    duckdb_path: str = "data/db/jonas.duckdb"
    motherduck_token: str = ""

    # Parquet storage root (local filesystem or future cloud path)
    parquet_root: str = "data/parquet"

    # LLM provider config
    # Supported providers: openai, google, ollama
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2"

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # Google Gemini (OpenAI-compatible endpoint)
    google_api_key: str = ""
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"

    # Ollama (OpenAI-compatible endpoint)
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: str = "ollama"


settings = Settings()
