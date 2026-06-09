from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://erp:erp_pass@localhost:5432/erp_nfc"

    # Oracle ADB (wallet) — DATABASE_URL을 oracle+oracledb://... 로 바꾸면 사용
    oracle_wallet_dir: str = ""
    oracle_wallet_password: str = ""

    # 외부 공공 API
    kma_api_key: str = ""
    holiday_api_key: str = ""

    # AI 해석 — provider 추상화 (gemini | ollama | rule)
    llm_provider: str = "gemini"

    # Gemini (Google AI Studio 무료 등급)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # 로컬 LLM (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"


settings = Settings()
