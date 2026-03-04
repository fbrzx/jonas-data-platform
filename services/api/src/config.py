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

    # Anthropic
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"


settings = Settings()
