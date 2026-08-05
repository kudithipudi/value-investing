from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    root_path: str = "/value-investing"
    db_path: str = "data/value-investing.db"
    pdf_dir: str = "data/pdfs"
    openrouter_api_key: str = ""
    admin_password: str = ""
    llm_model: str = "openai/gpt-4o-mini"
    llm_temperature: float = 0.1
    llm_timeout: int = 120
    mirror_archive_url: str = "https://www.grahamanddoddsville.net/?page_id=689"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )


def get_settings() -> Settings:
    # Not cached: this app runs a single gunicorn worker and Settings() is cheap
    # to build, so we always read the current environment/.env rather than risk
    # a stale cached instance (e.g. across tests that monkeypatch env vars).
    return Settings()
