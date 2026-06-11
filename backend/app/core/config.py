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

    # 통계청 KOSIS — 의류 소매판매액지수(거시 수요 외생변수)
    # KOSIS 통계표 화면에서 'OpenAPI'로 생성한 전체 URL(apiKey·기간 포함)을 그대로 넣는다.
    kosis_retail_url: str = ""

    # 조달청 나라장터 입찰공고정보서비스(실수요 신호) — data.go.kr 인증키(Decoding)
    nara_api_key: str = ""

    # 조달청 종합쇼핑몰 품목정보(실 계약단가) — 인증키 + (명세가 JS라) 전체 요청 URL을 받는다.
    pps_api_key: str = ""
    pps_shop_url: str = ""

    # AI 해석 — provider 추상화 (gemini | ollama | rule)
    llm_provider: str = "gemini"

    # Gemini (Google AI Studio 무료 등급)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # 로컬 LLM (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"


settings = Settings()
